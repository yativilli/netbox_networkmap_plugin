from django.db.models import Count, Q
from django.shortcuts import render
from django.views import View
from netbox.views import generic
from typing import List, Dict
from utilities.views import register_model_view
from dcim.models import Device, Interface
from ipam.models import VLAN

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
            VLAN.objects.filter(status='active')
            .select_related('group', 'role', 'site')
            .order_by('group__name', 'vid')
        )

    def build_elements(self, queryset):
        machines_by_vlan = {}
        interface_queryset = Interface.objects.filter(
            Q(untagged_vlan__in=queryset) | Q(tagged_vlans__in=queryset)
        ).select_related(
            'device',
            'device__primary_ip4',
            'untagged_vlan',
        ).prefetch_related('tagged_vlans').distinct()

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
                machines_by_vlan.setdefault(vlan_id, {})
                key = (machine.name, machine.ip_address)
                machines_by_vlan[vlan_id][key] = machine

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

