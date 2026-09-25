# NetBox Network Map Plugin

Machines on a network map inside NetBox: a machine list, a VLAN connection tree,
a topology map and a geographic subnet map, each also handed out as a picture.
Some views are Swiss-centric - the map shows a canton and draws on swisstopo
tiles.

## Install

```bash
cd /opt/netbox/network_map_plugin
/opt/netbox/venv/bin/python -m pip install --editable . --no-deps
```

The pages live under `/plugins/networkmap/` (`vlan-list/`, `vlan-topology/`,
`vlan-connections/`, `subnet-map/`, `coverage/`) and are linked from the NetBox
menu. In production, collect static files before restarting.

## Testing

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py test network_map
```

Where the database role may not create databases, copy
`netbox/configuration.py` to `netbox/configuration_testing.py`, set
`DEBUG = False`, add `'TEST': {'NAME': 'netbox'}` to the default database entry,
and run the same command with `NETBOX_CONFIGURATION=netbox.configuration_testing`
and `--keepdb`.

## Picture API

The kind of picture stands in the path, its format on the query string -
`?format=svg` (the default) or `?format=png`.

| Kind         | URL                                    |
| ------------ | -------------------------------------- |
| Machine list | `/api/plugins/networkmap/machine-list` |
| Logical map  | `/api/plugins/networkmap/logical-map`  |
| Subnet map   | `/api/plugins/networkmap/subnet-map`   |
| Topology map | `/api/plugins/networkmap/topology`     |

```bash
curl -H "Authorization: Token <token>" \
  "https://netbox.example.com/api/plugins/networkmap/topology?format=png" \
  -o topology.png
```

- Needs the `network_map.view_vlanelement` permission.
- A PNG needs a rasteriser on the server: `cairosvg` (the plugin's `png` extra)
  or ImageMagick. Without either the request answers 501; a picture too big for
  the rasteriser comes out smaller instead of failing.
- The subnet map puts every map tile it fetches into the document as a data URL,
  which is what makes it big: the canton of Bern as it stands in this NetBox
  measures about 1.8 MB as SVG and 3.8 MB as PNG, against 0.5 MB and 0.4 MB with
  `?background=0`, which leaves the ground out.
- Building the subnet map geocodes every Site that has no coordinates yet - one
  Nominatim lookup each, whose result is saved back on the Site - so this GET
  writes to the database.
- `/api/plugins/networkmap/` links these addresses, and the schema lists them
  under the `network-map` tag.

### Floor plans

A floor plan is asked for by its site, because several buildings stand in one
city and only the site is named uniquely. `/floor-plans/` lists what exists,
and each plan is then drawn by its own address:

| URL                                                | Answers                                       |
| -------------------------------------------------- | --------------------------------------------- |
| `/api/plugins/networkmap/floor-plans/`             | JSON `{"count", "city", "site", "plans"}`; the two filters are echoed back, and each plan carries a `city` read off its address |
| `/api/plugins/networkmap/floor-plan/<site-slug>/`  | the site's logical floor map, as SVG or PNG   |

```bash
curl -H "Authorization: Token <token>" \
  "https://netbox.example.com/api/plugins/networkmap/floor-plans/?city=Bern"
curl -H "Authorization: Token <token>" \
  "https://netbox.example.com/api/plugins/networkmap/floor-plan/sample-site/" \
  -o floor-plan.svg
