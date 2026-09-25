"""Machine-list SVG renderer."""

from django.utils.html import escape
from django.utils.translation import gettext as _

from .base import (
    BOTTOM_PAD,
    CHAR_FACTOR,
    DEFAULT_ACCENT,
    GRAY,
    LOCATION_HEX,
    RIGHT_PAD,
    WIDTH,
    _ph,
    build_svg,
    chars,
    text,
    wrap_lines,
)

# ---------------------------------------------------------------------- Machine list


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
