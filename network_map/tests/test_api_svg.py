"""SVG API and subnet-map rendering tests."""

import re
import unittest
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from ipam.models import VLAN, Prefix
from users.models import ObjectPermission, User

from .. import map_tiles, png_render, svg_render
from ..views import SubnetLocationView


class SvgApiTests(TestCase):
    KINDS = ("machine-list", "logical-map", "subnet-map", "topology")

    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )
        cls.vlan = VLAN.objects.create(vid=110, name="SVG VLAN", status="active")
        Prefix.objects.create(prefix="10.10.0.0/24", vlan=cls.vlan)
        cls.user = User.objects.create_user(username="svgviewer", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-svg",
            actions=["view"],
        )
        permission.object_types.add(cls.map_content_type)
        cls.user.object_permissions.add(permission)

    def setUp(self):
        # The ground of a served map comes off the network, which no test has to wait for; the tests that care about it say what it looks like.
        patcher = mock.patch.object(map_tiles, "background", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_svg(self, kind, query=None):
        # The mount prefix derives from the plugin's base_url/module name.
        for prefix in ("networkmap", "network_map"):
            url = f"/api/plugins/{prefix}/{kind}/"
            if query:
                url = f"{url}?{query}"
            response = self.client.get(url)
            if response.status_code != 404:
                return response
        return response

    def test_svg_endpoints_render(self):
        self.client.force_login(self.user)
        for kind in self.KINDS:
            with mock.patch(
                "network_map.api.views.get_canton_boundary", return_value=None
            ):
                response = self.get_svg(kind)
            self.assertEqual(response.status_code, 200, kind)
            self.assertTrue(response["Content-Type"].startswith("image/svg+xml"), kind)
            self.assertIn(b"<svg", response.content)

    @unittest.skipUnless(png_render.available(), "needs cairosvg or ImageMagick")
    def test_png_endpoints_render(self):
        self.client.force_login(self.user)
        for kind in self.KINDS:
            with mock.patch(
                "network_map.api.views.get_canton_boundary", return_value=None
            ):
                response = self.get_svg(kind, "format=png")
            self.assertEqual(response.status_code, 200, kind)
            self.assertTrue(response["Content-Type"].startswith("image/png"), kind)
            self.assertTrue(response.content.startswith(png_render.PNG_MAGIC), kind)

    def test_png_without_a_rasteriser_says_so(self):
        self.client.force_login(self.user)
        with mock.patch(
            "network_map.api.views.png_render.available", return_value=False
        ):
            response = self.get_svg("topology", "format=png")
        self.assertEqual(response.status_code, 501)
        self.assertIn(b"cairosvg", response.content)
        self.assertIn(b"<svg", self.get_svg("topology").content)

    def test_subnet_map_svg_uses_the_configured_border(self):
        self.client.force_login(self.user)
        with (
            mock.patch(
                "network_map.api.views.get_canton_boundary", return_value=MAP_BORDER
            ),
            mock.patch(
                "network_map.api.views.get_canton_label", return_value="Kanton Bern"
            ),
        ):
            response = self.get_svg("subnet-map")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"map-frame", response.content)
        self.assertIn(b'class="map-border"', response.content)
        self.assertIn(b"Kanton Bern", response.content)

    def test_a_served_map_carries_the_ground_it_was_given(self):
        self.client.force_login(self.user)
        tile = {
            "href": "data:image/jpeg;base64,TESTTILE",
            "rect": (400000.0, 150000.0, 900000.0, 300000.0),
        }
        with (
            mock.patch(
                "network_map.api.views.get_canton_boundary", return_value=MAP_BORDER
            ),
            mock.patch.object(map_tiles, "background", return_value=[tile]) as ground,
        ):
            response = self.get_svg("subnet-map")
        self.assertIn(
            b'<image href="data:image/jpeg;base64,TESTTILE"', response.content
        )
        self.assertTrue(ground.called)

    def test_a_plain_drawing_asks_for_no_ground(self):
        self.client.force_login(self.user)
        with (
            mock.patch(
                "network_map.api.views.get_canton_boundary", return_value=MAP_BORDER
            ),
            mock.patch.object(map_tiles, "background", return_value=[]) as ground,
        ):
            response = self.get_svg("subnet-map", "background=0")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<image", response.content)
        ground.assert_not_called()

    def test_unknown_kind_returns_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.get_svg("nope").status_code, 404)

    def test_api_root_lists_svg_endpoints(self):
        self.client.force_login(self.user)
        url = reverse("plugins-api:network_map-api:api-root")
        response = self.client.get(url, headers={"accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("installed-plugins", data)
        self.assertIn("floor-plans", data)
        for kind in self.KINDS:
            self.assertIn(kind, data)
            # The API root links the address as it is meant to be used: the kind alone, the format belonging on the query string.
            self.assertTrue(data[kind].endswith(f"/{kind}"), data[kind])
            self.assertEqual(data[f"{kind}.png"], f"{data[kind]}?format=png")

    def test_a_picture_answers_with_and_without_a_trailing_slash(self):
        # The address of a picture is its kind with the format on the query string, and a script that leaves the slash out gets the same.
        self.client.force_login(self.user)
        url = reverse(
            "plugins-api:network_map-api:svg-export", kwargs={"kind": "topology"}
        )
        # The address the root links is the one without the slash.
        self.assertFalse(url.endswith("/"))
        with mock.patch("network_map.api.views.get_canton_boundary", return_value=None):
            plain = self.client.get(f"{url}?format=svg")
            slashed = self.client.get(f"{url}/?format=svg")
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(slashed.status_code, 200)
        self.assertTrue(plain["Content-Type"].startswith("image/svg+xml"))
        self.assertEqual(plain.content, slashed.content)

    def test_anonymous_endpoints_are_rejected(self):
        for kind in ("topology", "floor-plans"):
            with self.subTest(kind=kind):
                self.assertIn(self.get_svg(kind).status_code, (401, 403))

    def test_users_without_permission_get_403(self):
        User.objects.create_user(username="nosvg", password="pass")  # nosec B106
        self.client.login(username="nosvg", password="pass")  # nosec B106
        for kind in ("machine-list", "floor-plans"):
            with self.subTest(kind=kind):
                self.assertEqual(self.get_svg(kind).status_code, 403)


# Well-nested GeoJSON, unlike SAMPLE_BORDER: the map renderer reads the polygon rings themselves, so it needs real MultiPolygon nesting.
MAP_BORDER = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"canton_no": 2},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [6.2, 46.9],
                        [7.6, 47.3],
                        [8.3, 46.6],
                        [6.4, 46.2],
                        [6.2, 46.9],
                    ],
                    [[7.4, 47.0], [7.5, 47.0], [7.5, 46.9], [7.4, 47.0]],
                ],
            },
        }
    ],
}

