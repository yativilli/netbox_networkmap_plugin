from django.db.models import Count 
from django.shortcuts import render
from django.views import View
from netbox.views import generic
from typing import List
from utilities.views import register_model_view
from dcim.models import Device

from .models import NetworkElement
from . import models
from .tables import NetworkElementTable

@register_model_view(models.NetworkElement, name='list', path='', detail=False)
class NetworkElementListView(generic.ObjectListView):
    queryset = models.NetworkElement.objects.annotate(
        device_count=Count('device_type')
    )
    filterset = None  # Add your filterset if needed
    table = NetworkElementTable
    template_name = 'network_map/networkelement_list.html'

class NetworkElementTopologyView(View):
    template_name = 'network_map/networkelement_topology.html'

    def get_queryset(self):
        return (Device.objects.filter(status="active", primary_ip4__isnull=False).select_related("device_type", "site", "primary_ip4"))

    def build_elements(self, queryset) -> List[NetworkElement]:
        elements = []
        for device in queryset:
            ip = None
            if device.primary_ip4:
                ip = device.primary_ip4.address.ip

            elements.append(NetworkElement(
                name = device.name,
                ip_address = ip,
                device_type = device.device_type.model if device.device_type else None,
                location = device.site.name if device.site else None
            ))
        return elements

    def get(self, request):
        queryset = self.get_queryset()
        elements = self.build_elements(queryset)
        context = {
            'elements': elements
        }
        return render(request, self.template_name, context)