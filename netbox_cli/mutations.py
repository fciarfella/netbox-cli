"""Minimal write services for NetBox create and update operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

import yaml

from .client import NetBoxClient
from .errors import APIError
from .query import RecordResult

MutationMethod = Literal["POST", "PATCH"]
SUPPORTED_PAYLOAD_FILE_EXTENSIONS = frozenset({".json", ".yaml", ".yml"})
PAYLOAD_INPUT_METHOD_ERROR = (
    "Choose exactly one payload input method: inline key=value fields or --file."
)


class MutationInputError(ValueError):
    """Raised when create or update arguments are malformed locally."""


@dataclass(frozen=True, slots=True)
class MutationRequest:
    """Prepared mutation request for a create or update command."""

    endpoint_path: str
    method: MutationMethod
    payload: dict[str, Any]
    object_id: str | None = None


def prepare_create_request(
    endpoint_path: str,
    inline_fields: Sequence[str] | None = None,
    payload_file: Path | None = None,
) -> MutationRequest:
    """Validate and normalize a create command before any API request is sent."""

    inline_payload = _parse_inline_payload(inline_fields or [])
    return MutationRequest(
        endpoint_path=_normalize_endpoint_path(endpoint_path),
        method="POST",
        payload=_choose_payload(inline_payload, payload_file),
    )


def prepare_update_request(
    endpoint_path: str,
    raw_fields: Sequence[str] | None = None,
    payload_file: Path | None = None,
) -> MutationRequest:
    """Validate and normalize an update command before any API request is sent."""

    object_id, inline_payload = _parse_update_fields(raw_fields or [])
    return MutationRequest(
        endpoint_path=_normalize_endpoint_path(endpoint_path),
        method="PATCH",
        object_id=object_id,
        payload=_choose_payload(inline_payload, payload_file),
    )


def create_record(client: NetBoxClient, request: MutationRequest) -> RecordResult:
    """Send a prepared create request to the target collection endpoint."""

    payload = client.post_json(request.endpoint_path, json_body=request.payload)
    return RecordResult(
        endpoint_path=request.endpoint_path,
        row=_coerce_response_row(payload, request.endpoint_path),
    )


def update_record(client: NetBoxClient, request: MutationRequest) -> RecordResult:
    """Send a prepared patch request to the target detail endpoint."""

    if request.object_id is None:
        raise APIError("Prepared update request is missing a target id.")

    payload = client.patch_json(
        f"{request.endpoint_path}/{request.object_id}",
        json_body=request.payload,
    )
    return RecordResult(
        endpoint_path=request.endpoint_path,
        row=_coerce_response_row(payload, request.endpoint_path),
    )


def _normalize_endpoint_path(endpoint_path: str) -> str:
    return endpoint_path.strip("/")


def _choose_payload(
    inline_payload: dict[str, Any],
    payload_file: Path | None,
) -> dict[str, Any]:
    has_inline_payload = bool(inline_payload)
    has_file_payload = payload_file is not None
    if has_inline_payload == has_file_payload:
        raise MutationInputError(PAYLOAD_INPUT_METHOD_ERROR)

    if payload_file is not None:
        return _load_payload_file(payload_file)

    return inline_payload


def _parse_inline_payload(raw_fields: Sequence[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw_field in raw_fields:
        key, value = _parse_field_assignment(raw_field)
        if key == "id":
            raise MutationInputError(
                "Create does not accept id=<id> as an inline field."
            )
        if key in payload:
            raise MutationInputError(
                f"Repeated payload field {key!r} is not allowed."
            )
        payload[key] = value
    return payload


def _parse_update_fields(raw_fields: Sequence[str]) -> tuple[str, dict[str, str]]:
    object_id: str | None = None
    payload: dict[str, str] = {}

    for raw_field in raw_fields:
        key, value = _parse_field_assignment(raw_field)
        if key == "id":
            if object_id is not None:
                raise MutationInputError(
                    "Update accepts exactly one id=<id> selector."
                )
            object_id = value
            continue

        if key in payload:
            raise MutationInputError(
                f"Repeated payload field {key!r} is not allowed."
            )
        payload[key] = value

    if object_id is None:
        raise MutationInputError("Update requires exactly one id=<id> selector.")

    return object_id, payload


def _parse_field_assignment(raw_field: str) -> tuple[str, str]:
    if "=" not in raw_field:
        raise MutationInputError(
            f"Expected fields in key=value form, got {raw_field!r}."
        )

    key, value = raw_field.split("=", 1)
    normalized_key = key.strip()
    if not normalized_key:
        raise MutationInputError(
            f"Expected fields in key=value form, got {raw_field!r}."
        )

    normalized_value = value.strip()
    if not normalized_value:
        raise MutationInputError(
            f"Incomplete field: {normalized_key}=. Choose a value or remove the field."
        )

    return normalized_key, normalized_value


def _load_payload_file(payload_file: Path) -> dict[str, Any]:
    extension = payload_file.suffix.lower()
    if extension not in SUPPORTED_PAYLOAD_FILE_EXTENSIONS:
        raise MutationInputError(
            "Unsupported payload file extension. Use .json, .yaml, or .yml."
        )
    if not payload_file.is_file():
        raise MutationInputError(f"Invalid file path: {payload_file}")

    try:
        raw_text = payload_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise MutationInputError(f"Invalid file path: {payload_file}") from exc

    if extension == ".json":
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise MutationInputError(f"Invalid JSON in {payload_file}.") from exc
    else:
        try:
            payload = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise MutationInputError(f"Invalid YAML in {payload_file}.") from exc

    return _coerce_payload_object(payload, payload_file)


def _coerce_payload_object(payload: Any, source: Path) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MutationInputError(
            f"Payload file must decode to an object/dict: {source}"
        )
    return dict(payload)


def _coerce_response_row(payload: Any, endpoint_path: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise APIError(
            f"NetBox mutation response for {endpoint_path} was not a JSON object."
        )
    return payload
