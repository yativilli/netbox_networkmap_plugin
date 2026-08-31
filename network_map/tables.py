from django.utils.translation import gettext_lazy as _
from netbox.tables import NetBoxTable

from .models import NetworkElement, VlanElement


class NetworkElementTable(NetBoxTable):
    class Meta(NetBoxTable.Meta):
        model = NetworkElement
        fields = ('pk', 'name', 'ip_address', 'device_type', 'location', 'actions')
        default_columns = ('name', 'ip_address', 'device_type', 'location')


class VlanElementTable(NetBoxTable):
    class Meta(NetBoxTable.Meta):
        model = VlanElement
        fields = ('pk', 'name', 'group', 'prefix', 'status', 'role', 'description', 'actions')
        default_columns = ('name', 'group', 'prefix', 'status', 'role')
