# NetBox Network Map Plugin

Machines on a network map inside NetBox: a machine list, a VLAN connection tree,
a topology map and a geographic subnet map, each also handed out as a picture.
Some views are Swiss-centric - the map shows a canton and draws on swisstopo
tiles.

## Requirements

- NetBox 4.5 - 4.7
- Python 3.12+

## Install

Install the wheel into NetBox's virtualenv. Add the `png` extra if the instance
should answer `?format=png` through `cairosvg` (ImageMagick on the server works
instead and needs no extra):

```bash
/opt/netbox/venv/bin/python -m pip install "netbox-plugin-network-map-yativilli[png]"
```

## Enable

Add the plugin to `netbox/netbox/configuration.py`:

```python
PLUGINS = ["network_map"]
```

Apply the migrations, collect the static files, and restart NetBox (and its RQ
workers, if it has them):

```bash
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input
```

The pages live under `/plugins/networkmap/` and are linked from the NetBox menu.

## Configuration

All options go under `network_map` in `PLUGINS_CONFIG` in the same file. The two
that most installs set are the gateway tag and the canton to draw:

```python
PLUGINS_CONFIG = {
    "network_map": {
        "gateway_search_tag": "GATEWAY-TAG",
        "canton_boundary_code": "BE",
    },
}
```

| Setting                 | Default        | Meaning                                                                      |
| ----------------------- | -------------- | ---------------------------------------------------------------------------- |
| `gateway_search_tag`    | `"GATEWAY-TAG"` | Device tag the VLAN-Connections view uses to find the central gateway object. |
| `canton_boundary_code`  | `"BE"`         | Canton whose border the subnet map draws: a two-letter code or a BFS id. `"CH"` or `"SW"` draws the national border, `""` draws none. |

Every other setting has a working default - change them only to point the map at
a different tile source, tune the picture frame, or adjust the outside requests.

<details>
<summary>Optional settings</summary>

Map background - the ground the served subnet map stands on:

| Setting                            | Default                 | Meaning                                              |
| ---------------------------------- | ----------------------- | ---------------------------------------------------- |
| `map_background`                   | `True`                  | Draw tiles behind the served subnet map.             |
| `map_background_source`            | `"SWISSTOPO"`           | `"SWISSTOPO"` or `"OSM"`.                            |
| `map_tile_url_template`            | the named source's      | Tile address, in the grid of whoever is named.       |
| `map_tile_fallback`                | empty                   | Second source asked for a tile the first lacks.      |
| `map_tile_fallback_url_template`   | the second source's     | That source's tile address.                          |
| `map_tile_zoom`                    | chosen from the picture | Force one zoom instead of the fitting one.           |
| `map_tile_max`                     | `64`                    | Tiles per picture; the zoom comes down to pay for it. |
| `map_tile_cache_seconds`           | 30 days                 | How long a tile is kept.                             |
| `map_tile_budget_seconds`          | `20`                    | What one picture waits for its tiles, all together.  |
| `map_attribution`                  | what the source asks    | Credit under the picture, naming the ground.         |

Picture frame - where a picture ends relative to the canton border:

| Setting           | Default | Meaning                                       |
| ----------------- | ------- | --------------------------------------------- |
| `map_border_cut`  | `3`     | How far beyond the border the picture is cut. |
| `map_border_room` | `22`    | Room between the border and the edge.         |
| `map_room_left`   | `20`    | Room the left edge adds to that.              |
| `map_room_bottom` | `20`    | Room the bottom edge adds to that.            |

Geocoding - for a site that has no coordinates yet:

| Setting                     | Default                 | Meaning                       |
| --------------------------- | ----------------------- | ----------------------------- |
| `nominatim_url`             | OpenStreetMap's service | Geocoder to ask.              |
| `country_codes`             | `"ch"`                  | Country to bias the lookup to. |
| `request_interval_seconds`  | `1.0`                   | Wait between lookups.         |
| `request_timeout_seconds`   | `10`                    | Timeout for one lookup.       |

Canton border - tried in that order until one answers; the geometry is fetched
live and cached, and the map renders without a border when none can be had:

| Setting                                     | Default             | Meaning                                    |
| ------------------------------------------- | ------------------- | ------------------------------------------ |
| `canton_boundary_url_template`              | swisstopo WFS       | Preferred source (`{id}` the BFS id).      |
| `canton_boundary_fallback_url_template`     | Nominatim           | Fallback (`{code}` as `CH-BE`).            |
| `canton_boundary_last_resort_url_template`  | map.geo.admin.ch    | Last resort.                               |
| `canton_boundary_cache_seconds`             | 30 days             | How long the border is kept.               |
| `canton_boundary_label`                     | the canton name     | Legend text under the picture.             |

</details>

## PNG rendering

`?format=png` needs a rasteriser on the server: `cairosvg` (the plugin's `png`
extra) or ImageMagick. Without either, the request answers `501`.
