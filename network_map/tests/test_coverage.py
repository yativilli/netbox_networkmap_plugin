"""Tests for the read-only map readiness coverage report."""

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
from django.test import TestCase
from django.urls import reverse
from ipam.models import VLAN, IPAddress, Prefix
from users.models import ObjectPermission, User

from .. import views as plugin_views
from ..coverage import (
    BLOCKING,
    INFO,
    WARNING,
    CoverageFinding,
    _group_findings,
    build_coverage,
)


class CoverageServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = DeviceRole.objects.create(name="Coverage role", slug="coverage-role")
        cls.manufacturer = Manufacturer.objects.create(
            name="Coverage vendor", slug="coverage-vendor"
        )
        cls.device_type = DeviceType.objects.create(
            manufacturer=cls.manufacturer, model="Coverage model", slug="coverage-model"
        )

    def setUp(self):
        # The gateway search touches NetBox's whole search index; coverage tests
        # care about its report rows, not about searching unrelated model types.
        patcher = mock.patch("network_map.coverage.search_backend.search")
        self.search = patcher.start()
        self.search.return_value = []
        self.addCleanup(patcher.stop)

    def coverage(self):
        report = build_coverage()
        return [
            {
                "category": finding.category,
                "severity": finding.severity,
                "issue": str(finding.issue),
                "site": finding.site,
                "label": finding.label,
            }
            for group in report["groups"]
            for finding in group["items"]
        ]

    def has_issue(self, findings, category, issue, site=""):
        return any(
            finding["category"] == category
            and finding["issue"] == issue
            and (not site or finding["site"] == site)
            for finding in findings
        )

    def test_reports_a_vlan_without_a_prefix(self):
        VLAN.objects.create(vid=999, name="No Prefix")
        self.assertTrue(
            self.has_issue(self.coverage(), "vlans", "VLAN has no prefix"),
        )

    def test_reports_a_site_with_machines_but_no_coordinates(self):
        site = Site.objects.create(name="No coords", slug="no-coords")
        self._device_with_ip(site=site, address="10.90.0.10/24")
        self.assertTrue(
            self.has_issue(
                self.coverage(),
                "sites",
                "No coordinates for a site with machines",
                site="No coords",
            )
        )

    def test_reports_blank_dns_names(self):
        site = Site.objects.create(
            name="DNS site", slug="dns-site", latitude=46.9, longitude=7.4
        )
        self._device_with_ip(
            site=site,
            address="10.91.0.10/24",
            dns_name="",
            vlan_vid=991,
        )
        self.assertTrue(
            self.has_issue(
                self.coverage(),
                "ips",
                "IP address has a blank DNS name",
                site="DNS site",
            )
        )

    def test_reports_physical_machines_without_a_room(self):
        site = Site.objects.create(
            name="Roomless", slug="roomless", latitude=46.9, longitude=7.4
        )
        self._device_with_ip(
            site=site,
            address="10.92.0.10/24",
            dns_name="roomless.example.com",
            vlan_vid=992,
        )
        self.assertTrue(
            self.has_issue(
                self.coverage(),
                "placements",
                "Physical machine has no room",
                site="Roomless",
            )
        )

    def test_reports_rooms_whose_floor_cannot_be_inferred(self):
        site = Site.objects.create(
            name="Floor site", slug="floor-site", latitude=46.9, longitude=7.4
        )
        Location.objects.create(site=site, name="Mystery area")
        self._device_with_ip(
            site=site,
            address="10.93.0.10/24",
            dns_name="floor.example.com",
            vlan_vid=993,
        )
        self.assertTrue(
            self.has_issue(
                self.coverage(),
                "rooms",
                "Floor cannot be inferred from the room name",
                site="Floor site",
            )
        )

    def _device_with_ip(
        self,
        *,
        site,
        address,
        dns_name="host.example.com",
        vlan_vid=None,
        prefix=None,
    ):
        device = Device.objects.create(
            site=site,
            name=f"device-{device_suffix(address)}",
            role=self.role,
            device_type=self.device_type,
        )
        interface = Interface.objects.create(
            device=device, name="eth0", type="1000base-t"
        )
        vlan = VLAN.objects.create(vid=vlan_vid or vlan_id_from_address(address))
        Prefix.objects.create(prefix=prefix or network_for_address(address), vlan=vlan)
        IPAddress.objects.create(
            address=address,
            status="active",
            dns_name=dns_name,
            assigned_object=interface,
        )
        return device


