"""Geographic, tile, border and settings tests."""

import json
import math
import re
from typing import ClassVar
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from users.models import ObjectPermission, User

from .. import lv03, map_tiles, swisstopo
from ..defaults import (
    DEFAULT_CANTON_BOUNDARY_CODE,
    canton_code,
    float_setting,
    int_setting,
)
from ..views import SubnetLocationView
from ._helpers import _FakeHTTPResponse, _FakeTileResponse, _lv03_extent, _static

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
                r"var g = (\{.*?\});\n", _static("subnet_map/lv03_grid.js"), re.DOTALL
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
        source = _static("subnet_map/subnet_map.js")
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


SAMPLE_BORDER = {
    "type": "Feature",
    "properties": {"canton_no": 2},
    "geometry": {
        "type": "MultiPolygon",
        "coordinates": [[[[[7.2, 46.9], [7.3, 46.9], [7.3, 47.0], [7.2, 46.9]]]]],
    },
}
SAMPLE_COLLECTION = {"type": "FeatureCollection", "features": [SAMPLE_BORDER]}


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
