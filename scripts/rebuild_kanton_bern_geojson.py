#!/usr/bin/env python3
"""Rebuild the Canton Bern boundary GeoJSON used by the network map plugin.

Output: network_map/static/network_map/kanton_bern.geojson
(WGS84 / EPSG:4326 MultiPolygon, main ring + Münchenwiler exclave + holes)

Sources, tried in order (override with --source):

1. wfs  Federal: swisstopo WFS, layer
        ch.swisstopo.swissboundaries3d-kanton-flaeche.fill (official
        swissBOUNDARIES3D boundary data). Requires the swisstopo WFS host
        to be reachable; try --wfs-url if the defaults are stale.
2. osm  Overpass API, OSM relation 1686344 (Kanton Bern). The OSM canton
        borders are survey-derived from swisstopo data; this is the
        fallback that was used to build the current file. Small gaps that
        OSM leaves in lake/river sections are chord-bridged (the script
        reports each one).

Only the Python standard library is used (tested on Python 3.9+).

Examples:
    python3 scripts/rebuild_kanton_bern_geojson.py
    python3 scripts/rebuild_kanton_bern_geojson.py --source osm
    python3 scripts/rebuild_kanton_bern_geojson.py --dry-run
"""

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET  # nosec B405 - only trusted WFS responses are parsed

RELATION_ID = 1686344
LAYER_BFS_NO = 36

OUT_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir,
        "network_map",
        "static",
        "network_map",
        "kanton_bern.geojson",
    )
)

WFS_BASE_URLS = [
    "https://wfs.geo.admin.ch/geoserver/ows",
    "https://api3.geo.admin.ch/ogc/wfs",
]
WFS_TYPENAMES = [
    "ch.swisstopo.swissboundaries3d-kanton-flaeche.fill",
    "ch.swisstopo.swissboundaries3d-kanton-flaeche.fill__6",
]
WFS_CRS84 = "urn:ogc:def:crs:OGC:1.3:CRS84"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# plausibility limits for the whole canton (WGS84 degrees / km^2)
BBOX_LIMITS = (5.5, 45.5, 11.5, 48.5)
AREA_LIMITS = (5700, 6200)

USER_AGENT = "network_map_plugin kanton_bern rebuilder/1.0"


def fetch(url, data=None, timeout=120, accept=None, tries=2):
    """GET (or POST when data is given) with retries; returns bytes."""
    last_error = None
    for attempt in range(1, tries + 1):
        request = urllib.request.Request(url, data=data)
        request.add_header("User-Agent", USER_AGENT)
        if accept:
            request.add_header("Accept", accept)
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(  # nosec B310 - fixed https endpoints
                request, timeout=timeout, context=context
            ) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 - reported to the user
            last_error = error
            if attempt < tries:
                print(f"  retrying {url} ({error})", file=sys.stderr)
                time.sleep(3)
    raise RuntimeError(f"{url}: {last_error}")


def rings_to_multipolygon(outer_rings, inner_rings):
    """Assign holes to the outer ring that contains them (bbox based,
    which is sufficient for the canton's exclaves/enclaves)."""

    def bbox(ring):
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return min(xs), min(ys), max(xs), max(ys)

    polygons = []
    total_area = 0.0
    for ring in sorted(outer_rings, key=approx_area_km2, reverse=True):
        outer_box = bbox(ring)
        holes = []
        for hole in inner_rings:
            hole_box = bbox(hole)
            if (
                outer_box[0] <= hole_box[0]
                and outer_box[1] <= hole_box[1]
                and hole_box[2] <= outer_box[2]
                and hole_box[3] <= outer_box[3]
            ):
                holes.append(hole)
        rings = [[[round(c, 6), round(p, 6)] for c, p in ring]]
        rings += [[[round(c, 6), round(p, 6)] for c, p in hole] for hole in holes]
        total_area += approx_area_km2(ring) - sum(approx_area_km2(h) for h in holes)
        polygons.append(rings)
    return polygons, total_area


