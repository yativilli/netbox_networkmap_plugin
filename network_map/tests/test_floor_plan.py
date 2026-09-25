"""Logical floor-plan drawing tests."""

import re
from pathlib import Path

from django.test import TestCase

from .. import floor_plan
from ..views import SubnetLocationView
from ._helpers import _static


class HousePlanHoverTests(TestCase):
    """What a machine dot on the house plan says when it is hovered."""

    def test_the_hover_says_what_the_machine_is(self):
        script = _static("subnet_map/subnet_map.js")
        start = script.index("const named = machine.name")
        block = script[start : script.index("subnet-machine-tooltip", start)]
        # The name, the address and - when NetBox has more to say than the name repeats - the description of the machine, all of them escaped.
        for part in ("machine-name", "machine-ip", "machine-desc"):
            self.assertIn(part, block)
        for value in ("escapeHtml(named)", "escapeHtml(machine.ip)"):
            self.assertIn(value, block)
        self.assertIn("escapeHtml(machine.description)", block)

    def test_the_stylesheet_knows_the_description_line(self):
        sheet = _static("subnet_map/subnet_map.css")
        self.assertIn(".subnet-machine-tooltip .machine-desc", sheet)

    def test_the_dots_are_placed_at_all(self):
        # A refactor dropped the forEach index while the marker stacked by it, and no dot was painted.
        script = _static("subnet_map/subnet_map.js")
        start = script.index("function addMachineMarkers")
        block = script[start : script.index("layer.addTo(currentMap", start)]
        self.assertIn("zIndexOffset: 6000 + index", block)
        self.assertRegex(block, r"machines\.forEach\(\(machine, index\) =>")


class FloorPlanBandTitleTests(TestCase):
    """The floor name at the left of each band of the generated floor plan."""

    def setUp(self):
        self.script = _static("subnet_map/subnet_map.js")
        self.layout = self.script[self.script.index("function buildLogicalLayout") :]

    def test_the_band_title_is_never_cut_off(self):
        # "Other rooms" came out as "Other roo...", because the name was cut to what a column of a fixed width could hold; it is now wrapped.
        self.assertNotIn("fmax", self.layout)
        self.assertNotIn("flabel", self.layout)
        self.assertIn("wrapWords(floor.label, BAND_W - 16", self.layout)
        self.assertNotIn("\u2026", self.layout[: self.layout.index("countChipText")])

    def test_the_column_grows_for_a_longer_name(self):
        # A name that fits on one line gets a wider column rather than a wrap; only past the widest column does it go over lines.
        self.assertIn(
            "Math.max(BAND_MIN, Math.ceil(widestFloor * FLOOR_LABEL_CHAR_W) + 24)",
            self.layout,
        )
        self.assertIn("BAND_MAX, Math.max(BAND_MIN", self.layout)


class FloorPlanLegendTests(TestCase):
    """The colour and shape key at the bottom of the generated floor plan."""

    def setUp(self):
        self.script = _static("subnet_map/subnet_map.js")
        self.layout = self.script[self.script.index("function buildLogicalLayout") :]

    def test_every_colour_of_the_plan_is_named(self):
        # A dot's colour says which prefix of which subnet a machine sits in, so every colour the plan shows has to be named in it as well.
        self.assertIn("color: pin.color", self.layout)
        self.assertIn("subnet: pin.subnet || ''", self.layout)
        self.assertIn("prefix: pin.prefix || ''", self.layout)
        self.assertIn("LEGEND_SWATCH", self.layout)
        # A prefix without a machine has no dot, so it is not keyed either.
        self.assertIn("if (!pin.machines.length)", self.layout)

    def test_the_key_is_a_rectangle_of_its_own(self):
        # The key stands right of the rooms; the rooms keep the width they had before it existed.
        self.assertIn("const legendX = PLAN_W + GAP;", self.layout)
        self.assertIn(
            "const W = entries.length ? legendX + LEGEND_W + PAD : PLAN_W;", self.layout
        )
        self.assertIn("PLAN_W - 2 * PAD - BAND_W - 12", self.layout)
        self.assertIn('x="${legendX}" y="110" width="${LEGEND_W}" ', self.layout)
        self.assertIn('fill="#ece7da"', self.layout)
        self.assertIn("t('legend', 'Legend')", self.layout)

    def test_a_long_subnet_name_goes_under_its_prefix(self):
        # Nothing of a subnet name is cut to the width of the key: what does not fit beside its prefix is written over lines under it.
        self.assertIn("wrapWords(entry.note, legendInner, CHIP_CHAR_W)", self.layout)
        self.assertNotIn("entry.note.slice(", self.layout)
        self.assertIn(
            "LEGEND_PAD + entries.reduce((tall, entry) => tall + entry.height, 0)",
            self.layout,
        )

    def test_the_key_follows_the_view_down_a_tall_plan(self):
        # A tall plan moves its key with the view: the key is one group, never pushed out of the plan.
        self.assertIn("<g class=\"plan-legend\">${key.join('')}</g>", self.script)
        self.assertIn("function stickLegend()", self.script)
        self.assertIn("map.on('move', stickLegend);", self.script)
        self.assertIn("map.off('move', stickLegend);", self.script)
        self.assertIn("Math.max(0, Math.min(slack, seen - box.y))", self.script)

    def test_the_exported_picture_keeps_the_key_where_the_plan_puts_it(self):
        # The exported picture is taken while the key may be stuck to the window, and nothing in it is hovered.
        export = _static("shared/svg_export.js")
        self.assertIn('/<g class="plan-legend"[^>]*>/g', export)
        self.assertIn("key-lit", export)

    def test_both_dot_shapes_are_explained(self):
        self.assertIn("t('physical_machine', 'Physical machine')", self.layout)
        self.assertIn("t('virtual_machine', 'Virtual machine')", self.layout)
        # The hollow chip is the virtual machine's dot: the plan's own ground showing through, ringed like the marker stylesheet draws it.
        self.assertIn('fill="#f7f4ea" stroke="#6b6b63" stroke-width="3"', self.layout)

    def test_the_key_words_come_from_the_server(self):
        data = SubnetLocationView().build_map_data([])
        for key in ("legend", "physical_machine", "virtual_machine"):
            self.assertIn(key, data["ui"])
            self.assertTrue(data["ui"][key])


