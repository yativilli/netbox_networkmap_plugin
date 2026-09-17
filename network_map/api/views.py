from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import svg_render
from ..views import (
    VlanConnectionView,
    VlanElementListView,
    VlanTopologyView,
)


class SvgRenderer(BaseRenderer):
    media_type = "image/svg+xml"
    format = "svg"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return str(data).encode(self.charset)


class MapSvgView(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (SvgRenderer,)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.has_perm("network_map.view_vlanelement"):
            raise PermissionDenied("Missing permission: network_map.view_vlanelement")

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
