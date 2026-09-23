# NetBox Network Map Plugin

Machines on a network map inside NetBox: a machine list, a VLAN connection tree,
a topology map and a geographic subnet map, each also handed out as a picture.
Some views are Swiss-centric - the map shows a canton and draws on swisstopo
tiles.

## Install

```bash
cd /opt/netbox/network_map_plugin/network_map
/opt/netbox/venv/bin/python -m pip install --editable . --no-deps
```

The pages live under `/plugins/networkmap/` (`vlan-list/`, `vlan-topology/`,
`vlan-connections/`, `subnet-map/`) and are linked from the NetBox menu. In
production, collect static files before restarting.

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
| `map_border_cut`  | `10`    | How far beyond the border the picture is cut. |
| `map_border_room` | `22`    | Room between the border and the edge.         |
| `map_room_left`   | `20`    | Room the left edge adds to that.              |
| `map_room_bottom` | `20`    | Room the bottom edge adds to that.            |

They are pixels of the picture and go in the same `PLUGINS_CONFIG` dictionary.
Both pictures obey them, the served one and the one the page's export button
makes, so the two never disagree about what belongs in them. A restart is needed,
and a page already open has to be reloaded, because it carries the numbers it was
served.

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