def approx_area_km2(ring):
    """Shoelace on a local equirectangular plane; ~0.5% accurate,
    sufficient for the sanity check."""
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx = 111.320 * math.cos(math.radians(lat0))
    ky = 110.574
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = (ring[i][0] - ring[0][0]) * kx, (ring[i][1] - ring[0][1]) * ky
        x2, y2 = (ring[i + 1][0] - ring[0][0]) * kx, (ring[i + 1][1] - ring[0][1]) * ky
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def validate(multipolygon):
    if not multipolygon:
        raise ValueError("no polygons produced")
    all_outer = [polygon[0] for polygon in multipolygon]
    for ring in all_outer:
        if ring[0] != ring[-1]:
            raise ValueError("outer ring not closed")
        if len(ring) < 4:
            raise ValueError(f"degenerate ring with {len(ring)} points")
    xs = [p[0] for r in all_outer for p in r]
    ys = [p[1] for r in all_outer for p in r]
    box = (min(xs), min(ys), max(xs), max(ys))
    limits = BBOX_LIMITS
    if not (
        limits[0] <= box[0]
        and limits[1] <= box[1]
        and box[2] <= limits[2]
        and box[3] <= limits[3]
    ):
        raise ValueError(f"bbox {box} outside plausible limits {limits}")
    area = sum(approx_area_km2(r) for r in all_outer)
    if not AREA_LIMITS[0] <= area <= AREA_LIMITS[1]:
        raise ValueError(f"area {area:.1f} km^2 outside plausible limits {AREA_LIMITS}")
    return box, area


def write_geojson(polygons, source_label, dry_run=False):
    feature_collection = {
        "type": "FeatureCollection",
        "name": "kanton_bern",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Kanton Bern",
                    "source": source_label,
                },
                "geometry": {"type": "MultiPolygon", "coordinates": polygons},
            }
        ],
    }
    payload = json.dumps(feature_collection, separators=(",", ":"))
    if dry_run:
        print(f"dry run: {len(polygons)} polygons, {len(payload)} bytes")
        return
    temp_path = OUT_PATH + ".tmp"
    with open(temp_path, "w") as handle:
        handle.write(payload)
    os.replace(temp_path, OUT_PATH)
    print(f"wrote {OUT_PATH} ({len(polygons)} polygons, {len(payload)} bytes)")


# ---------------------------------------------------------------- WFS ----


def _localname(tag):
    return tag.rsplit("}", 1)[-1]


def _ring_from(node):
    for element in node.iter():
        if _localname(element.tag) == "posList" and element.text:
            values = [float(v) for v in element.text.split()]
            points = [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]
            if points and points[0] != points[-1]:
                points.append(points[0])
            return points or None
    return None


def parse_gml_multipolygon(payload):
    """Extract [(exterior, [interiors]), ...] polygons from a WFS GML
    response (MultiSurface/Surface/Polygon, gml:posList, lon lat order
    requested via CRS84)."""
    root = ET.fromstring(payload)  # nosec B314 - trusted swisstopo WFS response
    polygons = []
    for surface in root.iter():
        if _localname(surface.tag) not in ("Polygon", "Surface"):
            continue
        exterior = None
        interiors = []
        for node in surface.iter():
            name = _localname(node.tag)
            if name in ("exterior", "outerBoundaryIs"):
                ring = _ring_from(node)
                if ring is not None and exterior is None:
                    exterior = ring
            elif name in ("interior", "innerBoundaryIs"):
                ring = _ring_from(node)
                if ring is not None:
                    interiors.append(ring)
        if exterior:
            polygons.append((exterior, interiors))
    return polygons


def from_wfs(base_url_override=None):
    urls = [base_url_override] if base_url_override else WFS_BASE_URLS
    for base_url in urls:
        for typename in WFS_TYPENAMES:
            query = urllib.parse.urlencode(
                {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": typename,
                    "srsName": WFS_CRS84,
                    "CQL_FILTER": f"bfs_no={LAYER_BFS_NO}",
                    "count": "1",
                }
            )
            url = f"{base_url}?{query}"
            print(f"trying WFS: {url}")
            try:
                payload = fetch(url, timeout=60, accept="application/gml+xml, text/xml")
            except Exception as error:  # noqa: BLE001
                print(f"  failed: {error}", file=sys.stderr)
                continue
            if b"Exception" in payload[:2000] and b"ServiceException" in payload[:2000]:
                reason = payload[:400].decode("utf-8", "replace")
                print(f"  WFS exception: {reason[:200]} ...", file=sys.stderr)
                continue
            try:
                polygons = parse_gml_multipolygon(payload)
            except ET.ParseError as error:
                print(f"  unparseable response: {error}", file=sys.stderr)
                continue
            outer = [poly[0] for poly in polygons]
            inner = [ring for poly in polygons for ring in poly[1]]
            if not outer:
                print("  no polygons in response", file=sys.stderr)
                continue
            return outer, inner, f"swisstopo WFS {typename}"
    return None


