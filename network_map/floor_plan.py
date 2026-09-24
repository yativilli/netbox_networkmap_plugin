"""
The floor plan of one site as a picture of its own: the logical map built from
NetBox locations.

The logical layout is a port of `buildLogicalLayout()` in
`network_map/static/network_map/subnet_map.js`, so the served plan and the one
the map page draws agree on floors, room boxes and the colour key. Because the
page keeps its own copy, the shared metrics are pinned in both files by
`FloorPlanParityTests`, which fails when one of them moves on its own.
"""

import math
import re

from django.utils.html import escape
from django.utils.translation import gettext as _

from . import svg_render

# The page's metrics, character for character, so both pictures come out the same size.
PLAN_W = 1400
PAD = 34
GAP = 14
BAND_MIN = 150  # the floor name's column is never narrower
BAND_MAX = 300  # nor wider; a longer name goes over lines
CHIP_CHAR_W = 7.4  # glyph width of the 14px count chip
ROOM_LABEL_CHAR_W = 8.6  # glyph width of the 17px room label
FLOOR_LABEL_CHAR_W = 11.7  # glyph width of the 22px floor label
GRID_PAD = 16  # padding inside a room box's dot grid
GRID_DOT_DX = 18  # minimum horizontal dot spacing
GRID_DOT_DENSITY = 2.5  # target fill ratio of the dot grid
GRID_ROW_H = 30  # machine-dot row pitch
ROOM_MIN_H = 150  # minimum room box height
FLOOR_LINE_H = 24  # pitch of a wrapped floor name's lines
LEGEND_SWATCH = 20  # side of a prefix's colour chip
LEGEND_TEXT_DX = 30  # from an entry's chip to its text
LEGEND_ROW_H = 30  # height of an entry's own line
LEGEND_NOTE_H = 18  # pitch of a subnet name's wrapped lines
LEGEND_PAD = 16  # space inside the key's rectangle
LEGEND_TITLE_H = 74  # room above the entries for the title
LEGEND_MIN = 240  # the key is never narrower ...
LEGEND_MAX = 460  # ... nor wider, so the plan stays a plan

# Numbered dots and a machine list under the plan, as the browser export does for dense plans.
BADGE_R = 9  # a numbered machine dot
LIST_EDGE = 24  # where the first list column starts
LIST_COL_W = 384  # width of one machine column of the list
LIST_ROW_H = 40  # height of a list entry's own two lines
LIST_TEXT_DX = 20  # from an entry's dot to its text
LIST_SUB_DY = 16  # from an entry's name to its description and address
LIST_NAME_CHAR_W = 9.0  # glyph width of the 15px machine name
LIST_SUB_CHAR_W = 8.1  # glyph width of the 13.5px line under it

PLAN_STYLE = "\n".join(
    (
        f"text {{ font-family: {svg_render.FONT}; pointer-events: none; }}",
        ".map-machine { stroke-width: 2; }",
        ".map-machine.is-vm { stroke-width: 3; }",
        ".map-machine-num { font-size: 9.5px; font-weight: 700; fill: #ffffff;",
        "  text-anchor: middle; paint-order: stroke;",
        "  stroke: rgba(0, 0, 0, 0.45); stroke-width: 2px; }",
        # The export halos virtual numbers white; on our own ground that halo would paint over the digit.
        ".map-machine-num.is-vm { fill: #1f2937; stroke: none; }",
        ".map-list-name { font-size: 15px; font-weight: 700; }",
        ".map-list-sub { font-size: 13.5px; fill: #6c757d; }",
    )
)

STOCK = re.compile(r"(\d+)\.\s*stock\b", re.IGNORECASE)
BASEMENT = re.compile(r"^(UG|ET|KG)\b|^U[\d\s]", re.IGNORECASE)
GROUND = re.compile(r"^EG\b", re.IGNORECASE)
ATTIC = re.compile(r"^(OG|AD)\b|^O[\d\s]", re.IGNORECASE)
ROOM_NUMBER = re.compile(r"\b(\d{2,3})\b")


