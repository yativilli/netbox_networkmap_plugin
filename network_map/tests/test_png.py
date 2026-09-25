"""PNG rasterizer tests."""

from unittest import mock

from django.test import TestCase

from .. import png_render


class PngRenderTests(TestCase):
    def test_the_vector_library_is_preferred_to_the_command_line(self):
        cairosvg = mock.Mock()
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png("<svg/>")
        cairosvg.svg2png.assert_called_once()

    def test_imagemagick_is_asked_for_a_raster(self):
        finished = mock.Mock(returncode=0, stdout=b"\x89PNG..", stderr=b"")
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch(
                "network_map.png_render.shutil.which", return_value="/usr/bin/magick"
            ),
            mock.patch(
                "network_map.png_render.subprocess.run", return_value=finished
            ) as run,
        ):
            self.assertEqual(png_render.render_png("<svg/>"), b"\x89PNG..")
        self.assertIn("-density", run.call_args.args[0])

    def test_a_failing_rasteriser_is_reported(self):
        finished = mock.Mock(returncode=1, stdout=b"", stderr=b"boom")
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch(
                "network_map.png_render.shutil.which", return_value="/usr/bin/magick"
            ),
            mock.patch("network_map.png_render.subprocess.run", return_value=finished),
            self.assertRaisesRegex(png_render.PngRenderError, "boom"),
        ):
            png_render.render_png("<svg/>")

    def test_a_document_no_raster_can_hold_comes_out_smaller(self):
        cairosvg = mock.Mock()
        giant = '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="71148"/>'
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png(giant)
        scale = cairosvg.svg2png.call_args.kwargs["scale"]
        self.assertLess(scale, 1)
        self.assertAlmostEqual(71148 * scale, png_render.PNG_MAX_EDGE, places=3)

    def test_an_ordinary_document_keeps_its_scale(self):
        cairosvg = mock.Mock()
        with mock.patch("network_map.png_render._cairosvg", return_value=cairosvg):
            png_render.render_png('<svg xmlns="x" width="1200" height="1100"/>')
        self.assertEqual(
            cairosvg.svg2png.call_args.kwargs["scale"], png_render.PNG_SCALE
        )

    def test_no_rasteriser_at_all_is_reported(self):
        with (
            mock.patch("network_map.png_render._cairosvg", return_value=None),
            mock.patch("network_map.png_render.shutil.which", return_value=None),
            self.assertRaises(png_render.PngRenderError),
        ):
            self.assertFalse(png_render.available())
            png_render.render_png("<svg/>")
