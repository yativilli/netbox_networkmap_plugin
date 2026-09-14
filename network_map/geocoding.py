import json
import logging
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "network_map_plugin/0.1 (NetBox network topology plugin)"
REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10


def geocode_site(site):
    """
    Return (latitude, longitude) for a site, using the stored NetBox
    coordinates when present and geocoding via Nominatim otherwise.
    Geocoded coordinates are written back to the Site so the lookup
    happens only once and can be corrected in the UI afterwards.
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
            "countrycodes": "ch",
        }
    )
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )

    try:
        # The URL is built from a fixed https constant plus an encoded
        # query string, so urlopen cannot be steered to other schemes.
        with urllib.request.urlopen(  # nosec B310
            request, timeout=REQUEST_TIMEOUT_SECONDS
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
    (max one request per second). Returns {site_name: (lat, lon)}.
    """
    coordinates = {}
    geocoded_now = 0

    for site in sites:
        if site.latitude is not None and site.longitude is not None:
            coordinates[site.name] = (float(site.latitude), float(site.longitude))
            continue

        if geocoded_now:
            time.sleep(REQUEST_INTERVAL_SECONDS)

        result = geocode_site(site)
        geocoded_now += 1
        if result:
            coordinates[site.name] = result

    return coordinates
