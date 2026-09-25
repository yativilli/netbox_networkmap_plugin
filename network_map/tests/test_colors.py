"""Colour tests for the map palette and subnet prefix shades."""

import colorsys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dcim.models import Site
from django.test import TestCase

from ..colors import (
    BASE_COLORS,
    LOCATION_COLORS,
    MIN_BASE_DISTANCE,
    oklab_distance,
    shade_of,
)
from ..views import SubnetLocationView

PALETTE_CSS = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "network_map"
    / "vlan_element_list"
    / "vlan_element_list.css"
)


def _rgb(color: str) -> tuple[int, int, int]:
    return (
        int(color[1:3], 16),
        int(color[3:5], 16),
        int(color[5:7], 16),
    )


def _hue(color: str) -> float:
    red, green, blue = (channel / 255.0 for channel in _rgb(color))
    return colorsys.rgb_to_hls(red, green, blue)[0] * 360.0


def _hue_distance(left: str, right: str) -> float:
    distance = abs(_hue(left) - _hue(right)) % 360.0
    return min(distance, 360.0 - distance)


def _lightness(color: str) -> float:
    red, green, blue = (channel / 255.0 for channel in _rgb(color))
    return colorsys.rgb_to_hls(red, green, blue)[1]


class LocationPaletteTests(TestCase):
    def test_base_palette_has_no_duplicates(self):
        self.assertEqual(len(BASE_COLORS), len(set(BASE_COLORS)))

    def test_base_palette_colours_are_perceptually_apart(self):
        for index, left in enumerate(BASE_COLORS):
            for right in BASE_COLORS[index + 1 :]:
                with self.subTest(left=left, right=right):
                    self.assertGreater(oklab_distance(left, right), MIN_BASE_DISTANCE)

    def test_css_location_colors_match_the_python_palette(self):
        css = PALETTE_CSS.read_text(encoding="utf-8")
        for name, color in LOCATION_COLORS:
            red, green, blue = _rgb(color)
            expected = f".{name} {{ --location-color: {red}, {green}, {blue}; }}"
            self.assertIn(expected, css)


class ShadeOfTests(TestCase):
    def test_first_index_keeps_the_base_colour(self):
        self.assertEqual(shade_of("#0072b2", 0), "#0072b2")

    def test_indexes_produce_distinct_shades(self):
        shades = [shade_of("#0072b2", index) for index in range(9)]
        self.assertEqual(len(set(shades)), 9)
        for shade in shades:
            self.assertRegex(shade, r"^#[0-9a-f]{6}$")

    def test_shades_keep_the_base_hue(self):
        for index in range(1, 9):
            with self.subTest(index=index):
                self.assertLess(
                    _hue_distance("#0072b2", shade_of("#0072b2", index)), 30
                )

    def test_shades_alternate_lighter_and_darker(self):
        base = _lightness("#0072b2")
        self.assertGreater(_lightness(shade_of("#0072b2", 1)), base)
        self.assertLess(_lightness(shade_of("#0072b2", 2)), base)
        self.assertGreater(_lightness(shade_of("#0072b2", 3)), base)
        self.assertLess(_lightness(shade_of("#0072b2", 4)), base)

    def test_unparsable_colour_is_returned_unchanged(self):
        self.assertEqual(shade_of("bogus", 3), "bogus")
        self.assertIsNone(shade_of(None, 3))


class SubnetShadeColorsTests(TestCase):
    @staticmethod
    def _element(name, prefix, machines):
        return SimpleNamespace(
            name=name,
            prefix=prefix,
            url="/vlan/",
            machines=[
                {
                    "dns_name": f"host{index}",
                    "ip": ip,
                    "url": "/ip/",
                    "location": "DC",
                    "prefix": prefix,
                }
                for index, ip in enumerate(machines)
            ],
        )

    def test_machines_carry_their_legend_fields(self):
        Site.objects.create(name="DC", latitude=46.948, longitude=7.447)
        elements = [self._element("Prod", "10.1.0.0/24", ["10.1.0.1", "10.1.0.2"])]
        elements[0].machines[0]["description"] = "Web frontend"
        pin = SubnetLocationView().build_map_data(elements)["pins"][0]
        self.assertRegex(pin["color"], r"^#[0-9a-f]{6}$")
        described, blank = pin["machines"]
        self.assertEqual(described["name"], "host0")
        self.assertEqual(described["ip"], "10.1.0.1")
        self.assertEqual(described["description"], "Web frontend")
        self.assertEqual(blank["description"], "")

    def test_sites_are_coloured_apart_even_inside_one_subnet(self):
        Site.objects.create(name="DC", slug="dc", latitude=46.948, longitude=7.447)
        Site.objects.create(name="Office", slug="office", latitude=47.0, longitude=7.5)
        element = SimpleNamespace(
            name="Prod",
            prefix="10.1.0.0/24",
            url="/vlan/",
            machines=[
                {
                    "dns_name": "host0",
                    "ip": "10.1.0.1",
                    "url": "/ip/",
                    "location": "DC",
                    "prefix": "10.1.0.0/24",
                },
                {
                    "dns_name": "host1",
                    "ip": "10.1.0.2",
                    "url": "/ip/",
                    "location": "Office",
                    "prefix": "10.1.0.0/24",
                },
            ],
        )
        pins = SubnetLocationView().build_map_data([element])["pins"]
        self.assertEqual(len({pin["color"] for pin in pins}), 1)
        colors = {pin["site"]: pin["site_color"] for pin in pins}
        self.assertEqual(colors, {"DC": mock.ANY, "Office": mock.ANY})
        self.assertEqual(len(set(colors.values())), 2)

    def test_prefixes_of_one_subnet_share_a_shade_family(self):
        Site.objects.create(name="DC", latitude=46.948, longitude=7.447)
        elements = [
            self._element("Prod", "10.1.0.0/24", ["10.1.0.1"]),
            self._element("Prod", "10.2.0.0/24", ["10.2.0.1"]),
            self._element("Office", "10.3.0.0/24", ["10.3.0.1"]),
        ]
        data = SubnetLocationView().build_map_data(elements)
        colors = {(pin["subnet"], pin["prefix"]): pin["color"] for pin in data["pins"]}
        self.assertEqual(len(colors), 3)
        first = colors[("Prod", "10.1.0.0/24")]
        second = colors[("Prod", "10.2.0.0/24")]
        # Same subnet: the colour family stays recognisable even when the
        # lightness is nudged to keep the legend readable.
        self.assertNotEqual(first, second)
        self.assertLess(_hue_distance(first, second), 30)
        self.assertNotIn(colors[("Office", "10.3.0.0/24")], (first, second))
