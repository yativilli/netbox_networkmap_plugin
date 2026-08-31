import ipaddress

from django.db.models import Count
from django.shortcuts import render
from django.views import View
from netbox.views import generic
from typing import List, Dict
from utilities.views import register_model_view
from dcim.models import Device, Interface
from ipam.models import VLAN, IPAddress

from .models import NetworkElement, VlanElement
from . import models
from .colors import color_for_location
from .tables import NetworkElementTable

@register_model_view(models.NetworkElement, name='list', path='', detail=False)
class NetworkElementListView(generic.ObjectListView):
    queryset = models.NetworkElement.objects.annotate(
        device_count=Count('device_type')
    )
    filterset = None  # Add your filterset if needed
    table = NetworkElementTable
    template_name = 'network_map/networkelement_list.html'

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

    def get_vlan_ip_assignments(self, vlan):
        networks = self.get_vlan_networks(vlan)
        if not networks:
            return []

        assignments = []
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

            if hasattr(assigned_object, 'device') and assigned_object.device:
                device = assigned_object.device
                name = getattr(device, 'name', None) or 'None'
                if not description or description == 'None':
                    description = getattr(device, 'description', None) or 'None'
            elif hasattr(assigned_object, 'name') and assigned_object.name:
                name = assigned_object.name
            elif hasattr(assigned_object, 'interface') and assigned_object.interface:
                name = getattr(assigned_object.interface, 'name', None) or 'None'
                if not description or description == 'None':
                    description = getattr(assigned_object.interface, 'description', None) or 'None'

            assignments.append({
                'name': name,
                'ip_address': ip_value,
                'description': description,
                'id': getattr(assigned_object, 'pk', 0),
            })

        return assignments

    def build_elements(self, queryset):
        machines_by_vlan = {}

        for vlan in queryset:
            assignments = self.get_vlan_ip_assignments(vlan)
            for assignment in assignments:
                machine = NetworkElement(
                    id=assignment['id'],
                    name=assignment['name'] or 'None',
                    ip_address=assignment['ip_address'] or 'None',
                    device_type='None',
                    location='None',
                    role='None',
                    tags='',
                    color='location-color-default',
                    description=assignment['description'] or 'None',
                )
                machines_by_vlan.setdefault(vlan.pk, {})
                machines_by_vlan[vlan.pk][(machine.name, machine.ip_address)] = machine

        elements = []
        for vlan in queryset:
            machine_list = sorted(
                machines_by_vlan.get(vlan.pk, {}).values(),
                key=lambda item: (item.name, item.ip_address)
            )
            vlan_element = VlanElement.from_vlan(vlan, machines=machine_list)
            vlan_element.name = vlan_element.name or 'None'
            vlan_element.group = vlan_element.group or 'None'
            vlan_element.status = vlan_element.status or 'None'
            vlan_element.role = vlan_element.role or 'None'
            vlan_element.description = vlan_element.description or 'None'
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
        location_colors = {}
        for location in locations:
            location_colors[location] = color_for_location(len(location_colors))
        legend = {}
        for element in elements:
            key = element.location or "Unknown"
            element.color = location_colors[key]
            legend[key] = location_colors[key]
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

