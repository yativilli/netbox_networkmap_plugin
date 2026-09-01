import ipaddress

from django.db.models import Q
from django.shortcuts import render
from django.views import View
from typing import List, Dict
from dcim.models import Device, Interface
from ipam.models import VLAN, IPAddress

from .models import NetworkElement, VlanElement
from .colors import color_for_location, location_color_map


class VlanElementListView(View):
    template_name = 'network_map/vlanelement_list.html'

    def get_queryset(self):
        return (
            VLAN.objects
            .select_related('group', 'role', 'site')
            .prefetch_related('prefixes')
            .order_by('group__name', 'vid')
        )

    def get_vlan_networks(self, vlan):
        networks = []
        for prefix in vlan.prefixes.all():
            if prefix.prefix:
                try:
                    networks.append(ipaddress.ip_network(prefix.prefix, strict=False))
                except ValueError:
                    continue
        return networks

    def dedupe_machines(self, machines):
        deduped = []
        by_name = {}
        by_ip = {}

        for machine in machines:
            name = (machine.name or 'None').strip()
            ip_value = (machine.ip_address or 'None').strip()
            if name == 'None':
                name = None
            if ip_value == 'None':
                ip_value = None

            name_key = name.lower() if name else None
            ip_key = ip_value if ip_value else None

            if name_key and name_key in by_name:
                existing = by_name[name_key]
                if ip_key and existing.ip_address in (None, 'None'):
                    existing.ip_address = ip_key
                if ip_key and existing.description in (None, 'None', '-') and machine.description not in (None, 'None', '-'):
                    existing.description = machine.description
                continue

            if ip_key and ip_key in by_ip:
                existing = by_ip[ip_key]
                if name_key and (existing.name in (None, 'None') or existing.name == '-'):
                    existing.name = name
                if existing.description in (None, 'None', '-') and machine.description not in (None, 'None', '-'):
                    existing.description = machine.description
                continue

            deduped.append(machine)
            if name_key:
                by_name[name_key] = machine
            if ip_key:
                by_ip[ip_key] = machine

        return deduped



    def build_elements(self, queryset):
        machines_by_vlan = {}

        interface_queryset = Interface.objects.filter(
            Q(untagged_vlan__in=queryset) | Q(tagged_vlans__in=queryset)
        ).select_related(
            'device',
            'device__primary_ip4',
            'untagged_vlan',
        ).prefetch_related('tagged_vlans', 'ip_addresses').distinct()

        for interface in interface_queryset:
            if not interface.device:
                continue

            device = interface.device
            description = getattr(device, 'description', '') or getattr(interface, 'description', '') or '-'
            machine = NetworkElement.from_device(device, description=description)
            if not machine.name:
                machine.name = 'None'
            if not machine.ip_address or machine.ip_address == '0.0.0.0':
                machine.ip_address = 'None'
            if not machine.description:
                machine.description = 'None'

            vlan_ids = set()
            if interface.untagged_vlan_id:
                vlan_ids.add(interface.untagged_vlan_id)
            vlan_ids.update(interface.tagged_vlans.values_list('id', flat=True))

            for vlan_id in vlan_ids:
                machines_by_vlan.setdefault(vlan_id, [])
                machines_by_vlan[vlan_id].append(machine)

        for vlan in queryset:
            networks = self.get_vlan_networks(vlan)
            if not networks:
                continue

            for ip_address in IPAddress.objects.filter(address__isnull=False):
                if not ip_address.address:
                    continue

                ip_value = str(ip_address.address.ip)
                try:
                    ip_obj = ipaddress.ip_address(ip_value)
                except ValueError:
                    continue

                if not any(ip_obj in network for network in networks):
                    continue

                assigned_object = getattr(ip_address, 'assigned_object', None)
                if assigned_object is None:
                    continue

                name = 'None'
                description = getattr(ip_address, 'description', None) or 'None'
                location = 'None'

                if hasattr(assigned_object, 'device') and assigned_object.device:
                    device = assigned_object.device
                    name = getattr(device, 'name', None) or 'None'
                    location = getattr(device.site, 'name', None) or 'None'
                    if not description or description == 'None':
                        description = getattr(device, 'description', None) or 'None'
                elif hasattr(assigned_object, 'name') and assigned_object.name:
                    name = assigned_object.name
                elif hasattr(assigned_object, 'interface') and assigned_object.interface:
                    interface = assigned_object.interface
                    name = getattr(interface, 'name', None) or 'None'
                    location = getattr(getattr(interface, 'device', None), 'site', None)
                    location = getattr(location, 'name', None) or 'None'
                    if not description or description == 'None':
                        description = getattr(interface, 'description', None) or 'None'

                machine_url = None
                if hasattr(assigned_object, 'get_absolute_url'):
                    try:
                        machine_url = assigned_object.get_absolute_url()
                    except Exception:
                        machine_url = None

                machine = NetworkElement(
                    id=getattr(assigned_object, 'pk', 0),
                    name=name or 'None',
                    ip_address=ip_value or 'None',
                    device_type='None',
                    location=location or 'None',
                    role='None',
                    tags='',
                    color='location-color-default',
                    description=description or 'None',
                    url=machine_url,
                )
                machines_by_vlan.setdefault(vlan.pk, [])
                machines_by_vlan[vlan.pk].append(machine)

        elements = []
        for vlan in queryset:
            machine_list = self.dedupe_machines(machines_by_vlan.get(vlan.pk, []))
            machine_list = sorted(machine_list, key=lambda item: (item.name, item.ip_address))

            color_map = location_color_map([m.location or 'None' for m in machine_list])
            for machine in machine_list:
                machine.color = color_map.get(machine.location or 'None', 'location-color-default')

            vlan_element = VlanElement.from_vlan(vlan, machines=machine_list)
            vlan_element.name = vlan_element.name or 'None'
            vlan_element.group = vlan_element.group or 'None'
            vlan_element.status = vlan_element.status or 'None'
            vlan_element.role = vlan_element.role or 'None'
            vlan_element.description = vlan_element.description or 'None'
            vlan_element.color = next(
                (machine.color for machine in machine_list if getattr(machine, 'color', None)),
                'location-color-default',
            )
            elements.append(vlan_element)
        return elements

    def get(self, request):
        queryset = self.get_queryset()
        context = {
            'elements': self.build_elements(queryset),
        }
        return render(request, self.template_name, context)


