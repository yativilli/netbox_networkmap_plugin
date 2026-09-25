"""Reading the place out of NetBox text fields."""


def place_in_text(text):
    """
    The place out of one line of text, or nothing. A place names itself with
    letters and no house number, whether it stands before the street ("Bern,
    Musterweg 30") or after a postal code ("Musterweg 30, 3000 Bern"); the
    segment that carries no number - a leading postal code dropped - is the
    place.
    """
    segments = [seg.strip() for seg in str(text or "").split(",") if seg.strip()]
    for segment in segments:
        if not any(word.isdigit() for word in segment.split()):
            return segment
    for segment in reversed(segments):
        words = segment.split()
        if words and words[0].isdigit():
            return " ".join(words[1:])
    return ""


def site_city(site):
    """
    The place a site is in. NetBox keeps no city of its own, so it is read off
    wherever the site names it - the physical address, the shipping address, or,
    as many sites do, the site's own name "Bern, Musterweg 30" - and the first of
    these that holds a place wins; a site that names none gives "".
    """
    for text in (site.physical_address, site.shipping_address, site.name):
        city = place_in_text(text)
        if city:
            return city
    return ""


def site_names_the_place(site, place):
    """Whether a site says it stands in the place one is looking for."""
    needle = str(place).casefold()
    return any(
        needle in str(field or "").casefold()
        for field in (
            site.physical_address,
            site.shipping_address,
            site.description,
            site.name,
        )
    )
