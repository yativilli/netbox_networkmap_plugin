"""Shared SVG primitives for the server-side renderers."""

from django.utils.html import escape

from ..colors import LOCATION_COLORS

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
