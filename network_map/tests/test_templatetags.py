"""Template tag tests."""

from django.templatetags.static import static
from django.test import TestCase

from ..templatetags.network_map_static import static_url


class StaticUrlTagTests(TestCase):
    def test_the_url_carries_the_files_modification_time(self):
        url = static_url("network_map/shared/svg_export.js")
        self.assertTrue(
            url.startswith(f"{static('network_map/shared/svg_export.js')}?v=")
        )

    def test_an_unknown_file_keeps_the_plain_url(self):
        self.assertEqual(
            static_url("network_map/nothing_here.js"),
            static("network_map/nothing_here.js"),
        )
