"""
The Swiss grid (LV03, EPSG:21781) and the tile grid swisstopo publishes in it,
so a picture the server draws stands on the same ground as the map in the
browser.

The coordinates come from the approximate transformation swisstopo publishes
under "Approximate formulas for the transformation between Swiss projection
coordinates and WGS 84", which is good to a couple of metres - a tile covers
some twenty kilometres, so it cannot tell the difference. The tile ladder is
the one of the WMTS capabilities document, mirrored by subnet_map.js; it
halves its resolution no more than a Web Mercator pyramid does, so the zoom of
a picture is looked up rather than calculated.
"""

import math

# The grid's top left corner and the side of one tile, in metres.
TILE_ORIGIN = (420000.0, 350000.0)
TILE_SIZE = 256
# Metres per pixel of every zoom step: 4000 - 250 m down to zoom 13, then the
# steps the capabilities document lists for the rest of the ladder.
RESOLUTIONS = tuple(4000.0 - 250.0 * step for step in range(14)) + (
    650.0,
    500.0,
    250.0,
    100.0,
    50.0,
    20.0,
    10.0,
    5.0,
    2.5,
    2.0,
    1.5,
    1.0,
    0.5,
    0.25,
    0.1,
    0.05,
    0.025,
)
MIN_ZOOM = 8
# The highest zoom the canton tiles are published at.
MAX_ZOOM = 27

# The auxiliary values of the transformation are the difference from the
# country's centre, counted in ten-thousandths of an arc second.
_CENTER_LAT = 169028.66
_CENTER_LON = 26782.5
_ARCSEC = 10000.0


def to_lv03(lat, lon):
    """WGS84 lat/lon in degrees to LV03 (east, north) in metres."""
    phi = (lat * 3600.0 - _CENTER_LAT) / _ARCSEC
    lam = (lon * 3600.0 - _CENTER_LON) / _ARCSEC
    east = (
        600072.37
        + 211455.93 * lam
        - 10938.51 * lam * phi
        - 0.36 * lam * phi**2
        - 44.54 * lam**3
    )
    north = (
        200147.07
        + 308807.95 * phi
        + 3745.25 * lam**2
        + 76.63 * phi**2
        - 194.56 * lam**2 * phi
        + 119.79 * phi**3
    )
    return east, north


def resolution(zoom):
    """Metres per pixel of a zoom step."""
    return RESOLUTIONS[min(max(zoom, 0), len(RESOLUTIONS) - 1)]


def zoom_for(metres_per_pixel):
    """The zoom step whose tiles are as fine as the picture needs them."""
    if metres_per_pixel <= 0:
        return MAX_ZOOM
    closest, gap = MIN_ZOOM, None
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        step = abs(math.log(resolution(zoom) / metres_per_pixel))
        if gap is None or step < gap:
            closest, gap = zoom, step
    return closest


def tile_of(east, north, zoom):
    """Tile column and row a point lies in; negative outside the country."""
    side = TILE_SIZE * resolution(zoom)
    return (
        int((east - TILE_ORIGIN[0]) // side),
        int((TILE_ORIGIN[1] - north) // side),
    )


def tile_rect(x, y, zoom):
    """Ground a tile covers, as (west, south, east, north) in LV03 metres."""
    side = TILE_SIZE * resolution(zoom)
    west = TILE_ORIGIN[0] + x * side
    north = TILE_ORIGIN[1] - y * side
    return west, north - side, west + side, north


def grid(extent, zoom):
    """
    Tile columns and rows covering an LV03 extent, as
    (from_x, from_y, to_x, to_y); the rows grow southwards from the grid's top
    edge, so the north edge of the extent carries the first one.
    """
    min_east, min_north, max_east, max_north = extent
    from_x, from_y = tile_of(min_east, max_north, zoom)
    to_x, to_y = tile_of(max_east, min_north, zoom)
    return from_x, from_y, to_x, to_y


def tile_count(extent, zoom):
    from_x, from_y, to_x, to_y = grid(extent, zoom)
    return max(0, to_x - from_x + 1) * max(0, to_y - from_y + 1)
