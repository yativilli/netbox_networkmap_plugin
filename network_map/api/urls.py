from django.urls import path

from .views import MapSvgView, PluginApiRootView

urlpatterns = [
    path("", PluginApiRootView.as_view(), name="api-root"),
    path("svg/<slug:kind>/", MapSvgView.as_view(), name="svg-export"),
]
