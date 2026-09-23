"""
Server-side SVG renderers for the three map views, mirroring the browser
exports (svg_export.js / vlan_topology.js) as simple hand-drawn vectors.
Text wrapping uses a rough per-character estimate instead of real font
metrics, so break points can deviate slightly from the browser version.
"""

import math
from itertools import combinations

from django.utils.html import escape
from django.utils.translation import gettext as _
from netbox.plugins import get_plugin_config

from . import lv03
from .colors import LOCATION_COLORS

WIDTH = 1200
RIGHT_PAD = 16
BOTTOM_PAD = 16
CHAR_FACTOR = 0.55  # rough glyph width as a factor of the font size
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
GRAY = "#c6cccb"
DEFAULT_ACCENT = "#6c757d"
STAGE_COLORS = ("#174a8b", "#19583b", "#9e4904", "#412477", "#a5003f")
LOCATION_HEX = dict(LOCATION_COLORS)

STYLE = "\n".join(
    (
        f"text {{ font-family: {FONT}; fill: #212529; }}",
        ".h-section { font-size: 16px; font-weight: 700; fill: #1f2937; }",
        ".p-title { font-size: 14.5px; font-weight: 700; }",
        ".f-label { font-size: 12px; font-weight: 700; fill: #6b7280; }",
        ".f-value { font-size: 12px; }",
        ".c-title { font-size: 12.5px; font-weight: 700; }",
        ".c-label { font-size: 11.5px; font-weight: 700; fill: #6b7280; }",
        ".c-value { font-size: 11.5px; }",
        ".chip-name { font-size: 12.5px; font-weight: 700; }",
        ".chip-count { font-size: 12.5px; }",
        ".n-title { font-size: 13.5px; font-weight: 700; }",
        ".n-sub { font-size: 11px; fill: #6c757d; }",
        ".i-label { font-size: 11.5px; font-weight: 700; fill: #6b7280; }",
        ".i-value { font-size: 11.5px; }",
    )
)

TOPO_STYLE = "\n".join(
    (
        f"text {{ font-family: {FONT}; pointer-events: none; }}",
        ".topo-edge { stroke: #b9c2cb; stroke-width: 1.5; }",
        ".topo-hub circle { fill: #0c0f13; }",
        ".topo-hub-name { fill: #fff; font-weight: 700; font-size: 13px; }",
        ".topo-hub-ip { fill: #cfd6dd; font-size: 10px; }",
        ".topo-subnet rect { fill: #f3a552; stroke: #c77b28; stroke-width: 1.5; }",
        ".topo-subnet-name { fill: #4a2a05; font-weight: 600; font-size: 12px; }",
        ".topo-subnet-prefix { fill: #8a5312; font-size: 10px; }",
        ".topo-machine circle { fill: #c9ecf2; stroke: #8fbcc6; stroke-width: 1.5; }",
        ".topo-machine-label { fill: #163a47; font-size: 10.5px; }",
        ".topo-machine-ip { fill: #8598a3; font-size: 9.5px; }",
        ".topo-machine-description { fill: #667885; font-size: 8.5px; }",
    )
)


def build_svg(width, height, body, style=STYLE):
    width, height = round(width), round(height)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f"<style>{style}</style>"
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f"{body}</svg>"
    )


def text(x, y, value, cls, extra=""):
    return f'<text x="{x}" y="{y}" class="{cls}"{extra}>{escape(str(value))}</text>'


def chars(max_width, font):
    """Roughly how many characters of the given font size fit into max_width."""
    return max(4, int(max_width / (font * CHAR_FACTOR)))