```

- The plan of a site is its logical floor map, built from the site's locations
  and named by the site's slug alone; a site whose machines the map places has
  a plan, every other address is answered 404.
- `?city=` reads the place out of the site name, physical address, shipping
  address or description, which is where NetBox keeps it; `?site=` takes the
  site's slug.
- The answer echoes the `city` and `site` it filtered by (null when not given),
  and every plan carries its own `city`, read off its address whether the place
  stands before the street (`Bern, Musterweg 5`) or after a postal code
  (`Musterweg 5, 3000 Bern`).
- The plan carries its machines the way the browser export of the map does:
  every dot is numbered in the machine's colour, virtual ones hollow, and under
  the picture the machines are listed with their name, description and address.
- The map is built from the site's locations, floor by floor, and carries the
  same colour key as the map page; the `network_map.floor_plan` module and
  `subnet_map.js` hold the same measurements, which `FloorPlanParityTests`
  checks.

## Data Coverage

`/plugins/networkmap/coverage/` is a read-only map-readiness report. It checks
whether the NetBox data behind the existing maps is complete enough to draw
useful pictures, without geocoding or saving anything while the page is opened.

The first report covers:

- sites with machines but missing coordinates or an unknown city,
- VLANs without prefixes and prefixes without active/reserved IP addresses,
- IP addresses with missing or blank DNS names,
- machines without a site or without a room for floor plans,
- locations whose floor cannot be inferred from the room name,
- gateway-tag problems for the logical connection view.

## Configuration

```python
PLUGINS_CONFIG = {
    "network_map": {
        "gateway_search_tag": "GATEWAY-TAG",
        "canton_boundary_code": "BE",
    },
}
```

- `gateway_search_tag`: the device tag the Vlan-Connections view uses to find the
  central gateway object.
- `canton_boundary_code`: the canton whose border the Subnet-Map draws, as a
  two-letter code (`"BE"`, which is also the default) or a BFS id; `"CH"` or
  `"SW"` draws the national border in its place, and `""` draws none.

<details>
<summary>Advanced settings</summary>

All of these go in the same `PLUGINS_CONFIG` dictionary.

Geocoding, for a site that has no coordinates yet: `nominatim_url` (defaults to
OpenStreetMap's service), `country_codes` (`"ch"`), `request_interval_seconds`
(`1.0`), `request_timeout_seconds` (`10`).

Canton border, tried in that order until one answers - the geometry is fetched
live and cached, and the map renders without a border when none can be had:
`canton_boundary_url_template` (swisstopo WFS, `{id}` the BFS id; preferred
because it carries interior rings, which keeps canton pockets such as Steinhof
SO, so leave `srsName=EPSG%3A4326` in it),
`canton_boundary_fallback_url_template` (Nominatim, `{code}` as `CH-BE`, also
carrying holes), `canton_boundary_last_resort_url_template` (`map.geo.admin.ch`,
without holes), `canton_boundary_cache_seconds` (30 days) and
`canton_boundary_label` (legend text, the canton name by default). The geometry
is also served on its own at `/plugins/networkmap/subnet-map/canton-boundary/`.

</details>

### Map background

The served subnet map stands on the same swisstopo tiles, in the same LV03 grid,
as the page's own map, which is why the two show the same ground. Tiles are
fetched side by side and cached, so the first caller pays for a canton, and a
tile that cannot be had simply stays out of the picture.

| Setting                   | Default                                    | Meaning                                               |
| ------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| `map_background`          | `True`                                     | Draw tiles behind the served subnet map.              |
| `map_tile_url_template`   | swisstopo `pixelkarte-farbe`, `21781` grid | Tile address; `{z}/{y}/{x}` are zoom, row and column. |
| `map_tile_zoom`           | chosen from the picture                    | Force one zoom instead of the fitting one.            |
| `map_tile_max`            | `64`                                       | Tiles per picture; the zoom comes down to pay for it. |
| `map_tile_cache_seconds`  | 30 days                                    | How long a tile is kept.                              |
| `map_tile_budget_seconds` | `20`                                       | What one picture waits for its tiles, all together.   |
| `map_attribution`         | empty                                      | Credit under the picture, if the source wants naming. |

A different source has to answer in the LV03 grid, which leaves mirrors of the
swisstopo tiles rather than OpenStreetMap.

### Room around the border

Two distances decide where a picture ends. The cut runs `map_border_cut` pixels
beyond the border, so a band of the neighbouring ground stays in the picture
instead of the picture ending on the line; `0` cuts on the line. And the border
keeps `map_border_room` pixels between itself and the edge of the picture, because
an area touches its own bounding box at a point - west of Geneva, south of Ticino
- which is where a tight frame used to cut the line off. The left and the bottom
edges add their own room to that.

| Setting           | Default | Meaning                                       |
| ----------------- | ------- | --------------------------------------------- |
| `map_border_cut`  | `3`     | How far beyond the border the picture is cut. |
| `map_border_room` | `22`    | Room between the border and the edge.         |
| `map_room_left`   | `20`    | Room the left edge adds to that.              |
| `map_room_bottom` | `20`    | Room the bottom edge adds to that.            |

They are pixels of the picture and go in the same `PLUGINS_CONFIG` dictionary.
Both pictures obey them, the served one and the one the page's export button
makes, so the two never disagree about what belongs in them. A restart is needed,
and a page already open has to be reloaded, because it carries the numbers it was
served.

Should the cantonal boundary become a rectangle with a rectangular cutout that is roughly centered on Basel, this is a problem with Netbox - you will need to restart netbox.

## Code structure

| File                                   | Purpose                                                            |
| -------------------------------------- | ------------------------------------------------------------------ |
| `models.py`                            | The `VlanElement` anchor model and the dataclasses the views fill. |
| `views.py`                             | The plugin pages: collecting what to show and handing it to the browser. |
| `urls.py`, `navigation.py`             | The page routes and the NetBox menu entries.                       |
| `__init__.py`, `defaults.py`           | Plugin registration, version, and the settings with their defaults. |
| `colors.py`                            | The location colour palette and the shades drawn from it.          |
| `places.py`                            | Reading the city/place out of site names and addresses.            |
| `coverage.py`                          | Read-only map-readiness checks for the Data Coverage page.         |
| `lv03.py`                              | WGS84 to LV03 conversion and the swisstopo tile-grid maths.         |
| `geocoding.py`                         | Nominatim lookup for Sites that have no coordinates yet.           |
| `swisstopo.py`                         | Fetching the canton border, with fallbacks, from public services.  |
| `map_tiles.py`                         | Fetching and caching the swisstopo tiles a served map stands on.   |
| `svg_render/`                          | Package entry re-exporting the server-side SVG renderers.          |
| `svg_render/base.py`                   | Shared SVG primitives: text helpers, wrapping, and shared styles.  |
| `svg_render/machine_list.py`           | Machine-list picture rendering.                                    |
| `svg_render/logical_tree.py`           | Logical VLAN connection tree rendering.                            |
| `svg_render/topology.py`               | Topology map rendering.                                            |
| `svg_render/subnet_map.py`             | Geographic subnet map rendering, border framing, and tiles.        |
| `floor_plan.py`                        | Drawing a site's logical floor plan.                               |
| `png_render.py`                        | Rasterising a served SVG to PNG with cairosvg or ImageMagick.      |
| `api/views.py`                         | The picture and floor-plan endpoints and their permission gate.    |
| `api/urls.py`                          | The API routes, with the path parts constrained by regex.          |
| `templatetags/network_map_static.py`   | The `static_url` tag keeping cached scripts honest.                |
| `templates/network_map/*.html`         | The pages' markup, data included as JSON.                          |
| `templates/network_map/includes/`      | `_info_item.html`, a detail-panel row of the connection page.      |
| `static/network_map/shared/`           | `svg_export.js`, the browser's own picture export.                 |
| `static/network_map/data_coverage/`    | Styles for the Data Coverage page.                                 |
| `static/network_map/subnet_map/`       | Subnet-map script and styles, plus the generated LV03 grid.        |
| `static/network_map/vlan_connection/`  | Styles for the VLAN connection page.                               |
| `static/network_map/vlan_element_list/`| Styles for the machine list page.                                  |
| `static/network_map/vlan_topology/`    | Topology-map script and styles.                                    |
| `static/network_map/vendor/leaflet/`   | The vendored Leaflet library the subnet map runs on.               |
| `migrations/`                          | Django's record of the model's state.                              |
| `locale/<lang>/LC_MESSAGES/`           | The German and French catalogs, compiled `.mo` included.           |
| `tests/`                               | The split test suite, run as described under Testing.              |

## Releases

`__version__` in `network_map/__init__.py` is the only place the version is
written; a new NetBox release needs `min_version`/`max_version` widened there, or
NetBox disables the plugin.

## Translations

Catalogs are `network_map/locale/<lang>/LC_MESSAGES/django.po` (`de`, `fr`); the
compiled `.mo` is committed because this tree does not compile it. After changing
strings, fill in the new `msgstr` values and rebuild:

```bash
cd /opt/netbox/network_map_plugin
DJANGO_SETTINGS_MODULE=netbox.settings PYTHONPATH=/opt/netbox/netbox \
  /opt/netbox/venv/bin/django-admin makemessages -l de -l fr --keep-pot
for lang in de fr; do
  msgfmt --check -o network_map/locale/$lang/LC_MESSAGES/django.mo \
    network_map/locale/$lang/LC_MESSAGES/django.po
done
```

`--keep-pot` keeps the master catalog `makemessages` would delete after merging;
`--all` is unusable here because it pulls in NetBox's own language list.
