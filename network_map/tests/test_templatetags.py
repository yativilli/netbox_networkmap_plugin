"""Template tag tests."""

import re

from django.templatetags.static import static
from django.test import TestCase

from ..templatetags.network_map_export import export_dialog_labels
from ..templatetags.network_map_static import static_url
from ._helpers import _static, _template


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


class ExportDialogTagTests(TestCase):
    def test_the_dialog_offers_a_bitmap_and_a_vector(self):
        words = export_dialog_labels()
        self.assertTrue(words["png"] and words["png_hint"])
        self.assertTrue(words["svg"] and words["svg_hint"])

    def test_the_button_is_named_after_a_picture_not_after_a_format(self):
        self.assertEqual(export_dialog_labels()["title"], "Export as picture")


class ExportDialogParityTests(TestCase):
    def test_the_script_reads_the_words_the_page_leaves_behind(self):
        script = _static("shared/export_dialog.js")
        template = _template("includes/_export_dialog.html")
        node_id = re.search(r"const LABELS_ID = '([^']+)'", script).group(1)
        self.assertIn(f'json_script:"{node_id}"', template)