class CoverageGroupingTests(TestCase):
    def _finding(self, category: str, severity: str, label: str):
        return CoverageFinding(
            category=category,
            severity=severity,
            issue=f"{category} {severity}",
            detail="test",
            object_type="Test",
            label=label,
            url="",
            site=label,
        )

    def test_groups_only_count_their_own_category(self):
        findings = [
            self._finding("sites", BLOCKING, "No coords"),
            self._finding("vlans", WARNING, "No prefix"),
            self._finding("rooms", INFO, "No machines"),
        ]
        groups = {
            group["key"]: group for group in _group_findings(findings, "", "", "")
        }

        self.assertEqual(groups["sites"]["total"], 1)
        self.assertEqual(groups["sites"]["severity_counts"][BLOCKING], 1)
        self.assertEqual(groups["vlans"]["total"], 1)
        self.assertEqual(groups["vlans"]["severity_counts"][WARNING], 1)
        self.assertEqual(groups["rooms"]["total"], 1)
        self.assertEqual(groups["rooms"]["severity_counts"][INFO], 1)
        self.assertEqual(groups["gateways"]["total"], 0)

    def test_category_filter_keeps_only_the_requested_group(self):
        findings = [
            self._finding("sites", BLOCKING, "No coords"),
            self._finding("vlans", WARNING, "No prefix"),
        ]
        groups = {
            group["key"]: group for group in _group_findings(findings, "sites", "", "")
        }

        self.assertEqual(groups["sites"]["total"], 1)
        self.assertEqual(groups["vlans"]["total"], 0)


class CoverageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.map_content_type = ContentType.objects.get(
            app_label="network_map", model="vlanelement"
        )

    def _viewer(self):
        user = User.objects.create_user(username="coverage", password="pass")  # nosec B106
        permission = ObjectPermission.objects.create(
            name="test-view-networkmap-coverage",
            actions=["view"],
        )
        permission.object_types.add(self.map_content_type)
        user.object_permissions.add(permission)
        return user

    def test_coverage_page_renders(self):
        user = self._viewer()
        self.client.force_login(user)
        with mock.patch("network_map.coverage.search_backend.search", return_value=[]):
            response = self.client.get(reverse("plugins:network_map:data_coverage"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Coverage")

    def test_coverage_page_does_not_geocode(self):
        user = self._viewer()
        self.client.force_login(user)
        with (
            mock.patch("network_map.coverage.search_backend.search", return_value=[]),
            mock.patch.object(plugin_views, "geocode_sites") as geocode,
        ):
            response = self.client.get(reverse("plugins:network_map:data_coverage"))
        self.assertEqual(response.status_code, 200)
        geocode.assert_not_called()

    def test_coverage_page_filters_by_site(self):
        user = self._viewer()
        self.client.force_login(user)
        with mock.patch("network_map.coverage.search_backend.search", return_value=[]):
            response = self.client.get(
                reverse("plugins:network_map:data_coverage"), {"site": "Nowhere"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No coverage issues found")


def device_suffix(address: str) -> str:
    return address.replace(".", "-").replace("/", "-")


def network_for_address(address: str) -> str:
    host, mask = address.split("/")
    return ".".join(host.split(".")[:3]) + f".0/{mask}"


def vlan_id_from_address(address: str) -> int:
    first = int(address.split(".")[0])
    return 1000 + (first % 1000)
