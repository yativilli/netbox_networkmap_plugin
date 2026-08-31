from django.db import models
from netbox.models import NetBoxModel
from .choices import LocationChoices, DeviceChoices

class NetworkElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(max_length=50, choices=DeviceChoices)
    location = models.CharField(max_length=100, choices=LocationChoices)
    role = models.CharField(max_length=50)
    tags = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=20)

    def __init__(self, *args, **kwargs):
        self.description = kwargs.pop('description', None)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

    @classmethod
    def from_device(cls, device, description='-'):
        ip_address = None
        if device.primary_ip4:
            ip_address = str(device.primary_ip4.address)

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
        )

class VlanElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    group = models.CharField(max_length=100)
    prefix = models.CharField(max_length=60)
    status = models.CharField(max_length=20)
    role = models.CharField(max_length=50)
    description = models.TextField(max_length=500, blank=True)

    def __init__(self, *args, **kwargs):
        self.machines = kwargs.pop('machines', [])
        super().__init__(*args, **kwargs)

    @classmethod
    def from_vlan(cls, vlan, machines=None):
        vlan_element = cls(
            id=vlan.pk,
            name=vlan.name or f"VLAN {vlan.vid}",
            group=vlan.group.name if vlan.group else 'None',
            prefix=str(vlan.vid) if vlan.vid is not None else 'None',
            status=getattr(vlan.status, 'label', vlan.status) or 'None',
            role=vlan.role.name if vlan.role else 'None',
            description=vlan.description or 'None',
            machines=machines or [],
        )
        return vlan_element