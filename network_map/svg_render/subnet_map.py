"""Subnet-location SVG renderer."""

import math
from itertools import combinations

from django.utils.translation import gettext as _

from .. import lv03
from ..defaults import int_setting
from .base import (
    BOTTOM_PAD,
    DEFAULT_ACCENT,
    FONT,
    WIDTH,
    build_svg,
    chars,
    text,
)

# ---------------------------------------------------------------------- Subnet location map

MAP_WIDTH = WIDTH
MAP_MARGIN = 24
MAP_MIN_H = 300
# The map's long edge in pixels; the browser export draws to the same size.
MAP_EDGE = 1200
# Room between border and picture edge: shapes touch their box at the west and south.
BORDER_ROOM = 22
ROOM_LEFT = 20
ROOM_BOTTOM = 20
# How far the cut stands beyond the border line; `map_border_cut`, 0 cuts on the line.
BORDER_CUT = 3
# A single address still shows ground around it; SWITZERLAND is the country's box.
SWITZERLAND = (485000.0, 75000.0, 834000.0, 296000.0)
PIN_R = 6
# A site is one pin with its number in it, like the machine dots of a plan.
SITE_R = 9
SITE_SPACE = 26
# Below the map the sites are listed in columns of a few entries each, with their subnets flowing side by side underneath the name.
LIST_ROWS = 6
LIST_COLUMNS = 3
LIST_COL_WIDTH = 384
LIST_ROW = 40
LIST_SUB_ROW = 16
SUBNET_GAP = " · "
LEGEND_ROWS = 14
SCALE_STEPS_M = (100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000)

MAP_STYLE = "\n".join(
    (
        f"text {{ font-family: {FONT}; }}",
        ".map-back { fill: #eef1f4; }",
        ".map-frame { fill: none; stroke: #c6cccb; stroke-width: 1; }",
        ".map-border { fill: #f8f7f2; fill-rule: evenodd; stroke: #c8102e;",
        "  stroke-width: 2; stroke-dasharray: 8 6; }",
        # The same line without the beige ground of its own, for a picture whose ground is the map it was drawn on.
        ".map-border-line { fill: none; stroke: #c8102e; stroke-width: 2;",
        "  stroke-dasharray: 8 6; }",
        ".map-border-halo { fill: none; stroke: #ffffff; stroke-width: 7;",
        "  stroke-opacity: 0.4; }",
        ".map-outside { fill: #ffffff; fill-rule: evenodd; }",
        ".map-pin { stroke: #ffffff; stroke-width: 1.2; }",
        ".map-pin.is-many { stroke-width: 4; }",
        ".map-pin-back { fill: #212529; }",
        ".map-num { font-size: 9.5px; font-weight: 700; fill: #ffffff;",
        "  text-anchor: middle; paint-order: stroke;",
        "  stroke: rgba(0, 0, 0, 0.45); stroke-width: 2px; }",
        ".map-offframe { fill: #6c757d; stroke: #ffffff; stroke-width: 1.5; }",
        # Two sizes for everything the picture says about itself, so the lettering reads as one voice next to a map of real place names.
        ".map-list-name { font-size: 15px; font-weight: 700; }",
        ".map-list-sub { font-size: 13.5px; fill: #6c757d; }",
        ".map-legend { font-size: 15px; fill: #212529; }",
        ".map-legend-border { fill: none; stroke: #c8102e; stroke-width: 2;",
        "  stroke-dasharray: 8 6; }",
        ".map-note { font-size: 13.5px; fill: #6c757d; }",
        ".map-scale { fill: none; stroke: #212529; stroke-width: 1.5; }",
        ".map-scale-label { font-size: 13.5px; fill: #212529; }",
        ".map-attribution { font-size: 13.5px; fill: #6c757d; }",
    )
)


