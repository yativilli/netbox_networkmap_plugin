"""
The ground behind the map the API draws, so a served picture looks like the one
the page's own export button makes. The page needs none of this, because its
Leaflet map loads its tiles itself.

The settings say which provider the ground comes from - the swisstopo grid in
LV03 (see lv03.py), which is the grid of the page as well and so shows the same
ground, or OpenStreetMap's Mercator pyramid (see web_mercator.py) - and whether
a second provider may step in for a tile the first one does not have.
"""

import base64
import hashlib
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

from django.core.cache import cache
from netbox.plugins import get_plugin_config

from . import __version__, lv03, web_mercator
from .defaults import choice_setting, float_setting, int_setting

logger = logging.getLogger(__name__)

# The providers a picture can stand on. A provider names the grid its tiles are numbered in, because a mirror answers in the grid of whoever it mirrors; the address of the server itself is a setting.
SWISSTOPO = "SWISSTOPO"
OSM = "OSM"
PROVIDERS = {
    # The national map in colour over the LV03 grid; {z}/{y}/{x} stand for the tile address.
    SWISSTOPO: {
        "url": "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe"
        "/default/current/21781/{z}/{y}/{x}.jpeg",
        "grid": "lv03",
        # The picture credits swisstopo on its own, so nothing has to be added under it.
        "attribution": "",
        # What the page shows under its own map, and the zooms the tiles are drawn at.
        "credit": '&copy; <a href="https://www.swisstopo.ch/">swisstopo</a>',
        "min_zoom": 8,
        "max_zoom": 27,
    },
    # The same planet in Web Mercator, numbered {z}/{x}/{y} from its north-west corner.
    OSM: {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "grid": "mercator",
        "attribution": "© OpenStreetMap contributors",
        "credit": '&copy; <a href="https://www.openstreetmap.org/copyright">'
        "OpenStreetMap</a> contributors",
        "min_zoom": 0,
        "max_zoom": 19,
    },
}
DEFAULT_TILE_URL = PROVIDERS[SWISSTOPO]["url"]
# No second provider by default: a tile the named provider does not have is usually ground outside the country, and asking twice for every one of those costs time.
DEFAULT_TILE_FALLBACK = ""
FALLBACK_CHOICES = ("", SWISSTOPO, OSM)
# A whole canton is a few dozen tiles; more than this is not worth waiting for.
MAX_TILES = 64
MAX_TILE_BYTES = 1_500_000
WORKERS = 8
CACHE_SECONDS = 60 * 60 * 24 * 30
# A tile that is not there - the sea, the next canton - stays missing without being asked for again on the next picture.
MISSING_CACHE_SECONDS = 60 * 10
REQUEST_TIMEOUT_SECONDS = 10
BUDGET_SECONDS = 20
USER_AGENT = f"network_map_plugin/{__version__} (NetBox network topology plugin)"


def background_source():
    """
    The provider the ground comes from, as the settings name it: SWISSTOPO's
    LV03 grid, which the page draws on too, or OSM's Mercator pyramid.
    """
    return choice_setting("map_background_source", SWISSTOPO, (SWISSTOPO, OSM))


def page_source():
    """
    What the page needs to draw on the same ground the served pictures stand on,
    as {"url", "grid", "min_zoom", "max_zoom", "credit"}: the address its tiles
    come from, the grid those tiles are numbered in - which decides the map's
    projection as much as the tile numbering - the zooms they are drawn at, and
    who has to be named under the map.
    """
    provider = PROVIDERS[background_source()]
    return {
        "url": get_plugin_config(
            "network_map", "map_tile_url_template", provider["url"]
        ),
        "grid": provider["grid"],
        "min_zoom": provider["min_zoom"],
        "max_zoom": provider["max_zoom"],
        "credit": get_plugin_config(
            "network_map", "map_attribution", provider["credit"]
        ),
    }


