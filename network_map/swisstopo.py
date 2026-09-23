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

# Reverse lookup from BFS number to two-letter canton code.
CANTON_CODES = {canton_id: code for code, canton_id in CANTON_IDS.items()}

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

# Primary geometry source: swisstopo WFS. The raw feature type carries the
# canton polygon *with* interior rings, so holes (neighbouring-canton pockets
# such as the Solothurn exclave at Steinhof) are preserved and excluded from
# the drawn area. {id} is replaced with the BFS canton number. srsName=EPSG:4326
# returns WGS84 lon/lat, which the Leaflet map projects through its LV03 CRS.
DEFAULT_URL_TEMPLATE = (
    "https://wfs.geo.admin.ch/?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=ch.swisstopo.swissboundaries3d-kanton-flaeche.fill"
    "&outputFormat=application%2Fjson&srsName=EPSG%3A4326&CQL_FILTER=id%3D{id}"
)

# Fallback geometry source: OpenStreetMap/Nominatim. Public Nominatim search
# with polygon_geojson=1 returns the administrative boundary with interior
# rings, so holes such as Steinhof SO are preserved when the WFS source is
# unreachable. {code} is replaced with the canton's ISO/CH code (e.g. CH-BE).
FALLBACK_URL_TEMPLATE = (
    "https://nominatim.openstreetmap.org/search?q=CH-{code}"
    "&countrycodes=ch&featuretype=country_subdivision"
    "&polygon_geojson=1&format=json&limit=1"
)

# Last-resort geometry source: the map.geo.admin.ch feature endpoint. Its
# polygon is display-optimised and carries no interior rings, so holes are not
# cut out. Used when the hole-carrying WFS and Nominatim sources are both
# unavailable.
LAST_RESORT_URL_TEMPLATE = (
    "https://api3.geo.admin.ch/rest/services/api/MapServer"
    "/ch.swisstopo.swissboundaries3d-kanton-flaeche.fill/{id}"
    "?geometry=true&returnGeometry=true&sr=4326&f=json"
)

# The whole country instead of a canton, which "CH" (or "SW") in
# canton_boundary_code asks for. The national border lives in its own layer,
# whose single feature is addressed by "CH".
COUNTRY = "CH"
COUNTRY_CODES = ("CH", "SW")
COUNTRY_NAME = "Schweiz"

COUNTRY_URL_TEMPLATE = (
    "https://api3.geo.admin.ch/rest/services/api/MapServer"
    "/ch.swisstopo.swissboundaries3d-land-flaeche.fill/{id}"
    "?geometry=true&returnGeometry=true&sr=4326&f=json"
)

# Nominatim's country polygon carries interior rings, so enclaves such as
# Büsingen stay outside the drawn country; the swisstopo feature endpoint above
# is tried first because its geometry is the official one.
COUNTRY_FALLBACK_URL_TEMPLATE = (
    "https://nominatim.openstreetmap.org/search?q=Switzerland"
    "&countrycodes=ch&featuretype=country"
    "&polygon_geojson=1&format=json&limit=1"
)

COUNTRY_LAST_RESORT_URL_TEMPLATE = (
    "https://wfs.geo.admin.ch/?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=ch.swisstopo.swissboundaries3d-land-flaeche.fill"
    "&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
)
REQUEST_TIMEOUT_SECONDS = 10
CACHE_SECONDS = 60 * 60 * 24 * 30
USER_AGENT = f"network_map_plugin/{__version__} (NetBox network topology plugin)"


def is_country(code):
    """
    Whether the settings ask for the whole country rather than one canton.
    """
    return str(code or "").strip().upper() in COUNTRY_CODES


def boundary_configured(code):
    """
    Whether a border is to be drawn at all: for a canton or for the country.
    """
    return is_country(code) or resolve_canton_id(code) is not None


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


