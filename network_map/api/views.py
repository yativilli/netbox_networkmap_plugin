from collections import OrderedDict

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from netbox.plugins import get_plugin_config
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from .. import svg_render
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
        entries.update(
            (
                kind,
                reverse(
                    "plugins-api:network_map-api:svg-export",
                    kwargs={"kind": kind},
                    request=request,
                    format=format,
                ),
            )
            for kind in SVG_KINDS
        )
        return Response(entries)


class MapSvgView(APIView):
    """
    Renders one of the network map views as a standalone SVG document.
    """

    permission_classes = (IsAuthenticated,)
    renderer_classes = (SvgRenderer,)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.has_perm("network_map.view_vlanelement"):
            raise PermissionDenied("Missing permission: network_map.view_vlanelement")

    def get_view_name(self):
        return "Map SVG"

    @extend_schema(
        tags=["network-map"],
        summary="Render a network map view as SVG",
        parameters=[
            OpenApiParameter(
                name="kind",
                type=OpenApiTypes.STR,
                location="path",
                required=True,
                enum=list(SVG_KINDS),
                description="Which map view to render.",
            ),
        ],
        responses={(200, "image/svg+xml"): OpenApiTypes.BINARY},
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
