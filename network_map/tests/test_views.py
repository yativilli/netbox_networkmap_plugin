"""Web view and view serialization tests."""

from types import SimpleNamespace
from unittest import mock

from dcim.models import (
    Device,
    DeviceRole,
    DeviceType,
    Interface,
    Manufacturer,
    Site,
)
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from ipam.models import VLAN, IPAddress, Prefix
from users.models import ObjectPermission, User

from .. import svg_render
from ..views import VlanElementListView, VlanTopologyView


class ViewAccessTests(TestCase):
    URL_NAMES = (
        "vlanelement_list",
        "vlan_topology",
        "vlan_connections",
        "subnet_map",
        "data_coverage",
    )

    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )

    def setUp(self):
        # Views that build full pages may search for gateway objects; these
        # tests care about routing and permissions, not NetBox's whole search.
        for target in (
            "network_map.views.search_backend.search",
            "network_map.coverage.search_backend.search",
        ):
            patcher = mock.patch(target, return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)

    def _viewer(self, username, permission_name):
        user = User.objects.create_user(username=username, password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name=permission_name,
            actions=["view"],
        )
        permission.object_types.add(self.map_content_type)
        user.object_permissions.add(permission)
        return user

    def test_urls_resolve(self):
        for name in self.URL_NAMES:
            self.assertTrue(reverse(f"plugins:network_map:{name}"))

    @override_settings(LOGIN_REQUIRED=True)
    def test_anonymous_urls_redirect_to_login(self):
        for name in self.URL_NAMES:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"plugins:network_map:{name}"))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response.url)

    def test_users_without_permission_get_403(self):
        User.objects.create_user(username="regular", password="pass")  # nosec B106
        self.client.login(username="regular", password="pass")  # nosec B106
        for name in self.URL_NAMES:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"plugins:network_map:{name}"))
                self.assertEqual(response.status_code, 403)

    def test_pages_render_for_a_permitted_user(self):
        user = self._viewer("viewer", "test-view-networkmap")
        self.client.force_login(user)
        for name in self.URL_NAMES:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"plugins:network_map:{name}"))
                self.assertEqual(response.status_code, 200, name)


class TopologyDescriptionTests(TestCase):
    def test_serialize_topology_handles_machine_description(self):
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
                },
                {
                    "dns_name": "host02",
                    "ip": "10.0.0.11",
                    "url": "/ip/2/",
                    "location": "Site A",
                },
            ],
        )
        data = VlanTopologyView().serialize_topology([element], None)
        described, missing = data["subnets"][0]["machines"]
        self.assertEqual(described["description"], "Finance backup")
        self.assertEqual(missing["description"], "")

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