def _lv03_points(geojson):
    """Every coordinate of a GeoJSON collection, in LV03 metres."""
    points = []

    def walk(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            points.append(lv03.to_lv03(coords[1], coords[0]))
            return
        for child in coords:
            walk(child)

    for feature in (geojson or {}).get("features", []):
        geometry = feature.get("geometry") or {}
        walk(geometry.get("coordinates") or [])
    return points


def _placed(map_data):
    """The pins that know where they stand."""
    return [
        pin
        for pin in (map_data.get("pins") or [])
        if pin.get("lat") is not None and pin.get("lon") is not None
    ]


def _bounds(points):
    """The box around some points."""
    east = [point[0] for point in points]
    north = [point[1] for point in points]
    return (min(east), min(north), max(east), max(north))


def map_extent(boundary=None):
    """
    The ground a picture has to show, as an LV03 box (west, south, east, north):
    the configured border's own bounding box when it is known - so that pictures
    taken at different times stay comparable - and the whole country otherwise,
    whether the settings asked for no border or the geometry could not be had.
    """
    points = _lv03_points(boundary)
    if points:
        return _bounds(points)
    return SWITZERLAND


def _polygon_rings(geojson):
    """Every polygon ring of a collection, holes included."""
    rings = []
    for feature in (geojson or {}).get("features", []):
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        if kind == "Polygon":
            rings.extend(coordinates)
        elif kind == "MultiPolygon":
            for polygon in coordinates:
                rings.extend(polygon)
    return [ring for ring in rings if len(ring) > 2]


def _ring_path(ring, project):
    """
    A polygon ring as a closed path. Points closer together than half a pixel
    are left out: the national border arrives with some fifty thousand of them,
    most of which would be drawn on top of their neighbours.
    """
    parts = []
    last = None
    for lon, lat in ring:
        x, y = project(lon, lat)
        if last is not None and max(abs(x - last[0]), abs(y - last[1])) < 0.5:
            continue
        last = (x, y)
        parts.append(f"M{x:.1f},{y:.1f}" if not parts else f"L{x:.1f},{y:.1f}")
    return "".join(parts) + "Z"


def _site_groups(pins):
    """
    One entry per site: the picture marks a location once, no matter how many
    of its subnets are pinned there, and lists those subnets underneath.
    """
    groups, order = {}, []
    for pin in pins:
        name = str(pin.get("site") or "")
        if name not in groups:
            groups[name] = {
                "name": name,
                "lats": [],
                "lons": [],
                "color": pin.get("site_color") or pin.get("color") or DEFAULT_ACCENT,
                "machines": 0,
                "subnets": [],
            }
            order.append(name)
        group = groups[name]
        group["lats"].append(pin["lat"])
        group["lons"].append(pin["lon"])
        group["machines"] += len(pin.get("machines") or [])
        subnet = str(pin.get("subnet") or "")
        prefix = str(pin.get("prefix") or "")
        label = f"{subnet} \u2014 {prefix}" if prefix else subnet
        if label and label not in group["subnets"]:
            group["subnets"].append(label)
    return [groups[name] for name in order]


def _proximity_order(sites):
    """
    Sites that lie next to each other belong next to each other in the list
    too: start in the north-west and always take the closest site still
    missing, so the buildings of one town - which share their coordinates -
    end up side by side.
    """
    pool = sorted(sites, key=lambda site: site["x"] + site["y"])
    if not pool:
        return []
    ordered = [pool.pop(0)]
    while pool:
        last = ordered[-1]
        nearest = min(
            range(len(pool)),
            key=lambda index: (
                (pool[index]["x"] - last["x"]) ** 2
                + (pool[index]["y"] - last["y"]) ** 2
            ),
        )
        ordered.append(pool.pop(nearest))
    return ordered


def _spread(sites, distance, bounds):
    """Numbered pins may not sit on top of each other; one that has to move
    stays near the place it stands for."""
    left, top, right, bottom = bounds
    for _pass in range(12):
        moved = False
        for first, second in combinations(sites, 2):
            dx = second["x"] - first["x"]
            dy = second["y"] - first["y"]
            gap = math.hypot(dx, dy)
            if gap >= distance:
                continue
            push = ((distance - gap) / 2) or 0.5
            ux, uy = (dx / gap, dy / gap) if gap else (1.0, 0.0)
            first["x"] -= ux * push
            first["y"] -= uy * push
            second["x"] += ux * push
            second["y"] += uy * push
            moved = True
        if not moved:
            break
    for site in sites:
        site["x"] = min(max(site["x"], left), right)
        site["y"] = min(max(site["y"], top), bottom)


def _cut(value, max_chars):
    value = str(value)
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip('.,;:)+/-')}\u2026"


def _draw_site_pin(out, site, number):
    """
    One pin per site on a dark disc, which stands out from any background; the
    border tells how many machines the place holds, as in the floor plan.
    """
    many = site["machines"] > 1
    border = 4 if many else 1.2
    out.append(
        f'<circle class="map-pin-back" cx="{site["x"]:.1f}" cy="{site["y"]:.1f}" '
        f'r="{SITE_R + border / 2 + 2:.1f}"/>'
    )
    out.append(
        f'<circle class="map-pin{" is-many" if many else ""}" '
        f'cx="{site["x"]:.1f}" cy="{site["y"]:.1f}" r="{SITE_R}" '
        f'fill="{site["color"]}"/>'
    )
    out.append(text(round(site["x"]), round(site["y"] + 3), number, "map-num"))


