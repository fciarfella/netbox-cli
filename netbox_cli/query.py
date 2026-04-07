"""Read-only list and get query services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from dataclasses import dataclass
from typing import Any, TypeAlias

from .client import NetBoxClient, QueryParam
from .discovery import list_filters
from .errors import InvalidFilterError, MultipleResultsError, NoResultsError

FilterInput: TypeAlias = Mapping[str, str] | Sequence[QueryParam]


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Normalized rows returned by a list query."""

    endpoint_path: str
    rows: list[dict[str, Any]]
    total_count: int


@dataclass(frozen=True, slots=True)
class RecordResult:
    """A single object returned by a get query."""

    endpoint_path: str
    row: dict[str, Any]


def list_records(
    client: NetBoxClient,
    endpoint_path: str,
    filters: FilterInput | None = None,
    *,
    limit: int | None = None,
) -> QueryResult:
    """List objects from a read-only NetBox endpoint."""

    normalized_path = endpoint_path.strip("/")
    normalized_filters = _normalize_list_filters(filters)
    _validate_filters(client, normalized_path, normalized_filters)

    response = client.paginate(
        normalized_path,
        params=normalized_filters,
        limit=limit,
    )
    if not response.rows:
        raise NoResultsError(f"No results found for {normalized_path}.")

    return QueryResult(
        endpoint_path=normalized_path,
        rows=response.rows,
        total_count=response.total_count,
    )


def get_record(
    client: NetBoxClient,
    endpoint_path: str,
    filters: FilterInput | None = None,
) -> RecordResult:
    """Return exactly one object from a read-only NetBox endpoint."""

    normalized_path = endpoint_path.strip("/")
    normalized_filters = _normalize_unique_filters(filters)
    if not normalized_filters:
        raise InvalidFilterError(
            f"`netbox get {normalized_path}` requires at least one lookup filter."
        )

    _validate_filters(client, normalized_path, normalized_filters)
    response = client.paginate(
        normalized_path,
        params=normalized_filters,
        limit=2,
    )

    if response.total_count == 0 or not response.rows:
        raise NoResultsError(f"No results found for {normalized_path}.")
    if response.total_count > 1 or len(response.rows) > 1:
        raise MultipleResultsError(
            f"Lookup for {normalized_path} matched multiple objects; refine the filters."
        )

    return RecordResult(endpoint_path=normalized_path, row=response.rows[0])


def get_record_by_id(
    client: NetBoxClient,
    endpoint_path: str,
    object_id: int | str,
) -> RecordResult:
    """Return a single object by its native detail endpoint."""

    normalized_path = endpoint_path.strip("/")
    payload = client.get_json(f"{normalized_path}/{object_id}")
    if not isinstance(payload, dict):
        raise NoResultsError(f"No detail record found for {normalized_path}/{object_id}.")
    return RecordResult(endpoint_path=normalized_path, row=payload)


def get_record_field(record: Mapping[str, Any], field_name: str) -> Any:
    """Extract a field from a NetBox object with simple nested fallback rules."""

    if field_name in record:
        return record[field_name]

    if field_name == "display":
        for fallback_key in ("display", "name", "label"):
            if fallback_key in record:
                return record[fallback_key]

    return None


def stringify_record_field(record: Mapping[str, Any], field_name: str) -> str:
    """Return a human-readable string representation for a record field."""

    return stringify_value(get_record_field(record, field_name))


def stringify_value(value: Any) -> str:
    """Normalize nested NetBox data for text-oriented output."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        parts = [stringify_value(item) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("display", "name", "label", "value", "slug", "id"):
            if key in value and value[key] not in (None, ""):
                return stringify_value(value[key])
        return json.dumps(value, sort_keys=True)
    return str(value)


def _normalize_list_filters(filters: FilterInput | None) -> list[QueryParam]:
    if not filters:
        return []

    items = filters.items() if isinstance(filters, Mapping) else filters
    normalized: list[QueryParam] = []
    for key, value in items:
        key_text = str(key).strip()
        if not key_text:
            continue
        normalized.append((key_text, str(value).strip()))
    return normalized


def _normalize_unique_filters(filters: FilterInput | None) -> dict[str, str]:
    normalized_pairs = _normalize_list_filters(filters)
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key, _ in normalized_pairs:
        if key in seen:
            duplicates.add(key)
            continue
        seen.add(key)

    if duplicates:
        duplicate_display = ", ".join(sorted(duplicates))
        raise InvalidFilterError(
            "Repeated lookup filters are not allowed for `get`: "
            f"{duplicate_display}. Use `list` for multi-value filters."
        )

    return {
        key: value
        for key, value in normalized_pairs
    }


def _validate_filters(
    client: NetBoxClient,
    endpoint_path: str,
    filters: FilterInput,
) -> None:
    if not filters:
        return

    available_filters = {filter_def.name for filter_def in list_filters(client, endpoint_path)}
    items = filters.items() if isinstance(filters, Mapping) else filters
    invalid_filters = sorted(
        {
            str(name)
            for name, _ in items
            if str(name) not in available_filters
        }
    )
    if invalid_filters:
        invalid_display = ", ".join(invalid_filters)
        raise InvalidFilterError(
            f"Invalid filters for {endpoint_path}: {invalid_display}."
        )
