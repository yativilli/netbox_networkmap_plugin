from collections import Counter

from dcim.models import Device, Location, Site
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from extras.models import ImageAttachment
from ipam.models import VLAN, IPAddress, Prefix
from netbox.plugins import get_plugin_config
from netbox.search import LookupTypes
from netbox.search.backends import search_backend
from utilities.views import ConditionalLoginRequiredMixin

from .colors import color_for_location, color_for_location_hex, shade_of
from .defaults import DEFAULT_CANTON_BOUNDARY_CODE, DEFAULT_GATEWAY_SEARCH_TAG
from .geocoding import geocode_sites
from .models import (
    DetailsElement,
    GatewayElement,
    IpDetailsElement,
    PrefixElement,
    VlanInfo,
)
from .swisstopo import get_canton_boundary, get_canton_label, resolve_canton_id


class NetworkMapPermissionRequiredMixin(
    ConditionalLoginRequiredMixin, PermissionRequiredMixin
):
    # AccessMixin defaults: anonymous users are redirected to the login
    # page, authenticated users without the permission get a 403.
    permission_required = "network_map.view_vlanelement"


class VlanElementListView(NetworkMapPermissionRequiredMixin, View):
    template_name = "network_map/vlan_element_list.html"

    def get_queryset(self):
        queryset = (
            VLAN.objects.select_related("group", "role", "site")
            .prefetch_related("prefixes")
            .order_by("group__name", "vid")
        )

        return queryset

    def build_elements(self, queryset):
        """
        Build VLAN elements without machine data.
        """
        elements = []
        locations = []
        for vlan in queryset:
            machines = []
            vlan_element = VlanInfo.from_vlan(vlan, machines=[])
            related_prefixes = list(vlan.prefixes.all())
            machine_count = 0
            for prefix in related_prefixes:
                active_ips = IPAddress.objects.filter(
                    status__in=["active", "reserved"],
                    address__net_contained_or_equal=prefix.prefix,
                    dns_name__isnull=False,
                ).order_by("address")

                for ip in active_ips:
                    assigned_object = getattr(ip, "assigned_object", None)
                    device = getattr(assigned_object, "device", None)
                    vm = getattr(assigned_object, "virtual_machine", None)

                    room = None
                    if device:
                        location = device.site.name if device.site else ""
                        url = device.get_absolute_url()
                        description = (
                            device.description or device.role or ip.comments or ""
                        )
                        role = device.role or ""
                        device_location = getattr(device, "location", None) or getattr(
                            getattr(device, "rack", None), "location", None
                        )
                        room = str(device_location.name) if device_location else None

                    elif vm:
                        location = vm.site.name if vm.site else ""
                        url = vm.get_absolute_url()
                        description = vm.description or vm.comments or ""
                        role = vm.role or ""
                    else:
                        location = ""
                        url = ip.get_absolute_url()
                        description = ip.description or ""
                        role = ip.role or ""

                    if location not in locations:
                        locations.append(location)
                    color = color_for_location(locations.index(location))

                    machines.append(
                        {
                            "ip": str(ip.address.ip),
                            "prefix": str(prefix.prefix),
                            "dns_name": ip.dns_name or device or ip.description or "",
                            "location": location,
                            "room": room,
                            "physical": device is not None,
                            "url": url,
                            "description": description,
                            "color": color,
                            "role": role,
                        }
                    )
                    machine_count += 1

            vlan_element.machines = machines
            vlan_element.machine_count = machine_count
            elements.append(vlan_element)
        return elements

    def get(self, request):
        queryset = self.get_queryset()
        context = {
            "elements": self.build_elements(queryset),
        }
        return render(request, self.template_name, context)


class CenterDeviceMixin:
    """
    Finds the device that anchors the topology views: prefer firewalls, then
    gateways/routers, else the first active device with a primary IP.
    """

    def get_center_device(self):
        queryset = (
            Device.objects.filter(status="active", primary_ip4__isnull=False)
            .select_related("device_type", "site", "primary_ip4", "role")
            .order_by("site__name", "name")
        )
        for params in (["firewall", "fw"], ["gateway", "router", "edge"]):
            found = self._search_for_center_device(queryset, params)
            if found:
                return found
        return queryset.first()

    def _search_for_center_device(self, queryset: QuerySet[Device], params: list[str]):
        for candidate in queryset:
            role_name = getattr(getattr(candidate, "role", None), "name", "") or ""
            device_model = (
                getattr(getattr(candidate, "device_type", None), "model", "") or ""
            )
            device_name = getattr(candidate, "name", "") or ""
            if any(
                token in (role_name + " " + device_model + " " + device_name).lower()
                for token in params
            ):
                return candidate


