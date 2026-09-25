"""Floor-plan API tests."""

import json
import unittest

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
from ipam.models import VLAN, IPAddress, Prefix
from users.models import ObjectPermission, User

from .. import floor_plan, png_render


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
        self.assertNotIn("floors", logical)
        self.assertEqual(logical["machines"], 2)
        self.assertIn("picture", logical)

    def test_the_city_is_read_whichever_way_the_address_runs(self):
        from network_map.places import site_city as _site_city

        self.assertEqual(
            _site_city(Site(physical_address="Musterweg 30, 3000 Bern")), "Bern"
        )
        self.assertEqual(
            _site_city(Site(physical_address="Bern, Musterweg 30")), "Bern"
        )
        self.assertEqual(_site_city(Site(physical_address="3000 Bern")), "Bern")
        self.assertEqual(_site_city(Site(physical_address="Musterweg 30")), "")
        self.assertEqual(_site_city(Site(physical_address="")), "")
        self.assertEqual(_site_city(Site()), "")
        # The place often lives only in the site name, "Bern, Nordring 30".
        self.assertEqual(_site_city(Site(name="Bern, Musterweg 30")), "Bern")
        self.assertEqual(
            _site_city(Site(name="Matten bei Interlaken, Wychelstrasse 28")),
            "Matten bei Interlaken",
        )
        self.assertEqual(
            _site_city(Site(name="Biel/Bienne, Spitalstrasse 20", physical_address="")),
            "Biel/Bienne",
        )
        # The address names the place first, so it wins over the name.
        self.assertEqual(
            _site_city(Site(name="Musterweg 30", physical_address="3000 Bern")), "Bern"
        )

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
