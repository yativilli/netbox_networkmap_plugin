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