def _subnet_lines(subnets, max_chars):
    """
    Every subnet of a site is listed: they flow side by side and wrap into the
    column, so a long row becomes several lines rather than a cut-off one.
    """
    lines, line = [], ""
    for subnet in subnets:
        value = _cut(subnet, max_chars)
        piece = f"{SUBNET_GAP}{value}" if line else value
        if line and len(line) + len(piece) > max_chars:
            lines.append(line)
            line = value
        else:
            line += piece
    lines.append(line)
    return lines


def _draw_site_list(out, sites, start_y):
    """
    The sites underneath the map, numbered as their pins and in the order they
    lie next to each other on the ground.
    """
    columns = max(1, min(LIST_COLUMNS, math.ceil(len(sites) / LIST_ROWS)))
    per_column = math.ceil(len(sites) / columns)
    budget = chars(LIST_COL_WIDTH - 34, 13.5)
    bottoms = [0] * columns
    for index, site in enumerate(sites):
        column = index // per_column
        x = MAP_MARGIN + column * LIST_COL_WIDTH
        y = start_y + bottoms[column]
        out.append(
            f'<circle class="map-pin" cx="{x + 6:.1f}" cy="{y - 4:.1f}" r="{PIN_R - 1}" '
            f'fill="{site["color"]}"/>'
        )
        out.append(
            text(
                x + 20,
                round(y),
                _cut(f"{index + 1}  {site['name']}", chars(LIST_COL_WIDTH - 34, 15)),
                "map-list-name",
                f' style="fill:{site["color"]}"',
            )
        )
        lines = (
            _subnet_lines(site["subnets"], budget)
            if len(site["subnets"]) > 1
            else [_cut(site["subnets"][0], budget)]
            if site["subnets"]
            else []
        )
        for offset, line in enumerate(lines):
            out.append(
                text(
                    x + 20,
                    round(y + LIST_SUB_ROW * (offset + 1)),
                    line,
                    "map-list-sub",
                )
            )
        bottoms[column] += max(LIST_ROW, LIST_SUB_ROW * len(lines) + 24)
    return start_y + max(bottoms) + 8


def _draw_tiles(out, tiles, place):
    """
    The ground underneath everything else. The tiles come out of the same grid
    the ground is drawn from, so each one is a rectangle here; it is grown a
    hair so no light seam shows where two of them meet.
    """
    for tile in tiles:
        west, south, east, north = tile["rect"]
        left, top = place(west, north)
        right, bottom = place(east, south)
        href = tile["href"]
        out.append(
            f'<image href="{href}" x="{left:.1f}" y="{top:.1f}" '
            f'width="{right - left + 0.5:.1f}" height="{bottom - top + 0.5:.1f}" '
            'preserveAspectRatio="none"/>'
        )


def _draw_scale(out, metres_per_pixel, origin_x, origin_y, map_w, map_h):
    """A bar of some round length in metres, in the frame's lower left corner."""
    wanted = metres_per_pixel * 120
    metres = next((step for step in SCALE_STEPS_M if step >= wanted), SCALE_STEPS_M[-1])
    bar = metres / metres_per_pixel
    x, y = origin_x + 12, origin_y + map_h - 16
    out.append(f'<path class="map-scale" d="M{x:.1f},{y:.1f} v-6 H{x + bar:.1f} v-6"/>')
    label = f"{metres // 1000} km" if metres >= 1000 else f"{metres} m"
    out.append(text(round(x + bar + 6), round(y), label, "map-scale-label"))


