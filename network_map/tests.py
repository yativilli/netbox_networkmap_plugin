import json
import math
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

from dcim.models import (
    Device,
    DeviceRole,
    DeviceType,
    Interface,
    Location,
    Manufacturer,
    Site,
)
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.templatetags.static import static
from django.test import TestCase, override_settings
from django.urls import reverse
from ipam.models import VLAN, IPAddress, Prefix, Role, VLANGroup
from users.models import ObjectPermission, User

from . import floor_plan, lv03, map_tiles, png_render, svg_render, swisstopo
from .colors import shade_of
from .defaults import (
    DEFAULT_CANTON_BOUNDARY_CODE,
    canton_code,
    float_setting,
    int_setting,
)
from .models import VlanInfo
from .templatetags.network_map_static import static_url
from .views import SubnetLocationView, VlanElementListView, VlanTopologyView


class VlanInfoFromVlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = VLANGroup.objects.create(name="Prod", slug="prod")
        cls.role = Role.objects.create(name="Core", slug="core")
        cls.vlan = VLAN.objects.create(
            vid=100,
            name="Test VLAN",
            status="active",
            group=cls.group,
            role=cls.role,
            description="A test VLAN",
        )
        Prefix.objects.create(prefix="10.0.0.0/24", vlan=cls.vlan)

    def test_maps_full_vlan(self):
        element = VlanInfo.from_vlan(self.vlan, machines=[{"ip": "10.0.0.1"}])
        self.assertEqual(element.id, self.vlan.pk)
        self.assertEqual(element.name, "Test VLAN")
        self.assertEqual(element.group, "Prod")
        self.assertEqual(element.role, "Core")
        self.assertEqual(element.prefix, "10.0.0.0/24")
        self.assertEqual(element.description, "A test VLAN")
        self.assertEqual(element.machine_count, 1)
        self.assertEqual(element.url, self.vlan.get_absolute_url())

    def test_missing_fields_become_empty_strings(self):
        vlan = VLAN.objects.create(vid=200, status="active")
        element = VlanInfo.from_vlan(vlan)
        self.assertEqual(element.name, "VLAN 200")
        self.assertEqual(element.group, "")
        self.assertEqual(element.role, "")
        self.assertEqual(element.description, "")
        self.assertEqual(element.prefix, "")
        self.assertEqual(element.machine_count, 0)


class ViewAccessTests(TestCase):
    URL_NAMES = ("vlanelement_list", "vlan_topology", "vlan_connections", "subnet_map")

    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )

    def test_urls_resolve(self):
        for name in self.URL_NAMES:
            self.assertTrue(reverse(f"plugins:network_map:{name}"))

    @override_settings(LOGIN_REQUIRED=True)
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("plugins:network_map:vlanelement_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_user_without_permission_gets_403(self):
        User.objects.create_user(username="regular", password="pass")  # nosec B106
        self.client.login(username="regular", password="pass")  # nosec B106
        response = self.client.get(reverse("plugins:network_map:vlanelement_list"))
        self.assertEqual(response.status_code, 403)

    def test_user_with_permission_gets_200(self):
        user = User.objects.create_user(username="viewer", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap",
            actions=["view"],
        )
        permission.object_types.add(self.map_content_type)
        user.object_permissions.add(permission)
        self.client.login(username="viewer", password="pass")  # nosec B106
        response = self.client.get(reverse("plugins:network_map:vlanelement_list"))
        self.assertEqual(response.status_code, 200)

    def test_topology_page_offers_svg_export(self):
        user = User.objects.create_user(username="exporter", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-topology",
            actions=["view"],
        )
        permission.object_types.add(self.map_content_type)
        user.object_permissions.add(permission)
        self.client.login(username="exporter", password="pass")  # nosec B106
        response = self.client.get(reverse("plugins:network_map:vlan_topology"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-export-svg")


class TopologyDescriptionTests(TestCase):
    def test_serialize_topology_includes_machine_description(self):
        element = SimpleNamespace(
            name="Test VLAN",
            prefix="10.0.0.0/24",
            url="/vlan/1/",
            machines=[
                {
                    "dns_name": "host01",
                    "ip": "10.0.0.10",
                    "url": "/ip/1/",
                    "location": "Site A",
                    "description": "Finance backup",
                }
            ],
        )
        data = VlanTopologyView().serialize_topology([element], None)
        machine = data["subnets"][0]["machines"][0]
        self.assertEqual(machine["description"], "Finance backup")

    def test_serialize_topology_defaults_description_to_empty(self):
        element = SimpleNamespace(
            name="Test VLAN",
            prefix="10.0.0.0/24",
            url="/vlan/1/",
            machines=[
                {
                    "dns_name": "host01",
                    "ip": "10.0.0.10",
                    "url": "/ip/1/",
                    "location": "Site A",
                }
            ],
        )
        data = VlanTopologyView().serialize_topology([element], None)
        machine = data["subnets"][0]["machines"][0]
        self.assertEqual(machine["description"], "")

    def test_render_topology_includes_machine_description(self):
        data = {
            "center": {"name": "Gateway", "ip": "", "url": ""},
            "subnets": [
                {
                    "name": "Test VLAN",
                    "prefix": "10.0.0.0/24",
                    "url": "/vlan/1/",
                    "machines": [
                        {
                            "name": "host01",
                            "ip": "10.0.0.10",
                            "url": "/ip/1/",
                            "description": "Finance backup",
                        }
                    ],
                }
            ],
        }
        svg = svg_render.render_topology(data)
        self.assertIn('class="topo-machine-description"', svg)
        self.assertIn("Finance", svg)
        self.assertIn("backup", svg)

    def test_render_topology_omits_empty_machine_description(self):
        data = {
            "center": {"name": "Gateway", "ip": "", "url": ""},
            "subnets": [
                {
                    "name": "Test VLAN",
                    "prefix": "10.0.0.0/24",
                    "url": "/vlan/1/",
                    "machines": [
                        {
                            "name": "host01",
                            "ip": "10.0.0.10",
                            "url": "/ip/1/",
                            "description": "",
                        }
                    ],
                }
            ],
        }
        svg = svg_render.render_topology(data)
        self.assertNotIn('class="topo-machine-description"', svg)


class PngRenderTests(TestCase):
    def test_the_vector_library_is_preferred_to_the_command_line(self):
        cairosvg = mock.Mock()
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png("<svg/>")
        cairosvg.svg2png.assert_called_once()

    def test_imagemagick_is_asked_for_a_raster(self):
        finished = mock.Mock(returncode=0, stdout=b"\x89PNG..", stderr=b"")
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch(
                "network_map.png_render.shutil.which", return_value="/usr/bin/magick"
            ),
            mock.patch(
                "network_map.png_render.subprocess.run", return_value=finished
            ) as run,
        ):
            self.assertEqual(png_render.render_png("<svg/>"), b"\x89PNG..")
        self.assertIn("-density", run.call_args.args[0])

    def test_a_failing_rasteriser_is_reported(self):
        finished = mock.Mock(returncode=1, stdout=b"", stderr=b"boom")
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch(
                "network_map.png_render.shutil.which", return_value="/usr/bin/magick"
            ),
            mock.patch("network_map.png_render.subprocess.run", return_value=finished),
            self.assertRaisesRegex(png_render.PngRenderError, "boom"),
        ):
            png_render.render_png("<svg/>")

    def test_a_document_no_raster_can_hold_comes_out_smaller(self):
        cairosvg = mock.Mock()
        giant = '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="71148"/>'
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png(giant)
        scale = cairosvg.svg2png.call_args.kwargs["scale"]
        self.assertLess(scale, 1)
        self.assertAlmostEqual(71148 * scale, png_render.PNG_MAX_EDGE, places=3)

    def test_an_ordinary_document_keeps_its_scale(self):
        cairosvg = mock.Mock()
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png('<svg xmlns="x" width="1200" height="1100"/>')
        self.assertEqual(
            cairosvg.svg2png.call_args.kwargs["scale"], png_render.PNG_SCALE
        )

    def test_no_rasteriser_at_all_is_reported(self):
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch("network_map.png_render.shutil.which", return_value=None),
            self.assertRaises(png_render.PngRenderError),
        ):
            self.assertFalse(png_render.available())
            png_render.render_png("<svg/>")


