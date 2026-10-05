"""
The tile pyramid OpenStreetMap publishes: Web Mercator (EPSG:3857), addressed by
zoom, column and row from the planet's north-west corner.

It is the pyramid outside the Swiss grid, so a patch of ground has to be handed
over from LV03 (see lv03.py) before it can be asked for. The ladder halves its
resolution with every step, as the swisstopo one does, so a picture planned in
one grid finds the step of the other that shows the same ground.
"""

import math

TILE_SIZE = 256
MIN_ZOOM = 0
# The zoom the public tile servers are drawn to; above it they answer 404.
MAX_ZOOM = 19
# The width of the world at zoom 0, in metres, which one tile spans.
WORLD_METRES = 40075016.686
# Mercator cannot say what sits past these latitudes.
MAX_LATITUDE = 85.051129


def resolution(zoom, latitude=0.0):
    """Metres per pixel of a zoom step at a latitude, which Mercator inflates."""
    at_equator = WORLD_METRES / (TILE_SIZE * 2.0**zoom)
    return at_equator * math.cos(math.radians(latitude))


def zoom_for(metres_per_pixel, latitude=46.95):
    """
    The zoom whose tiles cover the ground a picture planned at the given ground
    resolution is drawn of. It is the step whose tiles are at least as wide as
    the ground asked for and never twice as wide: a tile that stops short would
    leave part of the picture without ground, which a coarser step never does.
    """
    if metres_per_pixel <= 0:
        return MAX_ZOOM
    wanted = math.log2(resolution(MIN_ZOOM, latitude) / metres_per_pixel)
    return min(max(math.floor(wanted), MIN_ZOOM), MAX_ZOOM)


def tile_of(lat, lon, zoom):
    """Tile column and row a point lies in, counted from the north-west corner."""
    across = 2**zoom
    x = (lon + 180.0) / 360.0 * across
    sine = math.sin(math.radians(min(max(lat, -MAX_LATITUDE), MAX_LATITUDE)))
    y = (1.0 - math.atanh(sine) / math.pi) / 2.0 * across
    return min(max(int(x), 0), across - 1), min(max(int(y), 0), across - 1)


def tile_rect(x, y, zoom):
    """Ground a tile covers, as (west, south, east, north) in WGS84 degrees."""
    across = 2**zoom
    return (
        x / across * 360.0 - 180.0,
        _latitude(y + 1, across),
        (x + 1) / across * 360.0 - 180.0,
        _latitude(y, across),
    )


def _latitude(row, across):
    """The latitude a tile row's edge lies at."""
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * row / across))))