class VlanTopologyView(CenterDeviceMixin, VlanElementListView):
    template_name = "network_map/vlan_topology.html"

    def decorate_elements(self, elements):
        """
        Give every subnet a representative color (the location that shows up
        most often among its machines) and order them so the largest subnets
        are drawn closest to the center of the topology.
        """
        for element in elements:
            colors = [
                machine["color"] for machine in element.machines if machine.get("color")
            ]
            if colors:
                element.color = Counter(colors).most_common(1)[0][0]
            else:
                element.color = "location-color-default"

        return sorted(elements, key=lambda element: element.machine_count, reverse=True)

    def serialize_topology(self, elements, center_device):
        center = {
            "name": "Main Gateway / Firewall",
            "ip": "",
            "url": "",
        }
        if center_device:
            center["name"] = str(center_device.name or center["name"])
            if center_device.primary_ip4:
                center["ip"] = str(center_device.primary_ip4.address.ip)
            center["url"] = center_device.get_absolute_url()

        subnets = []
        for element in elements:
            subnets.append(
                {
                    "name": str(element.name),
                    "prefix": str(element.prefix),
                    "url": element.url or "",
                    "machines": [
                        {
                            "name": str(machine["dns_name"] or machine["ip"]),
                            "ip": str(machine["ip"]),
                            "url": machine["url"] or "",
                            "location": str(machine["location"]),
                            "description": str(machine.get("description") or ""),
                        }
                        for machine in element.machines
                    ],
                }
            )

        return {"center": center, "subnets": subnets}

    def get(self, request):
        queryset = self.get_queryset()
        center_device = self.get_center_device()
        elements = self.decorate_elements(self.build_elements(queryset))
        context = {
            "elements": elements,
            "center_device": center_device,
            "topology_data": self.serialize_topology(elements, center_device),
        }
        return render(request, self.template_name, context)