def _draw_subnet_legend(out, pins, start_y):
    """
    Legend of subnets, for a map of places that carry no site name - the
    numbered site list underneath the map would have nothing to show then.
    """
    entries, seen = [], set()
    for pin in pins:
        key = (pin.get("color"), pin.get("subnet"), pin.get("prefix"))
        if key in seen:
            continue
        seen.add(key)
        entries.append(pin)

    y = start_y
    for pin in entries[:LEGEND_ROWS]:
        name = pin.get("subnet") or ""
        prefix = pin.get("prefix") or ""
        value = f"{name} \u2014 {prefix}" if prefix else name
        out.append(
            f'<circle class="map-pin" cx="{MAP_MARGIN + 6}" cy="{y - 4:.1f}" '
            f'r="{PIN_R - 1}" fill="{pin.get("color") or DEFAULT_ACCENT}"/>'
        )
        out.append(text(MAP_MARGIN + 18, round(y), value, "map-legend"))
        y += 21
    if len(entries) > LEGEND_ROWS:
        out.append(
            text(
                MAP_MARGIN + 18,
                round(y),
                _("… further subnets not listed"),
                "map-note",
            )
        )
        y += 21
    return y


def _draw_footnotes(out, label, off_frame, start_y, attribution=None):
    """The canton line, the places outside the cutout and the source."""
    y = start_y
    if label:
        out.append(
            f'<path class="map-legend-border" d="M{MAP_MARGIN},{y - 4:.1f} h14"/>'
        )
        out.append(text(MAP_MARGIN + 22, round(y), label, "map-legend"))
        y += 21
    if off_frame:
        out.append(
            text(
                MAP_MARGIN + 18,
                round(y),
                f"{off_frame} {_('site(s) outside the drawn area')}",
                "map-note",
            )
        )
        y += 21
    out.append(
        text(
            MAP_MARGIN,
            round(y + 12),
            attribution or _("Map data: © swisstopo"),
            "map-attribution",
        )
    )
    return y + 26


def border_cut():
    """How far the cut stands beyond the border, in pixels of the picture."""
    return int_setting("map_border_cut", BORDER_CUT, minimum=0)


def frame_room():
    """
    The room a picture leaves between its border and its edge, in pixels: what
    every side gets, and what the left and the bottom add to it.
    """
    return (
        int(int_setting("map_border_room", BORDER_ROOM, minimum=0)),
        int(int_setting("map_room_left", ROOM_LEFT, minimum=0)),
        int(int_setting("map_room_bottom", ROOM_BOTTOM, minimum=0)),
    )


def _fit_scale(span_east, span_north, avail_w):
    """
    Pixels per metre of ground for a picture of this much ground: the long edge
    gets MAP_EDGE of them, the frame never grows over the page, and a tight
    cluster still comes out of some height - it may then stand in a frame that
    does not reach the page's edges.
    """
    span_east = max(span_east, 1e-6)
    span_north = max(span_north, 1e-6)
    scale = min(avail_w / span_east, MAP_EDGE / max(span_east, span_north))
    if span_north * scale < MAP_MIN_H:
        scale = min(MAP_MIN_H / span_north, avail_w / span_east)
    return scale


