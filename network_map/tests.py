from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from ipam.models import VLAN, Prefix, Role, VLANGroup
from users.models import ObjectPermission, User

from .models import VlanInfo


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


class SvgApiTests(TestCase):
    KINDS = ("machine-list", "logical-map", "topology")

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
            response = self.get_svg(kind)
            self.assertEqual(response.status_code, 200, kind)
            self.assertTrue(response["Content-Type"].startswith("image/svg+xml"), kind)
            self.assertIn(b"<svg", response.content)

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
