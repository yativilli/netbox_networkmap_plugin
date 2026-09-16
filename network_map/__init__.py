from typing import ClassVar

from netbox.plugins import PluginConfig


class NetworkMapConfig(PluginConfig):
    name = "network_map"
    verbose_name = "Netbox Network Map"
    description = "A simple plugin displaying the relations of vlans in netbox"
    version = "0.1.0"
    base_url = "networkmap"
    min_version = "4.5.0"
    max_version = "4.7.99"
    author = "Yannick Wernle"
    author_email = "yannick@wernle.net"
    license = "GPL-3.0"
    author_url = "https://github.com/yativilli/netbox_networkmap_plugin"
    default_settings: ClassVar[dict] = {
        # Tag identifying gateway devices/addresses in the connection view
        "gateway_search_tag": "GATEWAY-TAG",
        # Nominatim instance used to geocode sites without coordinates
        "nominatim_url": "https://nominatim.openstreetmap.org/search",
        # Restrict geocoding to these country codes (comma separated)
        "country_codes": "ch",
        # Nominatim usage policy: at most one request per interval
        "request_interval_seconds": 1.0,
        # Per-request timeout for the geocoding HTTP call
        "request_timeout_seconds": 10,
    }


config = NetworkMapConfig