class NetworkElementTopologyView(View):
    template_name = 'network_map/networkelement_topology.html'

    def get_queryset(self):
        return (Device.objects.filter(status="active", primary_ip4__isnull=False).select_related("device_type", "site", "primary_ip4", "role").order_by("site"))

    def build_elements(self, queryset) -> List[NetworkElement]:
        elements = []
        for device in queryset:
            ip = None
            if device.primary_ip4:
                ip = device.primary_ip4.address.ip

            location = device.site.name if device.site else "None"

            elements.append(NetworkElement(
                name = device.name,
                ip_address = ip,
                device_type = device.device_type.model if device.device_type else "None",
                location = location,
                role = device.role.name if device.role else "None",
                tags = [tag.name for tag in device.tags.all()],
                color="location-color-default"
            ))
        return elements

    def build_legend(self, elements: List[NetworkElement]) -> Dict[str, str]:
        locations = sorted({element.location or "Unknown" for element in elements})
        location_colors = location_color_map(locations)
        legend = {}
        for element in elements:
            key = element.location or "Unknown"
            element.color = location_colors.get(key, 'location-color-default')
            legend[key] = element.color
        return legend

    def get(self, request):
        queryset = self.get_queryset()
        elements = self.build_elements(queryset)
        legend = self.build_legend(elements)
        context = {
            'elements': elements,
            'legend': legend,
        }
        return render(request, self.template_name, context)

