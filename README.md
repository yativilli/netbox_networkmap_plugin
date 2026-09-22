# NetBox Network Map Plugin

A plugin for NetBox to display machines on a network map.
It was developed as a short-term project to improve a companies overview of their installed machines.
The company is from switzerland, therefore some of the views (esp. Map-View) are swiss-centric.

## Development

The plugin is installed from this directory in editable mode. This means that
Python code and templates are read from the working tree, but package metadata
changes still require reinstalling the plugin.

From the plugin directory, run:

```bash
cd /opt/netbox/network_map_plugin/network_map
/opt/netbox/venv/bin/python -m pip install --editable . --no-deps
```

Restart the NetBox service after changing Python code, templates, static files,
or plugin configuration. For local development, run:

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py runserver
```

The plugin is available at `/networkmap/`.

Before restarting NetBox, check that the plugin loads correctly:

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py check
```

## Testing

The test suite runs inside a NetBox installation and needs a PostgreSQL user
with the `CREATEDB` privilege, so it can build a disposable `test_netbox`
database:

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py test network_map
```

This is exactly what CI does (see `.github/workflows/ci.yml`, which runs the
tests against every supported NetBox version plus the newest release).

On machines whose database role lacks `CREATEDB` (e.g. this development box),
the suite can instead reuse the existing database: copy
`netbox/netbox/configuration.py` to `configuration_testing.py` in the same
directory, set `DEBUG = False`, and add `'TEST': {'NAME': 'netbox'}` to the
default database entry. The tests wrap everything in transactions and roll
back, so no data is changed:

```bash
cd /opt/netbox/netbox
NETBOX_CONFIGURATION=netbox.configuration_testing \
  /opt/netbox/venv/bin/python manage.py test network_map --keepdb
```

## SVG API Endpoints

The four map views are also served as server-side rendered SVG (no
`foreignObject`/HTML, so they open in any picture viewer). NetBox API token
authentication applies, and the caller needs the `network_map.view_vlanelement`
permission like for the web views:

| Kind            | URL                                              |
| --------------- | ------------------------------------------------ |
| Machine list    | `/api/plugins/networkmap/svg/machine-list/`      |
| Logical map     | `/api/plugins/networkmap/svg/logical-map/`       |
| Subnet map      | `/api/plugins/networkmap/svg/subnet-map/`        |
| Topology map    | `/api/plugins/networkmap/svg/topology/`          |

```bash
curl -H "Authorization: Token <token>" \
  https://netbox.example.com/api/plugins/networkmap/svg/topology/ -o topology.svg
```

The renderers live in `network_map/svg_render.py` and mirror the browser
exports; text wrapping uses a character-width estimate, so line breaks can
differ slightly from the on-page "Export as .SVG" buttons.

The subnet map is drawn geographically: pins are grouped per site, and the
extent is the bounding box of the configured `canton_boundary_code` border so
exports stay comparable. Sites outside that border are clamped to the frame
edge and counted rather than dropped; without a configured (or reachable)
border the padded pin bounding box is used instead. Like the web map, building
the data geocodes any site that has no coordinates yet, so the endpoint may
write to those Site records. Both subnet-map exports carry the swisstopo
attribution the tiles and boundary geometry require.

Subnet colours form a family: each subnet gets one colour from the location
palette and its prefixes are drawn in alternating lighter and darker shades of
it (`network_map/colors.py:shade_of`), on the map, in the floor plan and in
both exports.

The plugin is listed on the NetBox plugin API index (`/api/plugins/`) and its
API root (`/api/plugins/networkmap/`) links to the four endpoints above. They
are also documented in the OpenAPI schema (`/api/schema/`) under the
`network-map` tag.

## Publishing a New Version

The version is defined once, as `__version__` in `network_map/__init__.py`.
Both `pip` (via the setuptools dynamic `attr` in `pyproject.toml`) and the
NetBox plugin UI read it from there. To release, change `0.1.0` to `0.2.0`
in that file, then reinstall it:

```bash
cd /opt/netbox/network_map_plugin/network_map
/opt/netbox/venv/bin/python -m pip install --editable . --no-deps
```

Run the checks after installation:

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py check
```

For a production deployment, install the updated plugin from the same source
directory and restart NetBox using the service manager used by the deployment,
for example:

