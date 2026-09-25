"""
Static asset URLs for the plugin's own scripts and stylesheets.
"""

import os

from django.contrib.staticfiles import finders
from django.template import Library
from django.templatetags.static import static

register = Library()


@register.simple_tag
def static_url(path):
    """
    URL of a static file, stamped with the file's modification time. Without
    the stamp a browser keeps running the script it cached during the last
    visit, which makes an updated plugin look exactly like the old one until
    the cache is cleared by hand.
    """
    url = static(path)
    found = finders.find(path)
    source = found[0] if isinstance(found, list) else found
    if not source:
        return url
    try:
        stamp = int(os.path.getmtime(source))
    except OSError:
        return url
    return f"{url}?v={stamp}"