# ----------------------------------------------------------------- OSM ----


def fetch_relation():
    data = f"[out:json][timeout:60];rel({RELATION_ID});out geom;".encode()
    last_error = None
    for endpoint in OVERPASS_ENDPOINTS:
        print(f"fetching OSM relation {RELATION_ID} from {endpoint}")
        try:
            payload = fetch(endpoint, data=data, timeout=180)
            return json.loads(payload.decode("utf-8"))
        except Exception as error:  # noqa: BLE001
            last_error = error
            print(f"  failed: {error}", file=sys.stderr)
    raise RuntimeError(f"all Overpass endpoints failed: {last_error}")


def stitch(segments, label):
    """Join way segments head-to-tail into closed rings; unclosed rings
    are chord-bridged with a warning."""
    remaining = list(segments)
    rings = []
    while remaining:
        current = list(remaining.pop(0))
        if current[0] == current[-1]:
            rings.append(current)
            continue
        while True:
            head, tail = current[0], current[-1]
            found = None
            for index, other in enumerate(remaining):
                if other[-1] == head:
                    current = other[:-1][::-1] + current
                    found = index
                elif other[0] == head:
                    current = other[1:] + current
                    found = index
                elif other[0] == tail:
                    current = current + other[1:]
                    found = index
                elif other[-1] == tail:
                    current = current + other[::-1][1:]
                    found = index
                if found is not None:
                    break
            if found is None or current[0] == current[-1]:
                break
            remaining.pop(found)
        if current[0] != current[-1]:
            gap = math.hypot(
                (current[-1][0] - current[0][0]) * 65.0,
                (current[-1][1] - current[0][1]) * 111.0,
            )
            print(
                f"  warning: {label} ring left open with a {gap:.2f} km gap; "
                "bridged with a straight line (OSM has no boundary "
                "segment there, usually a lake)",
                file=sys.stderr,
            )
            current = current + [current[0]]
        rings.append(current)
    return rings


def from_osm():
    relation_data = fetch_relation()
    segments = {"outer": [], "inner": []}
    for member in relation_data["elements"]:
        if member.get("type") != "relation":
            continue
        for item in member.get("members", []):
            role = item.get("role") or "outer"
            geometry = item.get("geometry")
            if item.get("type") == "way" and role in ("outer", "inner") and geometry:
                segments[role].append(
                    [(point["lon"], point["lat"]) for point in geometry]
                )
    if not segments["outer"]:
        raise RuntimeError(f"relation {RELATION_ID} returned no outer ways")
    outer = stitch(segments["outer"], "outer")
    inner = stitch(segments["inner"], "inner")
    outer = [r for r in outer if len(r) >= 4]
    inner = [r for r in inner if len(r) >= 4]
    return outer, inner, f"OSM relation {RELATION_ID} (Overpass)"


# ------------------------------------------------------------- main ----


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        choices=("auto", "wfs", "osm"),
        default="auto",
        help="boundary source (default: auto)",
    )
    parser.add_argument("--wfs-url", help="override the swisstopo WFS base URL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and validate, but do not write the file",
    )
    args = parser.parse_args()

    sources = {"auto": ("wfs", "osm"), "wfs": ("wfs",), "osm": ("osm",)}[args.source]
    used = None
    for source in sources:
        try:
            if source == "wfs":
                used = from_wfs(args.wfs_url)
            else:
                used = from_osm()
        except Exception as error:  # noqa: BLE001
            print(f"{source} source failed: {error}", file=sys.stderr)
        if used:
            break
    if not used:
        print("no source succeeded", file=sys.stderr)
        return 1

    outer_rings, inner_rings, label = used
    polygons, total_area = rings_to_multipolygon(outer_rings, inner_rings)
    box, area = validate(polygons)
    print(f"source: {label}")
    print(
        f"polygons: {len(polygons)}, total area ~{area:.1f} km^2, "
        f"bbox: {tuple(round(v, 3) for v in box)}"
    )
    if total_area == 0:
        raise SystemExit("empty result")
    write_geojson(polygons, label, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
