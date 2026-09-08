from netbox.plugins import PluginConfig

class NetworkMapConfig(PluginConfig):
    name = "network_map"
    verbose_name = "Netbox Network Map"
    description = "A simple plugin displaying the relations of vlans in netbox"
    version = '0.1.0'
    base_url = 'networkmap'
    min_version = '4.5.0'
    max_version = '4.7.99'
    author = "Yannick Wernle"
    author_email = "yannick@wernle.net"
    license = 'GPL-3.0'   # <--- Make sure this is a string
    author_url = 'https://github.com/yativilli/netbox_networkmap_plugin' 

config = NetworkMapConfig