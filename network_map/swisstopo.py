import json
import logging
import urllib.error
import urllib.request

from django.core.cache import cache
from netbox.plugins import get_plugin_config

from . import __version__

logger = logging.getLogger(__name__)

# BFS / swisstopo canton numbers, keyed by the two-letter canton code.
# These are the feature ids of the swisstopo canton-area layer.
CANTON_IDS = {
    "ZH": 1,
    "BE": 2,
    "LU": 3,
    "UR": 4,
    "SZ": 5,
    "OW": 6,
    "NW": 7,
    "GL": 8,
    "ZG": 9,
    "FR": 10,
    "SO": 11,
    "BS": 12,
    "BL": 13,
    "SH": 14,
    "AR": 15,
    "AI": 16,
    "SG": 17,
    "GR": 18,
    "AG": 19,
    "TG": 20,
    "TI": 21,
    "VD": 22,
    "VS": 23,
    "NE": 24,
    "GE": 25,
    "JU": 26,
}

# Default legend labels, shown untranslated (proper nouns).
CANTON_NAMES = {
    "ZH": "Zürich",
    "BE": "Bern",
    "LU": "Luzern",
    "UR": "Uri",
    "SZ": "Schwyz",
    "OW": "Obwalden",
    "NW": "Nidwalden",
    "GL": "Glarus",
    "ZG": "Zug",
    "FR": "Fribourg",
    "SO": "Solothurn",
    "BS": "Basel-Stadt",
    "BL": "Basel-Landschaft",
    "SH": "Schaffhausen",
    "AR": "Appenzell A.Rh.",
    "AI": "Appenzell I.Rh.",
    "SG": "St. Gallen",
    "GR": "Graubünden",
    "AG": "Aargau",
    "TG": "Thurgau",
    "TI": "Ticino",
    "VD": "Waadt",
    "VS": "Wallis",
    "NE": "Neuenburg",
    "GE": "Genf",
    "JU": "Jura",
}

# swisstopo "map.geo.admin.ch" feature endpoint. {id} is the canton feature
# id (the BFS canton number). sr=4326 returns the geometry as WGS84 lon/lat,
# which the Leaflet map projects through its LV03 CRS.
DEFAULT_URL_TEMPLATE = (
    "https://api3.geo.admin.ch/rest/services/api/MapServer"
    "/ch.swisstopo.swissboundaries3d-kanton-flaeche.fill/{id}"
    "?geometry=true&returnGeometry=true&sr=4326&f=json"
)
REQUEST_TIMEOUT_SECONDS = 10
CACHE_SECONDS = 60 * 60 * 24 * 30
USER_AGENT = f"network_map_plugin/{__version__} (NetBox network topology plugin)"


def resolve_canton_id(code):
    """
    Map a canton code to its numeric BFS id. Accepts a two-letter code
    (case-insensitive) or a numeric id given as a string or int. Returns
    None for anything unrecognised.
    """
    if code is None:
        return None
    text = str(code).strip().upper()
    if not text:
        return None
    if text in CANTON_IDS:
        return CANTON_IDS[text]
    if text.isdigit():
        return int(text)
    return None


def _signed_area(ring):
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _close_ring(ring):
    if ring and ring[0] != ring[-1]:
        return [*ring, ring[0]]
    return ring


def _esri_rings_to_geometry(rings):
    """
    Convert swisstopo's Esri "rings" geometry (WGS84 lon/lat) to a GeoJSON
    Polygon/MultiPolygon. Exterior rings are clockwise (negative area) and
    start a new polygon; counter-clockwise rings are holes of the preceding
    polygon.
    """
    polygons = []
    for ring in rings:
        ring = _close_ring(ring)
        if not polygons or _signed_area(ring) < 0:
            polygons.append([ring])
        else:
            polygons[-1].append(ring)
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _payload_to_collection(payload):
    """
    Normalise a swisstopo response to a GeoJSON FeatureCollection, or None
    when it carries no usable geometry. Handles the map.geo.admin.ch feature
    response (Esri rings) as well as a plain GeoJSON FeatureCollection that an
    overridden URL template might return.
    """
    if not isinstance(payload, dict):
        return None

    feature = payload.get("feature")
    if isinstance(feature, dict):
        rings = (feature.get("geometry") or {}).get("rings")
        if not rings:
            return None
        geometry = _esri_rings_to_geometry(rings)
        properties = feature.get("attributes") or {}
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": properties, "geometry": geometry}
            ],
        }

    features = payload.get("features")
    if features:
        return {"type": "FeatureCollection", "features": features}
    return None


def get_canton_boundary(code):
    """
    Return the canton border as a GeoJSON FeatureCollection in WGS84
    lon/lat, fetched from swisstopo and cached. Returns None when no code
    is configured, the code is unknown, or the fetch/parse fails, so the
    caller can simply skip drawing the border.
    """
    canton_id = resolve_canton_id(code)
    if canton_id is None:
        return None

    cache_key = f"network_map:canton_boundary:{canton_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    template = get_plugin_config(
        "network_map", "canton_boundary_url_template", DEFAULT_URL_TEMPLATE
    )
    url = template.format(id=canton_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        # The URL comes from the plugin settings (an https swisstopo
        # endpoint) plus a numeric canton id, so urlopen cannot be steered
        # to other schemes.
        with urllib.request.urlopen(  # nosec B310
            request,
            timeout=get_plugin_config(
                "network_map", "request_timeout_seconds", REQUEST_TIMEOUT_SECONDS
            ),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        logger.warning(
            "Canton border request for canton id %s failed: HTTP %s (%s)",
            canton_id,
            error.code,
            url,
        )
        return None
    except (OSError, ValueError) as error:
        logger.warning(
            "Canton border request for canton id %s failed: %s (%s)",
            canton_id,
            error,
            url,
        )
        return None

    feature_collection = _payload_to_collection(payload)
    if feature_collection is None:
        logger.warning("No canton border geometry for canton id %s", canton_id)
        return None

    cache.set(
        cache_key,
        feature_collection,
        get_plugin_config(
            "network_map", "canton_boundary_cache_seconds", CACHE_SECONDS
        ),
    )
    return feature_collection


def get_canton_label(code):
    """
    Return the legend label for a canton: the explicit
    canton_boundary_label setting, else the canton's name, else None.
    """
    label = get_plugin_config("network_map", "canton_boundary_label", "")
    if label:
        return label
    canton_id = resolve_canton_id(code)
    if canton_id is None:
        return None
    name = CANTON_NAMES.get(str(code).strip().upper())
    if name:
        return f"Kanton {name}"
    return None
