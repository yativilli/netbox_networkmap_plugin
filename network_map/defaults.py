from netbox.plugins import get_plugin_config

DEFAULT_GATEWAY_SEARCH_TAG = "GATEWAY-TAG"
DEFAULT_CANTON_BOUNDARY_CODE = "BE"


def int_setting(name, default, minimum=None):
    """
    A plugin setting as an int: a value that cannot be read as a number falls
    back to the default instead of answering the request with a 500.
    """
    try:
        value = int(get_plugin_config("network_map", name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value is not None:
        value = max(minimum, value)
    return value
