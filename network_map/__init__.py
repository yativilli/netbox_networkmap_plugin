from typing import ClassVar

from netbox.plugins import PluginConfig

from .defaults import DEFAULT_CANTON_BOUNDARY_CODE, DEFAULT_GATEWAY_SEARCH_TAG

__version__ = "0.1.0"


class NetworkMapConfig(PluginConfig):
    name = "network_map"
    verbose_name = "Netbox Network Map"
    description = "A simple plugin displaying the relations of vlans in netbox"
    version = __version__
    base_url = "networkmap"
    min_version = "4.5.0"
    max_version = "4.7.99"
    author = "Yannick Wernle"
    author_email = "yannick@wernle.net"
    license = "GPL-3.0"
    author_url = "https://github.com/yativilli/netbox_networkmap_plugin"
    default_settings: ClassVar[dict] = {
        "gateway_search_tag": DEFAULT_GATEWAY_SEARCH_TAG,
        "canton_boundary_code": DEFAULT_CANTON_BOUNDARY_CODE,
    }


config = NetworkMapConfig
