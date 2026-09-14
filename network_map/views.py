from collections import Counter

from dcim.models import Device, Site
from django.db.models import QuerySet
from django.shortcuts import render
from django.views import View
from ipam.models import VLAN, IPAddress, Prefix
from netbox.search import LookupTypes
from netbox.search.backends import search_backend

from .colors import color_for_location, color_for_location_hex
from .geocoding import geocode_sites
from .models import (
    DetailsElement,
    GatewayElement,
    IpDetailsElement,
    PrefixElement,
    VlanElement,
)


class VlanElementListView(View):
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
            vlan_element = VlanElement.from_vlan(vlan, machines=[])
            vlan_element.name = vlan_element.name or "None"
            vlan_element.group = vlan_element.group or "None"
            vlan_element.status = vlan_element.status or "None"
            vlan_element.role = vlan_element.role or "None"
            vlan_element.description = vlan_element.description or "None"
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

                    if device:
                        location = device.site.name if device.site else "None"
                        url = device.get_absolute_url()
                        description = (
                            device.description or device.role or ip.comments or "None"
                        )
                        role = device.role or "None"

                    elif vm:
                        location = vm.site.name if vm.site else "None"
                        url = vm.get_absolute_url()
                        description = vm.description or vm.comments or "None"
                        role = vm.role or "None"
                    else:
                        location = "None"
                        url = ip.get_absolute_url()
                        description = ip.description or "None"
                        role = ip.role or "None"

                    if location not in locations:
                        locations.append(location)
                    color = color_for_location(locations.index(location))

                    machines.append(
                        {
                            "ip": str(ip.address.ip),
                            "prefix": str(prefix.prefix),
                            "dns_name": ip.dns_name
                            or device
                            or ip.description
                            or "None",
                            "location": location,
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


class VlanTopologyView(VlanElementListView):
    template_name = "network_map/vlan_topology.html"

    def get_center_device(self):
        queryset = (
            Device.objects.filter(status="active", primary_ip4__isnull=False)
            .select_related("device_type", "site", "primary_ip4", "role")
            .order_by("site__name", "name")
        )

        if self._search_for_center_device(queryset, ["firewall", "fw"]):
            return self._search_for_center_device(queryset, ["firewall", "fw"])

        if self._search_for_center_device(queryset, ["gateway", "router", "edge"]):
            return self._search_for_center_device(
                queryset, ["gateway", "router", "edge"]
            )

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
            "center_device_url": (
                center_device.get_absolute_url() if center_device else None
            ),
            "topology_data": self.serialize_topology(elements, center_device),
        }
        return render(request, self.template_name, context)


class SubnetLocationView(VlanElementListView):
    template_name = "network_map/subnet_map.html"

    def build_map_data(self, elements):
        """
        Group machines per subnet and site, so every subnet is drawn as one
        pin per site it has machines at, placed at the site's coordinates.
        """
        site_names = {
            machine["location"]
            for element in elements
            for machine in element.machines
            if machine["location"] != "None"
        }
        coordinates = geocode_sites(Site.objects.filter(name__in=site_names))

        placements = {}
        for element in elements:
            if not element.machines:
                continue
            vlan_prefix = str(element.prefix) if element.prefix else ""
            for machine in element.machines:
                if machine["location"] == "None":
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
        subnet_colors = {}
        for placement in placements.values():
            color_key = f"{placement['subnet']}|{placement['prefix']}"
            if color_key not in subnet_colors:
                subnet_colors[color_key] = color_for_location_hex(len(subnet_colors))

            placed_any = False
            for location, machines in placement["sites"].items():
                coords = coordinates.get(location)
                if not coords:
                    continue
                placed_any = True
                pins.append(
                    {
                        "subnet": placement["subnet"],
                        "prefix": placement["prefix"],
                        "url": placement["url"],
                        "color": subnet_colors[color_key],
                        "site": str(location),
                        "lat": coords[0],
                        "lon": coords[1],
                        "machines": [
                            {
                                "name": str(machine["dns_name"] or machine["ip"]),
                                "ip": str(machine["ip"]),
                                "url": machine["url"] or "",
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

        return {"pins": pins, "unplaced": unplaced}

    def get(self, request):
        queryset = self.get_queryset()
        elements = self.build_elements(queryset)
        context = {
            "elements": elements,
            "map_data": self.build_map_data(elements),
        }
        return render(request, self.template_name, context)


class VlanConnectionView(View):
    def build_elements(self) -> list[dict]:
        element_obj = []

        results = search_backend.search(
            "GATEWAY-TAG",
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
                location=device.site.name if device.site else "None",
                url=device.get_absolute_url(),
                description=str(
                    device.description or device.role or ip.comments or "None"
                ),
                type="Device",
            )

        elif vm:
            details = DetailsElement(
                id=vm.pk,
                name=vm.name,
                location=vm.site.name if vm.site else "None",
                url=vm.get_absolute_url(),
                description=vm.description or vm.comments or "None",
                type="Virtual Machine",
            )

        else:
            details = DetailsElement(
                id=ip.pk,
                name=ip.dns_name,
                location="None",
                url=ip.get_absolute_url(),
                description=ip.description or "None",
                type="IP-Address",
            )

        return details

    def _get_ip_details(self, ip: IPAddress) -> IpDetailsElement:
        return IpDetailsElement(
            pk=ip.pk,
            address=str(ip.address.ip),
            dns_name=ip.dns_name or "None",
            description=ip.description or "None",
            comments=ip.comments or "None",
            role=ip.role or "None",
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

    def get_center_device(self):
        queryset = (
            Device.objects.filter(status="active", primary_ip4__isnull=False)
            .select_related(
                "device_type",
                "site",
                "primary_ip4",
                "role",
            )
            .order_by("site__name", "name")
        )

        if self._search_for_center_device(queryset, ["firewall", "fw"]):
            return self._search_for_center_device(queryset, ["firewall", "fw"])

        if self._search_for_center_device(queryset, ["gateway", "router", "edge"]):
            return self._search_for_center_device(
                queryset, ["gateway", "router", "edge"]
            )

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

    def get(self, request):
        elements = self.build_elements()

        center_device = self.get_center_device()

        context = {
            "elements": elements,
            "center_device": center_device,
            "center_device_url": (
                center_device.get_absolute_url() if center_device else None
            ),
        }

        return render(request, "network_map/vlan_connection.html", context)
