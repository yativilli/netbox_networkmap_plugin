# NetBox Network Map Plugin

A plugin for NetBox to display machines on a network map.

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

Optional entry in NetBox's `configuration.py`:

```python
PLUGINS_CONFIG = {
    "network_map": {
        "gateway_search_tag": "GATEWAY-TAG",
        "nominatim_url": "https://nominatim.openstreetmap.org/search",
        "country_codes": "ch",
        "request_interval_seconds": 1.0,
        "request_timeout_seconds": 10,
    },
}
```

- `gateway_search_tag`: the device tag (or other exact-match search term)
  the Vlan-Connections view uses to locate the central gateway object.

### Site geocoding

Sites shown on the Subnet-Map need coordinates. If a site has no latitude and
longitude stored in NetBox, the plugin looks them up from the site's physical
address (or name) via a geocoding service and writes the result back to the
Site, so every site is geocoded only once and the values can be corrected in
the NetBox UI afterwards. The following settings control that lookup:

- `nominatim_url`: the geocoding endpoint used for the lookup. Defaults to
  OpenStreetMap's public Nominatim service; point it at a self-hosted instance
  for privacy or to avoid public rate limits.
- `country_codes`: comma-separated country filter for the address search
  (default `"ch"`), so an address such as "Bahnhofstrasse 1" resolves in
  Switzerland instead of Germany.
- `request_interval_seconds`: minimum delay between geocoding requests
  (default 1.0, per Nominatim's usage policy) when several sites need to be
  geocoded during one page load.
- `request_timeout_seconds`: how long a single lookup may take (default 10)
  before it is given up; without a timeout a hanging request would stall
  rendering of the Subnet-Map page.

All values are optional; omitting them reproduces the plugin's previous
hard-coded behaviour.
