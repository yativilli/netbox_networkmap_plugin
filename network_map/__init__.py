from netbox.plugins import PluginConfig

class NetworkMapConfig(PluginConfig):
    name = "network_map"
    verbose_name = "Netbox Network Map"
    description = "A simple network map integrated into netbox"
    version = '0.1.0'
    base_url = 'networkmap'
    min_version = '4.5.0'
    max_version = '4.7.99'

config = NetworkMapConfig