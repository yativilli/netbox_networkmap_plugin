from netbox.plugins import PluginMenuItem

menu_items = (
    PluginMenuItem(
        link='plugins:network_map:vlanelement_list',
        link_text='VLAN-Element Map',
        permissions=['network_map.view_vlanelement'],
    ),
    PluginMenuItem(
        link='plugins:network_map:vlan_topology',
        link_text='VLAN Topology Map',
        permissions=['network_map.view_vlanelement'],
    ),
    PluginMenuItem(
        link='plugins:network_map:networkelement_topology',
        link_text='Network Topology Map',
        permissions=['network_map.view_networkelement'],
    ),
)