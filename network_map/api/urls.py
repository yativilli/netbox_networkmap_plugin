from django.urls import path

from .views import MapSvgView, PluginApiRootView

urlpatterns = [
    path("", PluginApiRootView.as_view(), name="api-root"),
    # The kind of picture stands in the path and its format on the query
    # string, so the address of a raster is
    # /api/plugins/networkmap/subnet-map?format=png. The form without the
    # trailing slash answers too, for the caller that copies one address into a
    # script and does not follow redirects.
    path("<slug:kind>/", MapSvgView.as_view(), name="svg-export"),
    path("<slug:kind>", MapSvgView.as_view()),
]