# A canton drawn as a box around Bern alone, so that a site in Geneva lies far enough outside to be clamped however much room the picture.
MAP_TIGHT_BORDER = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"canton_no": 2},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [7.2, 46.85],
                        [7.7, 46.85],
                        [7.7, 47.05],
                        [7.2, 47.05],
                        [7.2, 46.85],
                    ],
                    [[7.4, 46.95], [7.45, 46.95], [7.45, 47.0], [7.4, 46.95]],
                ],
            },
        }
    ],
}

# What room a picture leaves around its border, and how far its cut stands beyond the border, are settings that whoever installed the plugin.
MAP_FRAME = {
    "map_border_room": 22,
    "map_room_left": 20,
    "map_room_bottom": 20,
    "map_border_cut": 10,
}

MAP_PINS = [
    {
        "subnet": "Prod-Web",
        "prefix": "10.10.10.0/24",
        "url": "",
        "color": "#0072b2",
        "site": "RZ Bern",
        "lat": 46.948,
        "lon": 7.447,
        "machines": [],
    },
    {
        "subnet": "Prod-DB",
        "prefix": "10.10.20.0/24",
        "url": "",
        "color": "#d55e00",
        "site": "RZ Bern",
        "lat": 46.948,
        "lon": 7.447,
        "machines": [],
    },
    {
        "subnet": "Genf",
        "prefix": "10.20.0.0/16",
        "url": "",
        "color": "#009e73",
        "site": "Filiale Genf",
        "lat": 46.204,
        "lon": 6.143,
        "machines": [],
    },
]


