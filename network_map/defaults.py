from netbox.plugins import get_plugin_config

DEFAULT_GATEWAY_SEARCH_TAG = "GATEWAY-TAG"
DEFAULT_CANTON_BOUNDARY_CODE = "BE"


def canton_code():
    """The canton whose border the map draws, as one asked for it."""
    return get_plugin_config(
        "network_map", "canton_boundary_code", DEFAULT_CANTON_BOUNDARY_CODE
    )


def _setting(name, cast, default, minimum=None):
    try:
        value = cast(get_plugin_config("network_map", name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value is not None:
        value = max(minimum, value)
    return value


def int_setting(name, default, minimum=None):
    """
    A plugin setting as an int: a value that cannot be read as a whole number
    falls back to the default instead of answering the request with a 500.
    """
    return _setting(name, int, default, minimum)


def float_setting(name, default, minimum=None):
    """
    A plugin setting as a float - for the waits and budgets that pace the
    outside requests: a value that is no number falls back to the default.
    """
    return _setting(name, float, default, minimum)