```bash
sudo systemctl restart netbox
```

Do not commit generated `*.egg-info/` directories. They are recreated by
`pip install` and should be ignored by Git.

When adopting a new NetBox release, verify the plugin works with it and adjust
`min_version`/`max_version` in `network_map/__init__.py` if needed; NetBox
disables the plugin outside that range.

## Configuration

The two settings normally needed are `gateway_search_tag` and
`canton_boundary_code`:

```python
PLUGINS_CONFIG = {
    "network_map": {
        "gateway_search_tag": "GATEWAY-TAG",
        "canton_boundary_code": "BE",
    },
}
```

- `gateway_search_tag`: the device tag (or other exact-match search term)
  the Vlan-Connections view uses to locate the central gateway object.
- `canton_boundary_code`: the canton border drawn on the Subnet-Map, as a
  two-letter code (e.g. `"BE"`, `"AG"`) or numeric BFS canton id. Defaults to
  `"BE"`; set it to `""` to disable the border.

All other settings have sensible code defaults and can remain unset.

The canton geometry is fetched live and cached; it is not shipped with the
plugin. The border is served through `/plugins/networkmap/subnet-map/canton-boundary/`
under the same `network_map.view_vlanelement` permission as the map itself. If
the geometry cannot be fetched, the map renders without a border.

<details>
<summary>Advanced settings</summary>

Advanced overrides can be added to the same `PLUGINS_CONFIG` dictionary.

### Site geocoding

Sites shown on the Subnet-Map need coordinates. If a site has no latitude and
longitude stored in NetBox, the plugin looks them up from the site's physical
address (or name) via a geocoding service and writes the result back to the
Site, so every site is geocoded only once and the values can be corrected in
the NetBox UI afterwards.

- `nominatim_url`: geocoding endpoint; defaults to OpenStreetMap's public
  Nominatim service.
- `country_codes`: comma-separated country filter for the address search;
  defaults to `"ch"`.
- `request_interval_seconds`: minimum delay between geocoding requests;
  defaults to `1.0`.
- `request_timeout_seconds`: timeout for a single lookup; defaults to `10`.

### Canton border sources

- `canton_boundary_label`: legend text for the border; defaults to the canton
  name when left empty.
- `canton_boundary_url_template`: primary swisstopo WFS URL, with `{id}`
  replaced by the BFS canton id. WFS is preferred because it carries interior
  rings, preserving canton pockets such as Steinhof SO. Keep
  `srsName=EPSG%3A4326` for WGS84 coordinates.
- `canton_boundary_fallback_url_template`: hole-carrying Nominatim fallback
  URL, with `{code}` replaced by the canton's ISO/CH code, e.g. `CH-BE`. Used
  automatically when WFS is unavailable.
- `canton_boundary_last_resort_url_template`: hole-less `map.geo.admin.ch`
  feature endpoint, used when both hole-carrying sources fail.
- `canton_boundary_cache_seconds`: cache lifetime for fetched geometry;
  defaults to 30 days.

</details>

## Translations

User-facing strings are marked with `{% trans %}` tags in the templates and
`gettext_lazy` (`_()`) in Python code. Translations live in
`network_map/locale/<lang>/LC_MESSAGES/django.po` (currently `de` and `fr`);
`network_map/locale/django.pot` is the generated master list of all
translatable strings.

After adding or changing translatable strings, update every catalog:

```bash
cd /opt/netbox/network_map_plugin
DJANGO_SETTINGS_MODULE=netbox.settings PYTHONPATH=/opt/netbox/netbox \
  /opt/netbox/venv/bin/django-admin makemessages -l de -l fr
```

This marks new and changed entries in each `.po` file; fill in the `msgstr`
values (by hand or with a tool like Poedit), then rebuild the binary `.mo`
catalogs that NetBox actually loads:

```bash
cd /opt/netbox/network_map_plugin
for lang in de fr; do
  msgfmt --check \
    -o network_map/locale/$lang/LC_MESSAGES/django.mo \
       network_map/locale/$lang/LC_MESSAGES/django.po
done
```

Restart NetBox afterwards; catalogs are read once at startup. The `.mo` files
are committed because the package is built from this tree and does not
compile them itself.
