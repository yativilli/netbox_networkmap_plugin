"""Shared test helpers."""

import json
import os

from .. import lv03


def _static(name):
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "static", "network_map", name
    )
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _lv03_extent(corners):
    """The LV03 box around lon/lat corners, as map_tiles is handed one."""
    points = [lv03.to_lv03(lat, lon) for lon, lat in corners]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


class _FakeTileResponse:
    """Minimal stand-in for the object urlopen() returns for a tile."""

    def __init__(self, payload=b"\xff\xd8\xff\xe0jpeg"):
        self._payload = payload

    def read(self, max_bytes=-1):
        if max_bytes is None or max_bytes < 0:
            return self._payload
        return self._payload[:max_bytes]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeHTTPResponse:
    """Minimal stand-in for the object urlopen() returns."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
