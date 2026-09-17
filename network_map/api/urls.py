from django.urls import path

from .views import MapSvgView

urlpatterns = [
    path("svg/<slug:kind>/", MapSvgView.as_view(), name="svg-export"),
]
