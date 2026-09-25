"""VLAN model mapping tests."""

from django.test import TestCase
from ipam.models import VLAN, Prefix, Role, VLANGroup

from ..models import VlanInfo


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
