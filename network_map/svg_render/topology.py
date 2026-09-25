"""Topology SVG renderer."""

import math

from django.utils.html import escape

from .base import TOPO_STYLE, build_svg, wrap_lines

# ---------------------------------------------------------------------- Topology map (port of vlan_topology.js buildGraph)

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
    total = len(subnets)
    by_size = sorted(range(total), key=lambda index: -len(subnets[index]["machines"]))
    order = [0] * total
    used = [False] * total
    for rank, subnet_index in enumerate(by_size):
        slot = int((((rank + 1) * 0.6180339887) % 1) * total)
        while used[slot]:
            slot = (slot + 1) % total
        used[slot] = True
        order[slot] = subnet_index
    return [subnets[index] for index in order]


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
