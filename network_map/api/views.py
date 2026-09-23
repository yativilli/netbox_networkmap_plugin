from collections import OrderedDict

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from netbox.plugins import get_plugin_config
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from .. import png_render, svg_render
from ..defaults import DEFAULT_CANTON_BOUNDARY_CODE
from ..swisstopo import get_canton_boundary, get_canton_label
from ..views import (
    SubnetLocationView,
    VlanConnectionView,
    VlanElementListView,
    VlanTopologyView,
)

SVG_KINDS = ("machine-list", "logical-map", "subnet-map", "topology")


class SvgRenderer(BaseRenderer):
    media_type = "image/svg+xml"
    format = "svg"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return str(data).encode(self.charset)


class PngRenderFailed(APIException):
    status_code = 501
    default_detail = "PNG rendering is not available on this NetBox."
    default_code = "png_unavailable"


class PngRenderer(BaseRenderer):
    """
    The very same documents as the SVG renderer, rasterised: for the callers
    that cannot do anything with SVG, a mail gateway or a terminal that only
    opens pictures. Which rasteriser does the work is up to png_render.
    """

    media_type = "image/png"
    format = "png"
    charset = None
    binary = True

    def render(self, data, accepted_media_type=None, renderer_context=None):
        markup = data if isinstance(data, str) else str(data)
        if not markup.lstrip().startswith(("<?xml", "<svg")):
            # What is not a document - an error message for one - is worth
            # more as its own text than as a picture of it.
            return markup.encode("utf-8")
        try:
            return png_render.render_png(markup)
        except png_render.PngRenderError as error:
            raise PngRenderFailed(str(error)) from error


class PluginApiRootView(APIView):
    _ignore_model_permissions = True
    schema = None

    @extend_schema(exclude=True)
    def get(self, request, format=None):
        entries = OrderedDict(
            (
                (
                    "installed-plugins",
                    reverse("plugins-api:plugins-list", request=request, format=format),
                ),
            )
        )
        for kind in SVG_KINDS:
            url = reverse(
                "plugins-api:network_map-api:svg-export",
                kwargs={"kind": kind},
                request=request,
                format=format,
            )
            entries[kind] = url
            # The same picture as a raster, which is what the map page's own
            # export button hands out; the format stands on the query string.
            entries[f"{kind}.png"] = f"{url}?format=png"
        return Response(entries)


class MapSvgView(APIView):
    """
    Renders one of the network map views as a standalone picture: an SVG
    document, or the same document rasterised when PNG is asked for.
    """

    permission_classes = (IsAuthenticated,)
    renderer_classes = (SvgRenderer, PngRenderer)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.has_perm("network_map.view_vlanelement"):
            raise PermissionDenied("Missing permission: network_map.view_vlanelement")
        # Better an answer than a picture that cannot be made: nothing here
        # draws SVG, so a PNG needs a rasteriser installed besides the plugin.
        renderer, _media_type = self.perform_content_negotiation(request)
        if getattr(renderer, "format", None) == "png" and not png_render.available():
            raise PngRenderFailed(
                "PNG needs a rasteriser: install the cairosvg package or "
                "ImageMagick on the NetBox server."
            )

    def get_view_name(self):
        return "Map SVG"

    @extend_schema(
        tags=["network-map"],
        summary="Render a network map view as SVG or PNG",
        parameters=[
            OpenApiParameter(
                name="kind",
                type=OpenApiTypes.STR,
                location="path",
                required=True,
                enum=list(SVG_KINDS),
                description="Which map view to render.",
            ),
            OpenApiParameter(
                name="format",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["svg", "png"],
                description="Picture format; SVG without it, PNG as ?format=png.",
            ),
        ],
        responses={
            (200, "image/svg+xml"): OpenApiTypes.BINARY,
            (200, "image/png"): OpenApiTypes.BINARY,
        },
    )
    def get(self, request, kind):
        if kind == "machine-list":
            list_view = VlanElementListView()
            svg = svg_render.render_machine_list(
                list_view.build_elements(list_view.get_queryset())
            )
        elif kind == "logical-map":
            connection_view = VlanConnectionView()
            svg = svg_render.render_logical_tree(
                connection_view.build_elements(), connection_view.get_center_device()
            )
        elif kind == "subnet-map":
            subnet_view = SubnetLocationView()
            map_data = subnet_view.build_map_data(
                subnet_view.build_elements(subnet_view.get_queryset())
            )
            canton_code = get_plugin_config(
                "network_map", "canton_boundary_code", DEFAULT_CANTON_BOUNDARY_CODE
            )
            boundary = get_canton_boundary(canton_code)
            svg = svg_render.render_subnet_map(
                map_data,
                boundary,
                get_canton_label(canton_code) if boundary else None,
            )
        elif kind == "topology":
            topology_view = VlanTopologyView()
            center_device = topology_view.get_center_device()
            elements = topology_view.decorate_elements(
                topology_view.build_elements(topology_view.get_queryset())
            )
            svg = svg_render.render_topology(
                topology_view.serialize_topology(elements, center_device)
            )
        else:
            return Response(f"Unknown SVG kind: {kind}", status=404)
        return Response(svg)
