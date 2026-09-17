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
        # Primary border geometry source: swisstopo WFS, whose raw polygon
        # carries interior rings (holes), so neighbouring-canton pockets are
        # excluded from the drawn area. {id} is replaced with the canton's
        # BFS number; srsName=EPSG:4326 gives WGS84 lon/lat for the map.
        "canton_boundary_url_template": (
            "https://wfs.geo.admin.ch/?service=WFS&version=2.0.0&request=GetFeature"
            "&typeNames=ch.swisstopo.swissboundaries3d-kanton-flaeche.fill"
            "&outputFormat=application%2Fjson&srsName=EPSG%3A4326&CQL_FILTER=id%3D{id}"
        ),
        # Fallback border geometry source: OpenStreetMap/Nominatim, used
        # automatically when the WFS source is unreachable or malformed. Its
        # polygon_geojson response also carries interior rings, so pockets
        # such as Steinhof SO are still excluded. {code} is replaced with the
        # canton's ISO/CH code (e.g. CH-BE). Set to "" to disable.
        "canton_boundary_fallback_url_template": (
            "https://nominatim.openstreetmap.org/search?q=CH-{code}"
            "&countrycodes=ch&featuretype=country_subdivision"
            "&polygon_geojson=1&format=json&limit=1"
        ),
        # Last-resort border geometry source: the hole-less
        # map.geo.admin.ch feature endpoint. Used when the hole-carrying WFS
        # and Nominatim sources both fail, so the border remains visible.
        # {id} is replaced with the BFS number. Set to "" to disable.
        "canton_boundary_last_resort_url_template": (
            "https://api3.geo.admin.ch/rest/services/api/MapServer"
            "/ch.swisstopo.swissboundaries3d-kanton-flaeche.fill/{id}"
            "?geometry=true&returnGeometry=true&sr=4326&f=json"
        ),
        # Cache lifetime (seconds) for the fetched border geometry.
        "canton_boundary_cache_seconds": 60 * 60 * 24 * 30,
    }


config = NetworkMapConfig
