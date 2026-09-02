import ipaddress

from django.shortcuts import render
from django.views import View
from typing import List, Dict
from dcim.models import Device
from ipam.models import VLAN, IPAddress, Prefix

from .models import NetworkElement, VlanElement
from .colors import color_for_location, location_color_map


class VlanElementListView(View):
    template_name = 'network_map/vlanelement_list.html'

    def get_queryset(self):
        queryset = (
            VLAN.objects
            .select_related("group", "role", "site")
            .prefetch_related("prefixes")
            .order_by("group__name", "vid")
        )

        return queryset

    def build_elements(self, queryset):
        """
        Build VLAN elements without machine data.
        """
        elements = []
        for vlan in queryset:
            machines = []
            vlan_element = VlanElement.from_vlan(vlan, machines=[])
            vlan_element.name = vlan_element.name or 'None'
            vlan_element.group = vlan_element.group or 'None'
            vlan_element.status = vlan_element.status or 'None'
            vlan_element.role = vlan_element.role or 'None'
            vlan_element.description = vlan_element.description or 'None'
            
            related_prefixes = list(vlan.prefixes.all())
            machine_count = 0
            for prefix in related_prefixes:
                active_ips = IPAddress.objects.filter(
                    status__in=["active", "reserved"],
                    address__net_contained_or_equal=prefix.prefix,
                    dns_name__isnull=False
                ).order_by("address")

                for ip in active_ips:
                    if ip.dns_name:
                        assigned_object = getattr(ip, "assigned_object", None)
                        device = getattr(assigned_object, "device", None)
                        vm = getattr(assigned_object, "virtual_machine", None)
            
                        if device:
                            location = device.site.name if device.site else 'None'
                            url = device.get_absolute_url()
                            description = device.description or device.device_type.model or ip.comments or 'None'
                            
                        elif vm:
                            location = vm.site.name if vm.site else 'None'
                            url = vm.get_absolute_url()
                            description = vm.description or vm.comments or 'None'
                        else:
                            location = 'None'
                            url = None
                            description = getattr(assigned_object, "description", None) or 'None'

                        machines.append({
                            "ip": str(ip.address.ip),
                            "dns_name": ip.dns_name or 'None',
                            "location": location,
                            "url": url,
                            "description": description
                        })
                        machine_count += 1
                        
            vlan_element.machines = machines
            vlan_element.machine_count = machine_count
            elements.append(vlan_element)
        return elements

    def get(self, request):
        queryset = self.get_queryset()
        context = {
            'elements': self.build_elements(queryset),
        }
        return render(request, self.template_name, context)


class VlanTopologyView(VlanElementListView):
    template_name = 'network_map/vlan_topology.html'

    def get_center_device(self):
        queryset = (
            Device.objects.filter(status='active', primary_ip4__isnull=False)
            .select_related('device_type', 'site', 'primary_ip4', 'role')
            .order_by('site__name', 'name')
        )

        for candidate in queryset:
            role_name = getattr(getattr(candidate, 'role', None), 'name', '') or ''
            device_model = getattr(getattr(candidate, 'device_type', None), 'model', '') or ''
            device_name = getattr(candidate, 'name', '') or ''

            if any(token in (role_name + ' ' + device_model + ' ' + device_name).lower() for token in ('firewall', 'fw')):
                return candidate

        for candidate in queryset:
            role_name = getattr(getattr(candidate, 'role', None), 'name', '') or ''
            device_model = getattr(getattr(candidate, 'device_type', None), 'model', '') or ''
            device_name = getattr(candidate, 'name', '') or ''

            if any(token in (role_name + ' ' + device_model + ' ' + device_name).lower() for token in ('gateway', 'router', 'edge')):
                return candidate

        return queryset.first()

    def get(self, request):
        queryset = self.get_queryset()
        center_device = self.get_center_device()
        context = {
            'elements': self.build_elements(queryset),
            'center_device': center_device,
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