def logical_floor(name):
    """
    The floor a NetBox location name stands for, as `(sort, label)`, exactly
    as the page derives it: "2. Stock - Gang" -> 2. Stock, "U204" -> UG,
    "O 242" -> OG, "Büro 267" -> 2. Stock, "019" -> EG. The Swiss labels
    UG/EG/OG and "N. Stock" deliberately stay untranslated.
    """
    name = str(name or "")
    match = STOCK.search(name)
    if match:
        floor = int(match.group(1))
        return floor, f"{floor}. Stock"
    if BASEMENT.match(name):
        return -2, "UG"
    if GROUND.match(name):
        return 0, "EG"
    if ATTIC.match(name):
        return 100, "OG"
    match = ROOM_NUMBER.search(name)
    if match:
        digit = int(match.group(1)[0])
        return (0, "EG") if digit == 0 else (digit, f"{digit}. Stock")
    return 200, _("Other rooms")


def wrap_words(value, width_px, char_w):
    """
    A label over as many lines as the given width takes. Only a word wider
    than a line itself is broken, so nothing of a name is lost the way a cut
    off one is.
    """
    take = max(1, int(width_px / char_w))
    words = [
        word[start : start + take]
        for word in str(value).split()
        for start in range(0, len(word), take)
    ]
    lines = []
    line = ""
    for word in words:
        joined = f"{line} {word}" if line else word
        if line and len(joined) * char_w > width_px:
            lines.append(line)
            line = word
        else:
            line = joined
    if line:
        lines.append(line)
    return lines or [str(value)]


def clip_room_label(name, width_px):
    """A room name cut to its box, with the ellipsis the page draws with."""
    room = max(6, int((width_px - 10) / ROOM_LABEL_CHAR_W))
    if len(str(name)) > room:
        return f"{str(name)[: max(1, room - 1)]}…"
    return str(name)


def room_grid_cols(width_px, count):
    """Columns a room box of this width fits for `count` machines."""
    return max(
        1,
        min(
            int((width_px - GRID_PAD) / GRID_DOT_DX),
            math.ceil(math.sqrt(count * GRID_DOT_DENSITY)),
        ),
    )


def count_chip_text(name, count):
    if name == "__virtual__":
        return f"{count} {_('VM') if count == 1 else _('VMs')}"
    return f"{count} {_('machine') if count == 1 else _('machines')}"


def count_chip_width(name, count):
    return len(count_chip_text(name, count)) * CHIP_CHAR_W + 4


def _text_width(value, char_w):
    return math.ceil(len(str(value)) * char_w)


def _prefix_sort_key(prefix):
    """Numeric-aware, so 10.9.0.0/24 sorts before 10.10.0.0/24."""
    parts = re.split(r"(\d+)", str(prefix))
    return tuple(int(part) if part.isdigit() else part for part in parts)


def collect_machines(pins):
    """
    The machines of one site, in the order the page walks them: every pin of
    every subnet that has machines there, sorted by address.
    """
    machines = [
        {
            # Name, description and address: the list under the picture, as the map export keeps it.
            "name": machine.get("name") or machine["ip"],
            "description": machine.get("description") or "",
            "ip": machine["ip"],
            "room": machine.get("room") or "",
            "physical": machine.get("physical", True) is not False,
            "color": pin["color"],
            "subnet": pin.get("subnet") or "",
            "prefix": pin.get("prefix") or "",
        }
        for pin in pins
        for machine in pin["machines"]
    ]

    def by_address(machine):
        parts = re.split(r"(\d+)", machine["ip"])
        return tuple(int(part) if part.isdigit() else part for part in parts)

    machines.sort(key=by_address)
    return machines


