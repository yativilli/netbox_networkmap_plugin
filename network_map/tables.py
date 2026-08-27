from django.utils.translation import gettext_lazy as _
from netbox.tables import NetBoxTable

from .models import NetworkElement


class NetworkElementTable(NetBoxTable):
    class Meta(NetBoxTable.Meta):
        model = NetworkElement
        fields = ('pk', 'name', 'ip_address', 'device_type', 'location', 'actions')
        default_columns = ('name', 'ip_address', 'device_type', 'location')
