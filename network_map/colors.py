import colorsys
import math

# A qualitative palette chosen for perceptual separation in OKLab.  The first
# eight entries are based on the colour-blind-safe Okabe-Ito set; the rest were
# chosen to stay distinct from it and from each other.
BASE_COLORS = (
    "#0072b2",
    "#d55e00",
    "#009e73",
    "#cc79a7",
    "#e69f00",
    "#56b4e9",
    "#882255",
    "#117733",
    "#7228e2",
    "#1cce1c",
    "#e228e2",
    "#4abfa0",
    "#b41818",
    "#ce1c93",
    "#284de2",
    "#ab1cce",
    "#e2284d",
    "#a0bf4a",
    "#879915",
    "#7e5211",
)

LOCATION_COLORS = tuple(
    (f"location-color-{index}", color) for index, color in enumerate(BASE_COLORS)
)

# Minimum OKLab distance expected between base palette colours.
MIN_BASE_DISTANCE = 0.10

# Minimum OKLab distance the view tries to keep between colours that appear
# together in a legend or map.
MIN_COLOR_DISTANCE = 0.075

# Lightness steps for prefixes of one subnet: prefix 0 keeps the base colour,
# then the ladder alternates lighter and darker while keeping the hue.
SHADE_LIGHTNESS = (
    0.66,
    0.30,
    0.74,
    0.24,
    0.80,
    0.20,
    0.86,
    0.16,
    0.90,
    0.12,
)

# Candidate lightness values used when a colour has to be nudged apart.
_ADJUST_LIGHTNESS = (
    0.68,
    0.26,
    0.50,
    0.74,
    0.32,
    0.80,
    0.20,
    0.86,
    0.14,
    0.42,
    0.60,
    0.92,
    0.36,
    0.18,
)


def color_for_location(index: int) -> str:
    return LOCATION_COLORS[index % len(LOCATION_COLORS)][0]


def color_for_location_hex(index: int) -> str:
    return LOCATION_COLORS[index % len(LOCATION_COLORS)][1]


def _clamp_channel(value: float) -> int:
    return max(0, min(255, round(value)))


def _hex_to_rgb(color: str) -> tuple[int, int, int] | None:
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
        return None
    try:
        channels = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
        return (channels[0], channels[1], channels[2])
    except ValueError:
        return None


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    return f"#{_clamp_channel(red):02x}{_clamp_channel(green):02x}{_clamp_channel(blue):02x}"


def _hex_to_hls(color: str) -> tuple[float, float, float] | None:
    rgb = _hex_to_rgb(color)
    if rgb is None:
        return None
    return colorsys.rgb_to_hls(*(channel / 255.0 for channel in rgb))


def _hls_to_hex(hue: float, lightness: float, saturation: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _rgb_to_hex(red * 255.0, green * 255.0, blue * 255.0)


def _linear_channel(value: int) -> float:
    value /= 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _to_oklab(color: str) -> tuple[float, float, float] | None:
    rgb = _hex_to_rgb(color)
    if rgb is None:
        return None

    red, green, blue = (_linear_channel(channel) for channel in rgb)
    long_wave = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    middle_wave = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short_wave = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue

    long_wave = math.copysign(abs(long_wave) ** (1.0 / 3.0), long_wave)
    middle_wave = math.copysign(abs(middle_wave) ** (1.0 / 3.0), middle_wave)
    short_wave = math.copysign(abs(short_wave) ** (1.0 / 3.0), short_wave)

    return (
        0.2104542553 * long_wave
        + 0.7936177850 * middle_wave
        - 0.0040720468 * short_wave,
        1.9779984951 * long_wave
        - 2.4285922050 * middle_wave
        + 0.4505937099 * short_wave,
        0.0259040371 * long_wave
        + 0.7827717662 * middle_wave
        - 0.8086757660 * short_wave,
    )


def oklab_distance(left: str, right: str) -> float:
    """Perceptual distance between two hex colours; invalid colours are far apart."""
    left_lab = _to_oklab(left)
    right_lab = _to_oklab(right)
    if left_lab is None or right_lab is None:
        return 0.0 if left == right else float("inf")
    return math.dist(left_lab, right_lab)


def minimum_oklab_distance(color: str, colors: list[str]) -> float:
    """Smallest distance from `color` to a list of already used colours."""
    if not colors:
        return float("inf")
    return min(oklab_distance(color, used) for used in colors)


def _adjusted_saturation(saturation: float, lightness: float) -> float:
    if saturation < 0.12:
        return saturation
    if lightness > 0.72:
        return max(0.40, min(saturation, 0.70))
    if lightness < 0.25:
        return max(0.40, min(saturation, 0.85))
    return min(saturation, 0.90)


def prefix_shade(color: str, index: int) -> str:
    """
    Return `color` for index 0, then a perceptual lightness ladder for the
    other indexes. The hue stays in place, so prefixes of one subnet remain one
    family in the subnet map, floor plans and SVG exports.
    """
    if index <= 0:
        return color
    hls = _hex_to_hls(color)
    if hls is None:
        return color
    hue, saturation, _ = hls
    lightness = SHADE_LIGHTNESS[(index - 1) % len(SHADE_LIGHTNESS)]
    return _hls_to_hex(hue, lightness, _adjusted_saturation(saturation, lightness))


def shade_of(color: str, index: int) -> str:
    """Compatibility name for the perceptual prefix-shading ladder."""
    return prefix_shade(color, index)


def with_minimum_distance(
    color: str,
    used_colors: list[str],
    threshold: float = MIN_COLOR_DISTANCE,
) -> str:
    """
    Return `color` when it is far enough from the already used colours.  If it
    is too close, move along the same hue towards another lightness and return
    the closest acceptable variant.
    """
    if not used_colors or minimum_oklab_distance(color, used_colors) >= threshold:
        return color

    hls = _hex_to_hls(color)
    if hls is None:
        return color
    hue, saturation, original_lightness = hls

    candidates: list[str] = []
    seen: set[str] = set()
    for lightness in (original_lightness, *_ADJUST_LIGHTNESS):
        candidate = _hls_to_hex(
            hue, lightness, _adjusted_saturation(saturation, lightness)
        )
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    candidates.sort(key=lambda candidate: (oklab_distance(color, candidate), candidate))
    for candidate in candidates:
        if minimum_oklab_distance(candidate, used_colors) >= threshold:
            return candidate

    return max(
        candidates,
        key=lambda candidate: (
            minimum_oklab_distance(candidate, used_colors),
            -oklab_distance(color, candidate),
            candidate,
        ),
    )


def pick_distinct_color(colors: tuple[str, ...], used_colors: list[str]) -> str:
    """Pick the palette colour that is most distant from the colours already used."""
    if not colors:
        return ""

    used = set(used_colors)
    pool = tuple(color for color in colors if color not in used) or colors

    best = pool[0]
    best_score = minimum_oklab_distance(
        best, [color for color in used_colors if color != best]
    )
    for color in pool[1:]:
        score = minimum_oklab_distance(
            color, [used for used in used_colors if used != color]
        )
        if score > best_score:
            best, best_score = color, score
    return best
