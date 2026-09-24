import json
import logging
import time
import urllib.parse
import urllib.request

from netbox.plugins import get_plugin_config

from . import __version__
from .defaults import float_setting

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
COUNTRY_CODES = "ch"
USER_AGENT = f"network_map_plugin/{__version__} (NetBox network topology plugin)"
REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10


def geocode_site(site):
    """
    Return (latitude, longitude) for a site, using the stored NetBox
    coordinates when present and geocoding via Nominatim otherwise.
    Geocoded coordinates are written back to the Site so the lookup
    happens only once and can be corrected in the UI afterwards.
    URL, country filter and timeout are configurable via PLUGINS_CONFIG.
    """
    if site.latitude is not None and site.longitude is not None:
        return float(site.latitude), float(site.longitude)

    query = site.physical_address or site.name
    if not query:
        return None

    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": get_plugin_config(
                "network_map", "country_codes", COUNTRY_CODES
            ),
        }
    )
    request = urllib.request.Request(
        f"{get_plugin_config('network_map', 'nominatim_url', NOMINATIM_URL)}?{params}",
        headers={"User-Agent": USER_AGENT},
    )

    try:
        # A configured https instance plus an encoded query, so urlopen stays on its scheme.
        with urllib.request.urlopen(  # nosec B310
            request,
            timeout=float_setting(
                "request_timeout_seconds", REQUEST_TIMEOUT_SECONDS, 0
            ),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        logger.warning("Geocoding request failed for site %s", site.name)
        return None

    if not payload:
        logger.warning("No geocoding result for site %s", site.name)
        return None

    latitude = payload[0].get("lat")
    longitude = payload[0].get("lon")
    if latitude is None or longitude is None:
        return None

    site.latitude = round(float(latitude), 6)
    site.longitude = round(float(longitude), 6)
    site.save(update_fields=["latitude", "longitude"])

    return site.latitude, site.longitude


def geocode_sites(sites):
    """
    Geocode an iterable of sites, respecting the Nominatim usage policy
    (max one request per configured interval). Returns {site_name: (lat, lon)}.
    """
    interval = float_setting("request_interval_seconds", REQUEST_INTERVAL_SECONDS, 0)
    coordinates = {}
    geocoded_now = 0

    for site in sites:
        if site.latitude is not None and site.longitude is not None:
            coordinates[site.name] = (float(site.latitude), float(site.longitude))
            continue

        if geocoded_now:
            time.sleep(interval)

        result = geocode_site(site)
        geocoded_now += 1
        if result:
            coordinates[site.name] = result

    return coordinates
