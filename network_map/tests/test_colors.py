"""Colour-shade tests."""

from types import SimpleNamespace
from unittest import mock

from dcim.models import (
    Site,
)
from django.test import TestCase

from ..colors import shade_of
from ..views import SubnetLocationView


class ShadeOfTests(TestCase):
    def test_first_index_keeps_the_base_colour(self):
        self.assertEqual(shade_of("#0072b2", 0), "#0072b2")

    def test_indexes_produce_distinct_shades(self):
        shades = [shade_of("#0072b2", index) for index in range(9)]
        self.assertEqual(len(set(shades)), 9)
        for shade in shades:
            self.assertRegex(shade, r"^#[0-9a-f]{6}$")

    def test_shades_alternate_lighter_and_darker(self):
        self.assertGreater(shade_of("#0072b2", 1), "#0072b2")
        self.assertLess(shade_of("#0072b2", 2), "#0072b2")

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
        # Same subnet, second prefix: the base colour lightened one step.
        self.assertNotEqual(first, second)
        self.assertEqual(shade_of(first, 1), second)
        self.assertNotIn(colors[("Office", "10.3.0.0/24")], (first, second))