class SubnetLocationView(VlanElementListView):
    template_name = "network_map/subnet_map.html"

    def build_site_plans(self, sites):
        """
        Map each site name to its first image attachment (used as the house
        plan shown when zooming into the building). Returns {} when the site
        has no uploaded plan, in which case the map falls back to a generic
        mock plan.
        """
        if not sites:
            return {}
        site_type = ContentType.objects.get_for_model(Site)
        plans = {}
        attachments = (
            ImageAttachment.objects.filter(
                object_type=site_type,
                object_id__in=[site.pk for site in sites],
            )
            .order_by("object_id", "id")
            .only("object_id", "image", "image_width", "image_height")
        )
        site_ids = {site.pk: str(site.name) for site in sites}
        for attachment in attachments:
            name = site_ids.get(attachment.object_id)
            if not name or name in plans:
                continue
            try:
                url = attachment.image.url
            except ValueError:
                continue
            plans[name] = {
                "url": url,
                "width": attachment.image_width or 1200,
                "height": attachment.image_height or 850,
            }
        return plans

    def build_site_locations(self, sites):
        """
        Map each site name to the list of its location (room) names, so the
        map can render a logical building layout including rooms that hold
        no devices.
        """
        if not sites:
            return {}
        locations = Location.objects.filter(site__in=sites).order_by(
            "site__name", "name"
        )
        tree = {}
        for location in locations:
            tree.setdefault(str(location.site.name), []).append(str(location.name))
        return tree

    def build_map_data(self, elements):
        """
        Group machines per subnet and site, so every subnet is drawn as one
        pin per site it has machines at, placed at the site's coordinates.
        """
        site_names = {
            machine["location"]
            for element in elements
            for machine in element.machines
            if machine["location"]
        }
        sites = list(Site.objects.filter(name__in=site_names))
        coordinates = geocode_sites(sites)

        site_plans = self.build_site_plans(sites)

        placements = {}
        for element in elements:
            if not element.machines:
                continue
            vlan_prefix = str(element.prefix) if element.prefix else ""
            for machine in element.machines:
                if not machine["location"]:
                    continue
                prefix = machine.get("prefix") or vlan_prefix
                key = (str(element.name), prefix)
                placement = placements.setdefault(
                    key,
                    {
                        "subnet": str(element.name),
                        "prefix": prefix,
                        "url": element.url or "",
                        "sites": {},
                    },
                )
                placement["sites"].setdefault(machine["location"], []).append(machine)

        pins = []
        unplaced = []
        # One base colour per subnet, its prefixes drawn in lighter and
        # darker shades of it, so several prefixes of one subnet read as a
        # family in the map, the floor plan and the SVG exports.
        subnet_base = {}
        subnet_prefixes = {}
        subnet_colors = {}
        for placement in placements.values():
            subnet = placement["subnet"]
            if subnet not in subnet_base:
                subnet_base[subnet] = color_for_location_hex(len(subnet_base))
            color_key = f"{subnet}|{placement['prefix']}"
            if color_key not in subnet_colors:
                seen = subnet_prefixes.setdefault(subnet, [])
                subnet_colors[color_key] = shade_of(subnet_base[subnet], len(seen))
                seen.append(placement["prefix"])

            placed_any = False
            for location, machines in placement["sites"].items():
                coords = coordinates.get(location)
                if not coords:
                    continue
                placed_any = True
                plan = site_plans.get(location) or {}
                pins.append(
                    {
                        "subnet": placement["subnet"],
                        "prefix": placement["prefix"],
                        "url": placement["url"],
                        "color": subnet_colors[color_key],
                        "site": str(location),
                        "lat": coords[0],
                        "lon": coords[1],
                        "plan_url": plan.get("url"),
                        "plan_w": plan.get("width"),
                        "plan_h": plan.get("height"),
                        "machines": [
                            {
                                "name": str(machine["dns_name"] or machine["ip"]),
                                "ip": str(machine["ip"]),
                                "description": str(machine.get("description") or ""),
                                "url": machine["url"] or "",
                                "room": machine.get("room"),
                                "physical": machine.get("physical", True),
                            }
                            for machine in machines
                        ],
                    }
                )

            if not placed_any:
                unplaced.append(
                    {
                        "subnet": placement["subnet"],
                        "prefix": placement["prefix"],
                        "url": placement["url"],
                        "locations": sorted(placement["sites"]),
                    }
                )

        canton_code = get_plugin_config(
            "network_map", "canton_boundary_code", DEFAULT_CANTON_BOUNDARY_CODE
        )
        canton_url = (
            reverse("plugins:network_map:canton_boundary")
            if resolve_canton_id(canton_code) is not None
            else None
        )

        return {
            "pins": pins,
            "unplaced": unplaced,
            "locations": self.build_site_locations(sites),
            "canton_boundary_url": canton_url,
            "canton_label": get_canton_label(canton_code) if canton_url else None,
            "ui": {
                "labels_show": _("Show labels"),
                "labels_hide": _("Hide labels"),
                "export_svg": _("Export as .SVG"),
                "export_png": _("Export as .PNG"),
                "export_failed": _("The export could not be created"),
                "machine": _("machine"),
                "machines": _("machines"),
                "subnet": _("subnet"),
                "subnets": _("subnets"),
                "details": _("Details"),
                "floor_map": _("Floor map"),
                "house_plan": _("House plan"),
                "badge_hint": _("scroll out to return to the map"),
                "logical_title": _("logical floor map"),
                "generated_from": _("generated from NetBox locations"),
                "no_location": _("No location"),
                "no_machines": _("No machines"),
                "machines_band": _("Machines"),
                "virtual": _("Virtual"),
                "other_rooms": _("Other rooms"),
                "vm": _("VM"),
                "vms": _("VMs"),
                "export_further_subnets": _("… further subnets not listed"),
                "export_outside_area": _("site(s) outside the drawn area"),
                "attribution": _("Map data: © swisstopo"),
            },
        }

    def get(self, request):
        queryset = self.get_queryset()
        elements = self.build_elements(queryset)
        context = {
            "elements": elements,
            "map_data": self.build_map_data(elements),
        }
        return render(request, self.template_name, context)


class CantonBoundaryView(NetworkMapPermissionRequiredMixin, View):
    """
    Serve the configured canton border as a WGS84 GeoJSON FeatureCollection,
    fetched from swisstopo and cached. Returns 204 when no canton is
    configured or the geometry cannot be resolved, so the map draws no border.
    """

    def get(self, request):
        canton_code = get_plugin_config(
            "network_map", "canton_boundary_code", DEFAULT_CANTON_BOUNDARY_CODE
        )
        boundary = get_canton_boundary(canton_code)
        if boundary is None:
            return HttpResponse(status=204)
        return JsonResponse(boundary, content_type="application/geo+json")


