from collections import OrderedDict

from dcim.models import Site
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from .. import floor_plan, map_tiles, png_render, svg_render
from ..defaults import canton_code
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
            return markup.encode("utf-8")
        try:
            return png_render.render_png(markup)
        except png_render.PngRenderError as error:
            raise PngRenderFailed(
                "Could not rasterise this picture; "
                "Try ?format=svg, for which no rasteriser is needed."
            ) from error


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
            # The same picture as a raster, which the page's export button also hands out.
            entries[f"{kind}.png"] = f"{url}?format=png"
        # Which plans exist is worth knowing first: a city holds several buildings.
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
        # A PNG needs a rasteriser installed besides the plugin; nothing here draws SVG itself.
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
            code = canton_code()
            boundary = get_canton_boundary(code)
            svg = svg_render.render_subnet_map(
                map_data,
                boundary,
                get_canton_label(code) if boundary else None,
                tiles_of=(
                    map_tiles.background if self._wants_background(request) else None
                ),
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


def _place_in(text):
    """
    The place out of one line of text, or nothing. A place names itself with
    letters and no house number, whether it stands before the street ("Bern,
    Nordring 30") or after a postal code ("Nordring 30, 3000 Bern"); the segment
    that carries no number - a leading postal code dropped - is the place.
    """
    segments = [seg.strip() for seg in str(text or "").split(",") if seg.strip()]
    for segment in segments:
        if not any(word.isdigit() for word in segment.split()):
            return segment
    for segment in reversed(segments):
        words = segment.split()
        if words and words[0].isdigit():
            return " ".join(words[1:])
    return ""


def _site_city(site):
    """
    The place a site is in. NetBox keeps no city of its own, so it is read off
    wherever the site names it - the physical address, the shipping address, or,
    as many sites do, the site's own name "Bern, Nordring 30" - and the first of
    these that holds a place wins; a site that names none gives "".
    """
    for text in (site.physical_address, site.shipping_address, site.name):
        city = _place_in(text)
        if city:
            return city
    return ""


def _floor_plan_entry(request, plan):
    """One plan as the index lists it, with the addresses of its picture."""
    site = plan["site"]
    svg = reverse(
        "plugins-api:network_map-api:floor-plan",
        kwargs={"slug": site.slug},
        request=request,
    )
    return {
        # Several buildings share a city, so only the site names a plan apart.
        "id": site.slug,
        "city": _site_city(site),
        "site": {
            "id": site.pk,
            "name": str(site.name),
            "slug": site.slug,
            # NetBox has no city field; the place is the text in the name or address.
            "address": str(site.physical_address or ""),
            "description": str(site.description or ""),
        },
        "machines": plan["machines"],
        "rooms": len([name for name in plan["rooms"] if name]),
        "picture": {"svg": svg, "png": f"{svg}?format=png"},
    }


def _names_the_place(site, place):
    """Whether a site says it stands in the place one is looking for."""
    needle = str(place).casefold()
    return any(
        needle in str(field or "").casefold()
        for field in (
            site.physical_address,
            site.shipping_address,
            site.description,
            site.name,
        )
    )


class FloorPlanIndexView(PictureAccessMixin, APIView):
    """
    Which floor plans exist: for every site the map places, the logical floor
    map built from its locations.
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
                    "Only the plans of sites whose name, address or description "
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
        ],
    )
    def get(self, request):
        plans = _map_floor_plans()
        city = request.query_params.get("city")
        if city:
            # The place is read out of the text that names where the site stands.
            plans = [p for p in plans if _names_the_place(p["site"], city)]
        site = request.query_params.get("site")
        if site:
            plans = [p for p in plans if p["site"].slug == site]
        return Response(
            {
                "count": len(plans),
                # The filters as they were asked for, so a caller sees what was applied.
                "city": city,
                "site": site,
                "plans": [_floor_plan_entry(request, p) for p in plans],
            }
        )


class FloorPlanPictureView(PictureAccessMixin, APIView):
    """
    One site's floor plan as a picture: the logical map built from the site's
    locations, with its machines dotted through the rooms and listed under it.
    """

    renderer_classes = (SvgRenderer, PngRenderer)

    @extend_schema(
        tags=["network-map"],
        operation_id="floor_plan_retrieve",
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
        site = Site.objects.filter(slug=slug).first()
        if site is None:
            return Response(f"No site with the slug {slug}", status=404)
        plan = next(
            (entry for entry in _map_floor_plans() if entry["site"].pk == site.pk),
            None,
        )
        if plan is None:
            return Response(f"Site {site.name} has no floor plan", status=404)
        svg = floor_plan.render_logical(site.name, plan["pins"], plan["rooms"])
        if svg is None:
            return Response(f"The plan of {site.name} cannot be read", status=404)
        return Response(svg)
