"""
Words the browser needs at run time, translated while the page is rendered.
"""

from django.template import Library
from django.utils.translation import gettext as _

register = Library()


@register.simple_tag
def export_dialog_labels():
    """
    Labels of the picture export dialog. The dialog is built by a script that
    knows no template, so the translated sentences have to travel to it inside
    the page.
    """
    return {
        "title": _("Export as picture"),
        "choose": _("In which format should the picture be saved?"),
        "png": _("PNG"),
        "png_hint": _("Bitmap picture with a fixed number of pixels"),
        "svg": _("SVG"),
        "svg_hint": _("Vector drawing that stays sharp when it is printed large"),
        "cancel": _("Cancel"),
    }
