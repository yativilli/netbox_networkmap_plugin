from django.db import models
from netbox.models import NetBoxModel

class NetworkElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(max_length=100)
    location = models.CharField(max_length=100)
    role = models.CharField(max_length=50)
    tags = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=20)

    def __init__(self, *args, **kwargs):
        self.description = kwargs.pop('description', None)
        self.url = kwargs.pop('url', None)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

    @classmethod
    def from_device(cls, device, description='-'):
        ip_address = None
        if device.primary_ip4:
            ip_address = str(device.primary_ip4.address)

        url = None
        if hasattr(device, 'get_absolute_url'):
            try:
                url = device.get_absolute_url()
            except Exception:
                url = None

        return cls(
            id=device.pk,
            name=device.name or 'None',
            ip_address=ip_address or 'None',
            device_type=getattr(device.device_type, 'model', None) or 'None',
            location=getattr(device.site, 'name', None) or 'None',
            role=getattr(device.role, 'name', None) or 'None',
            tags='',
            color='location-color-default',
            description=description or 'None',
            url=url,
        )

class VlanElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    group = models.CharField(max_length=100)
    prefix = models.CharField(max_length=60)
    status = models.CharField(max_length=20)
    role = models.CharField(max_length=50)
    machine_count = models.IntegerField(default=0)
    description = models.TextField(max_length=500, blank=True)

    def __init__(self, *args, **kwargs):
        self.machines = kwargs.pop('machines', [])
        self.url = kwargs.pop('url', None)
        super().__init__(*args, **kwargs)

    @classmethod
    def from_vlan(cls, vlan, machines=None):
        prefixes = sorted(
            {str(prefix.prefix) for prefix in vlan.prefixes.all() if getattr(prefix, 'prefix', None)},
            key=lambda value: value,
        )
        prefix_value = ', '.join(prefixes) if prefixes else 'None'

        url = None
        if hasattr(vlan, 'get_absolute_url'):
            try:
                url = vlan.get_absolute_url()
            except Exception:
                url = None

        machine_count = len(machines or [])

        vlan_element = cls(
            id=vlan.pk,
            name=vlan.name or f"VLAN {vlan.vid}",
            group=vlan.group.name if vlan.group else 'None',
            prefix=prefix_value,
            status=getattr(vlan.status, 'label', vlan.status) or 'None',
            role=vlan.role.name if vlan.role else 'None',
            machine_count=machine_count,
            description=vlan.description or 'None',
            machines=machines or [],
            url=url,
        )
        return vlan_element