class HousePlanSubnetHoverTests(TestCase):
    """Hovering a machine on the floor plan picks its subnet out."""

    def setUp(self):
        self.script = _static("subnet_map/subnet_map.js")

    def test_only_the_machine_under_the_cursor_is_ringed(self):
        # The colour of a dot already ties it to its subnet; ringing every dot of that subnet as well hid the one machine the cursor was on.
        self.assertIn("subnet: pin.subnet || ''", self.script)
        self.assertIn("function lightSubnet(marker, subnet, on)", self.script)
        self.assertIn("classList.toggle('hovered', on)", self.script)
        self.assertNotIn("subnetDots", self.script)
        self.assertIn(
            "marker.on('mouseover', () => lightSubnet(marker, machine.subnet, true))",
            self.script,
        )
        self.assertIn(
            "marker.on('mouseout', () => lightSubnet(marker, machine.subnet, false))",
            self.script,
        )

    def test_the_key_entry_naming_the_subnet_lights_with_it(self):
        self.assertIn("classList.toggle('key-lit', on)", self.script)
        self.assertIn('.legend-entry[data-subnet="${value}"]', self.script)
        # A subnet is named after whatever its owner typed, quotes included.
        self.assertIn("String(subnet).replace(", self.script)

    def test_the_stylesheet_knows_both_marks(self):
        sheet = _static("subnet_map/subnet_map.css")
        self.assertIn(".subnet-machine-pin.hovered", sheet)
        self.assertIn(".plan-legend .legend-entry.key-lit", sheet)


class FloorPlanParityTests(TestCase):
    """
    The served plan and the one the page draws are built apart, so the
    measurements they lay a plan out by are only allowed to move together.
    """

    METRICS = (
        "PLAN_W",
        "PAD",
        "GAP",
        "BAND_MIN",
        "BAND_MAX",
        "CHIP_CHAR_W",
        "ROOM_LABEL_CHAR_W",
        "FLOOR_LABEL_CHAR_W",
        "GRID_PAD",
        "GRID_DOT_DX",
        "GRID_DOT_DENSITY",
        "GRID_ROW_H",
        "ROOM_MIN_H",
        "FLOOR_LINE_H",
        "LEGEND_SWATCH",
        "LEGEND_TEXT_DX",
        "LEGEND_ROW_H",
        "LEGEND_NOTE_H",
        "LEGEND_PAD",
        "LEGEND_TITLE_H",
        "LEGEND_MIN",
        "LEGEND_MAX",
    )

    def test_the_page_and_the_picture_measure_a_plan_alike(self):
        java = (
            Path(floor_plan.__file__).parent
            / "static/network_map/subnet_map/subnet_map.js"
        ).read_text(encoding="utf-8")
        for metric in self.METRICS:
            with self.subTest(metric=metric):
                python = getattr(floor_plan, metric)
                digits = repr(python)
                pattern = rf"\b{metric} = (-?[\d.]+)[,;]"
                match = re.search(pattern, java)
                self.assertIsNotNone(match, f"{metric} is gone from the page")
                self.assertEqual(float(match.group(1)), float(python), digits)

    def test_the_floor_of_a_location_is_read_the_same_way(self):
        for name, expected in (
            ("2. Stock - Gang - DigiKri", (2, "2. Stock")),
            ("U204", (-2, "UG")),
            ("O 242", (100, "OG")),
            ("EG 12", (0, "EG")),
            ("B\u00fcro 267", (2, "2. Stock")),
            ("019", (0, "EG")),
        ):
            with self.subTest(name=name):
                self.assertEqual(floor_plan.logical_floor(name), expected)