def _bands(counts, floors):
    """Each floor's band: room widths by machine count, tall enough for grids."""
    bands = []
    for floor in floors:
        gap = 10 if len(floor["rooms"]) > 1 else 0
        avail_w = (
            PLAN_W - 2 * PAD - floor["band_w"] - 12 - gap * (len(floor["rooms"]) - 1)
        )
        weights = [math.pow(counts.get(name, 0), 0.65) + 1.6 for name in floor["rooms"]]
        total_w = sum(weights)
        max_rows = 1
        stacked = False
        widths = []
        for index, name in enumerate(floor["rooms"]):
            width = max(60.0, avail_w * weights[index] / total_w)
            count = counts.get(name, 0)
            cols = room_grid_cols(width, count)
            max_rows = max(max_rows, math.ceil(count / cols) if cols else 1)
            if (
                name not in ("", "__virtual__")
                and count > 0
                and width - count_chip_width(name, count) - 12 < 60
            ):
                stacked = True
            widths.append({"w": width, "cols": cols})
        box_h = max(ROOM_MIN_H, max_rows * GRID_ROW_H + 24)
        bands.append(
            {
                "floor": floor,
                "gap": gap,
                "widths": widths,
                "box_h": box_h,
                "stacked": stacked,
                "shift": 24 if stacked else 0,
            }
        )
    return bands


def _key_entries(pins, counts, vm_total):
    """One entry per prefix with a machine here, in the colour its dots carry."""
    shades = []
    seen = set()
    for pin in pins:
        if not pin["machines"]:
            continue
        key = f"{pin.get('subnet') or ''}|{pin.get('prefix') or ''}"
        if key in seen:
            continue
        seen.add(key)
        shades.append(
            {
                "subnet": pin.get("subnet") or "",
                "prefix": pin.get("prefix") or "",
                "color": pin["color"],
            }
        )
    shades.sort(key=lambda shade: (shade["subnet"], _prefix_sort_key(shade["prefix"])))
    entries = [
        {
            "color": shade["color"],
            "text": shade["prefix"],
            "note": shade["subnet"],
            "subnet": shade["subnet"],
        }
        for shade in shades
    ]
    physical = sum(count for name, count in counts.items() if name != "__virtual__")
    if physical > 0:
        entries.append({"shape": "full", "text": _("Physical machine")})
    if vm_total > 0:
        entries.append({"shape": "hollow", "text": _("Virtual machine")})
    return entries


def _key_rectangle(entries):
    """The key's own rectangle beside the rooms; {} when there is nothing to say."""
    if not entries:
        return {}
    widest = max(
        LEGEND_TEXT_DX
        + _text_width(entry["text"], ROOM_LABEL_CHAR_W)
        + (12 + _text_width(entry["note"], CHIP_CHAR_W) if entry.get("note") else 0)
        for entry in entries
    )
    width = min(LEGEND_MAX, max(LEGEND_MIN, widest + 2 * LEGEND_PAD))
    inner = width - 2 * LEGEND_PAD - LEGEND_TEXT_DX
    for entry in entries:
        note = entry.get("note")
        beside = bool(note) and (
            _text_width(entry["text"], ROOM_LABEL_CHAR_W)
            + 12
            + _text_width(note, CHIP_CHAR_W)
            <= inner
        )
        entry["note_beside"] = beside
        entry["note_lines"] = (
            [] if beside or not note else wrap_words(note, inner, CHIP_CHAR_W)
        )
        entry["height"] = LEGEND_ROW_H + len(entry["note_lines"]) * LEGEND_NOTE_H
    title = wrap_words(_("Legend"), width - 2 * LEGEND_PAD, FLOOR_LABEL_CHAR_W)
    height = (
        LEGEND_TITLE_H
        + (len(title) - 1) * FLOOR_LINE_H
        + LEGEND_PAD
        + sum(entry["height"] for entry in entries)
        + LEGEND_PAD
    )
    return {"width": width, "height": height, "title": title}


