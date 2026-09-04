
from django.shortcuts import render
from django.views import View
from dcim.models import Device
from ipam.models import VLAN, IPAddress, Prefix

from .models import VlanElement
from .colors import color_for_location

from netbox.search import LookupTypes
from netbox.search.backends import search_backend

class VlanElementListView(View):
    template_name = 'network_map/vlan_element_list.html'

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
        locations = []
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
                        assigned_object = getattr(ip, "assigned_object", None)
                        device = getattr(assigned_object, "device", None)
                        vm = getattr(assigned_object, "virtual_machine", None)
            
                        if device:
                            location = device.site.name if device.site else 'None'
                            url = device.get_absolute_url()
                            description = device.description or device.role or ip.comments or 'None'
                            
                        elif vm:
                            location = vm.site.name if vm.site else 'None'
                            url = vm.get_absolute_url()
                            description = vm.description or vm.comments or 'None'
                        else:
                            location = 'None'
                            url = ip.get_absolute_url()
                            description = ip.description or 'None'
                            
                        if location not in locations:
                            locations.append(location)
                        color = color_for_location(locations.index(location))

                        machines.append({
                            "ip": str(ip.address.ip),
                            "dns_name": ip.dns_name or device or ip.description or 'None',
                            "location": location,
                            "url": url,
                            "description": description,
                            "color": color
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
    
class VlanConnectionView(View):
    def get_queryset(self):
        queryset = (
            VLAN.objects
            .select_related("group", "role", "site")
            .prefetch_related("prefixes")
            .order_by("group__name", "vid")
        )
        
        return queryset
    
    def build_elements(self, queryset) -> list[dict]:
        element_obj = []

        results = search_backend.search(
            "N0000107",
            lookup=LookupTypes.EXACT,
        )

        for res in results:
            res_obj = res.object.__dict__.copy()
            res_obj.pop("_state", None)

            address = res_obj.get("address")

            if not address:
                continue

            prefix = Prefix.objects.filter(
                prefix__net_contains_or_equals=address
            ).first()

            if prefix is None:
                continue

            child_ips = []

            for ip in prefix.get_child_ips():
                details = {}

                ip_query = IPAddress.objects.filter(
                    address=ip.address
                ).first()

                if ip_query is not None:
                    assigned_object = getattr(ip, "assigned_object", None)
                    device = getattr(assigned_object, "device", None)
                    vm = getattr(assigned_object, "virtual_machine", None)

                    if device:
                        pk = device.pk
                        name = device.name
                        location = device.site.name if device.site else "None"
                        url = device.get_absolute_url()
                        description = str(
                            device.description
                            or device.role
                            or ip.comments
                            or "None"
                        )

                    elif vm:
                        pk = vm.pk
                        name = vm.name
                        location = vm.site.name if vm.site else "None"
                        url = vm.get_absolute_url()
                        description = vm.description or vm.comments or "None"

                    else:
                        pk = ip.pk
                        name = ip.dns_name
                        location = "None"
                        url = ip.get_absolute_url()
                        description = ip.description or "None"

                    details = {
                        "pk": pk,
                        "name": name,
                        "location": location,
                        "url": url,
                        "description": description,
                    }

                child_ips.append({
                    "pk": ip.pk,
                    "address": str(ip.address.ip),
                    "dns_name": ip.dns_name or "None",
                    "description": ip.description or "None",
                    "comments": ip.comments or "None",
                    "role": ip.role or "None",
                    "details": details,
                })

            element_obj.append({
                "address": address,
                "dns_name": res_obj.get("dns_name"),
                "description": res_obj.get("description"),
                "prefix": {
                    "id": prefix.pk,
                    "prefix": str(prefix.prefix),
                    "ip_addresses": child_ips,
                },
            })

        return element_obj

        
    
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
                return device_name

        for candidate in queryset:
            role_name = getattr(getattr(candidate, 'role', None), 'name', '') or ''
            device_model = getattr(getattr(candidate, 'device_type', None), 'model', '') or ''
            device_name = getattr(candidate, 'name', '') or ''

            if any(token in (role_name + ' ' + device_model + ' ' + device_name).lower() for token in ('gateway', 'router', 'edge')):
                return candidate

        return queryset.first()
    
    def get(self, request):
        queryset = self.get_queryset()
        elements = self.build_elements(queryset)
        context = {
            "elements": elements,
            "center_device": self.get_center_device()
        }
        return render(request, 'network_map/vlan_connection.html', context)