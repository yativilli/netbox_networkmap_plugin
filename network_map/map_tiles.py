"""
The ground behind the map the API draws, so a served picture looks like the one
the page's own export button makes. The page needs none of this, because its
Leaflet map loads its tiles itself.

Tiles come from the swisstopo grid in LV03 (see lv03.py), which is the grid of
the page as well, so the two pictures stand on the same ground; that grid is
addressed by zoom, row and column, in that order.
"""

import base64
import hashlib
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

from django.core.cache import cache
from netbox.plugins import get_plugin_config

from . import __version__, lv03
from .defaults import int_setting

logger = logging.getLogger(__name__)

# The national map in colour over the LV03 grid; {z}/{y}/{x} stand for the tile
# address. A mirror of the same grid has to answer the same way.
DEFAULT_TILE_URL = (
    "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe"
    "/default/current/21781/{z}/{y}/{x}.jpeg"
)
# A whole canton is a few dozen tiles; more than this is not worth waiting for.
MAX_TILES = 64
MAX_TILE_BYTES = 1_500_000
WORKERS = 8
CACHE_SECONDS = 60 * 60 * 24 * 30
# A tile that is not there - the sea, the next canton - stays missing without
# being asked for again on the next picture.
MISSING_CACHE_SECONDS = 60 * 10
REQUEST_TIMEOUT_SECONDS = 10
BUDGET_SECONDS = 20
USER_AGENT = f"network_map_plugin/{__version__} (NetBox network topology plugin)"


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
        # The address comes from the plugin settings - an https tile server -
        # plus the tile numbers, so urlopen cannot be steered to other schemes.
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


def _tile(url_template, zoom, x, y, timeout, cache_seconds):
    """A tile, from the picture cache when it was asked for before."""
    source = hashlib.md5(url_template.encode("utf-8")).hexdigest()[:8]  # nosec B324
    key = f"network_map:tile:{source}:{zoom}/{x}/{y}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    href = _fetch(url_template.format(z=zoom, x=x, y=y), timeout)
    cache.set(key, href or "", MISSING_CACHE_SECONDS if href is None else cache_seconds)
    return href


def _wanted(extent, zoom, limit):
    """
    The tiles to ask for, with the zoom taken down until they fit the budget:
    half a canton without its corner is better than a canton with holes, and a
    coarser step still shows the same ground.
    """
    while zoom > lv03.MIN_ZOOM and lv03.tile_count(extent, zoom) > limit:
        zoom -= 1
    from_x, from_y, to_x, to_y = lv03.grid(extent, zoom)
    # The grid starts at the corner of the country; the tile server answers 400
    # for the negative indices outside it.
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
    url_template = get_plugin_config(
        "network_map", "map_tile_url_template", DEFAULT_TILE_URL
    )
    if not url_template:
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

    timeout = get_plugin_config(
        "network_map", "request_timeout_seconds", REQUEST_TIMEOUT_SECONDS
    )
    cache_seconds = get_plugin_config(
        "network_map", "map_tile_cache_seconds", CACHE_SECONDS
    )
    budget = get_plugin_config("network_map", "map_tile_budget_seconds", BUDGET_SECONDS)

    # One tile after another costs seconds for a whole canton, which the caller
    # waits for in front of a closed connection; a few requests run side by side
    # under one shared deadline, and whatever is missing by then simply stays
    # out of the picture.
    found = []
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(tiles))) as pool:
        pending = {
            pool.submit(_tile, url_template, zoom, x, y, timeout, cache_seconds): (x, y)
            for x, y in tiles
        }
        wait(pending, timeout=budget)
        for future, (x, y) in pending.items():
            if not future.done():
                # The deadline has passed; a tile still on its way would only
                # make the caller wait for nothing.
                future.cancel()
                continue
            error = future.exception()
            if error is not None:
                logger.warning("Map tile %s/%s/%s failed: %s", zoom, x, y, error)
                continue
            href = future.result()
            if not href:
                continue
            found.append({"href": href, "rect": lv03.tile_rect(x, y, zoom)})

    if not found:
        logger.info(
            "No map tiles from %s at zoom %s; drawing the picture without them",
            url_template,
            zoom,
        )
    return found


def attribution():
    """
    The credit the configured tiles ask for, or nothing at all: the picture
    then says where its map data comes from on its own, which is what the
    built-in source wants.
    """
    return get_plugin_config("network_map", "map_attribution", "")