def _image_type(payload):
    if payload.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG"):
        return "image/png"
    if payload.startswith(b"GIF8"):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _fetch(url, timeout):
    """One tile as a data URL, or None when it cannot be had."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # A configured https tile server plus tile numbers, so urlopen stays on its scheme.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            payload = response.read(MAX_TILE_BYTES + 1)
    except (OSError, ValueError) as error:
        logger.debug("Map tile %s could not be fetched: %s", url, error)
        return None
    if len(payload) > MAX_TILE_BYTES:
        logger.warning("Map tile %s is too big to embed", url)
        return None
    kind = _image_type(payload)
    if kind is None:
        logger.warning("Map tile %s is not a picture", url)
        return None
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{kind};base64,{encoded}"


def _tile(url_template, address, timeout, cache_seconds):
    """A tile, from the picture cache when it was asked for before."""
    source = hashlib.md5(url_template.encode("utf-8")).hexdigest()[:8]  # nosec B324
    key = f"network_map:tile:{source}:{address['z']}/{address['x']}/{address['y']}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    href = _fetch(url_template.format(**address), timeout)
    cache.set(key, href or "", MISSING_CACHE_SECONDS if href is None else cache_seconds)
    return href


def _lv03_address(rect, zoom):
    """The tile of the Swiss grid that is the given ground."""
    west, south, east, north = rect
    x, y = lv03.tile_of((west + east) / 2, (south + north) / 2, zoom)
    if x < 0 or y < 0:
        # The grid starts at the corner of the country; the tile server answers 400 for the negative indices outside it.
        return None
    return {"z": zoom, "x": x, "y": y}, rect


def _mercator_address(rect, zoom):
    """
    The Mercator tile lying under a patch of the Swiss grid, with the ground it
    covers in LV03 metres: the two grids do not line up, so such a tile is
    drawn where its own corners fall and not where the patch it was asked for
    was. Its ladder ends finer than the Swiss one, so every step a picture is
    planned at has an answer to ask.
    """
    west, south, east, north = rect
    lat, lon = lv03.to_wgs84((west + east) / 2, (south + north) / 2)
    step = web_mercator.zoom_for(lv03.resolution(zoom), lat)
    x, y = web_mercator.tile_of(lat, lon, step)
    tile_west, tile_south, tile_east, tile_north = web_mercator.tile_rect(x, y, step)
    corners = [
        lv03.to_lv03(corner_lat, corner_lon)
        for corner_lat, corner_lon in (
            (tile_south, tile_west),
            (tile_south, tile_east),
            (tile_north, tile_west),
            (tile_north, tile_east),
        )
    ]
    covered = (
        min(corner[0] for corner in corners),
        min(corner[1] for corner in corners),
        max(corner[0] for corner in corners),
        max(corner[1] for corner in corners),
    )
    return {"z": step, "x": x, "y": y}, covered


GRIDS = {"lv03": _lv03_address, "mercator": _mercator_address}


def _sources():
    """
    The providers to ask for a tile, in that order, as {"name", "grid", "url"}
    entries: the one `map_background_source` names, then the one
    `map_tile_fallback` names when it names one at all. Asking the same server
    twice is not a fallback, so a name or an address that repeats the first
    one is left out.
    """
    wanted = (
        (background_source(), "map_tile_url_template"),
        (
            choice_setting(
                "map_tile_fallback", DEFAULT_TILE_FALLBACK, FALLBACK_CHOICES
            ),
            "map_tile_fallback_url_template",
        ),
    )
    sources = []
    seen = set()
    for name, setting in wanted:
        url = ""
        if name in PROVIDERS:
            url = get_plugin_config("network_map", setting, PROVIDERS[name]["url"])
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"name": name, "grid": PROVIDERS[name]["grid"], "url": url})
    return tuple(sources)


def _ask(rect, zoom, sources, timeout, cache_seconds):
    """
    The ground under one patch of the Swiss grid, from the first provider that
    has it: a provider that cannot answer costs one more request, and the patch
    only stays out of the picture when none of them can be had. Returns the
    tile as a data URL with the ground it covers and what it is called on its
    server, or None.
    """
    for source in sources:
        address = GRIDS[source["grid"]](rect, zoom)
        if address is None:
            continue
        tile_address, covered = address
        href = _tile(source["url"], tile_address, timeout, cache_seconds)
        if href:
            called = (
                source["url"],
                tile_address["z"],
                tile_address["x"],
                tile_address["y"],
            )
            return href, covered, called
    return None


def _wanted(extent, zoom, limit):
    """
    The tiles to ask for, with the zoom taken down until they fit the budget:
    half a canton without its corner is better than a canton with holes, and a
    coarser step still shows the same ground.
    """
    while zoom > lv03.MIN_ZOOM and lv03.tile_count(extent, zoom) > limit:
        zoom -= 1
    from_x, from_y, to_x, to_y = lv03.grid(extent, zoom)
    # The grid starts at the corner of the country; the tile server answers 400 for the negative indices outside it.
    tiles = [
        (x, y)
        for x in range(from_x, to_x + 1)
        for y in range(from_y, to_y + 1)
        if x >= 0 and y >= 0
    ]
    if len(tiles) > limit:
        logger.warning(
            "Map background needs %s tiles at zoom %s; only %s are fetched",
            len(tiles),
            zoom,
            limit,
        )
        tiles = tiles[:limit]
    return zoom, tiles


def background(extent, metres_per_pixel):
    """
    The tiles lying under a picture of an LV03 extent drawn at the given ground
    resolution, as a list of {"href": data URL, "rect": (west, south, east,
    north)} entries with the ground each tile covers. Empty when tiles are
    switched off, no ground is given, or nothing can be had - a tile server that
    does not answer costs a plain background, not the map.
    """
    if extent is None or not get_plugin_config("network_map", "map_background", True):
        return []
    sources = _sources()
    if not sources:
        return []

    asked = int_setting("map_tile_zoom", None)
    limit = int_setting("map_tile_max", MAX_TILES, minimum=1)
    if asked:
        zoom = min(max(asked, 0), lv03.MAX_ZOOM)
    else:
        zoom = lv03.zoom_for(metres_per_pixel)
    zoom, tiles = _wanted(extent, zoom, limit)
    if not tiles:
        return []

    timeout = float_setting("request_timeout_seconds", REQUEST_TIMEOUT_SECONDS, 0)
    cache_seconds = int_setting("map_tile_cache_seconds", CACHE_SECONDS, 0)
    budget = float_setting("map_tile_budget_seconds", BUDGET_SECONDS, 0)

    # One tile after another costs seconds for a whole canton, which the caller waits for in front of a closed connection; a few requests run.
    found = []
    drawn = set()
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(tiles))) as pool:
        pending = {
            pool.submit(
                _ask,
                lv03.tile_rect(x, y, zoom),
                zoom,
                sources,
                timeout,
                cache_seconds,
            ): (x, y)
            for x, y in tiles
        }
        wait(pending, timeout=budget)
        for future, (x, y) in pending.items():
            if not future.done():
                # The deadline has passed; a tile still on its way would only make the caller wait for nothing.
                future.cancel()
                continue
            error = future.exception()
            if error is not None:
                logger.warning("Map tile %s/%s/%s failed: %s", zoom, x, y, error)
                continue
            answer = future.result()
            if not answer:
                continue
            href, covered, called = answer
            if called in drawn:
                # Patches of the Swiss grid lie on one pyramid tile, which is one picture however often it was asked for.
                continue
            drawn.add(called)
            found.append({"href": href, "rect": covered})

    if not found:
        logger.info(
            "No map tiles from %s at zoom %s; drawing the picture without them",
            " or ".join(source["name"] for source in sources),
            zoom,
        )
    return found


def attribution():
    """
    The credit the configured ground wants, or nothing at all: the picture
    then says where its map data comes from on its own, which is what swisstopo
    is content with while OpenStreetMap asks to be named.
    """
    return get_plugin_config(
        "network_map",
        "map_attribution",
        PROVIDERS[background_source()]["attribution"],
    )
