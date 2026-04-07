"""Default column profiles for common endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EndpointProfile:
    """Presentation defaults for a NetBox endpoint."""

    title: str
    columns: tuple[str, ...]


DEFAULT_ENDPOINT_PROFILES: dict[str, EndpointProfile] = {
    "dcim/devices": EndpointProfile(
        title="Devices",
        columns=("id", "name", "site", "rack", "role", "status"),
    ),
    "dcim/sites": EndpointProfile(
        title="Sites",
        columns=("id", "name", "slug", "status", "tenant"),
    ),
    "dcim/racks": EndpointProfile(
        title="Racks",
        columns=("id", "name", "site", "status", "tenant"),
    ),
    "ipam/ip-addresses": EndpointProfile(
        title="IP Addresses",
        columns=("id", "address", "dns_name", "status", "assigned_object", "tenant"),
    ),
    "ipam/prefixes": EndpointProfile(
        title="Prefixes",
        columns=("id", "prefix", "status", "site", "vrf", "vlan", "description"),
    ),
    "ipam/vlans": EndpointProfile(
        title="VLANs",
        columns=("id", "vid", "name", "site", "status", "tenant"),
    ),
    "virtualization/virtual-machines": EndpointProfile(
        title="Virtual Machines",
        columns=("id", "name", "status", "cluster", "role", "tenant"),
    ),
    "plugins/netbox_dns/records": EndpointProfile(
        title="DNS Records",
        columns=("id", "zone", "name", "type", "value", "status"),
    ),
    "plugins/netbox-dns/records": EndpointProfile(
        title="DNS Records",
        columns=("id", "zone", "name", "type", "value", "status"),
    ),
}

FALLBACK_PROFILE = EndpointProfile(
    title="Results",
    columns=("id", "display", "name", "status"),
)


def get_default_columns(endpoint_path: str) -> tuple[str, ...]:
    """Return the default columns for an endpoint path."""

    return get_endpoint_profile(endpoint_path).columns


def get_endpoint_profile(endpoint_path: str) -> EndpointProfile:
    """Return the default presentation profile for an endpoint."""

    normalized_path = endpoint_path.strip("/")
    return DEFAULT_ENDPOINT_PROFILES.get(normalized_path, FALLBACK_PROFILE)


def get_endpoint_title(endpoint_path: str) -> str:
    """Return a human-friendly title for an endpoint."""

    return get_endpoint_profile(endpoint_path).title
