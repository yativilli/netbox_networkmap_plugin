from typing import ClassVar

from netbox.plugins import PluginConfig

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
        # Canton whose border is drawn on the subnet map, as a two-letter
        # code (e.g. "BE", "AG") or the numeric BFS canton id. Empty means
        # no border is drawn. The geometry is fetched live from swisstopo,
        # so no boundary file is shipped with the plugin.
        "canton_boundary_code": "BE",
        # Legend label for the border (a proper noun, shown untranslated).
        # Defaults to the canton name when left empty.
        "canton_boundary_label": "",
        # swisstopo feature URL template used to fetch the border. {id} is
        # replaced with the canton's feature id (the BFS canton number). Keep
        # sr=4326 so the coordinates arrive as WGS84 lon/lat for the map.
        "canton_boundary_url_template": (
            "https://api3.geo.admin.ch/rest/services/api/MapServer"
            "/ch.swisstopo.swissboundaries3d-kanton-flaeche.fill/{id}"
            "?geometry=true&returnGeometry=true&sr=4326&f=json"
        ),
        # Cache lifetime (seconds) for the fetched border geometry.
        "canton_boundary_cache_seconds": 60 * 60 * 24 * 30,
    }


config = NetworkMapConfig
