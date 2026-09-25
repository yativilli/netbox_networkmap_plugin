"""Logical-tree SVG renderer."""

from django.utils.translation import gettext as _

from .base import (
    BOTTOM_PAD,
    RIGHT_PAD,
    STAGE_COLORS,
    WIDTH,
    _ph,
    build_svg,
    chars,
    text,
    wrap_lines,
)

# ---------------------------------------------------------------------- Logical map (VLAN connections tree)


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