class VlanConnectionView(NetworkMapPermissionRequiredMixin, CenterDeviceMixin, View):
    def build_elements(self) -> list[dict]:
        element_obj = []

        results = search_backend.search(
            get_plugin_config(
                "network_map", "gateway_search_tag", DEFAULT_GATEWAY_SEARCH_TAG
            ),
            lookup=LookupTypes.EXACT,
        )

        for res in results:
            res_obj = res.object

            if hasattr(res_obj, "address"):
                if not res_obj.address:
                    continue

                current_prefix = (
                    Prefix.objects.filter(
                        prefix__net_contains_or_equals=res_obj.address
                    )
                    .select_related("vlan")
                    .first()
                )

                if current_prefix is None or current_prefix.vlan is None:
                    continue

                # Get the VLAN associated with the IP/prefix
                vlan = current_prefix.vlan

                # Get ALL prefixes belonging to this VLAN
                prefix = Prefix.objects.filter(vlan=vlan)

                prefixes = []
                for pref in prefix:
                    if pref is None:
                        continue

                    child_ips = []

                    for ip in pref.get_child_ips():
                        child_ips.append(self._get_ip_details(ip))

                    prefixes.append(self._get_prefix_details(pref, child_ips))

                element_obj.append(self._get_gateway_details(res_obj, vlan, prefixes))
        return element_obj

    def _get_device_vm_ip_details(self, ip: IPAddress) -> DetailsElement:
        assigned_object = getattr(ip, "assigned_object", None)
        device = getattr(assigned_object, "device", None)
        vm = getattr(assigned_object, "virtual_machine", None)

        details: DetailsElement
        if device:
            details = DetailsElement(
                id=device.pk,
                name=device.name,
                location=device.site.name if device.site else "",
                url=device.get_absolute_url(),
                description=str(device.description or device.role or ip.comments or ""),
                type="Device",
            )

        elif vm:
            details = DetailsElement(
                id=vm.pk,
                name=vm.name,
                location=vm.site.name if vm.site else "",
                url=vm.get_absolute_url(),
                description=vm.description or vm.comments or "",
                type="Virtual Machine",
            )

        else:
            details = DetailsElement(
                id=ip.pk,
                name=ip.dns_name,
                location="",
                url=ip.get_absolute_url(),
                description=ip.description or "",
                type="IP-Address",
            )

        return details

    def _get_ip_details(self, ip: IPAddress) -> IpDetailsElement:
        return IpDetailsElement(
            id=ip.pk,
            address=str(ip.address.ip),
            dns_name=ip.dns_name or "",
            description=ip.description or "",
            comments=ip.comments or "",
            role=ip.role or "",
            details=self._get_device_vm_ip_details(ip),
            url=ip.get_absolute_url(),
            type="IP-Address",
        )

    def _get_prefix_details(
        self, prefix: Prefix, child_ips: list[IpDetailsElement]
    ) -> PrefixElement:
        return PrefixElement(
            id=prefix.pk,
            prefix=str(prefix.prefix),
            ip_addresses=child_ips,
            type="Prefix",
        )

    def _get_gateway_details(
        self, result_object, vlan, prefixes: list[PrefixElement]
    ) -> GatewayElement:
        return GatewayElement(
            address=result_object.address,
            dns_name=result_object.dns_name,
            description=result_object.description,
            vlan=vlan,
            prefixes=prefixes,
            url=result_object.get_absolute_url(),
            type="VLAN / IP-Address",
        )

    def get(self, request):
        elements = self.build_elements()

        center_device = self.get_center_device()

        context = {
            "elements": elements,
            "center_device": center_device,
            # Info panel labels; extracted by makemessages and rendered
            # by the _info_item include (a plain variable there).
            "labels": {
                "address": _("Address"),
                "comments": _("Comments"),
                "dns_name": _("DNS Name"),
                "description": _("Description"),
                "gateway": _("Gateway"),
                "id": _("ID"),
                "ip_address": _("IP-Address"),
                "location": _("Location"),
                "name": _("Name"),
                "prefix": _("Prefix"),
                "role": _("Role"),
                "type": _("Type"),
                "vlan": _("VLAN"),
            },
        }

        return render(request, "network_map/vlan_connection.html", context)
