"""
Read-only map-readiness report.

The page this feeds does not draw a map and does not change NetBox data; it
looks for the missing pieces that make the maps, floor plans, and topology
incomplete or misleading.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from dcim.models import Location, Site
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from extras.models import Tag
from ipam.models import VLAN, IPAddress, Prefix
from netbox.plugins import get_plugin_config
from netbox.search import LookupTypes
from netbox.search.backends import search_backend

from .defaults import DEFAULT_GATEWAY_SEARCH_TAG
from .floor_plan import logical_floor
from .places import site_city

BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"

MACHINE_STATUSES = ("active", "reserved")
MAX_CATEGORY_ITEMS = 50
MAX_SCAN_ROWS = 500

CATEGORY_LABELS = {
    "sites": _lazy("Sites and coordinates"),
    "vlans": _lazy("VLANs and prefixes"),
    "ips": _lazy("IP addresses"),
    "placements": _lazy("Machine placement"),
    "rooms": _lazy("Rooms and floors"),
    "gateways": _lazy("Gateways"),
}

SEVERITY_LABELS = {
    BLOCKING: _lazy("Blocking"),
    WARNING: _lazy("Warning"),
    INFO: _lazy("Information"),
}


@dataclass(frozen=True)
class CoverageFinding:
    category: str
    severity: str
    issue: str
    detail: str
    object_type: str
    label: str
    url: str
    site: str = ""


def build_coverage(category: str = "", site: str = "", severity: str = "") -> dict:
    """Build the coverage report, optionally narrowed by the URL query."""
    findings = []
    elements = _vlan_elements()

    findings.extend(_site_findings(elements))
    findings.extend(_vlan_findings())
    findings.extend(_ip_findings())
    findings.extend(_placement_findings(elements))
    findings.extend(_room_findings(elements))
    findings.extend(_gateway_findings())

    groups = _group_findings(findings, category, site, severity)
    return {
        "filters": {
            "category": category,
            "site": site,
            "severity": severity,
        },
        "categories": [
            {"key": key, "label": CATEGORY_LABELS[key]} for key in CATEGORY_LABELS
        ],
        "severities": [
            {"key": key, "label": SEVERITY_LABELS[key]} for key in SEVERITY_LABELS
        ],
        "groups": groups,
        "summary": [group for group in groups if group["total"]],
        "totals": _totals(groups),
    }


def _vlan_elements():
    """The same machine elements the map pages collect, without geocoding."""
    from .views import VlanElementListView

    view = VlanElementListView()
    return view.build_elements(view.get_queryset())


def _site_findings(elements) -> list[CoverageFinding]:
    findings = []
    machine_counts = Counter(
        str(machine.get("location") or "")
        for element in elements
        for machine in element.machines
        if machine.get("location")
    )

    sites_by_name: dict[str, list[Site]] = defaultdict(list)
    for site in Site.objects.filter(name__in=machine_counts):
        sites_by_name[str(site.name)].append(site)

    for name, count in sorted(machine_counts.items()):
        matches = sites_by_name.get(name, [])
        if not matches:
            findings.append(
                CoverageFinding(
                    category="sites",
                    severity=BLOCKING,
                    issue=_("Site name is not present in NetBox"),
                    detail=_(
                        "Machines point to this site name, but the subnet map "
                        "cannot place them unless a Site with the same name exists."
                    ),
                    object_type=_("Site"),
                    label=name,
                    url=_list_url("dcim:site_list"),
                    site=name,
                )
            )
            continue

        if len(matches) > 1:
            findings.append(
                CoverageFinding(
                    category="sites",
                    severity=BLOCKING,
                    issue=_("Site name is ambiguous"),
                    detail=_(
                        "Several sites share this name. Rename them or map "
                        "machines by site so the map can choose the right one."
                    ),
                    object_type=_("Site"),
                    label=name,
                    url=_list_url("dcim:site_list"),
                    site=name,
                )
            )
            continue

        site = matches[0]
        if site.latitude is None or site.longitude is None:
            findings.append(
                CoverageFinding(
                    category="sites",
                    severity=BLOCKING,
                    issue=_("No coordinates for a site with machines"),
                    detail=_(
                        "Add latitude and longitude on the Site, or fill in an "
                        "address so geocoding can find it later."
                    ),
                    object_type=_("Site"),
                    label=str(site.name),
                    url=_object_url(site),
                    site=str(site.name),
                )
            )

        if not site_city(site):
            findings.append(
                CoverageFinding(
                    category="sites",
                    severity=WARNING,
                    issue=_("City cannot be inferred from the site"),
                    detail=_(
                        "Floor-plan filtering by city cannot find this site. Put "
                        "the city in the site name or physical address."
                    ),
                    object_type=_("Site"),
                    label=str(site.name),
                    url=_object_url(site),
                    site=str(site.name),
                )
            )

    return findings


def _vlan_findings() -> list[CoverageFinding]:
    findings = []

    for vlan in VLAN.objects.filter(prefixes__isnull=True).order_by("vid", "name"):
        findings.append(
            CoverageFinding(
                category="vlans",
                severity=BLOCKING,
                issue=_("VLAN has no prefix"),
                detail=_(
                    "Machines are collected from IP addresses inside related "
                    "prefixes, so a VLAN without a prefix stays empty."
                ),
                object_type=_("VLAN"),
                label=_vlan_label(vlan),
                url=_object_url(vlan),
                site=_site_name(vlan),
            )
        )
        if len(findings) >= MAX_SCAN_ROWS:
            break

    prefix_findings = _prefix_findings()
    findings.extend(prefix_findings)
    return findings


def _prefix_findings() -> list[CoverageFinding]:
    findings = []
    prefixes = Prefix.objects.filter(vlan__isnull=False).order_by("prefix")[
        :MAX_SCAN_ROWS
    ]
    for prefix in prefixes:
        has_ips = IPAddress.objects.filter(
            status__in=MACHINE_STATUSES,
            address__net_contained_or_equal=prefix.prefix,
        ).exists()
        if has_ips:
            continue
        findings.append(
            CoverageFinding(
                category="vlans",
                severity=INFO,
                issue=_("Prefix has no active or reserved IP addresses"),
                detail=_(
                    "The map will show this prefix only as an empty subnet unless "
                    "an active or reserved IP address is inside it."
                ),
                object_type=_("Prefix"),
                label=str(prefix.prefix),
                url=_object_url(prefix),
                site=_site_name(prefix),
            )
        )
    return findings


def _ip_findings() -> list[CoverageFinding]:
    findings = []
    seen_ips: set[int] = set()
    prefixes = Prefix.objects.filter(vlan__isnull=False).order_by("prefix")[
        :MAX_SCAN_ROWS
    ]

    for prefix in prefixes:
        for ip in IPAddress.objects.filter(
            status__in=MACHINE_STATUSES,
            address__net_contained_or_equal=prefix.prefix,
        ).order_by("address")[:MAX_SCAN_ROWS]:
            if ip.pk in seen_ips:
                continue
            seen_ips.add(ip.pk)

            owner = getattr(ip, "assigned_object", None)
            site_name = _assigned_site_name(owner)

            if ip.dns_name is None:
                findings.append(
                    CoverageFinding(
                        category="ips",
                        severity=BLOCKING,
                        issue=_("IP address has no DNS name"),
                        detail=_(
                            "The current machine collection only picks up IP "
                            "addresses with a DNS name."
                        ),
                        object_type=_("IP address"),
                        label=str(ip.address.ip),
                        url=_object_url(ip),
                        site=site_name,
                    )
                )
            elif not str(ip.dns_name).strip():
                findings.append(
                    CoverageFinding(
                        category="ips",
                        severity=WARNING,
                        issue=_("IP address has a blank DNS name"),
                        detail=_(
                            "The machine list falls back to names or descriptions, "
                            "which is harder to read than a real DNS name."
                        ),
                        object_type=_("IP address"),
                        label=str(ip.address.ip),
                        url=_object_url(ip),
                        site=site_name,
                    )
                )

            if owner is None:
                findings.append(
                    CoverageFinding(
                        category="ips",
                        severity=WARNING,
                        issue=_("IP address has no device or virtual machine"),
                        detail=_(
                            "Assign the address to an interface if it represents "
                            "a machine that should appear on the map."
                        ),
                        object_type=_("IP address"),
                        label=str(ip.address.ip),
                        url=_object_url(ip),
                        site=site_name,
                    )
                )
                continue

            if not site_name:
                findings.append(
                    CoverageFinding(
                        category="placements",
                        severity=BLOCKING,
                        issue=_("Assigned machine has no site"),
                        detail=_(
                            "Give the device or virtual machine a site, otherwise "
                            "the subnet map cannot place it."
                        ),
                        object_type=_("Machine"),
                        label=_assigned_label(owner),
                        url=_object_url(owner),
                        site="",
                    )
                )

            device = getattr(owner, "device", None)
            if device is not None and _device_has_no_room(device):
                findings.append(
                    CoverageFinding(
                        category="placements",
                        severity=WARNING,
                        issue=_("Physical machine has no room"),
                        detail=_(
                            "Set the device location, or a rack location, so the "
                            "floor plan can put the machine in a room."
                        ),
                        object_type=_("Device"),
                        label=str(device.name or ""),
                        url=_object_url(device),
                        site=_site_name(device),
                    )
                )

            if len(findings) >= MAX_SCAN_ROWS:
                return findings

    return findings


def _placement_findings(elements) -> list[CoverageFinding]:
    findings = []
    seen: set[tuple[str, str, str]] = set()

    for element in elements:
        for machine in element.machines:
            location = str(machine.get("location") or "")
            label = str(machine.get("dns_name") or machine.get("ip") or "")
            url = str(machine.get("url") or "")
            key = ("no-site", label, url)
            if not location and key not in seen:
                seen.add(key)
                findings.append(
                    CoverageFinding(
                        category="placements",
                        severity=WARNING,
                        issue=_("Machine is not attached to a site"),
                        detail=_(
                            "It stays in the unplaced list because neither the "
                            "assigned object nor the IP gives a site."
                        ),
                        object_type=_("Machine"),
                        label=label,
                        url=url or _list_url("ipam:ipaddress_list"),
                        site="",
                    )
                )
    return findings


def _room_findings(elements) -> list[CoverageFinding]:
    findings = []
    machine_counts = Counter(
        str(machine.get("location") or "")
        for element in elements
        for machine in element.machines
        if machine.get("location")
    )
    machine_rooms: dict[str, set[str]] = defaultdict(set)
    for element in elements:
        for machine in element.machines:
            site_name = str(machine.get("location") or "")
            room = str(machine.get("room") or "")
            if site_name and room and machine.get("physical", True):
                machine_rooms[site_name].add(room)

    sites = Site.objects.filter(name__in=machine_counts)
    locations = Location.objects.filter(site__in=sites).order_by("site__name", "name")[
        :MAX_SCAN_ROWS
    ]

    for location in locations:
        site_name = str(location.site.name)
        floor, _label = logical_floor(location.name)
        if floor == 200:
            findings.append(
                CoverageFinding(
                    category="rooms",
                    severity=WARNING,
                    issue=_("Floor cannot be inferred from the room name"),
                    detail=_(
                        "The floor plan will place this room under "
                        '"Other rooms". Use a name such as "2. Stock - Gang", '
                        '"EG 12", or "OG 2" to make the floor readable.'
                    ),
                    object_type=_("Location"),
                    label=str(location.name),
                    url=_object_url(location),
                    site=site_name,
                )
            )

        if (
            machine_rooms.get(site_name)
            and str(location.name) not in machine_rooms[site_name]
        ):
            findings.append(
                CoverageFinding(
                    category="rooms",
                    severity=INFO,
                    issue=_("Room has no machines"),
                    detail=_(
                        "The room will be drawn, but it carries no physical "
                        "machine from the current IP data."
                    ),
                    object_type=_("Location"),
                    label=str(location.name),
                    url=_object_url(location),
                    site=site_name,
                )
            )
    return findings


def _gateway_findings() -> list[CoverageFinding]:
    tag = get_plugin_config(
        "network_map", "gateway_search_tag", DEFAULT_GATEWAY_SEARCH_TAG
    )
    if not tag:
        return [
            CoverageFinding(
                category="gateways",
                severity=BLOCKING,
                issue=_("Gateway search tag is not configured"),
                detail=_(
                    "Set the network_map gateway_search_tag plugin setting to the "
                    "tag used for gateway IP addresses."
                ),
                object_type=_("Setting"),
                label="gateway_search_tag",
                url=_list_url("extras:tag_list"),
            )
        ]

    try:
        results = list(search_backend.search(tag, lookup=LookupTypes.EXACT))
    except (AttributeError, LookupError, TypeError, ValueError) as error:
        return [
            CoverageFinding(
                category="gateways",
                severity=BLOCKING,
                issue=_("Gateway search failed"),
                detail=str(error),
                object_type=_("Tag"),
                label=tag,
                url=_list_url("extras:tag_list"),
            )
        ]

    if not results:
        return [
            CoverageFinding(
                category="gateways",
                severity=WARNING,
                issue=_("No gateway-tagged objects were found"),
                detail=_(
                    "The logical connection view starts from objects tagged with "
                    "the configured gateway tag."
                ),
                object_type=_("Tag"),
                label=tag,
                url=_list_url("extras:tag_list"),
            )
        ]

    if not Tag.objects.filter(name=tag).exists():
        return [
            CoverageFinding(
                category="gateways",
                severity=WARNING,
                issue=_("Gateway search tag does not match a tag object"),
                detail=_(
                    "The search found text matches, but no tag with this exact "
                    "name exists. Check the plugin setting or create the tag."
                ),
                object_type=_("Tag"),
                label=tag,
                url=_list_url("extras:tag_list"),
            )
        ]

    usable = 0
    findings = []
    for result in results[:MAX_SCAN_ROWS]:
        obj = getattr(result, "object", None)
        address = getattr(obj, "address", None)
        if address is None or not _usable_gateway_prefix(address):
            findings.append(
                CoverageFinding(
                    category="gateways",
                    severity=WARNING,
                    issue=_("Gateway-tagged object is not usable on the logical map"),
                    detail=_(
                        "The logical map needs an IP address whose prefix has a "
                        "VLAN assigned."
                    ),
                    object_type=_(type(obj).__name__),
                    label=_gateway_label(obj),
                    url=_object_url(obj),
                    site=_site_name(obj),
                )
            )
            continue
        usable += 1

    if usable == 0 and findings:
        return findings
    return findings


def _group_findings(
    findings: list[CoverageFinding],
    category: str,
    site: str,
    severity: str,
) -> list[dict]:
    needle_site = site.casefold()
    needle_category = category.casefold()
    needle_severity = severity.casefold()

    groups = []
    for key, label in CATEGORY_LABELS.items():
        items = [
            finding
            for finding in findings
            if finding.category == key
            and (not needle_category or finding.category == needle_category)
            and (not needle_severity or finding.severity == needle_severity)
            and (
                not needle_site
                or needle_site in finding.site.casefold()
                or needle_site in finding.label.casefold()
            )
        ]
        severity_counts = Counter(finding.severity for finding in items)
        groups.append(
            {
                "key": key,
                "label": label,
                "items": items[:MAX_CATEGORY_ITEMS],
                "total": len(items),
                "truncated": len(items) > MAX_CATEGORY_ITEMS,
                "severity_counts": severity_counts,
            }
        )
    return groups


def _totals(groups: list[dict]) -> dict:
    counts = Counter()
    for group in groups:
        for severity, count in group["severity_counts"].items():
            counts[severity] += count
        counts["total"] += group["total"]
    return counts


def _device_has_no_room(device: Any) -> bool:
    location = getattr(device, "location", None)
    if location is not None:
        return False
    rack = getattr(device, "rack", None)
    rack_location = getattr(rack, "location", None) if rack is not None else None
    return rack_location is None


def _usable_gateway_prefix(address) -> bool:
    if not address:
        return False
    prefix = (
        Prefix.objects.filter(prefix__net_contains_or_equals=address)
        .select_related("vlan")
        .first()
    )
    return bool(prefix and prefix.vlan)


def _assigned_site_name(assigned_object: Any) -> str:
    if assigned_object is None:
        return ""
    owner = _assigned_owner(assigned_object)
    if owner is None:
        owner = getattr(assigned_object, "site", None)
    site = getattr(owner, "site", None) if owner is not None else None
    if site is None and hasattr(assigned_object, "site"):
        site = assigned_object.site
    return str(site.name) if site is not None else ""


def _assigned_owner(assigned_object: Any) -> Any:
    return (
        getattr(assigned_object, "device", None)
        or getattr(assigned_object, "virtual_machine", None)
        or assigned_object
    )


def _assigned_label(assigned_object: Any) -> str:
    owner = _assigned_owner(assigned_object)
    return str(getattr(owner, "name", None) or owner or "")


def _site_name(obj: Any) -> str:
    site = getattr(obj, "site", None)
    if site is None:
        return ""
    return str(site.name)


def _vlan_label(vlan) -> str:
    if vlan.name:
        return str(vlan.name)
    return f"VLAN {vlan.vid}"


def _gateway_label(obj: Any) -> str:
    address = getattr(obj, "address", None)
    name = getattr(obj, "dns_name", "") or getattr(obj, "name", "")
    if address and name:
        return f"{name} ({address})"
    if address:
        return str(address)
    if name:
        return str(name)
    return str(obj)


def _object_url(obj: Any) -> str:
    if hasattr(obj, "get_absolute_url"):
        return obj.get_absolute_url()
    return ""


def _list_url(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""
