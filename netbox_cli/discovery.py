"""NetBox app, endpoint, and filter discovery services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .client import NetBoxClient
from .errors import APIError, InvalidEndpointError


@dataclass(frozen=True, slots=True)
class DiscoveredEndpoint:
    app: str
    endpoint: str
    path: str
    url: str


@dataclass(frozen=True, slots=True)
class ChoiceDefinition:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class FilterDefinition:
    name: str
    description: str = ""
    required: bool = False
    value_type: str | None = None
    choices: tuple[ChoiceDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedListPath:
    kind: Literal["root", "app", "endpoint"]
    path: str | None = None


def list_apps(client: NetBoxClient) -> list[str]:
    """Return the available top-level NetBox apps."""

    return sorted(client.get_api_root().keys())


def resolve_list_path(client: NetBoxClient, raw_path: str | None) -> ResolvedListPath:
    """Resolve a CLI list target to root, app, or endpoint using discovery metadata."""

    normalized_path = (raw_path or "").strip("/")
    if not normalized_path:
        return ResolvedListPath(kind="root")

    try:
        list_endpoints(client, normalized_path)
    except InvalidEndpointError:
        pass
    else:
        return ResolvedListPath(kind="app", path=normalized_path)

    try:
        list_filters(client, normalized_path)
    except InvalidEndpointError as exc:
        raise InvalidEndpointError(
            f"Unknown NetBox path: {raw_path}. Use `netbox list` to view apps or `netbox list <app>` to view endpoints."
        ) from exc

    return ResolvedListPath(kind="endpoint", path=normalized_path)


def list_endpoints(client: NetBoxClient, app_name: str) -> list[DiscoveredEndpoint]:
    """Return endpoints for an app or plugin app path."""

    normalized_app = app_name.strip("/")
    api_root = client.get_api_root()

    if normalized_app in api_root:
        payload = client.get_json(api_root[normalized_app])
    elif normalized_app.startswith("plugins/"):
        payload = client.get_app_root(normalized_app)
    else:
        raise InvalidEndpointError(f"Unknown NetBox app: {app_name}")

    if not isinstance(payload, dict):
        raise APIError(f"NetBox app root for {normalized_app} was not a JSON object.")

    endpoints: list[DiscoveredEndpoint] = []
    for endpoint_name, endpoint_url in payload.items():
        if not isinstance(endpoint_name, str) or not isinstance(endpoint_url, str):
            continue
        endpoints.append(
            DiscoveredEndpoint(
                app=normalized_app,
                endpoint=endpoint_name,
                path=f"{normalized_app}/{endpoint_name}",
                url=endpoint_url,
            )
        )

    return sorted(endpoints, key=lambda item: item.endpoint)


def list_filters(client: NetBoxClient, endpoint_path: str) -> list[FilterDefinition]:
    """Return endpoint filter metadata enriched with known choices where available."""

    schema = client.get_schema()
    choice_metadata = discover_choice_metadata(client, endpoint_path)
    operation = _get_get_operation(schema, endpoint_path)

    filters: list[FilterDefinition] = []
    for parameter in _iter_query_parameters(schema, operation):
        name = str(parameter.get("name", "")).strip()
        if not name:
            continue

        parameter_schema = _resolve_schema_refs(schema, parameter.get("schema", {}))
        filters.append(
            FilterDefinition(
                name=name,
                description=str(parameter.get("description", "")).strip(),
                required=bool(parameter.get("required", False)),
                value_type=_extract_type_name(parameter_schema),
                choices=choice_metadata.get(name, ()),
            )
        )

    return sorted(filters, key=lambda item: item.name)


def discover_choice_metadata(
    client: NetBoxClient,
    endpoint_path: str,
) -> dict[str, tuple[ChoiceDefinition, ...]]:
    """Return field and filter choices discovered from OPTIONS and schema metadata."""

    schema = client.get_schema()
    operation = _get_get_operation(schema, endpoint_path)
    try:
        options = client.get_options(endpoint_path)
    except (APIError, InvalidEndpointError):
        options = {}

    choices_by_field = _extract_option_choices(options)
    for parameter in _iter_query_parameters(schema, operation):
        name = str(parameter.get("name", "")).strip()
        if not name or name in choices_by_field:
            continue

        parameter_schema = _resolve_schema_refs(schema, parameter.get("schema", {}))
        enum_choices = _choices_from_schema(parameter_schema)
        if enum_choices:
            choices_by_field[name] = enum_choices

    return dict(sorted(choices_by_field.items()))


def _get_get_operation(schema: dict[str, Any], endpoint_path: str) -> dict[str, Any]:
    schema_path = _normalize_schema_path(endpoint_path)
    path_item = schema.get("paths", {}).get(schema_path)
    if not isinstance(path_item, dict):
        raise InvalidEndpointError(f"Endpoint path not found in schema: {endpoint_path}")

    operation = path_item.get("get")
    if not isinstance(operation, dict):
        raise InvalidEndpointError(f"Endpoint does not expose GET metadata: {endpoint_path}")

    return {
        "path_parameters": path_item.get("parameters", []),
        "operation_parameters": operation.get("parameters", []),
    }


def _normalize_schema_path(endpoint_path: str) -> str:
    normalized = endpoint_path.strip("/")
    return f"/api/{normalized}/"


def _iter_query_parameters(
    schema: dict[str, Any],
    operation: dict[str, Any],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    raw_parameters = []
    raw_parameters.extend(operation.get("path_parameters", []))
    raw_parameters.extend(operation.get("operation_parameters", []))

    for raw_parameter in raw_parameters:
        parameter = _resolve_schema_refs(schema, raw_parameter)
        if not isinstance(parameter, dict):
            continue
        if parameter.get("in") != "query":
            continue
        merged.append(parameter)
    return merged


def _extract_option_choices(options_payload: dict[str, Any]) -> dict[str, tuple[ChoiceDefinition, ...]]:
    actions = options_payload.get("actions", {})
    if not isinstance(actions, dict):
        return {}

    choices_by_field: dict[str, tuple[ChoiceDefinition, ...]] = {}
    for method_name in ("POST", "PUT", "PATCH"):
        method_fields = actions.get(method_name)
        if not isinstance(method_fields, dict):
            continue

        for field_name, metadata in method_fields.items():
            if field_name in choices_by_field or not isinstance(metadata, dict):
                continue
            field_choices = _coerce_choices(metadata.get("choices", []))
            if field_choices:
                choices_by_field[str(field_name)] = field_choices

    return choices_by_field


def _choices_from_schema(schema: Any) -> tuple[ChoiceDefinition, ...]:
    if not isinstance(schema, dict):
        return ()

    enum_values = schema.get("enum")
    if not isinstance(enum_values, list):
        return ()

    return tuple(
        ChoiceDefinition(value=str(value), label=str(value))
        for value in enum_values
        if value is not None
    )


def _coerce_choices(raw_choices: Any) -> tuple[ChoiceDefinition, ...]:
    if not isinstance(raw_choices, list):
        return ()

    choices: list[ChoiceDefinition] = []
    for choice in raw_choices:
        if isinstance(choice, dict):
            value = choice.get("value", choice.get("id", choice.get("name")))
            label = choice.get(
                "display_name",
                choice.get("label", choice.get("display", value)),
            )
        else:
            value = choice
            label = choice

        if value is None:
            continue
        choices.append(ChoiceDefinition(value=str(value), label=str(label)))

    return tuple(choices)


def _resolve_schema_refs(schema: dict[str, Any], value: Any) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        reference = value["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise APIError(f"Unsupported schema reference: {reference!r}")
        resolved: Any = schema
        for part in reference[2:].split("/"):
            if not isinstance(resolved, dict) or part not in resolved:
                raise APIError(f"Broken schema reference: {reference!r}")
            resolved = resolved[part]
        return _resolve_schema_refs(schema, resolved)

    if isinstance(value, dict):
        return {key: _resolve_schema_refs(schema, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_schema_refs(schema, item) for item in value]
    return value


def _extract_type_name(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None

    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type

    for key in ("anyOf", "oneOf", "allOf"):
        values = schema.get(key)
        if not isinstance(values, list):
            continue
        nested_types = sorted(
            {
                nested_type
                for item in values
                for nested_type in [_extract_type_name(item)]
                if nested_type is not None
            }
        )
        if nested_types:
            return "|".join(nested_types)

    if "enum" in schema:
        return "enum"
    return None