def build_layout(site_name, pins, room_names):
    """
    The logical plan of one site: floors as bands, rooms as boxes, machines as
    dots, and the colour key beside them. Returns the drawing's size, the room
    boxes and the markup, or None when the site holds no machines at all.
    """
    counts = {}
    vm_total = 0
    machines = collect_machines(pins)
    for machine in machines:
        if not machine["physical"]:
            vm_total += 1
            continue
        counts[machine["room"]] = counts.get(machine["room"], 0) + 1
    rooms = list(counts)
    for name in room_names or []:
        if name not in rooms:
            rooms.append(name)
        counts.setdefault(name, 0)

    grouped = {}
    for name in rooms:
        if name == "":
            continue
        sort, label = logical_floor(name)
        grouped.setdefault(sort, {"sort": sort, "label": label, "rooms": []})[
            "rooms"
        ].append(name)
    floors = [grouped[sort] for sort in sorted(grouped, reverse=True)]
    if "" in rooms:
        only = all(name == "" for name in rooms)
        floors.append(
            {
                "sort": -1000,
                "label": _("Machines") if only else _("No location"),
                "rooms": [""],
            }
        )
    if vm_total:
        counts["__virtual__"] = vm_total
        floors.append({"sort": -2000, "label": _("Virtual"), "rooms": ["__virtual__"]})
    if not machines and not floors:
        return None

    widest = max(len(str(floor["label"])) for floor in floors) if floors else 0
    band_w = min(BAND_MAX, max(BAND_MIN, math.ceil(widest * FLOOR_LABEL_CHAR_W) + 24))
    for floor in floors:
        floor["band_w"] = band_w

    bands = _bands(counts, floors)
    entries = _key_entries(pins, counts, vm_total)
    key = _key_rectangle(entries)
    legend_x = PLAN_W + GAP
    width = PLAN_W + key["width"] + GAP + PAD if key else PLAN_W
    rooms_h = (
        110 + sum(band["box_h"] + 90 + GAP + band["shift"] for band in bands) + PAD
    )
    height = max(rooms_h, 110 + key.get("height", 0) + PAD)

    out = [
        (
            f'<text x="{PAD}" y="64" font-size="26" fill="#3d3d38" font-style="italic">'
            f"{escape(site_name)} \u2014 {escape(_('logical floor map'))}</text>"
        ),
        (
            f'<text x="{PLAN_W - PAD}" y="64" text-anchor="end" font-size="16" '
            f'fill="#8a8378">{escape(_("generated from NetBox locations"))}</text>'
        ),
    ]
    boxes = {}
    y0 = 110
    for band in bands:
        floor = band["floor"]
        box_h = band["box_h"]
        shift = band["shift"]
        out.append(
            f'<rect x="{PAD}" y="{y0}" width="{PLAN_W - 2 * PAD}" '
            f'height="{box_h + 74 + shift}" rx="8" fill="#ece7da" '
            'stroke="#d8d2c2" stroke-width="1.5"/>'
        )
        for k, line in enumerate(
            wrap_words(floor["label"], band_w - 16, FLOOR_LABEL_CHAR_W)
        ):
            out.append(
                f'<text x="{PAD + band_w / 2}" y="{y0 + 40 + k * FLOOR_LINE_H}" '
                'text-anchor="middle" font-size="22" font-weight="bold" '
                f'fill="#6b5d4a">{escape(line)}</text>'
            )
        box_top = y0 + 62 + shift
        x = PAD + band_w + 6
        for index, name in enumerate(floor["rooms"]):
            room_w = band["widths"][index]["w"]
            count = counts.get(name, 0)
            if name not in ("", "__virtual__"):
                budget = (
                    room_w - 6
                    if band["stacked"]
                    else room_w - (count_chip_width(name, count) + 12 if count else 10)
                )
                out.append(
                    f'<text x="{x}" y="{box_top - (32 if band["stacked"] else 8)}" '
                    f'font-size="17" fill="#3d3d38">'
                    f"{escape(clip_room_label(name, budget))}</text>"
                )
            if count:
                anchor = (
                    f'x="{x}"'
                    if band["stacked"]
                    else f'x="{x + room_w - 6}" text-anchor="end"'
                )
                out.append(
                    f'<text {anchor} y="{box_top - 8}" font-size="14" '
                    f'fill="#8a8378">{escape(count_chip_text(name, count))}</text>'
                )
            out.append(
                f'<rect x="{x}" y="{box_top}" width="{room_w:.1f}" height="{box_h}" '
                'rx="6" fill="#f7f4ea" stroke="#6b6b63" stroke-width="2.5"/>'
            )
            boxes[name] = {
                "x": x,
                "y": box_top,
                "w": room_w,
                "h": box_h,
                "cols": band["widths"][index]["cols"],
            }
            x += room_w + band["gap"]
        y0 += box_h + 90 + GAP + shift

    # The room grid keeps badges apart by construction, so the dots never need nudging.
    out.extend(machine_badges(machines, grid_points(machines, boxes)))
    if key:
        out.append(_draw_key(key, entries, legend_x))
    bottom, listing = machine_list(machines, width, height - PAD + GAP)
    out.extend(listing)
    height = max(height, bottom + PAD)
    return {
        "w": width,
        "h": height,
        "boxes": boxes,
        "body": "".join(out),
        "floors": [floor["label"] for floor in floors],
        "rooms": len([name for name in rooms if name != ""]),
        "machines": len(machines),
    }


