from django.urls import path, re_path

from .views import MapSvgView, PluginApiRootView

urlpatterns = [
    path("", PluginApiRootView.as_view(), name="api-root"),
    # The kind of picture stands in the path and its format on the query
    # string, so the address of a raster is
    # /api/plugins/networkmap/subnet-map?format=png. One pattern answers both
    # with and without the trailing slash, which keeps the address the API root
    # links - and the schema - free of a second entry for the same picture.
    re_path(r"^(?P<kind>[\w-]+)/?$", MapSvgView.as_view(), name="svg-export"),
]
