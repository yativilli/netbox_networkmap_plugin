"""
Server-side SVG renderers for the three map views, mirroring the browser
exports (svg_export.js / vlan_topology.js) as simple hand-drawn vectors.
Text wrapping uses a rough per-character estimate instead of real font
metrics, so break points can deviate slightly from the browser version.
"""

import math

from django.utils.html import escape
from django.utils.translation import gettext as _

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
            name_lines = wrap_lines(machine["name"], 11, 2)
            ip = machine["ip"]
            name_block = (len(name_lines) - 1) * 11
            name_mid = cy - (7 if ip else 0) - name_block / 2
            _add_text(out, "topo-machine-label", cx, name_mid, name_lines, 11)
            if ip:
                _add_text(
                    out,
                    "topo-machine-ip",
                    cx,
                    name_mid + name_block / 2 + 12,
                    [ip],
                    11,
                )
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