def grid_points(machines, boxes):
    """
    Where each machine's dot stands in its room, keyed by its place in the
    machine list; room by room, in the order the machines are walked.
    """
    totals = {}
    for machine in machines:
        room = machine["room"] if machine["physical"] else "__virtual__"
        totals[room] = totals.get(room, 0) + 1
    seen = {}
    points = {}
    for index, machine in enumerate(machines):
        room = machine["room"] if machine["physical"] else "__virtual__"
        box = boxes.get(room) or boxes.get("")
        if not box:
            continue
        count = seen.get(room, 0)
        seen[room] = count + 1
        total = totals[room]
        cols = box["cols"] or room_grid_cols(box["w"], total)
        rows = max(1, math.ceil(total / cols))
        cell_w = (box["w"] - GRID_PAD) / cols
        cell_h = max(GRID_PAD, (box["h"] - GRID_PAD) / rows)
        points[index] = (
            box["x"] + 8 + ((count % cols) + 0.5) * cell_w,
            box["y"] + 8 + math.floor(count / cols) * cell_h + cell_h / 2,
        )
    return points


def machine_badges(machines, points):
    """
    The dots, numbered and in the machine's colour, a virtual one hollow; the
    number is what ties a dot to its line in the list under the plan.
    """
    out = []
    for index, machine in enumerate(machines):
        point = points.get(index)
        if point is None:
            continue
        color = machine["color"] or "#6b6b63"
        fill = color if machine["physical"] else "#ffffff"
        virtual = "" if machine["physical"] else " is-vm"
        out.append(
            f'<circle class="map-machine{virtual}" cx="{point[0]:.1f}" '
            f'cy="{point[1]:.1f}" r="{BADGE_R}" fill="{escape(fill)}" '
            f'stroke="{escape(color)}"/>'
        )
        out.append(
            f'<text class="map-machine-num{virtual}" x="{round(point[0])}" '
            f'y="{round(point[1]) + 3}">{index + 1}</text>'
        )
    return out


def clip_to(value, width_px, char_w):
    """A label cut to the room it has, with the ellipsis the export cuts with."""
    label = str(value or "")
    while len(label) > 1 and (len(label) + 1) * char_w > width_px:
        label = label[:-1]
    if label != str(value or ""):
        label = re.sub(r"[\s.,;:)+/-]+$", "", label) + "\u2026"
    return label


