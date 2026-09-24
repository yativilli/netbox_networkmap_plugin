from django.urls import path, re_path

from .views import (
    FloorPlanIndexView,
    FloorPlanPictureView,
    MapSvgView,
    PluginApiRootView,
)

urlpatterns = [
    path("", PluginApiRootView.as_view(), name="api-root"),
    # Plans are named by site, and both must precede the kind pattern, which would swallow "floor-plans".
    path(
        "floor-plans/",
        FloorPlanIndexView.as_view(),
        name="floor-plan-list",
    ),
    re_path(
        r"^floor-plan/(?P<slug>[\w-]+)/?$",
        FloorPlanPictureView.as_view(),
        name="floor-plan",
    ),
    # The kind stands in the path, the format on the query string; one pattern answers with and without a trailing slash.
    re_path(r"^(?P<kind>[\w-]+)/?$", MapSvgView.as_view(), name="svg-export"),
]
