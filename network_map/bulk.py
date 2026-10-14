"""
Bulk data-access helpers.

The map pages used to ask the database once per prefix and several times per
machine, which made the first page load crawl on larger installations. These
helpers fetch the same rows in a fixed number of queries instead.
"""

import operator
from collections import defaultdict
from functools import reduce

import netaddr
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from ipam.models import IPAddress
from tenancy.models import ContactAssignment

# One query per assigned-object model resolves the whole page; the joined
# tables are exactly what views.py and coverage.py read off the owner.
ASSIGNED_OBJECT_SELECT_RELATED = {
    "dcim.interface": (
        "device",
        "device__site",
        "device__role",
        "device__location",
        "device__rack__location",
    ),
    "virtualization.vminterface": (
        "virtual_machine",
        "virtual_machine__site",
        "virtual_machine__role",
    ),
}


def ips_for_prefixes(prefixes, **filters):
    """
    All IP addresses inside any of the prefixes, in a single query, as
    {prefix.pk: [IPAddress, ...]}. Each list is ordered by address just like
    the old per-prefix queries were, and an address inside two prefixes
    shows up under both.
    """
    prefixes = list(prefixes)
    if not prefixes:
        return {}

    query = reduce(
        operator.or_,
        (Q(address__net_contained_or_equal=prefix.prefix) for prefix in prefixes),
    )
    # Instances that never came from the database still hold the plain string.
    networks = [(prefix.pk, netaddr.IPNetwork(prefix.prefix)) for prefix in prefixes]
    grouped = defaultdict(list)
    for ip in IPAddress.objects.filter(query, **filters).order_by("address"):
        for prefix_pk, network in networks:
            if ip.address in network:
                grouped[prefix_pk].append(ip)
    return dict(grouped)


def resolve_assigned_objects(ips):
    """
    Map {ip.pk: assigned object} with one query per involved model instead
    of one per IP address, joined so device/VM site and role come along for
    free. IPs without an assignment map to None.
    """
    ips_by_type = defaultdict(list)
    for ip in ips:
        if ip.assigned_object_type_id and ip.assigned_object_id:
            ips_by_type[ip.assigned_object_type_id].append(ip)

    objects_by_pk = {}
    for type_id, group in ips_by_type.items():
        model = ContentType.objects.get_for_id(type_id).model_class()
        if model is None:
            continue
        queryset = model.objects.filter(pk__in={ip.assigned_object_id for ip in group})
        select_related = ASSIGNED_OBJECT_SELECT_RELATED.get(
            f"{model._meta.app_label}.{model._meta.model_name}"
        )
        if select_related:
            queryset = queryset.select_related(*select_related)
        for obj in queryset:
            objects_by_pk[(type_id, obj.pk)] = obj

    return {
        ip.pk: objects_by_pk.get((ip.assigned_object_type_id, ip.assigned_object_id))
        for ip in ips
    }


def contact_key(obj):
    """The key contacts_for_objects stores an object's contact names under."""
    return obj._meta.app_label, obj._meta.model_name, obj.pk


def contacts_for_objects(objects):
    """
    Map {contact_key(obj): "Name1, Name2"} of the NetBox contacts assigned to
    the objects, in one contact query per involved model. The assignments are
    their own rows in the database, so these pages fetch them beside the
    existing queries instead of growing those.
    """
    pks_by_model = defaultdict(set)
    for obj in objects:
        if obj is None:
            continue
        app_label, model_name, pk = contact_key(obj)
        pks_by_model[(app_label, model_name)].add(pk)

    contacts = {}
    for (app_label, model_name), pks in pks_by_model.items():
        content_type = ContentType.objects.get_by_natural_key(app_label, model_name)
        names_by_pk = defaultdict(list)
        for assignment in ContactAssignment.objects.filter(
            object_type=content_type, object_id__in=pks
        ).select_related("contact"):
            names = names_by_pk[assignment.object_id]
            name = str(assignment.contact.name)
            if name not in names:
                names.append(name)
        for pk, names in names_by_pk.items():
            contacts[(app_label, model_name, pk)] = ", ".join(names)
    return contacts


def machine_of_assigned(assigned_object):
    """
    The device or virtual machine behind an IP's assigned interface, or None
    when the address stands for a machine on its own.
    """
    if assigned_object is None:
        return None
    return getattr(assigned_object, "device", None) or getattr(
        assigned_object, "virtual_machine", None
    )
