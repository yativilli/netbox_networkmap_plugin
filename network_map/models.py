from django.db import models
from netbox.models import NetBoxModel


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
        self.machines = kwargs.pop("machines", [])
        self.url = kwargs.pop("url", None)
        super().__init__(*args, **kwargs)

    @classmethod
    def from_vlan(cls, vlan, machines=None):
        prefixes = sorted(
            {
                str(prefix.prefix)
                for prefix in vlan.prefixes.all()
                if getattr(prefix, "prefix", None)
            },
            key=lambda value: value,
        )
        prefix_value = ", ".join(prefixes) if prefixes else "None"

        url = None
        if hasattr(vlan, "get_absolute_url"):
            url = vlan.get_absolute_url()

        machine_count = len(machines or [])

        vlan_element = cls(
            id=vlan.pk,
            name=vlan.name or f"VLAN {vlan.vid}",
            group=vlan.group.name if vlan.group else "None",
            prefix=prefix_value,
            status=getattr(vlan.status, "label", vlan.status) or "None",
            role=vlan.role.name if vlan.role else "None",
            machine_count=machine_count,
            description=vlan.description or "None",
            machines=machines or [],
            url=url,
        )
        return vlan_element


class DetailsElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=100)
    url = models.CharField(max_length=100)
    description = models.CharField(max_length=100)
    type = models.CharField(max_length=100)


class IpDetailsElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    address = models.GenericIPAddressField()
    dns_name = models.CharField(max_length=100)
    description = models.CharField(max_length=100)
    comments = models.CharField(max_length=200)
    role = models.CharField(max_length=100)
    details = models.JSONField(default=list)
    url = models.CharField(max_length=100)
    type = models.CharField(max_length=100)


class PrefixElement(NetBoxModel):
    id = models.CharField(primary_key=True)
    prefix = models.CharField(max_length=100)
    ip_addresses = models.JSONField(default=list)
    type = models.CharField(max_length=100)


class GatewayElement(NetBoxModel):
    address = models.GenericIPAddressField()
    dns_name = models.CharField(max_length=100)
    description = models.CharField(max_length=100)
    vlan = models.JSONField(default=list)
    prefixes = models.JSONField(default=list)
    url = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