# Two sites in one town, which share their coordinates, and one far away.
MAP_NEIGHBOURS = [
    {
        "subnet": "A",
        "prefix": "10.1.0.0/24",
        "url": "",
        "color": "#0072b2",
        "site_color": "#0072b2",
        "site": "RZ Bern",
        "lat": 46.948,
        "lon": 7.447,
        "machines": [],
    },
    {
        "subnet": "B",
        "prefix": "10.2.0.0/24",
        "url": "",
        "color": "#d55e00",
        "site_color": "#d55e00",
        "site": "RZ Bern Zweigstelle",
        "lat": 46.948,
        "lon": 7.448,
        "machines": [],
    },
    {
        "subnet": "C",
        "prefix": "10.3.0.0/24",
        "url": "",
        "color": "#009e73",
        "site_color": "#009e73",
        "site": "Depot Zürich",
        "lat": 47.376,
        "lon": 8.541,
        "machines": [],
    },
]


class SubnetMapSvgTests(TestCase):
    @staticmethod
    def render(pins, boundary=None, label=None, **kwargs):
        return svg_render.render_subnet_map({"pins": pins}, boundary, label, **kwargs)

    def render_framed(self, pins, boundary=None, label=None, **kwargs):
        """A picture whose frame is stated rather than whatever is configured."""
        with override_settings(PLUGINS_CONFIG={"network_map": MAP_FRAME}):
            return self.render(pins, boundary, label, **kwargs)

    def test_the_ground_lies_under_the_painted_border(self):
        tile = {
            "href": "data:image/jpeg;base64,TESTTILE",
            "rect": (400000.0, 150000.0, 900000.0, 300000.0),
        }
        asked = []

        def ground(extent, metres_per_pixel):
            asked.append((extent, metres_per_pixel))
            return [tile]

        svg = self.render_framed(
            MAP_PINS,
            MAP_BORDER,
            "Kanton Bern",
            tiles_of=ground,
            attribution="© Someone",
        )
        self.assertIn('<image href="data:image/jpeg;base64,TESTTILE"', svg)
        # The tiles are asked for the ground the picture shows, and asked at the size the picture is drawn: metres per pixel.
        ground = asked[0][0]
        border = svg_render.map_extent(MAP_BORDER)
        self.assertLess(ground[0], border[0])
        self.assertLess(ground[1], border[1])
        self.assertGreater(ground[2], border[2])
        self.assertGreater(ground[3], border[3])
        self.assertGreater(asked[0][1], 0)
        self.assertLess(svg.index("<image"), svg.index('class="map-border-halo"'))
        # Whoever the tiles come from is said under the picture.
        self.assertIn("© Someone", svg)
        # Left and bottom get room of their own: shapes touch their box at Geneva's west and Ticino's south.
        self.assertGreater(border[0] - ground[0], ground[2] - border[2])
        self.assertGreater(border[1] - ground[1], ground[3] - border[3])

    def render_ground(self, **config):
        asked = []

        def ground(extent, metres_per_pixel):
            asked.append(extent)
            return []

        with override_settings(PLUGINS_CONFIG={"network_map": config}):
            self.render(MAP_PINS, MAP_BORDER, "Kanton Bern", tiles_of=ground)
        return asked[0]

    def test_the_room_and_the_cut_shape_the_ground(self):
        # The room between border and picture edge decides which ground is asked for; the cut decides how wide the band of kept ground around.
        border = svg_render.map_extent(MAP_BORDER)
        off = self.render_ground(map_border_room=0, map_room_left=0, map_room_bottom=0)
        with self.subTest(room="switched off"):
            self.assertEqual(off, border)
        spare = self.render_ground(
            map_border_room=22, map_room_left=0, map_room_bottom=0
        )
        wide = self.render_ground(
            map_border_room=122, map_room_left=0, map_room_bottom=0
        )
        with self.subTest(room="bigger"):
            self.assertGreater(border[0] - wide[0], border[0] - spare[0])
            self.assertGreater(wide[2] - border[2], spare[2] - border[2])
        for asked, stroke in ((10, 20), (40, 80)):
            config = dict(MAP_FRAME, map_border_cut=asked)
            with self.subTest(cut=asked):
                with override_settings(PLUGINS_CONFIG={"network_map": config}):
                    svg = self.render(MAP_PINS, MAP_BORDER, "Kanton Bern")
                self.assertIn(f'stroke-width="{stroke}"', svg)
        with self.subTest(cut="on the line"):
            with override_settings(
                PLUGINS_CONFIG={"network_map": {"map_border_cut": 0}}
            ):
                svg = self.render(MAP_PINS, MAP_BORDER, "Kanton Bern")
            self.assertNotIn("map-ground", svg)
            self.assertIn('class="map-outside"', svg)

    def test_a_picture_is_as_wide_as_it_can_be(self):
        # These sites reach from Geneva to Zurich, so the picture of them fills the page instead of standing small in the middle of it.
        svg = self.render(MAP_PINS)
        width = re.search(r'<rect class="map-frame"[^>]*width="([\d.]+)"', svg)
        self.assertIsNotNone(width)
        self.assertGreater(float(width.group(1)), 1100)

    def test_a_picture_without_a_ground_does_not_mention_one(self):
        svg = self.render(MAP_PINS, tiles_of=lambda extent, metres_per_pixel: [])
        self.assertNotIn("<image", svg)
        self.assertIn('class="map-back"', svg)

    def test_border_extent_frames_the_export(self):
        svg = self.render_framed(MAP_PINS, MAP_BORDER, "Kanton Bern")
        self.assertIn("Kanton Bern", svg)
        # One border path, carrying the exterior ring and the hole.
        self.assertEqual(svg.count('class="map-border" d='), 1)
        # Nothing beyond the border is drawn, so the picture ends with the canton and no frame line is left standing around it.
        self.assertIn('mask="url(#map-ground)"', svg)
        self.assertNotIn('class="map-outside"', svg)
        self.assertNotIn('class="map-frame"', svg)

    def test_a_site_outside_the_border_is_clamped_and_counted(self):
        # Geneva lies far outside a canton drawn around Bern alone - far enough that the room around the border cannot bring it into the picture.
        svg = self.render_framed(MAP_PINS, MAP_TIGHT_BORDER, "Kanton Bern")
        self.assertIn('class="map-offframe"', svg)
        self.assertIn("outside the drawn area", svg)

    def test_a_picture_without_a_border_shows_the_country(self):
        asked = []

        def ground(extent, metres_per_pixel):
            asked.append(extent)
            return []

        svg = self.render(MAP_PINS, tiles_of=ground)
        # Nothing to end the picture with, so it ends with the country: every site is on it, whichever canton it happens to stand in.
        self.assertEqual(asked[0], svg_render.SWITZERLAND)
        self.assertIn("RZ Bern", svg)
        self.assertIn("Filiale Genf", svg)

    def test_the_country_is_the_extent_without_a_border(self):
        self.assertEqual(svg_render.map_extent(None), svg_render.SWITZERLAND)
        self.assertEqual(svg_render.map_extent({}), svg_render.SWITZERLAND)

    def test_a_border_thicker_than_a_pixel_keeps_its_shape(self):
        # The national border's fifty thousand points are thinned, its corners kept.
        ring = [[step / 1000.0, 47.0] for step in range(1000)]
        path = svg_render._ring_path(ring, lambda lon, lat: (lon * 100.0, 0.0))
        self.assertTrue(path.endswith("Z"))
        self.assertGreater(path.count("L"), 100)
        self.assertLess(path.count("L"), len(ring) // 2)
        self.assertIn("99.", path)

    def test_pin_extent_used_without_border(self):
        svg = self.render(MAP_PINS)
        self.assertNotIn('class="map-border"', svg)
        self.assertIn('class="map-frame"', svg)
        self.assertNotIn('class="map-offframe"', svg)
        self.assertIn("Filiale Genf", svg)
        self.assertIn("10.10.10.0/24", svg)
        self.assertIn("swisstopo", svg)

    def test_a_site_is_pinned_once_and_numbered(self):
        svg = self.render(MAP_PINS)
        self.assertEqual(svg.count("RZ Bern"), 1)
        self.assertEqual(svg.count("Filiale Genf"), 1)
        self.assertEqual(svg.count('class="map-num"'), 2)
        # Every pin sits on a dark disc, which is what stands it off from the background the picture may have.
        self.assertEqual(svg.count('class="map-pin-back"'), 2)

    def test_a_site_of_several_machines_wants_a_thick_border(self):
        busy = dict(MAP_PINS[0], machines=[{"ip": "10.10.10.1"}, {"ip": "10.10.10.2"}])
        self.assertIn('class="map-pin is-many"', self.render([busy]))
        self.assertNotIn('class="map-pin is-many"', self.render([MAP_PINS[0]]))

    def test_sites_that_neighbour_each_other_are_listed_beside_each_other(self):
        svg = self.render(MAP_NEIGHBOURS)
        names = ["RZ Bern<", "RZ Bern Zweigstelle<", "Depot Zürich<"]
        order = [name for _, name in sorted((svg.index(name), name) for name in names)]
        self.assertEqual(
            order.index("RZ Bern<") + 1, order.index("RZ Bern Zweigstelle<")
        )

    def test_several_subnets_of_one_site_are_listed_side_by_side(self):
        # Neither subnet is dropped when the line of one site fills up, which a wide lettering does sooner: the line simply continues underneath.
        svg = self.render(MAP_PINS)
        self.assertIn("Prod-Web \u2014 10.10.10.0/24", svg)
        self.assertIn("Prod-DB \u2014 10.10.20.0/24", svg)
        # A pair with room left is set side by side rather than under each other, whatever the width of the lettering is.
        short = [
            {**MAP_PINS[0], "subnet": "Web", "prefix": "10.0.0.0/24"},
            {**MAP_PINS[1], "subnet": "DB", "prefix": "10.1.1.0/24"},
        ]
        svg = self.render(short)
        self.assertIn("Web \u2014 10.0.0.0/24 \u00b7 DB \u2014 10.1.1.0/24", svg)

    def test_every_subnet_of_a_busy_site_is_listed(self):
        # Many subnets simply grow the entry, wrapping into the column as needed.
        many = [
            {**MAP_PINS[0], "subnet": f"Net{i}", "prefix": f"10.0.{i}.0/24"}
            for i in range(40)
        ]
        svg = self.render(many)
        self.assertIn("Net3 \u2014 10.0.3.0/24", svg)
        self.assertIn("Net39 \u2014 10.0.39.0/24", svg)
        self.assertNotIn("further subnets not listed", svg)

    def test_map_without_pins_renders_a_stub(self):
        svg = self.render([])
        self.assertIn("<svg", svg)
        self.assertNotIn('class="map-pin"', svg)


EMPTY_MAP_DATA = {
    "pins": [],
    "unplaced": [],
    "locations": {},
    "ui": {},
    "canton_boundary_url": None,
    "canton_label": None,
}


class PageExportButtonTests(TestCase):
    PAGES = ("vlan_topology", "subnet_map")

    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )
        cls.user = User.objects.create_user(username="mapexporter", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-export",
            actions=["view"],
        )
        permission.object_types.add(cls.map_content_type)
        cls.user.object_permissions.add(permission)

    def get_page(self, page_name, map_data=None):
        self.client.force_login(self.user)
        if map_data is not None:
            with mock.patch.object(
                SubnetLocationView, "build_map_data", return_value=map_data
            ):
                return self.client.get(reverse(f"plugins:network_map:{page_name}"))
        return self.client.get(reverse(f"plugins:network_map:{page_name}"))

    def test_pages_offer_svg_export(self):
        for page_name in self.PAGES:
            with self.subTest(page=page_name):
                map_data = (
                    {**EMPTY_MAP_DATA, "pins": MAP_PINS}
                    if page_name == "subnet_map"
                    else None
                )
                response = self.get_page(page_name, map_data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-export-svg")

    def test_no_export_button_without_pins(self):
        self.assertNotContains(
            self.get_page("subnet_map", EMPTY_MAP_DATA), "data-export-svg"
        )