def resolve_canton_code(code):
    """
    Map a canton code to its canonical two-letter ISO/CH code. Accepts a
    two-letter code or a numeric BFS id and returns None for unknown ids.
    """
    canton_id = resolve_canton_id(code)
    if canton_id is None:
        return None
    return CANTON_CODES.get(canton_id, str(canton_id))


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
    Normalise a swisstopo or Nominatim response to a GeoJSON FeatureCollection,
    or None when it carries no usable geometry. Handles the map.geo.admin.ch
    feature response (Esri rings), a plain GeoJSON FeatureCollection, and a
    Nominatim search response carrying a `geojson` polygon.
    """
    if isinstance(payload, list):
        features = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            geometry = item.get("geojson") or item.get("geometry")
            if not isinstance(geometry, dict):
                continue
            properties = {
                key: value
                for key, value in item.items()
                if key not in {"geojson", "geometry", "boundingbox"}
            }
            features.append(
                {"type": "Feature", "properties": properties, "geometry": geometry}
            )
        if features:
            return {"type": "FeatureCollection", "features": features}
        return None

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
    if features and any(
        isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
        for feature in features
    ):
        return {"type": "FeatureCollection", "features": features}
    return None


def _format_url(template, canton_id, canton_code):
    return template.format(
        id=canton_id,
        code=canton_code or "",
        name=CANTON_NAMES.get(canton_code or "", ""),
    )


def _try_collection(source, template, canton_id, canton_code):
    """
    Fetch and normalise a single canton boundary URL template for the canton.
    Returns a GeoJSON FeatureCollection, or None when the template is unset,
    malformed, the request fails, or the payload carries no usable geometry.
    """
    if not template:
        return None

    try:
        url = _format_url(template, canton_id, canton_code)
    except (KeyError, IndexError, ValueError) as error:
        logger.warning(
            "Canton border %s URL template is malformed: %s",
            source,
            error,
        )
        return None

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
            "Canton border %s request for canton id %s failed: HTTP %s (%s)",
            source,
            canton_id,
            error.code,
            url,
        )
        return None
    except (OSError, ValueError) as error:
        logger.warning(
            "Canton border %s request for canton id %s failed: %s (%s)",
            source,
            canton_id,
            error,
            url,
        )
        return None

    feature_collection = _payload_to_collection(payload)
    if feature_collection is None:
        logger.warning(
            "No canton border geometry from the %s source for canton id %s (%s)",
            source,
            canton_id,
            url,
        )
    return feature_collection


def _fetch_boundary(what, area_id, area_code, templates):
    """
    Fetch a border geometry from the first source that answers, and cache it.
    `templates` is the (source label, URL template) list in the order to try;
    `what` names the area in the cache key and the log.
    """
    cache_key = f"network_map:canton_boundary:{what}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    feature_collection = None
    source = None
    seen_templates = set()
    for source_label, template in templates:
        if not template or template in seen_templates:
            continue
        seen_templates.add(template)
        feature_collection = _try_collection(source_label, template, area_id, area_code)
        if feature_collection is not None:
            source = source_label
            break
    if feature_collection is None:
        return None

    logger.info("Border geometry for %s fetched from the %s source", what, source)
    cache_seconds = get_plugin_config(
        "network_map", "canton_boundary_cache_seconds", CACHE_SECONDS
    )
    cache.set(cache_key, feature_collection, cache_seconds)
    return feature_collection


def get_canton_boundary(code):
    """
    Return the configured border as a GeoJSON FeatureCollection in WGS84
    lon/lat, fetched from the configured sources and cached. A canton is tried
    first through the WFS source (its geometry carries holes), then the
    Nominatim fallback (also hole-carrying), then the hole-less
    map.geo.admin.ch feature endpoint; "CH" or "SW" asks for the national
    border instead, from its own layer. Returns None only when no code is
    configured, the code is unknown, or all sources fail, so the caller can
    simply skip drawing the border.
    """
    if is_country(code):
        return _fetch_boundary(
            COUNTRY,
            COUNTRY,
            COUNTRY,
            (
                (
                    "primary",
                    get_plugin_config(
                        "network_map",
                        "country_boundary_url_template",
                        COUNTRY_URL_TEMPLATE,
                    ),
                ),
                (
                    "fallback",
                    get_plugin_config(
                        "network_map",
                        "country_boundary_fallback_url_template",
                        COUNTRY_FALLBACK_URL_TEMPLATE,
                    ),
                ),
                (
                    "last-resort",
                    get_plugin_config(
                        "network_map",
                        "country_boundary_last_resort_url_template",
                        COUNTRY_LAST_RESORT_URL_TEMPLATE,
                    ),
                ),
            ),
        )

    canton_id = resolve_canton_id(code)
    if canton_id is None:
        return None
    return _fetch_boundary(
        canton_id,
        canton_id,
        resolve_canton_code(code),
        (
            (
                "primary",
                get_plugin_config(
                    "network_map", "canton_boundary_url_template", DEFAULT_URL_TEMPLATE
                ),
            ),
            (
                "fallback",
                get_plugin_config(
                    "network_map",
                    "canton_boundary_fallback_url_template",
                    FALLBACK_URL_TEMPLATE,
                ),
            ),
            (
                "last-resort",
                get_plugin_config(
                    "network_map",
                    "canton_boundary_last_resort_url_template",
                    LAST_RESORT_URL_TEMPLATE,
                ),
            ),
        ),
    )


def get_canton_label(code):
    """
    Return the legend label for a border: the explicit canton_boundary_label
    setting, else the canton's name prefixed as on the page, else "Schweiz" for
    the country, else None.
    """
    label = get_plugin_config("network_map", "canton_boundary_label", "")
    if label:
        return label
    if is_country(code):
        return COUNTRY_NAME
    canton_id = resolve_canton_id(code)
    if canton_id is None:
        return None
    name = CANTON_NAMES.get(str(code).strip().upper())
    if name:
        return f"Kanton {name}"
    return None
