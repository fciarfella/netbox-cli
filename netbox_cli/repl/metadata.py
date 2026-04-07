"""Session-scoped metadata helpers for shell completion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..client import NetBoxClient
from ..discovery import FilterDefinition, list_apps, list_endpoints, list_filters
from ..errors import InvalidFilterError, NetBoxCLIError
from ..query import get_record_field, stringify_value
from ..settings import RecordReference

MAX_VALUE_SUGGESTIONS = 20
DEFAULT_VALUE_PREFIX_LENGTH = 1


@dataclass(frozen=True, slots=True)
class FilterValueSuggestion:
    """One candidate value for a filter completion."""

    value: str
    label: str | None = None
    source: str = "static"


@dataclass(frozen=True, slots=True)
class RelatedValueLookupSpec:
    """How to resolve filter values from a related NetBox endpoint."""

    endpoint_path: str
    query_fields: tuple[str, ...] = ("q",)
    value_field: str = "name"
    label_field: str | None = None
    min_prefix_length: int = DEFAULT_VALUE_PREFIX_LENGTH
    max_suggestions: int = MAX_VALUE_SUGGESTIONS
    empty_prefix_ordering: str | None = None


RELATED_VALUE_LOOKUPS: dict[str, RelatedValueLookupSpec] = {
    "site": RelatedValueLookupSpec(
        endpoint_path="dcim/sites",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "rack": RelatedValueLookupSpec(
        endpoint_path="dcim/racks",
        query_fields=("name__ic", "q"),
        value_field="name",
        label_field="site",
    ),
    "tenant": RelatedValueLookupSpec(
        endpoint_path="tenancy/tenants",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "role": RelatedValueLookupSpec(
        endpoint_path="dcim/device-roles",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "platform": RelatedValueLookupSpec(
        endpoint_path="dcim/platforms",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "manufacturer": RelatedValueLookupSpec(
        endpoint_path="dcim/manufacturers",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "location": RelatedValueLookupSpec(
        endpoint_path="dcim/locations",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "region": RelatedValueLookupSpec(
        endpoint_path="dcim/regions",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "site_group": RelatedValueLookupSpec(
        endpoint_path="dcim/site-groups",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
    "device_type": RelatedValueLookupSpec(
        endpoint_path="dcim/device-types",
        query_fields=("slug__ic", "model__ic", "q"),
        value_field="slug",
        label_field="model",
    ),
    "vlan": RelatedValueLookupSpec(
        endpoint_path="ipam/vlans",
        query_fields=("q", "name__ic"),
        value_field="vid",
        label_field="name",
    ),
    "vrf": RelatedValueLookupSpec(
        endpoint_path="ipam/vrfs",
        query_fields=("name__ic", "rd__ic", "q"),
        value_field="name",
        label_field="rd",
    ),
    "tag": RelatedValueLookupSpec(
        endpoint_path="extras/tags",
        query_fields=("slug__ic", "name__ic", "q"),
        value_field="slug",
        label_field="name",
    ),
}

ENDPOINT_RELATED_VALUE_LOOKUPS: dict[tuple[str, str], RelatedValueLookupSpec] = {}


@dataclass(slots=True)
class CompletionMetadataProvider:
    """Lazy in-memory metadata cache used by the shell completer."""

    client: NetBoxClient
    _apps: tuple[str, ...] | None = None
    _children_by_path: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _filters_by_endpoint: dict[str, tuple[FilterDefinition, ...]] = field(default_factory=dict)
    _related_values_by_key: dict[
        tuple[str, str, str],
        tuple[FilterValueSuggestion, ...],
    ] = field(default_factory=dict)

    def get_apps(self) -> tuple[str, ...]:
        """Return cached top-level app names."""

        if self._apps is None:
            try:
                self._apps = tuple(list_apps(self.client))
            except NetBoxCLIError:
                self._apps = ()
        return self._apps

    def get_child_segments(self, parent_service_path: str) -> tuple[str, ...]:
        """Return cached child path segments for a root or app context."""

        normalized = parent_service_path.strip("/")
        if not normalized:
            return self.get_apps()

        cached = self._children_by_path.get(normalized)
        if cached is not None:
            return cached

        try:
            endpoints = list_endpoints(self.client, normalized)
            cached = tuple(endpoint.endpoint for endpoint in endpoints)
        except NetBoxCLIError:
            cached = ()

        self._children_by_path[normalized] = cached
        return cached

    def get_filters(self, endpoint_path: str) -> tuple[FilterDefinition, ...]:
        """Return cached filter metadata for an endpoint."""

        normalized = endpoint_path.strip("/")
        if not normalized:
            return ()

        cached = self._filters_by_endpoint.get(normalized)
        if cached is not None:
            return cached

        try:
            cached = tuple(list_filters(self.client, normalized))
        except NetBoxCLIError:
            cached = ()

        self._filters_by_endpoint[normalized] = cached
        return cached

    def get_filter_names(self, endpoint_path: str) -> tuple[str, ...]:
        """Return cached filter names for an endpoint."""

        return tuple(filter_def.name for filter_def in self.get_filters(endpoint_path))

    def get_filter_choices(
        self,
        endpoint_path: str,
        filter_name: str,
    ) -> tuple[str, ...]:
        """Return known static choice values for one filter."""

        normalized_name = filter_name.strip()
        for filter_def in self.get_filters(endpoint_path):
            if filter_def.name != normalized_name:
                continue
            return tuple(choice.value for choice in filter_def.choices)
        return ()

    def get_filter_value_suggestions(
        self,
        endpoint_path: str,
        filter_name: str,
        prefix: str,
        *,
        recent_results: Sequence[RecordReference] | None = None,
    ) -> tuple[FilterValueSuggestion, ...]:
        """Resolve dynamic filter values from metadata, related lookups, and recent results."""

        normalized_endpoint = endpoint_path.strip("/")
        normalized_filter = filter_name.strip()
        normalized_prefix = prefix.strip()

        suggestions: list[FilterValueSuggestion] = []
        suggestions.extend(
            self._static_choice_suggestions(
                normalized_endpoint,
                normalized_filter,
                normalized_prefix,
            )
        )
        suggestions.extend(
            self._related_value_suggestions(
                normalized_endpoint,
                normalized_filter,
                normalized_prefix,
            )
        )
        suggestions.extend(
            self._recent_result_suggestions(
                normalized_filter,
                normalized_prefix,
                recent_results or (),
            )
        )

        return _dedupe_suggestions(suggestions)[:MAX_VALUE_SUGGESTIONS]

    def _static_choice_suggestions(
        self,
        endpoint_path: str,
        filter_name: str,
        prefix: str,
    ) -> tuple[FilterValueSuggestion, ...]:
        return tuple(
            FilterValueSuggestion(
                value=choice.value,
                label=choice.label if choice.label != choice.value else None,
                source="static",
            )
            for filter_def in self.get_filters(endpoint_path)
            if filter_def.name == filter_name
            for choice in filter_def.choices
            if _text_matches_prefix(choice.value, prefix)
            or (
                choice.label != choice.value
                and _text_matches_prefix(choice.label, prefix)
            )
        )

    def _related_value_suggestions(
        self,
        endpoint_path: str,
        filter_name: str,
        prefix: str,
    ) -> tuple[FilterValueSuggestion, ...]:
        lookup_spec = self._resolve_related_lookup_spec(endpoint_path, filter_name)
        if lookup_spec is None:
            return ()
        cache_key = (endpoint_path, filter_name, prefix.casefold())
        cached = self._related_values_by_key.get(cache_key)
        if cached is not None:
            return cached

        if prefix:
            if len(prefix) < lookup_spec.min_prefix_length:
                return ()
            suggestions = self._fetch_related_value_suggestions(lookup_spec, prefix)
        else:
            suggestions = self._fetch_empty_prefix_related_value_suggestions(lookup_spec)

        self._related_values_by_key[cache_key] = suggestions
        return suggestions

    def _fetch_empty_prefix_related_value_suggestions(
        self,
        lookup_spec: RelatedValueLookupSpec,
    ) -> tuple[FilterValueSuggestion, ...]:
        empty_prefix_params = self._empty_prefix_query_params(lookup_spec)
        fallback_params = {
            key: value
            for key, value in empty_prefix_params.items()
            if key != "ordering"
        }

        suggestions = self._fetch_related_value_suggestions(
            lookup_spec,
            "",
            base_params=empty_prefix_params,
        )
        if suggestions:
            return suggestions

        if fallback_params != empty_prefix_params:
            return self._fetch_related_value_suggestions(
                lookup_spec,
                "",
                base_params=fallback_params,
            )

        return ()

    def _fetch_related_value_suggestions(
        self,
        lookup_spec: RelatedValueLookupSpec,
        prefix: str,
        *,
        base_params: dict[str, Any] | None = None,
    ) -> tuple[FilterValueSuggestion, ...]:
        if not prefix:
            try:
                response = self.client.paginate(
                    lookup_spec.endpoint_path,
                    params=(
                        self._empty_prefix_query_params(lookup_spec)
                        if base_params is None
                        else base_params
                    ),
                    limit=lookup_spec.max_suggestions,
                )
            except InvalidFilterError:
                return ()
            except NetBoxCLIError:
                return ()

            suggestions: list[FilterValueSuggestion] = []
            for row in response.rows:
                suggestion = _build_related_value_suggestion(row, lookup_spec)
                if suggestion is None:
                    continue
                suggestions.append(suggestion)
            return tuple(_dedupe_suggestions(suggestions)[: lookup_spec.max_suggestions])

        for query_field in lookup_spec.query_fields:
            try:
                response = self.client.paginate(
                    lookup_spec.endpoint_path,
                    params={
                        **(base_params or {}),
                        query_field: prefix,
                    },
                    limit=lookup_spec.max_suggestions,
                )
            except InvalidFilterError:
                continue
            except NetBoxCLIError:
                return ()

            suggestions: list[FilterValueSuggestion] = []
            for row in response.rows:
                suggestion = _build_related_value_suggestion(row, lookup_spec)
                if suggestion is None:
                    continue
                if not _suggestion_matches_prefix(suggestion, prefix):
                    continue
                suggestions.append(suggestion)

            if suggestions:
                return _dedupe_suggestions(suggestions)[: lookup_spec.max_suggestions]

        return ()

    def _recent_result_suggestions(
        self,
        filter_name: str,
        prefix: str,
        recent_results: Sequence[RecordReference],
    ) -> tuple[FilterValueSuggestion, ...]:
        suggestions: list[FilterValueSuggestion] = []
        for record in recent_results:
            for raw_value in _iter_recent_values(record.payload, filter_name):
                value = stringify_value(raw_value).strip()
                if not value or not _text_matches_prefix(value, prefix):
                    continue
                suggestions.append(
                    FilterValueSuggestion(
                        value=value,
                        source="recent",
                    )
                )
        return tuple(_dedupe_suggestions(suggestions)[:MAX_VALUE_SUGGESTIONS])

    def _resolve_related_lookup_spec(
        self,
        endpoint_path: str,
        filter_name: str,
    ) -> RelatedValueLookupSpec | None:
        endpoint_key = endpoint_path.strip("/")
        filter_key = filter_name.strip()
        return ENDPOINT_RELATED_VALUE_LOOKUPS.get(
            (endpoint_key, filter_key),
            RELATED_VALUE_LOOKUPS.get(filter_key),
        )

    def _empty_prefix_query_params(
        self,
        lookup_spec: RelatedValueLookupSpec,
    ) -> dict[str, Any]:
        ordering = lookup_spec.empty_prefix_ordering or lookup_spec.value_field
        if not ordering:
            return {}
        return {"ordering": ordering}


def _build_related_value_suggestion(
    row: dict[str, Any],
    lookup_spec: RelatedValueLookupSpec,
) -> FilterValueSuggestion | None:
    value = _extract_row_value(row, lookup_spec.value_field)
    if not value:
        return None

    label = None
    if lookup_spec.label_field:
        label = _extract_row_value(row, lookup_spec.label_field) or None
        if label == value:
            label = None

    return FilterValueSuggestion(
        value=value,
        label=label,
        source="related",
    )


def _extract_row_value(row: dict[str, Any], field_name: str) -> str:
    return stringify_value(get_record_field(row, field_name)).strip()


def _iter_recent_values(payload: dict[str, Any], filter_name: str) -> Iterable[Any]:
    value = get_record_field(payload, filter_name)
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(item for item in value if item not in (None, ""))
    return (value,)


def _dedupe_suggestions(
    suggestions: Sequence[FilterValueSuggestion],
) -> list[FilterValueSuggestion]:
    deduped: list[FilterValueSuggestion] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        key = suggestion.value.casefold()
        if not suggestion.value or key in seen:
            continue
        seen.add(key)
        deduped.append(suggestion)
    return deduped


def _suggestion_matches_prefix(suggestion: FilterValueSuggestion, prefix: str) -> bool:
    if not prefix:
        return True
    if _text_matches_prefix(suggestion.value, prefix):
        return True
    if suggestion.label and _text_matches_prefix(suggestion.label, prefix):
        return True
    return False


def _text_matches_prefix(value: str, prefix: str) -> bool:
    if not prefix:
        return True
    return value.casefold().startswith(prefix.casefold())