def render_subnet_map(
    map_data, boundary=None, label=None, tiles_of=None, attribution=None
):
    """
    Geographic overview of the subnets, drawn like the browser's own export:
    the map tiles behind everything, one numbered pin per site in that site's
    colour, a thick white border where the place holds more than one machine,
    and the sites listed underneath in the order they lie next to each other,
    each with its subnets beside it.  Everything outside the configured canton
    border is painted over, so the picture ends with the canton; sites outside
    the picture are clamped to its edge and counted, never silently dropped.

    tiles_of, when given, is asked for the tiles lying under the picture, with
    the ground they cover and the metres one pixel of the picture stands for; a
    picture without them says nothing about them, it simply has no ground.
    attribution then names whoever the tiles come from, and the picture credits
    swisstopo by itself.

    Everything stands on the LV03 grid, as it does in the browser: the tiles are
    published in it, and the distances of a canton keep their shape in it, so
    the served picture and the one the page's button makes show the same ground
    the same way.
    """
    pins = _placed(map_data)
    rings = _polygon_rings(boundary)
    min_east, min_north, max_east, max_north = map_extent(boundary)
    avail_w = MAP_WIDTH - 2 * MAP_MARGIN
    scale = _fit_scale(max_east - min_east, max_north - min_north, avail_w)
    if rings:
        # Room around the ground in metres at this scale; without it the frame clips the border.
        border, left, bottom = frame_room()
        min_east -= (border + left) / scale
        min_north -= (border + bottom) / scale
        max_east += border / scale
        max_north += border / scale
        scale = _fit_scale(max_east - min_east, max_north - min_north, avail_w)
    extent = (min_east, min_north, max_east, max_north)
    map_w, map_h = (max_east - min_east) * scale, (max_north - min_north) * scale

    origin_x = MAP_MARGIN + (avail_w - map_w) / 2
    origin_y = MAP_MARGIN

    def place(east, north):
        return (
            origin_x + (east - min_east) * scale,
            origin_y + (max_north - north) * scale,
        )

    def project(lon, lat):
        return place(*lv03.to_lv03(lat, lon))

    out = []
    frame = (
        f'x="{origin_x:.1f}" y="{origin_y:.1f}" '
        f'width="{map_w:.1f}" height="{map_h:.1f}"'
    )
    # The cut: the ground is asked for the whole box, but only what lies within the border belongs in the picture.
    outline = "".join(_ring_path(ring, project) for ring in rings)
    offset = border_cut() if rings else 0
    defs = f'<clipPath id="map-clip"><rect {frame}/></clipPath>'
    ground_mask = ""
    if outline and offset:
        defs += (
            f'<mask id="map-ground" maskUnits="userSpaceOnUse" {frame}>'
            f'<path d="{outline}" fill="#ffffff" fill-rule="evenodd"/>'
            f'<path d="{outline}" fill="none" stroke="#ffffff" stroke-linejoin="round" '
            f'stroke-width="{2 * offset}"/>'
            f"</mask>"
        )
        ground_mask = ' mask="url(#map-ground)"'
    out.append(f"<defs>{defs}</defs>")

    # Ground first, so the border and the pins lie on top of it: the tiles asked for are the ones of this ground at this size.
    out.append(
        f'<g clip-path="url(#map-clip)"{ground_mask}><rect class="map-back" {frame}/>'
    )
    tiles = tiles_of(extent, 1.0 / scale) if tiles_of else []
    _draw_tiles(out, tiles, place)
    out.append("</g>")

    if rings:
        path = outline
        # What the mask did not keep: without a mask to run the cut beyond the line, everything outside the border is painted over instead.
        outside = ""
        if not ground_mask:
            cut = (
                f"M{origin_x:.1f},{origin_y:.1f}H{origin_x + map_w:.1f}"
                f"V{origin_y + map_h:.1f}H{origin_x:.1f}Z"
            )
            outside = f'<path class="map-outside" d="{cut}{path}"/>'
        # The outside is painted through a mask, so the cut can stand off the border line.
        out.append(
            '<g clip-path="url(#map-clip)">'
            f"{outside}"
            f'<path class="map-border-halo" d="{path}"/>'
            f'<path class="{"map-border-line" if tiles else "map-border"}" '
            f'd="{path}"/></g>'
        )
    else:
        out.append(f'<rect class="map-frame" {frame}/>')

    inset = SITE_R + 4
    inside = (
        origin_x + inset,
        origin_y + inset,
        origin_x + map_w - inset,
        origin_y + map_h - inset,
    )
    off_frame = 0
    named, nameless = [], []
    for site in _site_groups(pins):
        x, y = project(
            sum(site["lons"]) / len(site["lons"]),
            sum(site["lats"]) / len(site["lats"]),
        )
        site["offframe"] = not (
            origin_x <= x <= origin_x + map_w and origin_y <= y <= origin_y + map_h
        )
        off_frame += 1 if site["offframe"] else 0
        site["x"] = min(max(x, inside[0]), inside[2])
        site["y"] = min(max(y, inside[1]), inside[3])
        (named if site["name"] else nameless).append(site)

    # One numbered pin per site, in the order the places lie next to each other, which is also the order of the list underneath the map.
    named = _proximity_order(named)
    _spread(named, SITE_SPACE, inside)
    for site in nameless:
        out.append(
            f'<circle class="map-pin" cx="{site["x"]:.1f}" cy="{site["y"]:.1f}" '
            f'r="{PIN_R}" fill="{site["color"]}"/>'
        )
    for number, site in enumerate(named, start=1):
        if site["offframe"]:
            out.append(
                '<circle class="map-offframe" '
                f'cx="{site["x"] - 13:.1f}" cy="{site["y"] - 13:.1f}" r="4"/>'
            )
        _draw_site_pin(out, site, number)

    _draw_scale(out, 1.0 / scale, origin_x, origin_y, map_w, map_h)
    # The gap keeps the first line of the list clear of the scale bar.
    height = origin_y + map_h + 42
    if named:
        height = _draw_site_list(out, named, height)
    elif nameless:
        height = _draw_subnet_legend(out, pins, height)
    height = _draw_footnotes(out, label, off_frame, height, attribution)
    return build_svg(MAP_WIDTH, height + BOTTOM_PAD, "".join(out), MAP_STYLE)
