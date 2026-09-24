from django.urls import path, re_path

from .views import (
    FloorPlanIndexView,
    FloorPlanMainView,
    FloorPlanPictureView,
    MapSvgView,
    PluginApiRootView,
)

urlpatterns = [
    path("", PluginApiRootView.as_view(), name="api-root"),
    # A floor plan is asked for by site, because several sites - and so several
    # plans - share a city and only the site is named uniquely. These three come
    # before the kind pattern below, which would otherwise read "floor-plans"
    # as the kind of a picture.
    path(
        "floor-plans/",
        FloorPlanIndexView.as_view(),
        name="floor-plan-list",
    ),
    re_path(
        r"^floor-plan/(?P<slug>[\w-]+)/(?P<plan>[\w.-]+)/?$",
        FloorPlanPictureView.as_view(),
        name="floor-plan",
    ),
    re_path(
        r"^floor-plan/(?P<slug>[\w-]+)/?$",
        FloorPlanMainView.as_view(),
        name="floor-plan-main",
    ),
    # The kind of picture stands in the path and its format on the query
    # string, so the address of a raster is
    # /api/plugins/networkmap/subnet-map?format=png. One pattern answers both
    # with and without the trailing slash, which keeps the address the API root
    # links - and the schema - free of a second entry for the same picture.
    re_path(r"^(?P<kind>[\w-]+)/?$", MapSvgView.as_view(), name="svg-export"),
]
