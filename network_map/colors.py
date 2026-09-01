LOCATION_COLORS = (
    ("location-color-0", "#0072b2"),
    ("location-color-1", "#d55e00"),
    ("location-color-2", "#009e73"),
    ("location-color-3", "#cc79a7"),
    ("location-color-4", "#e69f00"),
    ("location-color-5", "#56b4e9"),
    ("location-color-6", "#882255"),
    ("location-color-7", "#117733"),
    ("location-color-8", "#332288"),
    ("location-color-9", "#aa4499"),
    ("location-color-10", "#44aa99"),
    ("location-color-11", "#999933"),
    ("location-color-12", "#661100"),
    ("location-color-13", "#6699cc"),
    ("location-color-14", "#aa4466"),
    ("location-color-15", "#447744"),
    ("location-color-16", "#774488"),
    ("location-color-17", "#cc6677"),
    ("location-color-18", "#117755"),
    ("location-color-19", "#999933"),
)


def color_for_location(index: int) -> str:
    return LOCATION_COLORS[index % len(LOCATION_COLORS)][0]


def location_color_map(locations) -> dict[str, str]:
    normalized_locations = []
    for location in locations:
        value = str(location or 'None').strip() or 'None'
        if value in {'None', 'Unknown'}:
            continue
        normalized_locations.append(value)

    ordered_locations = sorted(set(normalized_locations))
    mapping = {
        location: color_for_location(index)
        for index, location in enumerate(ordered_locations)
    }

    mapping['None'] = 'location-color-default'
    mapping['Unknown'] = 'location-color-default'
    return mapping
