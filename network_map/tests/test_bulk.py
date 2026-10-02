"""Bulk data-access helper tests."""

from dcim.models import (
    Device,
    DeviceRole,
    DeviceType,
    Interface,
    Location,
    Manufacturer,
    Site,
)
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from ipam.models import VLAN, IPAddress, Prefix
from virtualization.models import VirtualMachine, VMInterface

from ..bulk import ips_for_prefixes, resolve_assigned_objects
from ..views import VlanElementListView


def _naive_ips(prefix, **filters):
    """What the pages used to run: one containment query per prefix."""
    return list(
        IPAddress.objects.filter(
            address__net_contained_or_equal=prefix.prefix, **filters
        ).order_by("address")
    )


class IpsForPrefixesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vlan = VLAN.objects.create(vid=10, name="Bulk")
        cls.prefix = Prefix.objects.create(prefix="10.9.0.0/24", vlan=cls.vlan)
        cls.subprefix = Prefix.objects.create(prefix="10.9.0.0/25", vlan=cls.vlan)
        cls.outside = Prefix.objects.create(prefix="10.8.0.0/24", vlan=cls.vlan)
        cls.in_range = IPAddress.objects.create(
            address="10.9.0.20/24", dns_name="b.example.com", status="active"
        )
        cls.in_range_low = IPAddress.objects.create(
            address="10.9.0.5/25", dns_name="a.example.com", status="active"
        )
        cls.deprecated = IPAddress.objects.create(
            address="10.9.0.30/24", dns_name="old.example.com", status="deprecated"
        )
        cls.no_dns = IPAddress.objects.create(address="10.9.0.40/24", status="active")
        cls.out_of_range = IPAddress.objects.create(
            address="10.8.0.1/24", dns_name="elsewhere.example.com", status="active"
        )

    def test_groups_match_the_per_prefix_queries(self):
        grouped = ips_for_prefixes(
            [self.prefix, self.subprefix, self.outside],
            status__in=["active", "reserved"],
            dns_name__isnull=False,
        )
        self.assertEqual(
            [ip.pk for ip in grouped[self.prefix.pk]],
            [
                ip.pk
                for ip in _naive_ips(
                    self.prefix,
                    status__in=["active", "reserved"],
                    dns_name__isnull=False,
                )
            ],
        )
        self.assertEqual(
            [ip.pk for ip in grouped[self.subprefix.pk]],
            [
                ip.pk
                for ip in _naive_ips(
                    self.subprefix,
                    status__in=["active", "reserved"],
                    dns_name__isnull=False,
                )
            ],
        )
        self.assertEqual(
            [ip.pk for ip in grouped[self.outside.pk]],
            [
                ip.pk
                for ip in _naive_ips(
                    self.outside,
                    status__in=["active", "reserved"],
                    dns_name__isnull=False,
                )
            ],
        )

    def test_applies_filters(self):
        grouped = ips_for_prefixes([self.prefix])
        pks = {ip.pk for ip in grouped[self.prefix.pk]}
        self.assertEqual(
            pks,
            {
                self.in_range.pk,
                self.in_range_low.pk,
                self.deprecated.pk,
                self.no_dns.pk,
            },
        )

    def test_no_query_without_prefixes(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(ips_for_prefixes([]), {})
        self.assertEqual(len(queries), 0)


class ResolveAssignedObjectsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="DC", slug="dc")
        cls.room = Location.objects.create(site=cls.site, name="EG 1", slug="eg-1")
        role, _ = DeviceRole.objects.get_or_create(
            name="Server", defaults={"slug": "server"}
        )
        manufacturer = Manufacturer.objects.create(name="Vendor", slug="vendor")
        device_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="Model", slug="model"
        )
        cls.device = Device.objects.create(
            site=cls.site,
            location=cls.room,
            name="srv1",
            role=role,
            device_type=device_type,
        )
        cls.interface = Interface.objects.create(
            device=cls.device, name="eth0", type="1000base-t"
        )
        cls.vm = VirtualMachine.objects.create(site=cls.site, name="vm1")
        cls.vminterface = VMInterface.objects.create(
            virtual_machine=cls.vm, name="eth0"
        )
        Prefix.objects.create(prefix="10.7.0.0/24")
        cls.device_ip = IPAddress.objects.create(
            address="10.7.0.10/24",
            dns_name="srv1.example.com",
            assigned_object=cls.interface,
        )
        cls.vm_ip = IPAddress.objects.create(
            address="10.7.0.11/24",
            dns_name="vm1.example.com",
            assigned_object=cls.vminterface,
        )
        cls.loose_ip = IPAddress.objects.create(
            address="10.7.0.12/24", dns_name="free.example.com"
        )

    def ips(self):
        return list(
            IPAddress.objects.filter(
                pk__in=[self.device_ip.pk, self.vm_ip.pk, self.loose_ip.pk]
            )
        )

    def test_maps_ips_to_their_owners(self):
        owners = resolve_assigned_objects(self.ips())
        self.assertEqual(owners[self.device_ip.pk], self.interface)
        self.assertEqual(owners[self.vm_ip.pk], self.vminterface)
        self.assertIsNone(owners[self.loose_ip.pk])

    def test_site_and_role_come_with_the_join(self):
        owners = resolve_assigned_objects(self.ips())
        with CaptureQueriesContext(connection) as queries:
            device = owners[self.device_ip.pk].device
            self.assertEqual(device.site.name, "DC")
            self.assertEqual(device.location.name, "EG 1")
            self.assertEqual(str(device.role), "Server")
            vm = owners[self.vm_ip.pk].virtual_machine
            self.assertEqual(vm.site.name, "DC")
        self.assertEqual(len(queries), 0)

    def test_one_query_per_model(self):
        with CaptureQueriesContext(connection) as queries:
            resolve_assigned_objects(self.ips())
        # One per involved model, plus the content-type lookups; not one per IP.
        self.assertLessEqual(len(queries), 4)


class BuildElementsQueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name="Many", slug="many")
        role, _ = DeviceRole.objects.get_or_create(
            name="Worker", defaults={"slug": "worker"}
        )
        manufacturer = Manufacturer.objects.create(name="V", slug="v")
        device_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="M", slug="m"
        )
        for vid in range(1, 5):
            vlan = VLAN.objects.create(vid=vid, name=f"V{vid}")
            Prefix.objects.create(prefix=f"10.60.{vid}.0/24", vlan=vlan)
            for last in range(1, 5):
                device = Device.objects.create(
                    site=site,
                    name=f"d{vid}{last}",
                    role=role,
                    device_type=device_type,
                )
                interface = Interface.objects.create(
                    device=device, name="eth0", type="1000base-t"
                )
                IPAddress.objects.create(
                    address=f"10.60.{vid}.{last}/24",
                    dns_name=f"d{vid}{last}.example.com",
                    assigned_object=interface,
                )

    def test_query_count_stays_flat(self):
        view = VlanElementListView()
        with CaptureQueriesContext(connection) as queries:
            elements = view.build_elements(view.get_queryset())
        # 4 VLANs x 4 machines: the old per-prefix, per-IP loading needed
        # over 80 queries; this must stay a small constant.
        self.assertEqual(sum(e.machine_count for e in elements), 16)
        self.assertLessEqual(len(queries), 10)
