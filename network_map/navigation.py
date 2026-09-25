from django.utils.translation import gettext_lazy as _
from netbox.plugins import PluginMenuItem

menu_items = (
    PluginMenuItem(
        link="plugins:network_map:vlanelement_list",
        link_text=_("Machine List"),
        permissions=["network_map.view_vlanelement"],
    ),
    PluginMenuItem(
        link="plugins:network_map:vlan_connections",
        link_text=_("Logical Map"),
        permissions=["network_map.view_vlanelement"],
    ),
    PluginMenuItem(
        link="plugins:network_map:vlan_topology",
        link_text=_("Topology Map"),
        permissions=["network_map.view_vlanelement"],
    ),
    PluginMenuItem(
        link="plugins:network_map:subnet_map",
        link_text=_("Site Map"),
        permissions=["network_map.view_vlanelement"],
    ),
    PluginMenuItem(
        link="plugins:network_map:data_coverage",
        link_text=_("Data Coverage"),
        permissions=["network_map.view_vlanelement"],
    ),
)
