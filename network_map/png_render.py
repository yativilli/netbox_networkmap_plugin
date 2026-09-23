"""
Rasterising the generated SVG documents to PNG.

Nothing inside NetBox draws SVG: the browser does it for the web pages and the
API hands the document itself out. A PNG therefore needs somebody else to
rasterise it, and the plugin takes whichever of the two usual suspects it
finds - the cairosvg package, which follows CSS closely, or the ImageMagick
command line, which is installed everywhere but quietly drops what it does not
understand (dashed strokes for one, so the canton border disappears). Without
either, a PNG request says so rather than sending a broken picture.
"""

import shutil
import subprocess  # nosec B404 - only a fixed rasteriser command is run

# SVG user units are pixels at 96 dpi, and cairosvg's scale multiplies that.
# Twice the size of the document is what the web page's own export rasterises
# at, and it still prints a canton map readably.
PNG_SCALE = 2
# A map of a whole canton is a large canvas; conversion may not hang a request.
PNG_TIMEOUT = 60
# Ceiling for ImageMagick, so a mistaken scale cannot ask for gigabytes.
IMAGEMAGICK_AREA = "100MP"
# ImageMagick reads an SVG at this density unless told otherwise.
IMAGEMAGICK_DPI = 72
PNG_MAGIC = b"\x89PNG"


class PngRenderError(Exception):
    """No rasteriser is installed, or the one present failed."""


def _cairosvg():
    try:
        import cairosvg
    except ImportError:
        return None
    return cairosvg


def backend():
    """
    Name of the rasteriser a PNG request would use, or None when there is
    none: the cairosvg package when it is installed, ImageMagick otherwise.
    """
    if _cairosvg() is not None:
        return "cairosvg"
    return shutil.which("magick") or shutil.which("convert")


def available():
    """True when a PNG can be made at all."""
    return backend() is not None


def render_png(markup, scale=PNG_SCALE):
    """Return the PNG bytes of one standalone SVG document."""
    cairosvg = _cairosvg()
    if cairosvg is not None:
        try:
            return cairosvg.svg2png(bytestring=markup.encode("utf-8"), scale=scale)
        except Exception as error:
            # cairosvg raises whatever its parsers raise, none of it worth
            # showing the requester beyond "could not do it".
            raise PngRenderError(
                f"cairosvg could not rasterise the map: {error}"
            ) from error
    return _imagemagick(markup, scale)


def _imagemagick(markup, scale):
    binary = shutil.which("magick") or shutil.which("convert")
    if binary is None:
        raise PngRenderError(
            "no SVG rasteriser available: install the cairosvg package or "
            "ImageMagick to ask for PNG"
        )
    command = [
        binary,
        "-limit",
        "area",
        IMAGEMAGICK_AREA,
        "-background",
        "white",
        "-density",
        str(int(IMAGEMAGICK_DPI * scale)),
        "svg:-",
        "png:-",
    ]
    try:
        finished = subprocess.run(  # nosec B603 - fixed command, no shell
            command,
            input=markup.encode("utf-8"),
            capture_output=True,
            timeout=PNG_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PngRenderError(f"ImageMagick could not be run: {error}") from error
    if finished.returncode != 0 or not finished.stdout.startswith(PNG_MAGIC):
        detail = finished.stderr.decode("utf-8", "replace").strip()
        raise PngRenderError(f"ImageMagick could not rasterise the map: {detail}")
    return finished.stdout
