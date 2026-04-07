"""Global multi-endpoint search services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from .client import NetBoxClient, QueryParam, QueryParamsInput
from .discovery import list_filters
from .errors import InvalidEndpointError, InvalidFilterError, NoResultsError
from .profiles import get_endpoint_title
from .query import get_record_field, stringify_record_field, stringify_value

SearchStrategyResult: TypeAlias = tuple[str, list[dict[str, object]], int]
SearchStrategy: TypeAlias = Callable[[NetBoxClient, "SearchTarget", str], SearchStrategyResult | None]


@dataclass(frozen=True, slots=True)
class SearchTarget:
    """Configuration for one global search target endpoint."""

    title: str
    endpoint_path: str
    filter_builder: Callable[[str], QueryParamsInput]
    match_fields: tuple[str, ...]
    endpoint_candidates: tuple[str, ...] = ()
    search_strategy: SearchStrategy | None = None


@dataclass(frozen=True, slots=True)
class SearchGroup:
    """Grouped search results for a single endpoint."""

    title: str
    endpoint_path: str
    rows: list[dict[str, object]]
    total_count: int


def default_query_filter(term: str) -> dict[str, str]:
    """Return the default NetBox free-text filter."""

    return {"q": term}


def dns_record_search_strategy(
    client: NetBoxClient,
    target: SearchTarget,
    term: str,
) -> SearchStrategyResult | None:
    """Search DNS records using endpoint-specific value and name filters when available."""

    for endpoint_path in _iter_endpoint_paths(target):
        try:
            supported_filters = {
                filter_def.name
                for filter_def in list_filters(client, endpoint_path)
            }
        except InvalidEndpointError:
            continue
        except InvalidFilterError:
            supported_filters = set()

        query_variants = _build_dns_query_variants(term, supported_filters)
        if not query_variants:
            query_variants = [target.filter_builder(term)]

        merged_rows: list[dict[str, object]] = []
        seen_row_ids: set[str] = set()
        attempted_query = False

        for params in query_variants:
            try:
                response = client.paginate(endpoint_path, params=params)
            except (InvalidEndpointError, InvalidFilterError):
                continue

            attempted_query = True
            for row in response.rows:
                row_identity = _row_identity(row)
                if row_identity in seen_row_ids:
                    continue
                seen_row_ids.add(row_identity)
                merged_rows.append(row)

        if attempted_query:
            return endpoint_path, merged_rows, len(merged_rows)

    return None


DEFAULT_SEARCH_TARGETS: tuple[SearchTarget, ...] = (
    SearchTarget(
        title="Devices",
        endpoint_path="dcim/devices",
        filter_builder=default_query_filter,
        match_fields=("name", "display", "serial", "asset_tag"),
    ),
    SearchTarget(
        title="Virtual Machines",
        endpoint_path="virtualization/virtual-machines",
        filter_builder=default_query_filter,
        match_fields=("name", "display"),
    ),
    SearchTarget(
        title="IP Addresses",
        endpoint_path="ipam/ip-addresses",
        filter_builder=default_query_filter,
        match_fields=("address", "display", "dns_name"),
    ),
    SearchTarget(
        title="Prefixes",
        endpoint_path="ipam/prefixes",
        filter_builder=default_query_filter,
        match_fields=("prefix", "display", "description"),
    ),
    SearchTarget(
        title="VLANs",
        endpoint_path="ipam/vlans",
        filter_builder=default_query_filter,
        match_fields=("name", "vid", "display"),
    ),
    SearchTarget(
        title="Sites",
        endpoint_path="dcim/sites",
        filter_builder=default_query_filter,
        match_fields=("name", "slug", "display"),
    ),
    SearchTarget(
        title="Racks",
        endpoint_path="dcim/racks",
        filter_builder=default_query_filter,
        match_fields=("name", "display", "facility_id"),
    ),
    SearchTarget(
        title="DNS Records",
        endpoint_path="plugins/netbox-dns/records",
        endpoint_candidates=("plugins/netbox_dns/records",),
        filter_builder=default_query_filter,
        match_fields=("value", "name", "display", "zone", "type"),
        search_strategy=dns_record_search_strategy,
    ),
)


def global_search(
    client: NetBoxClient,
    term: str,
    *,
    limit_per_group: int | None = None,
    search_targets: tuple[SearchTarget, ...] = DEFAULT_SEARCH_TARGETS,
) -> list[SearchGroup]:
    """Search across curated endpoints and return grouped ranked results."""

    normalized_term = term.strip()
    if not normalized_term:
        raise InvalidFilterError("Search term must not be empty.")

    groups: list[SearchGroup] = []
    for target in search_targets:
        resolved = _search_target(client, target, normalized_term)
        if resolved is None:
            continue

        endpoint_path, rows, total_count = resolved
        if not rows:
            continue

        ranked_rows = sorted(
            rows,
            key=lambda row: _rank_search_row(row, target.match_fields, normalized_term),
        )
        display_rows = (
            ranked_rows[:limit_per_group]
            if limit_per_group is not None
            else ranked_rows
        )
        groups.append(
            SearchGroup(
                title=target.title or get_endpoint_title(endpoint_path),
                endpoint_path=endpoint_path,
                rows=display_rows,
                total_count=total_count,
            )
        )

    if not groups:
        raise NoResultsError(f"No results found for search term {normalized_term!r}.")

    return groups


def _search_target(
    client: NetBoxClient,
    target: SearchTarget,
    term: str,
) -> SearchStrategyResult | None:
    strategy = target.search_strategy or _default_search_strategy
    return strategy(client, target, term)


def _default_search_strategy(
    client: NetBoxClient,
    target: SearchTarget,
    term: str,
) -> SearchStrategyResult | None:
    for endpoint_path in _iter_endpoint_paths(target):
        try:
            response = client.paginate(
                endpoint_path,
                params=target.filter_builder(term),
            )
        except (InvalidEndpointError, InvalidFilterError):
            continue
        return endpoint_path, response.rows, response.total_count
    return None


def _iter_endpoint_paths(target: SearchTarget) -> tuple[str, ...]:
    ordered_paths: list[str] = []
    for endpoint_path in (target.endpoint_path, *target.endpoint_candidates):
        normalized = endpoint_path.strip("/")
        if normalized and normalized not in ordered_paths:
            ordered_paths.append(normalized)
    return tuple(ordered_paths)


def _build_dns_query_variants(
    term: str,
    supported_filters: set[str],
) -> list[list[QueryParam]]:
    filter_candidates: list[tuple[str, str]] = []

    if "value" in supported_filters:
        filter_candidates.append(("value", term))
    if "value__ic" in supported_filters:
        filter_candidates.append(("value__ic", term))
    if "name" in supported_filters:
        filter_candidates.append(("name", term))
    if "name__ic" in supported_filters:
        filter_candidates.append(("name__ic", term))
    if "q" in supported_filters:
        filter_candidates.append(("q", term))

    seen_filters: set[tuple[str, str]] = set()
    variants: list[list[QueryParam]] = []
    for filter_name, filter_value in filter_candidates:
        key = (filter_name, filter_value)
        if key in seen_filters:
            continue
        seen_filters.add(key)
        variants.append([(filter_name, filter_value)])
    return variants


def _row_identity(row: dict[str, object]) -> str:
    object_id = get_record_field(row, "id")
    if object_id not in (None, ""):
        return f"id:{stringify_value(object_id)}"

    parts = [
        stringify_record_field(row, field_name)
        for field_name in ("display", "name", "value", "type", "zone")
    ]
    return "|".join(parts)


def _rank_search_row(
    row: dict[str, object],
    match_fields: tuple[str, ...],
    term: str,
) -> tuple[int, int, str]:
    normalized_term = term.casefold()
    best_rank = 3
    best_field_index = len(match_fields)
    best_text = ""

    for field_index, field_name in enumerate(match_fields):
        candidate = stringify_record_field(row, field_name)
        if not candidate:
            continue
        normalized_candidate = candidate.casefold()
        if normalized_candidate == normalized_term:
            return (0, field_index, candidate)
        if normalized_candidate.startswith(normalized_term):
            if best_rank > 1 or (best_rank == 1 and field_index < best_field_index):
                best_rank = 1
                best_field_index = field_index
                best_text = candidate
            continue
        if normalized_term in normalized_candidate:
            if best_rank > 2 or (best_rank == 2 and field_index < best_field_index):
                best_rank = 2
                best_field_index = field_index
                best_text = candidate

    if best_text:
        return (best_rank, best_field_index, best_text)

    fallback = stringify_record_field(row, "display") or stringify_record_field(row, "name")
    return (3, len(match_fields), fallback)
