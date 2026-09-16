from dataclasses import dataclass, field
from typing import Any

from django.db import models


class VlanElement(models.Model):
    """
    Unmanaged anchor model providing the content type and the
    network_map.view_vlanelement permission used by the plugin menu and
    views. No instances are ever stored in the database.
    """

    class Meta:
        managed = False
        default_permissions = ("view",)


@dataclass
class VlanInfo:
    id: int
    name: str
    group: str
    prefix: str
    status: str
    role: str
    machine_count: int = 0
    description: str = ""
    machines: list[dict] = field(default_factory=list)
    url: str | None = None
    color: str = ""

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

        return cls(
            id=vlan.pk,
            name=vlan.name or f"VLAN {vlan.vid}",
            group=vlan.group.name if vlan.group else "None",
            prefix=prefix_value,
            status=getattr(vlan.status, "label", vlan.status) or "None",
            role=vlan.role.name if vlan.role else "None",
            machine_count=len(machines or []),
            description=vlan.description or "None",
            machines=machines or [],
            url=url,
        )


@dataclass
class DetailsElement:
    id: int
    name: str
    location: str
    url: str
    description: str
    type: str


@dataclass
class IpDetailsElement:
    id: int
    address: str
    dns_name: str
    description: str
    comments: str
    role: str
    details: DetailsElement
    url: str
    type: str


@dataclass
class PrefixElement:
    id: int
    prefix: str
    ip_addresses: list[IpDetailsElement] = field(default_factory=list)
    type: str = "Prefix"


@dataclass
class GatewayElement:
    address: str
    dns_name: str
    description: str
    vlan: Any
    prefixes: list[PrefixElement] = field(default_factory=list)
    url: str = ""
    type: str = ""