def wrap_lines(value, max_chars, max_lines=99):
    """Port of the browser's wrapLines(): word wrap, truncation with …."""
    words = str(value or "").split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = f"{word[: max_chars - 1]}…" if len(word) > max_chars else word
    if current:
        lines.append(current)
    if not lines:
        lines = [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = f"{lines[-1][:-1].rstrip('.,;:)+/-')}…"
    return lines


def _ph(value):
    value = "" if value is None else str(value)
    return value if value.strip() else "—"


# ----------------------------------------------------------------------
# Machine list
# ----------------------------------------------------------------------


def _machine_fields(machine):
    return (
        (f"{_('Location')}:", _ph(machine.get("location"))),
        (f"{_('IP')}:", machine.get("ip", "")),
        (f"{_('Role')}:", _ph(machine.get("role"))),
        (f"{_('Description')}:", _ph(machine.get("description"))),
    )


def _draw_fields(out, fields, x, y, max_width, label_cls, value_cls, row, font):
    for label, value in fields:
        label_width = len(label) * font * CHAR_FACTOR + 6
        lines = wrap_lines(value, chars(max_width - label_width, font))
        out.append(f'<text x="{x}" y="{y}" class="{label_cls}">{escape(label)}</text>')
        for index, line in enumerate(lines):
            out.append(text(x + label_width, y + index * row, line, value_cls))
        y += len(lines) * row
    return y


def render_machine_list(elements):
    out, y = [], 16.0
    inner_w = WIDTH - RIGHT_PAD

    if elements:
        out.append(text(4, y + 13, _("VLAN Overview"), "h-section"))
        y += 28
        x = 0.0
        for element in elements:
            name, count = str(element.name), str(element.machine_count)
            chip_w = 30 + (len(name) + len(count)) * 12.5 * CHAR_FACTOR
            if x > 0 and x + chip_w > inner_w:
                x, y = 0.0, y + 38
            out.append(
                f'<rect x="{x}" y="{y}" width="{chip_w}" height="30" rx="5" fill="#fff" '
                'stroke="#d7dce1" stroke-width="1"/>'
            )
            out.append(f'<rect x="{x}" y="{y}" width="5" height="30" fill="{GRAY}"/>')
            out.append(text(x + 13, y + 19.5, name, "chip-name"))
            out.append(
                text(
                    x + 19 + len(name) * 12.5 * CHAR_FACTOR,
                    y + 19.5,
                    count,
                    "chip-count",
                )
            )
            x += chip_w + 8
        y += 48

    out.append(text(4, y + 13, _("VLAN Elements"), "h-section"))
    y += 30

    columns = max(1, int((inner_w - 32 + 14) // (280 + 14)))
    child_w = int((inner_w - 32 - (columns - 1) * 14) // columns)

    for element in elements:
        fields = (
            (f"{_('Group')}:", _ph(element.group)),
            (f"{_('Description')}:", _ph(element.description)),
            (f"{_('Role')}:", _ph(element.role)),
            (f"{_('Machines')}:", element.machine_count),
            (f"{_('Range')}:", _ph(element.prefix)),
        )
        content_x, content_w = 21, inner_w - 31
        title_lines = wrap_lines(element.name, chars(content_w, 14.5), 2)

        plans = []
        for machine in element.machines:
            title = _ph(machine.get("dns_name") or machine.get("ip"))
            lines = wrap_lines(title, chars(child_w - 30, 12.5), 2)
            used = _draw_fields(
                [], _machine_fields(machine), 18, 0, child_w - 30, "", "", 14, 11.5
            )
            plans.append(
                (machine, title, lines, round(14 + len(lines) * 15 + used + 10))
            )
        rows = [plans[i : i + columns] for i in range(0, len(plans), columns)]
        row_heights = [max([plan[3] for plan in row] + [54]) for row in rows]

        field_height = round(
            _draw_fields([], fields, content_x, 0, content_w, "", "", 16, 12)
        )
        grid_height = sum(10 + height + 14 for height in row_heights)
        card_height = 14 + len(title_lines) * 19 + field_height + grid_height + 14

        out.append(
            f'<rect x="0.5" y="{y}" width="{inner_w - 1}" height="{card_height}" rx="6" '
            'fill="#ffffff" stroke="#d7dce1" stroke-width="1"/>'
        )
        out.append(
            f'<rect x="0" y="{y}" width="5" height="{card_height}" fill="{GRAY}"/>'
        )
        ty = y + 22
        for line in title_lines:
            out.append(text(content_x, ty, line, "p-title"))
            ty += 19
        ty = _draw_fields(
            out, fields, content_x, ty, content_w, "f-label", "f-value", 16, 12
        )

        for row, row_height in zip(rows, row_heights):
            ty += 10
            cx = 16
            for machine, _title, lines, _height in row:
                accent = LOCATION_HEX.get(machine.get("color", ""), DEFAULT_ACCENT)
                out.append(
                    f'<rect x="{cx}" y="{ty}" width="{child_w}" height="{row_height}" rx="5" '
                    'fill="#ffffff" stroke="#d7dce1" stroke-width="1"/>'
                )
                out.append(
                    f'<rect x="{cx}" y="{ty}" width="{child_w}" height="{row_height}" rx="5" '
                    f'fill="{accent}" fill-opacity="0.07"/>'
                )
                out.append(
                    f'<rect x="{cx}" y="{ty}" width="5" height="{row_height}" fill="{accent}"/>'
                )
                child_ty = ty + 18
                for line in lines:
                    out.append(text(cx + 18, child_ty, line, "c-title"))
                    child_ty += 15
                _draw_fields(
                    out,
                    _machine_fields(machine),
                    cx + 18,
                    child_ty,
                    child_w - 30,
                    "c-label",
                    "c-value",
                    14,
                    11.5,
                )
                cx += child_w + 14
            ty += row_height + 14

        y += card_height + 14

    return build_svg(WIDTH, y + BOTTOM_PAD, "".join(out))


# ----------------------------------------------------------------------
# Logical map (VLAN connections tree)
# ----------------------------------------------------------------------


def _tree_node(out, y, depth, title, sub, items):
    x = 4 + depth * 24
    title_x = x + 18
    color = STAGE_COLORS[min(depth, len(STAGE_COLORS) - 1)]
    out.append(
        f'<line x1="{x}" y1="{y - 4}" x2="{x + 11}" y2="{y - 4}" '
        f'stroke="{color}" stroke-width="2.5"/>'
    )
    for line in wrap_lines(title, chars(WIDTH - RIGHT_PAD - title_x, 13.5)):
        out.append(text(title_x, y, line, "n-title", f' fill="{color}"'))
        y += 17
    if sub:
        for line in wrap_lines(sub, chars(WIDTH - RIGHT_PAD - title_x, 11)):
            out.append(text(title_x, y + 3, line, "n-sub"))
            y += 13
    y += 3
    for label, value in items:
        lines = wrap_lines(value, chars(WIDTH - RIGHT_PAD - title_x - 118, 11.5))
        out.append(text(title_x, y + 10, label, "i-label"))
        for index, line in enumerate(lines):
            out.append(text(title_x + 110, y + 10 + index * 13, line, "i-value"))
        y += len(lines) * 13 + 7
    return y + 10


def render_logical_tree(elements, center_device):
    out, y = [], 20.0
    device = center_device
    primary_ip4 = getattr(device, "primary_ip4", None)
    y = _tree_node(
        out,
        y,
        0,
        "" if device is None else str(device),
        str(getattr(device, "role", "") or ""),
        (
            (_("Name"), "" if device is None else device.name),
            (_("Description"), "" if device is None else device.description),
            (_("Location"), "" if device is None else getattr(device, "site", "")),
            (_("IP-Address"), "" if primary_ip4 is None else primary_ip4.address),
            (_("Type"), str(getattr(device, "role", "") or "")),
        ),
    )
    for gateway in elements:
        vlan = gateway.vlan
        y = _tree_node(
            out,
            y,
            1,
            f"VLAN {vlan.vid} - {vlan.name}",
            gateway.description,
            (
                (_("VLAN"), vlan.vid),
                (_("Name"), vlan.name),
                (_("Gateway"), gateway.address),
                (_("DNS Name"), gateway.dns_name),
                (_("Description"), gateway.description),
                (_("Type"), gateway.type),
            ),
        )
        for prefix in gateway.prefixes:
            y = _tree_node(
                out,
                y,
                2,
                prefix.prefix,
                _("Prefix"),
                (
                    (_("Prefix"), prefix.prefix),
                    (_("ID"), prefix.id),
                    (_("Type"), prefix.type),
                ),
            )
            for ip in prefix.ip_addresses:
                y = _tree_node(
                    out,
                    y,
                    3,
                    _ph(ip.dns_name),
                    ip.address,
                    (
                        (_("Address"), ip.address),
                        (_("DNS Name"), ip.dns_name),
                        (_("Description"), ip.description),
                        (_("Comments"), ip.comments),
                        (_("Role"), ip.role),
                        (_("Type"), ip.type),
                    ),
                )
                if ip.details:
                    details = ip.details
                    y = _tree_node(
                        out,
                        y,
                        4,
                        _ph(details.name),
                        details.type,
                        (
                            (_("Name"), details.name),
                            (_("Description"), details.description),
                            (_("Location"), details.location),
                            (_("Type"), details.type),
                        ),
                    )
    return build_svg(WIDTH, y + BOTTOM_PAD, "".join(out))


# ----------------------------------------------------------------------
# Topology map (port of vlan_topology.js buildGraph)
# ----------------------------------------------------------------------

HUB_R = 60
SUB_W = 150
SUB_H = 110
SUB_DIAG = math.hypot(SUB_W / 2, SUB_H / 2)
MACH_R = 42
GAP = 2.5
MIN_SEP = MACH_R * 2 + GAP * 2
R0 = 140
RING_STEP = 95
MIN_HUB_DIST = 265
MARGIN = 40


def _machine_rings(count):
    if not count:
        return []
    rings, radius, capacity = [], R0, 0
    while capacity < count:
        cap = max(1, math.floor((2 * math.pi * radius) / MIN_SEP))
        rings.append({"radius": radius, "cap": cap, "count": 0})
        capacity += cap
        radius += RING_STEP
    assigned, index = 0, 0
    while assigned < count:
        ring = rings[index % len(rings)]
        if ring["count"] < ring["cap"]:
            ring["count"] += 1
            assigned += 1
        index += 1
    return [ring for ring in rings if ring["count"]]


def _cluster_footprint(plan):
    machine_reach = plan[-1]["radius"] + MACH_R + GAP if plan else 0
    return max(machine_reach, SUB_DIAG + GAP)


def _golden_slots(subnets):
    by_size = sorted(
        range(len(subnets)), key=lambda index: -len(subnets[index]["machines"])
    )
    slots = [None] * len(subnets)
    for rank, subnet_index in enumerate(by_size):
        slot = int((((rank + 1) * 0.6180339887) % 1) * len(subnets))
        while slots[slot] is not None:
            slot = (slot + 1) % len(subnets)
        slots[slot] = subnets[subnet_index]
    return slots


def _resolve_collisions(radii, footprints, pushed_out, angle_at, clearance):
    for _pass in range(500):
        moved = False
        for i in range(len(radii)):
            for j in range(i + 1, len(radii)):
                if not pushed_out[i] and not pushed_out[j]:
                    continue
                reach = footprints[i] + footprints[j] + clearance
                delta = angle_at(i) - angle_at(j)
                da, sa = math.cos(delta), math.sin(delta)
                di, dj = radii[i], radii[j]
                dist2 = di * di + dj * dj - 2 * di * dj * da
                if dist2 >= reach * reach:
                    continue
                if (
                    pushed_out[i]
                    and pushed_out[j]
                    and abs(footprints[i] - footprints[j]) < 1e-6
                ):
                    scale = (reach + 0.01) / math.sqrt(max(dist2, 1))
                    radii[i], radii[j] = di * scale, dj * scale
                elif pushed_out[i] and (
                    not pushed_out[j] or footprints[i] >= footprints[j]
                ):
                    radii[i] = max(
                        di,
                        dj * da
                        + math.sqrt(max(0.0, reach * reach - dj * dj * sa * sa))
                        + 0.01,
                    )
                else:
                    radii[j] = max(
                        dj,
                        di * da
                        + math.sqrt(max(0.0, reach * reach - di * di * sa * sa))
                        + 0.01,
                    )
                moved = True
        if not moved:
            break


def _add_text(out, cls, x, y, lines, line_height):
    first = y - ((len(lines) - 1) * line_height) / 2
    spans = "".join(
        f'<tspan x="{x}" y="{first + index * line_height}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    out.append(f'<text x="{x}" text-anchor="middle" class="{cls}">{spans}</text>')


def _machine_sections(machine):
    sections = [
        (wrap_lines(machine["name"], 11, 2), 11, "topo-machine-label"),
    ]

    ip = str(machine.get("ip") or "")
    if ip:
        sections.append(([ip], 11, "topo-machine-ip"))

    description = str(machine.get("description") or "").strip()
    if description:
        sections.append(
            (wrap_lines(description, 13, 2), 10, "topo-machine-description")
        )
    return sections


def _draw_machine_text(out, cx, cy, machine):
    sections = _machine_sections(machine)
    gap = 1
    total_height = sum(
        len(lines) * line_height + (gap if index else 0)
        for index, (lines, line_height, _cls) in enumerate(sections)
    )
    top = cy - total_height / 2
    for lines, line_height, cls in sections:
        section_height = len(lines) * line_height
        _add_text(out, cls, cx, top + section_height / 2, lines, line_height)
        top += section_height + gap


def render_topology(topology_data):
    subnets = topology_data.get("subnets", [])
    center = topology_data.get("center", {})
    if not subnets:
        return build_svg(400, 80, "", TOPO_STYLE)

    ordered = _golden_slots(subnets)
    plans = [_machine_rings(len(subnet["machines"])) for subnet in ordered]
    footprints = [_cluster_footprint(plan) for plan in plans]
    count = len(ordered)

    def angle_at(index):
        return -math.pi / 2 + (index * 2 * math.pi) / count

    push_clearance = 50
    sorted_footprints = sorted(footprints)
    median = sorted_footprints[len(sorted_footprints) // 2]
    half_chord = math.sin(math.pi / max(count, 2))

    ring_sum = 0.0
    for i in range(count):
        neighbour = (i + 1) % count
        if footprints[i] <= median + 1e-6 and footprints[neighbour] <= median + 1e-6:
            ring_sum = max(ring_sum, footprints[i] + footprints[neighbour] + 2 * GAP)
    ring_radius = max(MIN_HUB_DIST, ring_sum / (2 * half_chord))
    radii = [ring_radius] * count
    pushed_out = [footprint > median + 1e-6 for footprint in footprints]
    _resolve_collisions(radii, footprints, pushed_out, angle_at, push_clearance)

    bounds = {"min_x": -HUB_R, "min_y": -HUB_R, "max_x": HUB_R, "max_y": HUB_R}

    def grow(x, y, rx, ry):
        bounds["min_x"] = min(bounds["min_x"], x - rx)
        bounds["max_x"] = max(bounds["max_x"], x + rx)
        bounds["min_y"] = min(bounds["min_y"], y - ry)
        bounds["max_y"] = max(bounds["max_y"], y + ry)

    layout = []
    for index, subnet in enumerate(ordered):
        angle = angle_at(index)
        x, y = radii[index] * math.cos(angle), radii[index] * math.sin(angle)
        grow(x, y, SUB_W / 2, SUB_H / 2)
        machines, next_machine = [], 0
        for ring_index, ring in enumerate(plans[index]):
            step = (2 * math.pi) / ring["count"]
            for k in range(ring["count"]):
                if ring["count"] == 1:
                    a = angle
                else:
                    a = angle + (ring_index * math.pi) / ring["count"] + k * step
                mx = x + ring["radius"] * math.cos(a)
                my = y + ring["radius"] * math.sin(a)
                grow(mx, my, MACH_R, MACH_R)
                machines.append((mx, my, subnet["machines"][next_machine]))
                next_machine += 1
        layout.append((subnet, x, y, machines))

    offset_x = -bounds["min_x"] + MARGIN
    offset_y = -bounds["min_y"] + MARGIN
    width = bounds["max_x"] - bounds["min_x"] + MARGIN * 2
    height = bounds["max_y"] - bounds["min_y"] + MARGIN * 2
    hub_x, hub_y = offset_x, offset_y

    out = ['<g class="topo-edges">']
    for _subnet, x, y, machines in layout:
        cx, cy = x + offset_x, y + offset_y
        out.append(
            f'<line class="topo-edge" x1="{hub_x}" y1="{hub_y}" x2="{cx}" y2="{cy}"/>'
        )
        for mx, my, _machine in machines:
            out.append(
                f'<line class="topo-edge" x1="{cx}" y1="{cy}" '
                f'x2="{mx + offset_x}" y2="{my + offset_y}"/>'
            )
    out.append("</g>")

    for _subnet, _x, _y, machines in layout:
        for mx, my, machine in machines:
            cx, cy = mx + offset_x, my + offset_y
            out.append(
                f'<g class="topo-machine"><circle cx="{cx}" cy="{cy}" r="{MACH_R}"/>'
            )
            _draw_machine_text(out, cx, cy, machine)
            out.append("</g>")

    for subnet, x, y, _machines in layout:
        cx, cy = x + offset_x, y + offset_y
        out.append(
            f'<g class="topo-subnet"><rect x="{cx - SUB_W / 2}" y="{cy - SUB_H / 2}" '
            f'width="{SUB_W}" height="{SUB_H}" rx="8"/>'
        )
        _add_text(
            out, "topo-subnet-name", cx, cy - 12, wrap_lines(subnet["name"], 16, 3), 14
        )
        if subnet["prefix"]:
            _add_text(
                out,
                "topo-subnet-prefix",
                cx,
                cy + SUB_H / 2 - 14,
                wrap_lines(subnet["prefix"], 26, 1),
                11,
            )
        out.append("</g>")

    out.append('<g class="topo-hub">')
    out.append(f'<circle cx="{hub_x}" cy="{hub_y}" r="{HUB_R}"/>')
    _add_text(
        out,
        "topo-hub-name",
        hub_x,
        hub_y - 6,
        wrap_lines(center.get("name", ""), 12, 2),
        15,
    )
    if center.get("ip"):
        _add_text(out, "topo-hub-ip", hub_x, hub_y + 24, [center["ip"]], 11)
    out.append("</g>")

    return build_svg(width, height, "".join(out), TOPO_STYLE)


# ----------------------------------------------------------------------
# Subnet location map
# ----------------------------------------------------------------------

MAP_WIDTH = WIDTH
MAP_MARGIN = 24
MAP_MIN_H = 300
# The long edge of the map picture, in pixels, which is what the browser export
# draws too: the picture comes out this big unless the page is too narrow.
MAP_EDGE = 1200
# Room the picture leaves around the border it cuts along, in pixels of the
# picture: the line and its white halo hang over the geometry, and a shape
# touches its bounding box at a point - mostly in the west and the south, which
# is where Geneva's edge and Ticino's tip get cut. `map_border_room` moves the
# cut away from the border, `map_room_left` and `map_room_bottom` add room on
# the two edges that need it most.
BORDER_ROOM = 22
ROOM_LEFT = 20
ROOM_BOTTOM = 20
# How far the cut itself stands beyond the border, so that the picture is not
# cut directly on the line but leaves this much of the neighbouring ground
# visible: `map_border_cut` changes it, `0` cuts on the line.
BORDER_CUT = 3
# A picture of a single address still shows some ground around it.
# Switzerland's own bounding box in LV03 metres, the limits of the national
# border as swisstopo publishes them rounded outward. A picture without a border
# to stand on shows the country instead of a box around whatever happens to be
# registered.
SWITZERLAND = (485000.0, 75000.0, 834000.0, 296000.0)
PIN_R = 6
# A site is one pin with its number in it, like the machine dots of a plan.
SITE_R = 9
SITE_SPACE = 26
# Below the map the sites are listed in columns of a few entries each, with
# their subnets flowing side by side underneath the name.
LIST_ROWS = 6
LIST_COLUMNS = 3
LIST_COL_WIDTH = 320
LIST_ROW = 30
LIST_SUB_ROW = 12
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
        # The same line without the beige ground of its own, for a picture
        # whose ground is the map it was drawn on.
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
        ".map-list-name { font-size: 10.5px; font-weight: 700; }",
        ".map-list-sub { font-size: 10px; fill: #6c757d; }",
        ".map-legend { font-size: 11.5px; fill: #212529; }",
        ".map-legend-border { fill: none; stroke: #c8102e; stroke-width: 2;",
        "  stroke-dasharray: 8 6; }",
        ".map-note { font-size: 11px; fill: #6c757d; }",
        ".map-scale { fill: none; stroke: #212529; stroke-width: 1.5; }",
        ".map-scale-label { font-size: 10px; fill: #212529; }",
        ".map-attribution { font-size: 10px; fill: #6c757d; }",
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
    Several subnets flow side by side and wrap into the column, instead of one
    line that has to be cut off.
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
    budget = chars(LIST_COL_WIDTH - 34, 10)
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
                _cut(f"{index + 1}  {site['name']}", chars(LIST_COL_WIDTH - 34, 10.5)),
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
        bottoms[column] += max(LIST_ROW, LIST_SUB_ROW * len(lines) + 18)
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
        y += 16
    if len(entries) > LEGEND_ROWS:
        out.append(
            text(
                MAP_MARGIN + 18,
                round(y),
                _("… further subnets not listed"),
                "map-note",
            )
        )
        y += 16
    return y


def _draw_footnotes(out, label, off_frame, start_y, attribution=None):
    """The canton line, the places outside the cutout and the source."""
    y = start_y
    if label:
        out.append(
            f'<path class="map-legend-border" d="M{MAP_MARGIN},{y - 4:.1f} h14"/>'
        )
        out.append(text(MAP_MARGIN + 22, round(y), label, "map-legend"))
        y += 16
    if off_frame:
        out.append(
            text(
                MAP_MARGIN + 18,
                round(y),
                f"{off_frame} {_('site(s) outside the drawn area')}",
                "map-note",
            )
        )
        y += 16
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
    return max(0, int(get_plugin_config("network_map", "map_border_cut", BORDER_CUT)))


def frame_room():
    """
    The room a picture leaves between its border and its edge, in pixels: what
    every side gets, and what the left and the bottom add to it.
    """
    return (
        max(0, int(get_plugin_config("network_map", "map_border_room", BORDER_ROOM))),
        max(0, int(get_plugin_config("network_map", "map_room_left", ROOM_LEFT))),
        max(0, int(get_plugin_config("network_map", "map_room_bottom", ROOM_BOTTOM))),
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
        # Room around the ground, measured in metres at this scale; the frame
        # would otherwise end where the border line and the shape's own western
        # and southern extremes still are.
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
    # The cut: the ground is asked for the whole box, but only what lies within
    # the border belongs in the picture. The mask keeps the area and the band
    # around it - the area filled, and the same shape stroked wide - so the cut
    # runs `border_cut()` pixels beyond the line instead of on it. Masks are
    # painted inline, since a renderer that does not read the document's styles
    # would otherwise mask the ground away entirely, and a picture of a canton
    # is worth more than a picture of its neighbours.
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

    # Ground first, so the border and the pins lie on top of it: the tiles
    # asked for are the ones of this ground at this size. A background of its
    # own shows through wherever a tile could not be had.
    out.append(
        f'<g clip-path="url(#map-clip)"{ground_mask}><rect class="map-back" {frame}/>'
    )
    tiles = tiles_of(extent, 1.0 / scale) if tiles_of else []
    _draw_tiles(out, tiles, place)
    out.append("</g>")

    if rings:
        path = outline
        # What the mask did not keep: without a mask to run the cut beyond the
        # line, everything outside the border is painted over instead, which
        # cuts the picture on the line itself.
        outside = ""
        if not ground_mask:
            cut = (
                f"M{origin_x:.1f},{origin_y:.1f}H{origin_x + map_w:.1f}"
                f"V{origin_y + map_h:.1f}H{origin_x:.1f}Z"
            )
            outside = f'<path class="map-outside" d="{cut}{path}"/>'
        # Painting the outside with a mask, rather than as one path with the
        # border as its inner edge, lets the cut stand off that line: the black
        # shape of the mask - the area, filled and stroked - keeps a band of
        # ground on both sides of the border visible.
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

    # One numbered pin per site, in the order the places lie next to each
    # other, which is also the order of the list underneath the map.
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
