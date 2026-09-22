import json
from types import SimpleNamespace
from unittest import mock

from dcim.models import Site
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from ipam.models import VLAN, Prefix, Role, VLANGroup
from users.models import ObjectPermission, User

from . import svg_render, swisstopo
from .colors import shade_of
from .models import VlanInfo
from .views import SubnetLocationView, VlanTopologyView


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

    def get_svg(self, kind):
        # The mount prefix derives from the plugin's base_url/module name.
        for prefix in ("networkmap", "network_map"):
            response = self.client.get(f"/api/plugins/{prefix}/svg/{kind}/")
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
            self.assertIn(f"/svg/{kind}/", data[kind])

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
        # WFS returns plain GeoJSON; interior rings (holes) must survive and
        # come from the primary source without hitting the fallback.
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
    def test_fallback_used_when_primary_empty(self, urlopen):
        empty = _FakeHTTPResponse({"type": "FeatureCollection", "features": []})
        api3 = _FakeHTTPResponse(
            {
                "feature": {
                    "attributes": {"ak": "BE"},
                    "geometry": {
                        "rings": [[[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.0, 47.0]]]
                    },
                }
            }
        )
        urlopen.side_effect = [empty, api3]
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["features"][0]["properties"]["ak"], "BE")

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_fallback_used_when_primary_fails(self, urlopen):
        api3 = _FakeHTTPResponse(
            {
                "feature": {
                    "attributes": {"ak": "BE"},
                    "geometry": {
                        "rings": [[[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.0, 47.0]]]
                    },
                }
            }
        )
        urlopen.side_effect = [OSError("offline"), api3]
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["features"][0]["properties"]["ak"], "BE")

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

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_last_resort_used_when_first_two_sources_fail(self, urlopen):
        empty_collection = _FakeHTTPResponse(
            {"type": "FeatureCollection", "features": []}
        )
        api3 = _FakeHTTPResponse(
            {
                "feature": {
                    "attributes": {"ak": "BE"},
                    "geometry": {
                        "rings": [[[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.0, 47.0]]]
                    },
                }
            }
        )
        empty_nominatim = _FakeHTTPResponse([])
        urlopen.side_effect = [empty_collection, empty_nominatim, api3]
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(result["features"][0]["properties"]["ak"], "BE")

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
        urlopen.return_value = _FakeHTTPResponse(
            {"type": "FeatureCollection", "features": []}
        )
        self.assertIsNone(swisstopo.get_canton_boundary("BE"))
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_features_without_geometry_fall_back(self, urlopen):
        no_geometry = _FakeHTTPResponse(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": 2}, "geometry": None}
                ],
            }
        )
        api3 = _FakeHTTPResponse(
            {
                "feature": {
                    "attributes": {"ak": "BE"},
                    "geometry": {
                        "rings": [[[7.0, 47.0], [7.0, 47.1], [7.1, 47.1], [7.0, 47.0]]]
                    },
                }
            }
        )
        urlopen.side_effect = [no_geometry, api3]
        result = swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["features"][0]["properties"]["ak"], "BE")

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_boundary_cached_after_first_fetch(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(SAMPLE_COLLECTION)
        swisstopo.get_canton_boundary("BE")
        swisstopo.get_canton_boundary("BE")
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch("network_map.swisstopo.urllib.request.urlopen", side_effect=OSError)
    def test_fetch_failure_returns_none(self, urlopen):
        self.assertIsNone(swisstopo.get_canton_boundary("BE"))

    @mock.patch("network_map.swisstopo.urllib.request.urlopen")
    def test_empty_geometry_returns_none(self, urlopen):
        urlopen.return_value = _FakeHTTPResponse(
            {"type": "FeatureCollection", "features": []}
        )
        self.assertIsNone(swisstopo.get_canton_boundary("BE"))

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
            mock.patch("network_map.views.resolve_canton_id", return_value=2),
            mock.patch(
                "network_map.views.get_canton_label", return_value="Kanton Bern"
            ),
        ):
            data = view.build_map_data([])
        self.assertEqual(data["canton_boundary_url"], boundary_url)
        self.assertEqual(data["canton_label"], "Kanton Bern")

    def test_build_map_data_omits_boundary_when_unset(self):
        view = SubnetLocationView()
        with (
            mock.patch(
                "network_map.views.get_plugin_config",
                side_effect=lambda name, key, default=None: default,
            ),
            mock.patch("network_map.views.resolve_canton_id", return_value=None),
        ):
            data = view.build_map_data([])
        self.assertIsNone(data["canton_boundary_url"])
        self.assertIsNone(data["canton_label"])


# Well-nested GeoJSON, unlike SAMPLE_BORDER: the map renderer reads the
# polygon rings themselves, so it needs real MultiPolygon nesting.
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


class SubnetMapSvgTests(TestCase):
    def test_border_extent_frames_the_export(self):
        svg = svg_render.render_subnet_map(
            {"pins": MAP_PINS}, MAP_BORDER, "Kanton Bern"
        )
        self.assertIn('class="map-border" d=', svg)
        self.assertIn("Kanton Bern", svg)
        # One border path, drawn twice (halo and fill), carrying the
        # exterior ring and the hole as two subpaths.
        self.assertEqual(svg.count('class="map-border" d='), 1)
        self.assertEqual(svg.count("ZM"), 2)
        # Pins outside the configured border are clamped, never dropped.
        self.assertIn('class="map-offframe"', svg)
        self.assertIn("outside the drawn area", svg)

    def test_pin_extent_used_without_border(self):
        svg = svg_render.render_subnet_map({"pins": MAP_PINS})
        self.assertNotIn('class="map-border"', svg)
        self.assertNotIn('class="map-offframe"', svg)
        self.assertIn("Filiale Genf", svg)
        self.assertIn("10.10.10.0/24", svg)
        self.assertIn("swisstopo", svg)

    def test_subnets_at_one_site_share_a_cluster_label(self):
        svg = svg_render.render_subnet_map({"pins": MAP_PINS})
        self.assertEqual(svg.count(">RZ Bern<"), 1)
        self.assertEqual(svg.count(">Filiale Genf<"), 1)

    def test_map_without_pins_renders_a_stub(self):
        svg = svg_render.render_subnet_map({"pins": []})
        self.assertIn("<svg", svg)
        self.assertNotIn('class="map-pin"', svg)


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
