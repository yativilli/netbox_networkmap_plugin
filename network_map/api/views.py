from collections import OrderedDict

from dcim.models import Site
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from netbox.plugins import get_plugin_config
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from .. import floor_plan, map_tiles, png_render, svg_render
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
        # Which floor plans exist, and where each one is drawn, is worth
        # knowing before asking for one: a city holds several buildings.
        entries["floor-plans"] = reverse(
            "plugins-api:network_map-api:floor-plan-list",
            request=request,
            format=format,
        )
        return Response(entries)


class PictureAccessMixin:
    """
    What every picture of this plugin answers to: the permission to see the
    network map, and - for a raster - a rasteriser on the server.
    """

    permission_classes = (IsAuthenticated,)

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


class MapSvgView(PictureAccessMixin, APIView):
    """
    Renders one of the network map views as a standalone picture: an SVG
    document, or the same document rasterised when PNG is asked for.
    """

    renderer_classes = (SvgRenderer, PngRenderer)

    @staticmethod
    def _wants_background(request):
        """
        Whether the ground is to be fetched for the picture. The tiles are what
        makes a served map look like the one the page's own button makes, but
        they are also what makes the document big, so a caller that only wants
        the drawing asks for it plain.
        """
        return request.query_params.get("background", "1").lower() not in (
            "0",
            "false",
            "off",
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
            OpenApiParameter(
                name="background",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["1", "0"],
                description=(
                    "For the subnet map only: 1 (the default) draws the map "
                    "tiles behind the picture, 0 leaves the ground out."
                ),
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
                tiles_of=map_tiles.background
                if self._wants_background(request)
                else None,
                attribution=map_tiles.attribution(),
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


def _map_floor_plans():
    """Every floor plan the subnet map can show, from the map's own data."""
    view = SubnetLocationView()
    elements = view.build_elements(view.get_queryset())
    return view.build_floor_plans(view.build_map_data(elements))


def _floor_labels(plan):
    """
    The floors a plan shows, named as the plan names its bands, so the index
    and the picture agree without the index having to lay the plan out.
    """
    rooms = [name for name in plan["rooms"] if name]
    labels = {}
    for name in rooms:
        sort, label = floor_plan.logical_floor(name)
        labels.setdefault(sort, label)
    machines = [machine for pin in plan["pins"] for machine in pin["machines"]]
    if any(not machine.get("room") for machine in machines):
        labels[-1000] = _("Machines") if not rooms else _("No location")
    if any(machine.get("physical", True) is False for machine in machines):
        labels[-2000] = _("Virtual")
    return [labels[sort] for sort in sorted(labels, reverse=True)]


def _floor_plan_entry(request, plan):
    """One plan as the index lists it, with the addresses of its picture."""
    site = plan["site"]
    svg = reverse(
        "plugins-api:network_map-api:floor-plan",
        kwargs={"slug": site.slug, "plan": plan["plan"]},
        request=request,
    )
    entry = {
        # A plan is named by its site, because several sites - and so several
        # plans - share a city, and only the site is named uniquely.
        "id": f"{site.slug}:{plan['plan']}",
        "kind": plan["kind"],
        # The plan the map shows when one zooms into the building, which is
        # what "first" asks for.
        "main": plan["main"],
        "label": plan["label"],
        "site": {
            "id": site.pk,
            "name": str(site.name),
            "slug": site.slug,
            # NetBox has no field for a city, so the place a site stands in is
            # the text its address or description carries.
            "address": str(site.physical_address or ""),
            "description": str(site.description or ""),
        },
        "machines": plan["machines"],
        "rooms": len([name for name in plan["rooms"] if name]),
        "floors": _floor_labels(plan),
        "picture": {"svg": svg, "png": f"{svg}?format=png"},
    }
    if plan["kind"] == "uploaded":
        entry["width"] = plan["width"]
        entry["height"] = plan["height"]
        entry["image"] = plan["url"]
    return entry


def _names_the_place(site, place):
    """Whether a site says it stands in the place one is looking for."""
    needle = str(place).casefold()
    return any(
        needle in str(field or "").casefold()
        for field in (site.physical_address, site.shipping_address, site.description)
    )


class FloorPlanIndexView(PictureAccessMixin, APIView):
    """
    Which floor plans exist: every uploaded house plan and, for every site the
    map places, the logical floor map built from its locations.
    """

    @extend_schema(
        tags=["network-map"],
        operation_id="floor_plan_list",
        summary="List the available floor plans",
        parameters=[
            OpenApiParameter(
                name="city",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Only the plans of sites whose address or description "
                    "mentions this place, whatever it is spelled as."
                ),
            ),
            OpenApiParameter(
                name="site",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only the plans of the site with this slug.",
            ),
            OpenApiParameter(
                name="kind",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["uploaded", "logical"],
                description="Only uploaded house plans, or only logical maps.",
            ),
        ],
    )
    def get(self, request):
        plans = _map_floor_plans()
        city = request.query_params.get("city")
        if city:
            # A city is not a field of its own on a site, so the place is read
            # out of the text that names where the site stands.
            plans = [p for p in plans if _names_the_place(p["site"], city)]
        site = request.query_params.get("site")
        if site:
            plans = [p for p in plans if p["site"].slug == site]
        kind = request.query_params.get("kind")
        if kind:
            plans = [p for p in plans if p["kind"] == kind]
        return Response(
            {
                "count": len(plans),
                "plans": [_floor_plan_entry(request, p) for p in plans],
            }
        )


class FloorPlanPictureView(PictureAccessMixin, APIView):
    """
    One site's floor plan as a picture: the uploaded house plan, with its bytes
    inside the document, or the logical map built from the site's locations.
    """

    renderer_classes = (SvgRenderer, PngRenderer)

    @extend_schema(
        tags=["network-map"],
        summary="Render one site's floor plan as SVG or PNG",
        parameters=[
            OpenApiParameter(
                name="slug",
                type=OpenApiTypes.STR,
                location="path",
                required=True,
                description="Which site: its unique slug.",
            ),
            OpenApiParameter(
                name="plan",
                type=OpenApiTypes.STR,
                location="path",
                required=False,
                description=(
                    "Which plan of that site: 'first' (the default, the one the "
                    "map shows), 'logical', or the number of an uploaded plan."
                ),
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
    def get(self, request, slug, plan="first"):
        site = Site.objects.filter(slug=slug).first()
        if site is None:
            return Response(f"No site with the slug {slug}", status=404)
        plans = [entry for entry in _map_floor_plans() if entry["site"].pk == site.pk]
        if not plans:
            return Response(f"Site {site.name} has no floor plan", status=404)
        if plan == "first":
            chosen = plans[0]
        else:
            chosen = next((entry for entry in plans if entry["plan"] == plan), None)
        if chosen is None:
            names = [entry["plan"] for entry in plans]
            if any(entry["kind"] == "uploaded" for entry in plans):
                names.insert(0, "first")
            return Response(
                f"Site {site.name} has no plan {plan}; it has {', '.join(names)}",
                status=404,
            )
        if chosen["kind"] == "logical":
            svg = floor_plan.render_logical(site.name, chosen["pins"], chosen["rooms"])
        else:
            svg = self._uploaded(site, chosen)
        if svg is None:
            return Response(f"The plan of {site.name} cannot be read", status=404)
        return Response(svg)

    @staticmethod
    def _uploaded(site, plan):
        """The uploaded picture, inlined when it is small enough to be."""
        try:
            with plan["attachment"].image.open("rb") as handle:
                payload = handle.read(floor_plan.MAX_EMBED_BYTES + 1)
        except (OSError, ValueError):
            return None
        mime = floor_plan.image_mime(payload)
        if len(payload) > floor_plan.MAX_EMBED_BYTES or mime is None:
            return floor_plan.render_uploaded(
                site.name,
                plan["url"],
                plan["width"],
                plan["height"],
                embedded=False,
            )
        return floor_plan.render_uploaded(
            site.name,
            floor_plan.data_url(payload, mime),
            plan["width"],
            plan["height"],
        )


class FloorPlanMainView(FloorPlanPictureView):
    """
    The plan the map itself shows for a site - its first upload, or its logical
    map when nothing was uploaded - without having to name the plan.
    """

    @extend_schema(
        tags=["network-map"],
        operation_id="floor_plan_main_retrieve",
        summary="Render the floor plan the map shows for a site",
        parameters=[
            OpenApiParameter(
                name="slug",
                type=OpenApiTypes.STR,
                location="path",
                required=True,
                description="Which site: its unique slug.",
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
    def get(self, request, slug):
        return super().get(request, slug, "first")