class _FakeTileResponse:
    """Minimal stand-in for the object urlopen() returns for a tile."""

    def __init__(self, payload=b"\xff\xd8\xff\xe0jpeg"):
        self._payload = payload

    def read(self, max_bytes=-1):
        if max_bytes is None or max_bytes < 0:
            return self._payload
        return self._payload[:max_bytes]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lv03_extent(corners):
    """The LV03 box around lon/lat corners, as map_tiles is handed one."""
    points = [lv03.to_lv03(lat, lon) for lon, lat in corners]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _static(name):
    path = os.path.join(os.path.dirname(__file__), "static", "network_map", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# Bernese Oberland corner, one Bern address, whole country: few tiles, cheap zoom, many tiles.
TILE_AREA = ((7.40, 46.90), (7.48, 46.96))
ONE_ADDRESS = ((7.44, 46.94), (7.45, 46.946))
SWITZERLAND = ((5.96, 45.82), (10.49, 47.81))


class LV03Tests(TestCase):
    """
    The server draws on the grid of the page, whose own projection grid was
    generated offline with PROJ - that grid is the yardstick here.
    """

    @staticmethod
    def _grid():
        return json.loads(
            re.search(
                r"var g = (\{.*?\});\n", _static("lv03_grid.js"), re.DOTALL
            ).group(1)
        )

    @staticmethod
    def _sample(values, grid, lat, lon):
        """The browser's bilinear sampling, ported."""
        i = min(max((lat - grid["lat0"]) / grid["latStep"], 0), grid["nLat"] - 1)
        j = min(max((lon - grid["lon0"]) / grid["lonStep"], 0), grid["nLon"] - 1)
        i0, j0 = int(i), int(j)
        i1 = min(i0 + 1, grid["nLat"] - 1)
        j1 = min(j0 + 1, grid["nLon"] - 1)
        fi, fj = i - i0, j - j0
        wide = grid["nLon"]
        near = values[i0 * wide + j0] * (1 - fj) + values[i0 * wide + j1] * fj
        far = values[i1 * wide + j0] * (1 - fj) + values[i1 * wide + j1] * fj
        return near * (1 - fi) + far * fi

    def test_a_known_place_lands_where_it_stands(self):
        east, north = lv03.to_lv03(46.9514, 7.4396)  # the Bundeshaus
        self.assertAlmostEqual(east, 600074, delta=10)
        self.assertAlmostEqual(north, 200035, delta=10)

    def test_the_server_puts_a_point_where_the_page_puts_it(self):
        grid = self._grid()
        rows = max(1, grid["nLat"] // 12)
        cols = max(1, grid["nLon"] // 12)
        for row in range(0, grid["nLat"], rows):
            for col in range(0, grid["nLon"], cols):
                lat = grid["lat0"] + row * grid["latStep"]
                lon = grid["lon0"] + col * grid["lonStep"]
                east, north = lv03.to_lv03(lat, lon)
                drift = math.hypot(
                    east - self._sample(grid["e"], grid, lat, lon),
                    north - self._sample(grid["n"], grid, lat, lon),
                )
                self.assertLess(round(drift, 1), 50, f"{lat}, {lon}")

    def test_the_ladder_is_the_one_the_page_tiles_with(self):
        source = _static("subnet_map.js")
        ladder = re.search(r"\[([\d.,\s]+)\]\.forEach\(\(res\)", source).group(1)
        steps = json.loads(f"[{ladder}]")
        self.assertEqual(
            lv03.RESOLUTIONS[:14], tuple(4000.0 - 250.0 * step for step in range(14))
        )
        self.assertEqual(list(lv03.RESOLUTIONS[14:]), steps)

    def test_a_tile_covers_the_ground_it_is_asked_for(self):
        rect = lv03.tile_rect(7, 5, 17)
        west, south, east, north = rect
        side = lv03.TILE_SIZE * lv03.resolution(17)
        self.assertAlmostEqual(east - west, side)
        self.assertAlmostEqual(north - south, side)
        self.assertEqual(
            lv03.tile_of((west + east) / 2, (south + north) / 2, 17), (7, 5)
        )

    def test_the_grid_covers_the_ground_it_shows(self):
        extent = _lv03_extent(SWITZERLAND)
        zoom = lv03.zoom_for(200.0)
        from_x, from_y, to_x, to_y = lv03.grid(extent, zoom)
        west = min(lv03.tile_rect(x, from_y, zoom)[0] for x in (from_x, to_x))
        east = max(lv03.tile_rect(x, from_y, zoom)[2] for x in (from_x, to_x))
        south = min(lv03.tile_rect(from_x, y, zoom)[1] for y in (from_y, to_y))
        north = max(lv03.tile_rect(from_x, y, zoom)[3] for y in (from_y, to_y))
        self.assertLessEqual(west, extent[0])
        self.assertLessEqual(south, extent[1])
        self.assertGreaterEqual(east, extent[2])
        self.assertGreaterEqual(north, extent[3])

    def test_the_zoom_is_the_step_that_suits_the_picture(self):
        self.assertEqual(lv03.zoom_for(100.0), 17)
        self.assertGreater(lv03.zoom_for(20.0), lv03.zoom_for(800.0))
        self.assertGreaterEqual(lv03.zoom_for(9000.0), lv03.MIN_ZOOM)
        self.assertLessEqual(lv03.zoom_for(0.01), lv03.MAX_ZOOM)


class MapTileTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_the_ground_of_a_picture_is_a_picture_too(self, urlopen):
        urlopen.return_value = _FakeTileResponse()
        tiles = map_tiles.background(_lv03_extent(TILE_AREA), 100.0)
        self.assertTrue(tiles)
        url = urlopen.call_args.args[0].full_url
        self.assertTrue(url.startswith("https://wmts.geo.admin.ch/"))
        # 100 metres per pixel is zoom step 17 of the ladder, and the grid is addressed by zoom, row and column.
        self.assertIn("/17/", url)
        for tile in tiles:
            self.assertTrue(tile["href"].startswith("data:image/jpeg;base64,"))
            west, south, east, north = tile["rect"]
            self.assertLess(west, east)
            self.assertLess(south, north)

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_a_tile_that_was_fetched_once_is_not_asked_again(self, urlopen):
        urlopen.return_value = _FakeTileResponse()
        first = map_tiles.background(_lv03_extent(TILE_AREA), 100.0)
        asked = urlopen.call_count
        again = map_tiles.background(_lv03_extent(TILE_AREA), 100.0)
        self.assertEqual(len(again), len(first))
        self.assertEqual(urlopen.call_count, asked)

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_a_tile_that_is_not_there_is_not_asked_again_right_away(self, urlopen):
        urlopen.side_effect = OSError("no route to the tile server")
        extent = _lv03_extent(TILE_AREA)
        self.assertEqual(map_tiles.background(extent, 100.0), [])
        asked = urlopen.call_count
        self.assertEqual(map_tiles.background(extent, 100.0), [])
        self.assertEqual(urlopen.call_count, asked)

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_a_source_that_hands_out_nothing_hands_out_nothing(self, urlopen):
        urlopen.return_value = _FakeTileResponse(b"<html>not a tile</html>")
        self.assertEqual(map_tiles.background(_lv03_extent(TILE_AREA), 100.0), [])

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_a_picture_can_do_without_a_ground(self, urlopen):
        with override_settings(
            PLUGINS_CONFIG={"network_map": {"map_background": False}}
        ):
            self.assertEqual(map_tiles.background(_lv03_extent(TILE_AREA), 100.0), [])
        urlopen.assert_not_called()

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_the_zoom_the_settings_ask_for_is_the_zoom_used(self, urlopen):
        urlopen.return_value = _FakeTileResponse()
        with override_settings(PLUGINS_CONFIG={"network_map": {"map_tile_zoom": 17}}):
            tiles = map_tiles.background(_lv03_extent(ONE_ADDRESS), 100.0)
        self.assertEqual(len(tiles), 1)
        self.assertIn("/17/", urlopen.call_args.args[0].full_url)

    @mock.patch("network_map.map_tiles.urllib.request.urlopen")
    def test_a_zoom_that_cannot_be_paid_for_comes_down(self, urlopen):
        urlopen.return_value = _FakeTileResponse()
        wanted = lv03.zoom_for(5.0)
        extent = _lv03_extent(SWITZERLAND)
        self.assertGreater(lv03.tile_count(extent, wanted), map_tiles.MAX_TILES)
        with override_settings(PLUGINS_CONFIG={"network_map": {"map_tile_max": 2}}):
            tiles = map_tiles.background(extent, 5.0)
        self.assertTrue(tiles)
        self.assertLessEqual(len(tiles), 2)
        for call in urlopen.call_args_list:
            used = int(call.args[0].full_url.split("/")[-3])
            self.assertLess(used, wanted)

    def test_a_source_wants_naming_itself(self):
        self.assertEqual(map_tiles.attribution(), "")
        with override_settings(
            PLUGINS_CONFIG={"network_map": {"map_attribution": "© OpenStreetMap"}}
        ):
            self.assertEqual(map_tiles.attribution(), "© OpenStreetMap")


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

    def test_the_kind_no_longer_wants_an_svg_segment(self):
        self.client.force_login(self.user)
        root = reverse("plugins-api:network_map-api:api-root")
        self.assertEqual(self.client.get(f"{root}svg/topology/").status_code, 404)

    def test_anonymous_is_rejected(self):
        response = self.get_svg("topology")
        self.assertIn(response.status_code, (401, 403))

    def test_user_without_permission_gets_403(self):
        User.objects.create_user(username="nosvg", password="pass")  # nosec B106
        self.client.login(username="nosvg", password="pass")  # nosec B106
        self.assertEqual(self.get_svg("machine-list").status_code, 403)


SAMPLE_BORDER = {
    "type": "Feature",
    "properties": {"canton_no": 2},
    "geometry": {
        "type": "MultiPolygon",
        "coordinates": [[[[[7.2, 46.9], [7.3, 46.9], [7.3, 47.0], [7.2, 46.9]]]]],
    },
}
SAMPLE_COLLECTION = {"type": "FeatureCollection", "features": [SAMPLE_BORDER]}


class _FakeHTTPResponse:
    """Minimal stand-in for the object urlopen() returns."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SwisstopoResolverTests(TestCase):
    # Mocked source answers: one without geometry passes on, and none left means no border.
    _EMPTY: ClassVar[dict] = {"type": "FeatureCollection", "features": []}
    _NO_GEOMETRY: ClassVar[dict] = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": None}],
    }
    _ESRI_BE: ClassVar[dict] = {
        "feature": {
            "attributes": {"ak": "BE"},
            "geometry": {
                "rings": [[[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.0, 47.0]]]
            },
        }
    }
    _CASES = (
        # name, code, answers of the sources in order, expected requests, attribute of the winning canton or None, (call, URL text) checks
        ("primary empty", "BE", (_EMPTY, _ESRI_BE), 2, "BE", ()),
        ("primary offline", "BE", (OSError("offline"), _ESRI_BE), 2, "BE", ()),
        ("primary without geometry", "BE", (_NO_GEOMETRY, _ESRI_BE), 2, "BE", ()),
        ("both fallbacks empty", "BE", (_EMPTY, [], _ESRI_BE), 3, "BE", ()),
        ("every source empty", "BE", (_EMPTY,) * 3, 3, None, ()),
        ("every source offline", "BE", (OSError(),) * 3, 3, None, ()),
        (
            "country primary offline",
            "CH",
            (
                OSError("no route"),
                [{"geojson": {"type": "Polygon", "coordinates": []}}],
            ),
            2,
            None,
            ((1, "q=Switzerland"), (1, "featuretype=country")),
        ),
    )

    def setUp(self):
        cache.clear()

    def test_resolve_canton_id(self):
        self.assertEqual(swisstopo.resolve_canton_id("BE"), 2)
        self.assertEqual(swisstopo.resolve_canton_id("ag"), 19)
        self.assertEqual(swisstopo.resolve_canton_id("2"), 2)
        self.assertIsNone(swisstopo.resolve_canton_id("XX"))
        self.assertIsNone(swisstopo.resolve_canton_id(""))
        self.assertIsNone(swisstopo.resolve_canton_id(None))

    def test_resolve_canton_code(self):
        self.assertEqual(swisstopo.resolve_canton_code("BE"), "BE")
        self.assertEqual(swisstopo.resolve_canton_code("ag"), "AG")
        self.assertEqual(swisstopo.resolve_canton_code("2"), "BE")
        self.assertIsNone(swisstopo.resolve_canton_code("XX"))

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_boundary_wrapped_in_feature_collection(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(SAMPLE_COLLECTION)
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(result, SAMPLE_COLLECTION)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_esri_feature_response_is_converted(self, urlopen):
        # map.geo.admin.ch returns Esri rings (clockwise exterior) + attributes.
        cw_square = [[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.1, 47.0]]
        urlopen.return_value = _FakeHTTPResponse(
            {
                "feature": {
                    "attributes": {"ak": "AG", "name": "Aargau"},
                    "geometry": {
                        "rings": [cw_square],
                        "spatialReference": {"wkid": 4326},
                    },
                }
            }
        )
        result = swisstopo.get_canton_boundary("AG")
        feature = result["features"][0]
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertEqual(feature["properties"]["ak"], "AG")
        # linear rings are closed (first point repeated at the end)
        ring = feature["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_esri_multiple_exterior_rings_become_multipolygon(self, urlopen):
        cw = lambda a, b: [[a, b], [a, b + 1], [a + 1, b + 1], [a + 1, b]]
        urlopen.return_value = _FakeHTTPResponse(
            {"feature": {"attributes": {}, "geometry": {"rings": [cw(0, 0), cw(5, 5)]}}}
        )
        result = swisstopo.get_canton_boundary(2)
        self.assertEqual(result["features"][0]["geometry"]["type"], "MultiPolygon")
        self.assertEqual(len(result["features"][0]["geometry"]["coordinates"]), 2)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_wfs_holes_are_preserved(self, urlopen):
        # WFS returns plain GeoJSON; interior rings (holes) must survive and come from the primary source without hitting the fallback.
        exterior = [[7.0, 47.0], [8.0, 47.0], [8.0, 48.0], [7.0, 48.0], [7.0, 47.0]]
        hole = [[7.4, 47.4], [7.6, 47.4], [7.6, 47.6], [7.4, 47.6], [7.4, 47.4]]
        urlopen.return_value = _FakeHTTPResponse(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": 2},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [exterior, hole],
                        },
                    }
                ],
            }
        )
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 1)
        geometry = result["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        self.assertEqual(len(geometry["coordinates"]), 2)  # exterior + 1 hole

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_a_source_without_geometry_passes_on(self, urlopen):
        for name, code, answers, calls, won, urls in self._CASES:
            with self.subTest(case=name):
                cache.clear()
                urlopen.reset_mock()
                urlopen.side_effect = [
                    answer if isinstance(answer, OSError) else _FakeHTTPResponse(answer)
                    for answer in answers
                ]
                result = swisstopo.get_canton_boundary(code)
                self.assertEqual(urlopen.call_count, calls)
                for call, text in urls:
                    self.assertIn(text, urlopen.call_args_list[call].args[0].full_url)
                if won:
                    self.assertEqual(result["features"][0]["properties"]["ak"], won)
                elif urls:
                    self.assertIsNotNone(result)
                else:
                    self.assertIsNone(result)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_nominatim_fallback_geometry_is_converted(self, urlopen):
        exterior = [[7.0, 47.0], [8.0, 47.0], [8.0, 48.0], [7.0, 48.0], [7.0, 47.0]]
        hole = [[7.4, 47.4], [7.6, 47.4], [7.6, 47.6], [7.4, 47.6], [7.4, 47.4]]
        empty = _FakeHTTPResponse({"type": "FeatureCollection", "features": []})
        nominatim = _FakeHTTPResponse(
            [
                {
                    "place_id": 1,
                    "display_name": "Bern/Berne, Schweiz",
                    "geojson": {
                        "type": "Polygon",
                        "coordinates": [exterior, hole],
                    },
                }
            ]
        )
        urlopen.side_effect = [empty, nominatim]
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn("q=CH-BE", urlopen.call_args_list[1].args[0].full_url)
        feature = result["features"][0]
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertEqual(len(feature["geometry"]["coordinates"]), 2)
        self.assertEqual(feature["properties"]["display_name"], "Bern/Berne, Schweiz")

    @override_settings(
        PLUGINS_CONFIG={
            "network_map": {
                "canton_boundary_fallback_url_template": "",
                "canton_boundary_last_resort_url_template": "",
            }
        }
    )
    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_fallbacks_can_be_disabled(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(self._EMPTY)
        self.assertIsNone(swisstopo.get_canton_boundary("BE"))
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_boundary_cached_after_first_fetch(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(SAMPLE_COLLECTION)
        swisstopo.get_canton_boundary("BE")
        swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 1)

    def test_unknown_code_returns_none_without_request(self):
        with mock.patch("network_map.swisstopo.urllib.request.urlopen") as urlopen:
            self.assertIsNone(swisstopo.get_canton_boundary("ZZ"))
            urlopen.assert_not_called()

    @override_settings(
        PLUGINS_CONFIG={"network_map": {"canton_boundary_label": "Kt. Aargau"}}
    )
    def test_explicit_label_wins(self):
        self.assertEqual(swisstopo.get_canton_label("AG"), "Kt. Aargau")

    def test_derived_label(self):
        self.assertEqual(swisstopo.get_canton_label("BE"), "Kanton Bern")

    def test_no_label_when_unconfigured(self):
        self.assertIsNone(swisstopo.get_canton_label(""))


_COUNTRY_GEOMETRY = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"id": "CH", "bez": "Schweiz"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[6.0, 46.0], [10.0, 46.0], [10.0, 47.8], [6.0, 47.8], [6.0, 46.0]]
                ],
            },
        }
    ],
}


class CountryBorderTests(TestCase):
    """
    "CH" in canton_boundary_code asks for the whole country - the same handling
    as a canton, with the national border in its place.
    """

    def setUp(self):
        cache.clear()

    def test_the_country_is_recognised(self):
        self.assertTrue(swisstopo.is_country("CH"))
        self.assertTrue(swisstopo.is_country(" sw "))
        self.assertTrue(swisstopo.boundary_configured("CH"))
        self.assertTrue(swisstopo.boundary_configured("BE"))
        self.assertFalse(swisstopo.is_country("BE"))
        self.assertFalse(swisstopo.boundary_configured(""))
        self.assertFalse(swisstopo.boundary_configured(None))

    def test_the_default_border_stays_a_canton(self):
        # The shipped default stays a canton: unnamed installs keep drawing one.
        self.assertEqual(DEFAULT_CANTON_BOUNDARY_CODE, "BE")
        self.assertFalse(swisstopo.is_country(DEFAULT_CANTON_BOUNDARY_CODE))
        self.assertTrue(swisstopo.boundary_configured(DEFAULT_CANTON_BOUNDARY_CODE))

    def test_the_country_names_itself(self):
        self.assertEqual(swisstopo.get_canton_label("CH"), "Schweiz")
        with override_settings(
            PLUGINS_CONFIG={"network_map": {"canton_boundary_label": "Switzerland"}}
        ):
            self.assertEqual(swisstopo.get_canton_label("CH"), "Switzerland")

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_the_border_of_the_country_comes_from_its_own_layer(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(_COUNTRY_GEOMETRY)
        result = swisstopo.get_canton_boundary("CH")
        self.assertIn(
            "swissboundaries3d-land-flaeche.fill/CH", urlopen.call_args.args[0].full_url
        )
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result["features"][0]["geometry"]["type"], "Polygon")

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_the_country_is_fetched_once(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(_COUNTRY_GEOMETRY)
        swisstopo.get_canton_boundary("CH")
        swisstopo.get_canton_boundary("sw")
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_no_source_means_no_border(self, urlopen):
        urlopen.side_effect = OSError("offline")
        self.assertIsNone(swisstopo.get_canton_boundary("CH"))


class CantonBoundaryViewTests(TestCase):
    URL = "plugins:network_map:canton_boundary"

    @classmethod
    def setUpTestData(cls):
        cls.content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )
        cls.user = User.objects.create_user(username="boundary", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-boundary", actions=["view"]
        )
        permission.object_types.add(cls.content_type)
        cls.user.object_permissions.add(permission)

    def test_unconfigured_returns_204(self):
        self.client.force_login(self.user)
        with mock.patch("network_map.views.get_canton_boundary", return_value=None):
            response = self.client.get(reverse(self.URL))
        self.assertEqual(response.status_code, 204)

    def test_configured_returns_geojson(self):
        self.client.force_login(self.user)
        with mock.patch(
            "network_map.views.get_canton_boundary", return_value=SAMPLE_COLLECTION
        ):
            response = self.client.get(reverse(self.URL))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/geo+json")
        self.assertEqual(json.loads(response.content), SAMPLE_COLLECTION)

    def test_user_without_permission_gets_403(self):
        User.objects.create_user(username="noboundary", password="pass")  # nosec B106
        self.client.login(username="noboundary", password="pass")  # nosec B106
        response = self.client.get(reverse(self.URL))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_rejected(self):
        response = self.client.get(reverse(self.URL))
        self.assertIn(response.status_code, (302, 401, 403))


class MapDataCantonBoundaryTests(TestCase):
    def test_build_map_data_includes_url_and_label(self):
        view = SubnetLocationView()
        boundary_url = reverse("plugins:network_map:canton_boundary")
        with (
            mock.patch(
                "network_map.views.get_plugin_config",
                side_effect=lambda name, key, default=None: (
                    "BE" if key == "canton_boundary_code" else default
                ),
            ),
            mock.patch("network_map.views.boundary_configured", return_value=True),
            mock.patch(
                "network_map.views.get_canton_label", return_value="Kanton Bern"
            ),
        ):
            data = view.build_map_data([])
        self.assertEqual(data["canton_boundary_url"], boundary_url)
        self.assertEqual(data["canton_label"], "Kanton Bern")
        # The exporter gets the same room the served picture leaves around the border, so the two do not disagree about what belongs in them.
        self.assertEqual(set(data["export_room"]), {"border", "left", "bottom", "cut"})

    def test_build_map_data_omits_boundary_when_unset(self):
        view = SubnetLocationView()
        with (
            mock.patch(
                "network_map.views.get_plugin_config",
                side_effect=lambda name, key, default=None: default,
            ),
            mock.patch("network_map.views.boundary_configured", return_value=False),
        ):
            data = view.build_map_data([])
        self.assertIsNone(data["canton_boundary_url"])
        self.assertIsNone(data["canton_label"])


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


class SubnetMapExportButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )
        cls.user = User.objects.create_user(username="mapexporter", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-subnet",
            actions=["view"],
        )
        permission.object_types.add(cls.map_content_type)
        cls.user.object_permissions.add(permission)

    def get_page(self, map_data):
        self.client.force_login(self.user)
        with mock.patch.object(
            SubnetLocationView, "build_map_data", return_value=map_data
        ):
            return self.client.get(reverse("plugins:network_map:subnet_map"))

    def test_page_offers_svg_export(self):
        response = self.get_page({**EMPTY_MAP_DATA, "pins": MAP_PINS})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-export-svg")
        self.assertContains(response, "svg_export.js")

    def test_no_export_button_without_pins(self):
        self.assertNotContains(self.get_page(EMPTY_MAP_DATA), "data-export-svg")


class MachineDescriptionTests(TestCase):
    """What the line about a machine is taken from: comment first, role last."""

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name="DC", slug="dc")
        cls.role, _ = DeviceRole.objects.get_or_create(
            name="Finance server", defaults={"slug": "finance-server"}
        )
        manufacturer = Manufacturer.objects.create(name="Vendor", slug="vendor")
        device_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="PowerEdge", slug="poweredge"
        )
        cls.device = Device.objects.create(
            site=site,
            name="srv1",
            role=cls.role,
            device_type=device_type,
            comments="Nightly finance backup",
        )
        interface = Interface.objects.create(
            device=cls.device, name="eth0", type="1000base-t"
        )
        cls.vlan = VLAN.objects.create(vid=10, name="Prod")
        Prefix.objects.create(prefix="10.1.0.0/24", vlan=cls.vlan)
        cls.ip = IPAddress.objects.create(
            address="10.1.0.10/24",
            dns_name="srv1.example.com",
            comments="Managed over the BMC",
            assigned_object=interface,
        )

    def description(self):
        elements = VlanElementListView().build_elements(
            VLAN.objects.filter(pk=self.vlan.pk)
        )
        return elements[0].machines[0]["description"]

    def test_a_comment_says_what_the_role_cannot(self):
        # The role names the kind of thing it is; the comment says what it does here, and that is what the tooltip shows.
        self.assertEqual(self.description(), "Nightly finance backup")

    def test_what_stands_on_the_machine_comes_first(self):
        self.device.description = "Firewall of the finance VLAN"
        self.device.save()
        self.assertEqual(self.description(), "Firewall of the finance VLAN")

    def test_the_address_speaks_when_the_machine_stays_silent(self):
        self.device.comments = ""
        self.device.save()
        self.assertEqual(self.description(), "Managed over the BMC")

    def test_the_role_is_the_last_resort(self):
        self.device.comments = ""
        self.device.save()
        self.ip.comments = ""
        self.ip.save()
        self.assertEqual(self.description(), self.role.name)


class HousePlanHoverTests(TestCase):
    """What a machine dot on the house plan says when it is hovered."""

    def test_the_hover_says_what_the_machine_is(self):
        script = _static("subnet_map.js")
        start = script.index("const named = machine.name")
        block = script[start : script.index("subnet-machine-tooltip", start)]
        # The name, the address and - when NetBox has more to say than the name repeats - the description of the machine, all of them escaped.
        for part in ("machine-name", "machine-ip", "machine-desc"):
            self.assertIn(part, block)
        for value in ("escapeHtml(named)", "escapeHtml(machine.ip)"):
            self.assertIn(value, block)
        self.assertIn("escapeHtml(machine.description)", block)

    def test_the_stylesheet_knows_the_description_line(self):
        sheet = _static("subnet_map.css")
        self.assertIn(".subnet-machine-tooltip .machine-desc", sheet)

    def test_the_dots_are_placed_at_all(self):
        # A refactor dropped the forEach index while the marker stacked by it, and no dot was painted.
        script = _static("subnet_map.js")
        start = script.index("function addMachineMarkers")
        block = script[start : script.index("layer.addTo(currentMap", start)]
        self.assertIn("zIndexOffset: 6000 + index", block)
        self.assertRegex(block, r"machines\.forEach\(\(machine, index\) =>")


class FloorPlanBandTitleTests(TestCase):
    """The floor name at the left of each band of the generated floor plan."""

    def setUp(self):
        self.script = _static("subnet_map.js")
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
        self.script = _static("subnet_map.js")
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
        export = _static("svg_export.js")
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
        self.script = _static("subnet_map.js")

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
        sheet = _static("subnet_map.css")
        self.assertIn(".subnet-machine-pin.hovered", sheet)
        self.assertIn(".plan-legend .legend-entry.key-lit", sheet)


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


class FloorPlanApiTests(TestCase):
    """The logical floor plans the API knows, and the picture each one draws."""

    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )
        cls.user = User.objects.create_user(username="planviewer", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-plans",
            actions=["view"],
        )
        permission.object_types.add(cls.map_content_type)
        cls.user.object_permissions.add(permission)

        # Two buildings in one city: only the site names a plan apart, and NetBox keeps the city nowhere but in the site's address.
        cls.north = Site.objects.create(
            name="Musterweg 30",
            slug="musterweg-30",
            physical_address="Musterweg 30, 3000 Bern",
            latitude=46.948,
            longitude=7.447,
        )
        cls.south = Site.objects.create(
            name="Beispielweg 4",
            slug="beispielweg-4",
            physical_address="Beispielweg 4, 3000 Bern",
            latitude=46.95,
            longitude=7.45,
        )
        ground = Location.objects.create(
            name="EG - B\u00fcro 019", slug="eg-buero", site=cls.north
        )
        attic = Location.objects.create(name="O 242", slug="o-242", site=cls.north)
        role, _ = DeviceRole.objects.get_or_create(
            name="Server", defaults={"slug": "server-plan"}
        )
        manufacturer = Manufacturer.objects.create(name="Vendor", slug="vendor-plan")
        device_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="PowerEdge", slug="poweredge-plan"
        )
        cls.vlan = VLAN.objects.create(vid=118, name="Plans")
        Prefix.objects.create(prefix="10.18.0.0/24", vlan=cls.vlan)
        cls.machine_said = [
            ("Nightly finance backup", ""),
            ("", "Managed over the BMC"),
            ("Access switch of the depot", ""),
        ]
        for index, ((site, room), (comment, ip_comment)) in enumerate(
            zip(
                ((cls.north, ground), (cls.north, attic), (cls.south, None)),
                cls.machine_said,
            )
        ):
            device = Device.objects.create(
                site=site,
                location=room,
                name=f"srv{index}",
                role=role,
                device_type=device_type,
                comments=comment,
            )
            interface = Interface.objects.create(
                device=device, name="eth0", type="1000base-t"
            )
            IPAddress.objects.create(
                address=f"10.18.0.{index + 1}/24",
                dns_name=f"srv{index}.example.com",
                comments=ip_comment,
                assigned_object=interface,
            )

    def setUp(self):
        super().setUp()
        # The mount prefix derives from the plugin's base_url/module name.
        self.prefix = "networkmap"
        for prefix in ("networkmap", "network_map"):
            response = self.client.get(f"/api/plugins/{prefix}/floor-plans/")
            if response.status_code != 404:
                self.prefix = prefix
                break

    def get_plan(self, path):
        return self.client.get(f"/api/plugins/{self.prefix}/{path}")

    def index(self, query=None):
        url = "floor-plans/" + (f"?{query}" if query else "")
        response = self.get_plan(url)
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)

    def test_the_index_lists_the_plan_of_every_site(self):
        self.client.force_login(self.user)
        plans = self.index("city=Bern")["plans"]
        ids = [plan["id"] for plan in plans]
        # Both buildings stand in Bern and both have machines, each named by its site alone.
        self.assertEqual(ids, ["beispielweg-4", "musterweg-30"])
        self.assertEqual({plan["city"] for plan in plans}, {"Bern"})
        self.assertEqual(len(set(ids)), len(plans))
        logical = next(plan for plan in plans if plan["id"] == "musterweg-30")
        self.assertEqual(logical["rooms"], 2)
        self.assertEqual(logical["floors"], ["OG", "EG"])
        self.assertEqual(logical["machines"], 2)
        self.assertIn("picture", logical)

    def test_the_city_is_read_whichever_way_the_address_runs(self):
        from .api.views import _site_city

        self.assertEqual(
            _site_city(Site(physical_address="Musterweg 30, 3000 Bern")), "Bern"
        )
        self.assertEqual(
            _site_city(Site(physical_address="Bern, Musterweg 30")), "Bern"
        )
        self.assertEqual(_site_city(Site(physical_address="3000 Bern")), "Bern")
        self.assertEqual(_site_city(Site(physical_address="Musterweg 30")), "30")
        self.assertEqual(_site_city(Site(physical_address="")), "")
        self.assertEqual(_site_city(Site()), "")

    def test_the_index_narrows_to_a_city_or_a_site(self):
        self.client.force_login(self.user)
        Site.objects.create(
            name="Depot", slug="depot", physical_address="Fabrikweg 2, Zollikofen"
        )
        self.assertEqual(self.index("city=Bern")["count"], 2)
        self.assertEqual(self.index("city=bern")["count"], 2)
        self.assertEqual(self.index("city=Zollikofen")["count"], 0)
        self.assertEqual(
            [p["id"] for p in self.index("site=beispielweg-4")["plans"]],
            ["beispielweg-4"],
        )
        # The index names the filter it applied, and echoes nothing when none was asked.
        self.assertEqual(self.index("city=Bern")["city"], "Bern")
        self.assertIsNone(self.index("city=Bern")["site"])
        self.assertEqual(self.index("site=beispielweg-4")["site"], "beispielweg-4")
        self.assertIsNone(self.index("site=beispielweg-4")["city"])
        self.assertIsNone(self.index()["city"])
        self.assertIsNone(self.index()["site"])

    def test_the_plan_numbers_its_dots_and_lists_its_machines(self):
        # The plan numbers its dots and lists the machines under it, in the dots' own colours.
        self.client.force_login(self.user)
        body = self.get_plan("floor-plan/musterweg-30/").content.decode()
        self.assertIn('<circle class="map-machine"', body)
        self.assertIn('class="map-machine-num"', body)
        self.assertIn(">1</text>", body)
        self.assertIn(">2</text>", body)
        self.assertIn("1  srv0.example.com", body)
        self.assertIn("Nightly finance backup \u2014 10.18.0.1", body)
        self.assertIn("Managed over the BMC \u2014 10.18.0.2", body)
        self.assertIn('style="fill:#', body)

    def test_a_long_description_is_cut_rather_than_wide(self):
        long_name = "x" * 90
        cut = floor_plan.clip_to(f"1  {long_name}", 200, floor_plan.LIST_NAME_CHAR_W)
        self.assertTrue(cut.endswith("\u2026"))
        self.assertLess(len(cut) * floor_plan.LIST_NAME_CHAR_W, 210)
        self.assertEqual(floor_plan.clip_to("srv1", 200, 9), "srv1")

    def test_the_plan_is_drawn_from_the_locations(self):
        self.client.force_login(self.user)
        response = self.get_plan("floor-plan/musterweg-30/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("image/svg+xml"))
        body = response.content.decode()
        self.assertIn("Musterweg 30", body)
        self.assertIn("logical floor map", body)
        self.assertIn("EG - B\u00fcro 019", body)
        self.assertIn('<g class="plan-legend">', body)
        self.assertIn("10.18.0.0/24", body)

    def test_a_site_without_a_plan_or_a_name_is_answered(self):
        self.client.force_login(self.user)
        other = Site.objects.create(name="Depot", slug="depot")
        response = self.get_plan(f"floor-plan/{other.slug}/")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"no floor plan", response.content)
        self.assertIn(
            b"No site with the slug", self.get_plan("floor-plan/nothing/").content
        )

    def test_a_plan_needs_the_map_permission(self):
        response = self.get_plan("floor-plans/")
        self.assertIn(response.status_code, (302, 403))
        self.client.force_login(
            User.objects.create_user(username="plain", password="pass")  # nosec B106
        )
        self.assertEqual(self.get_plan("floor-plans/").status_code, 403)
        self.assertEqual(self.get_plan("floor-plan/musterweg-30/").status_code, 403)

    @unittest.skipUnless(png_render.available(), "needs cairosvg or ImageMagick")
    def test_a_plan_can_be_handed_over_as_a_raster(self):
        self.client.force_login(self.user)
        response = self.get_plan("floor-plan/musterweg-30/?format=png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("image/png"))
        self.assertTrue(response.content.startswith(png_render.PNG_MAGIC))

    def test_the_api_root_points_at_the_plans(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/api/plugins/{self.prefix}/")
        self.assertIn(b"floor-plans", response.content)


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
            Path(floor_plan.__file__).parent / "static/network_map/subnet_map.js"
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


class SettingGettersTests(TestCase):
    """The reading of plugin settings: numbers that stay numbers."""

    def test_the_default_stands_when_nothing_is_set(self):
        self.assertEqual(canton_code(), DEFAULT_CANTON_BOUNDARY_CODE)
        self.assertEqual(int_setting("map_border_cut", 3), 3)
        self.assertEqual(float_setting("request_timeout_seconds", 10), 10.0)

    def test_a_set_number_is_read_as_its_kind(self):
        with override_settings(
            PLUGINS_CONFIG={
                "network_map": {"map_border_cut": "7", "map_tile_budget_seconds": "1.5"}
            }
        ):
            self.assertEqual(int_setting("map_border_cut", 3), 7)
            self.assertEqual(float_setting("map_tile_budget_seconds", 20), 1.5)

    def test_a_malformed_value_falls_back_instead_of_raising(self):
        with override_settings(
            PLUGINS_CONFIG={
                "network_map": {
                    "map_border_cut": "wide",
                    "request_timeout_seconds": "forever",
                }
            }
        ):
            self.assertEqual(int_setting("map_border_cut", 3, minimum=0), 3)
            self.assertEqual(float_setting("request_timeout_seconds", 10, 0), 10.0)

    def test_the_minimum_holds_for_a_configured_value(self):
        with override_settings(PLUGINS_CONFIG={"network_map": {"map_border_cut": -5}}):
            self.assertEqual(int_setting("map_border_cut", 3, minimum=0), 0)

    def test_the_canton_code_is_the_configured_one(self):
        with override_settings(
            PLUGINS_CONFIG={"network_map": {"canton_boundary_code": "CH"}}
        ):
            self.assertEqual(canton_code(), "CH")


class StaticUrlTagTests(TestCase):
    def test_the_url_carries_the_files_modification_time(self):
        url = static_url("network_map/svg_export.js")
        self.assertTrue(url.startswith(f"{static('network_map/svg_export.js')}?v="))

    def test_an_unknown_file_keeps_the_plain_url(self):
        self.assertEqual(
            static_url("network_map/nothing_here.js"),
            static("network_map/nothing_here.js"),
        )
