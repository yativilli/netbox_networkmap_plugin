from netbox.plugins import PluginMenuItem

menu_items = (
    PluginMenuItem(
        link='plugins:network_map:vlanelement_list',
        link_text='Machine List',
        permissions=['network_map.view_vlanelement'],
    ),
    PluginMenuItem(
        link='plugins:network_map:vlan_topology',
        link_text='Topology Map',
        permissions=['network_map.view_vlanelement'],
    )
)