def machine_list(machines, width, start_y):
    """
    The machines in columns under the plan: number and name in the colour of
    their dot, what the machine is for and its address on the line under it.
    """
    if not machines:
        return start_y, []
    columns = max(1, int((width - 2 * LIST_EDGE) // LIST_COL_W) or 1)
    per_column = math.ceil(len(machines) / columns)
    room = LIST_COL_W - 34
    bottoms = [0] * columns
    out = []
    for index, machine in enumerate(machines):
        column = min(int(index / per_column), columns - 1)
        x = LIST_EDGE + column * LIST_COL_W
        y = start_y + bottoms[column]
        color = machine["color"] or "#6b6b63"
        fill = color if machine["physical"] else "#ffffff"
        virtual = "" if machine["physical"] else " is-vm"
        out.append(
            f'<circle class="map-machine{virtual}" cx="{x + 6}" cy="{y - 4}" r="6" '
            f'fill="{escape(fill)}" stroke="{escape(color)}"/>'
        )
        name = f"{index + 1}  {machine['name']}{'' if machine['physical'] else ' (VM)'}"
        out.append(
            f'<text class="map-list-name" x="{x + LIST_TEXT_DX}" y="{y}" '
            f'style="fill:{escape(color)}">'
            f"{escape(clip_to(name, room, LIST_NAME_CHAR_W))}</text>"
        )
        sub = " \u2014 ".join(
            part for part in (machine["description"], machine["ip"]) if part
        )
        out.append(
            f'<text class="map-list-sub" x="{x + LIST_TEXT_DX}" '
            f'y="{y + LIST_SUB_DY}">{escape(clip_to(sub, room, LIST_SUB_CHAR_W))}</text>'
        )
        bottoms[column] += LIST_ROW_H
    return start_y + max(bottoms) + 6, out


def _draw_key(key, entries, legend_x):
    """The colour and shape key, in its own rectangle beside the rooms."""
    width = key["width"]
    parts = [
        (
            f'<g class="plan-legend"><rect x="{legend_x}" y="110" width="{width}" '
            f'height="{key["height"]}" rx="8" fill="#ece7da" stroke="#d8d2c2" '
            'stroke-width="1.5"/>'
        )
    ]
    for k, line in enumerate(key["title"]):
        parts.append(
            f'<text x="{legend_x + LEGEND_PAD}" y="{110 + 44 + k * FLOOR_LINE_H}" '
            'font-size="22" font-weight="bold" fill="#6b5d4a">'
            f"{escape(line)}</text>"
        )
    y = 110 + LEGEND_TITLE_H + (len(key["title"]) - 1) * FLOOR_LINE_H + LEGEND_PAD
    for entry in entries:
        x = legend_x + LEGEND_PAD
        base = y + 20
        lines = []
        if entry.get("shape"):
            chip = (
                'fill="#6b6b63"/>'
                if entry["shape"] == "full"
                else 'fill="#f7f4ea" stroke="#6b6b63" stroke-width="3"/>'
            )
            lines.append(
                f'<circle cx="{x + LEGEND_SWATCH / 2}" '
                f'cy="{base - LEGEND_SWATCH / 2 + 5}" r="9" {chip}'
            )
        else:
            lines.append(
                f'<rect x="{x}" y="{base - LEGEND_SWATCH + 5}" '
                f'width="{LEGEND_SWATCH}" height="{LEGEND_SWATCH}" rx="4" '
                f'fill="{escape(entry["color"])}" stroke="#6b6b63" '
                'stroke-width="1.5"/>'
            )
        lines.append(
            f'<text x="{x + LEGEND_TEXT_DX}" y="{base}" font-size="17" '
            f'fill="#3d3d38">{escape(entry["text"])}</text>'
        )
        if entry.get("note_beside"):
            note_x = (
                x + LEGEND_TEXT_DX + _text_width(entry["text"], ROOM_LABEL_CHAR_W) + 12
            )
            lines.append(
                f'<text x="{note_x}" y="{base}" font-size="14" fill="#8a8378">'
                f"{escape(entry['note'])}</text>"
            )
        for k, line in enumerate(entry["note_lines"]):
            lines.append(
                f'<text x="{x + LEGEND_TEXT_DX}" '
                f'y="{base + (k + 1) * LEGEND_NOTE_H}" font-size="14" '
                f'fill="#8a8378">{escape(line)}</text>'
            )
        parts.append(f'<g class="legend-entry">{"".join(lines)}</g>')
        y += entry["height"]
    parts.append("</g>")
    return "".join(parts)


def render_logical(site_name, pins, room_names):
    """The logical floor map of one site, framed like the other pictures."""
    layout = build_layout(site_name, pins, room_names)
    if layout is None:
        return None
    body = (
        f'<rect x="0" y="0" width="{layout["w"]}" height="{layout["h"]}" '
        'fill="#f8f5ec"/>'
        f'<rect x="4" y="4" width="{layout["w"] - 8}" height="{layout["h"] - 8}" '
        'fill="none" stroke="#555" stroke-width="4"/>'
        f"{layout['body']}"
    )
    return svg_render.build_svg(layout["w"], layout["h"], body, style=PLAN_STYLE)
