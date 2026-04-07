"""Thin typed client for the NetBox REST API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, TypeAlias

import httpx

from .cache import MetadataCache
from .errors import (
    APIError,
    InvalidEndpointError,
    InvalidFilterError,
    NetBoxAuthError,
    NetBoxConnectionError,
)
from .settings import NetBoxSettings

SCHEMA_FORMAT_CANDIDATES: tuple[str, ...] = (
    "openapi",
    "json",
)
DEFAULT_PAGE_SIZE = 100
QueryParam: TypeAlias = tuple[str, Any]
QueryParamsInput: TypeAlias = Mapping[str, Any] | Sequence[QueryParam]


@dataclass(frozen=True, slots=True)
class PaginatedResponse:
    """Normalized response data for NetBox collection endpoints."""

    rows: list[dict[str, Any]]
    total_count: int


@dataclass(slots=True)
class NetBoxClient:
    """Small httpx-based wrapper around the NetBox API."""

    settings: NetBoxSettings
    metadata_cache: MetadataCache | None = None
    http_client: httpx.Client | None = None

    def test_connection(self) -> dict[str, str]:
        """Validate connectivity and authentication against the API root."""

        return self.get_api_root(use_cache=False)

    def api_url(self, path: str = "") -> str:
        """Return an absolute URL under the NetBox API root."""

        if path.startswith(("http://", "https://")):
            return path

        base_url = self.settings.url.rstrip("/")
        normalized = path.lstrip("/")
        if normalized.startswith("api/"):
            normalized = normalized[4:]

        if not normalized:
            return f"{base_url}/api/"

        if "?" not in normalized and not normalized.endswith("/"):
            normalized = f"{normalized}/"
        return f"{base_url}/api/{normalized}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: QueryParamsInput | None = None,
    ) -> httpx.Response:
        """Perform an authenticated API request."""

        method_name = method.upper()
        url = self.api_url(path)
        request_params = self._normalize_query_params(params)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.settings.token}",
            "User-Agent": "netbox-cli/0.1.0",
        }

        try:
            if self.http_client is not None:
                response = self.http_client.request(
                    method_name,
                    url,
                    headers=headers,
                    params=request_params,
                )
            else:
                with httpx.Client(
                    timeout=self.settings.timeout_seconds,
                    verify=self.settings.verify_tls,
                    follow_redirects=True,
                ) as client:
                    response = client.request(
                        method_name,
                        url,
                        headers=headers,
                        params=request_params,
                    )
        except httpx.TimeoutException as exc:
            raise NetBoxConnectionError(
                f"Timed out while contacting NetBox at {self.settings.url}."
            ) from exc
        except httpx.RequestError as exc:
            raise NetBoxConnectionError(
                f"Could not connect to NetBox at {self.settings.url}."
            ) from exc

        self._raise_for_status(response, method_name, path)
        return response

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: QueryParamsInput | None = None,
    ) -> Any:
        """Perform a request and decode the JSON response body."""

        response = self.request(method, path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise APIError("NetBox returned invalid JSON.") from exc

    def get_json(self, path: str, *, params: QueryParamsInput | None = None) -> Any:
        """Perform an authenticated GET request and decode JSON."""

        return self.request_json("GET", path, params=params)

    def get_api_root(self, *, use_cache: bool = True) -> dict[str, str]:
        """Return the API root app mapping."""

        if use_cache and self.metadata_cache is not None:
            cached = self.metadata_cache.read_api_root()
            if cached is not None:
                return self._coerce_string_mapping(cached, "API root")

        payload = self.request_json("GET", "")
        api_root = self._coerce_string_mapping(payload, "API root")
        if self.metadata_cache is not None:
            self.metadata_cache.write_api_root(api_root)
        return api_root

    def get_schema(self, *, use_cache: bool = True) -> dict[str, Any]:
        """Return the NetBox OpenAPI schema document."""

        if use_cache and self.metadata_cache is not None:
            cached = self.metadata_cache.read_schema()
            if cached is not None:
                return cached

        last_error: InvalidEndpointError | None = None
        for schema_format in SCHEMA_FORMAT_CANDIDATES:
            try:
                payload = self.request_json(
                    "GET",
                    "schema",
                    params={"format": schema_format},
                )
            except InvalidEndpointError as exc:
                last_error = exc
                continue

            schema = self._coerce_object(payload, "schema")
            if self.metadata_cache is not None:
                self.metadata_cache.write_schema(schema)
            return schema

        if last_error is not None:
            raise APIError("NetBox schema endpoint is not available.") from last_error
        raise APIError("NetBox schema retrieval failed.")

    def get_options(self, endpoint_path: str, *, use_cache: bool = True) -> dict[str, Any]:
        """Return OPTIONS metadata for an endpoint."""

        normalized = endpoint_path.strip("/")
        if use_cache and self.metadata_cache is not None:
            cached = self.metadata_cache.read_options(normalized)
            if cached is not None:
                return cached

        payload = self.request_json("OPTIONS", normalized)
        options = self._coerce_object(payload, f"OPTIONS {normalized}")
        if self.metadata_cache is not None:
            self.metadata_cache.write_options(normalized, options)
        return options

    def paginate(
        self,
        path: str,
        *,
        params: QueryParamsInput | None = None,
        limit: int | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse:
        """Normalize NetBox list responses with optional pagination handling."""

        if limit is not None and limit <= 0:
            return PaginatedResponse(rows=[], total_count=0)

        normalized_params = self._normalize_query_params(params)
        requested_page_size = self._effective_page_size(limit, page_size)

        payload = self.request_json(
            "GET",
            path,
            params=self._with_pagination(normalized_params, requested_page_size, 0),
        )
        rows, total_count, has_next = self._normalize_collection_payload(payload, path)

        if not has_next or (limit is not None and len(rows) >= limit):
            return PaginatedResponse(
                rows=rows[:limit] if limit is not None else rows,
                total_count=total_count,
            )

        collected_rows = list(rows)
        offset = len(rows)
        while has_next and (limit is None or len(collected_rows) < limit):
            next_page_size = self._effective_page_size(
                None if limit is None else limit - len(collected_rows),
                page_size,
            )
            page_payload = self.request_json(
                "GET",
                path,
                params=self._with_pagination(normalized_params, next_page_size, offset),
            )
            page_rows, page_total_count, has_next = self._normalize_collection_payload(
                page_payload,
                path,
            )
            collected_rows.extend(page_rows)
            offset += len(page_rows)
            total_count = max(total_count, page_total_count, len(collected_rows))
            if not page_rows:
                break

        return PaginatedResponse(
            rows=collected_rows[:limit] if limit is not None else collected_rows,
            total_count=total_count,
        )

    def get_app_root(self, app_name: str) -> dict[str, Any]:
        """Return endpoint metadata for an app or plugin app path."""

        payload = self.get_json(app_name.strip("/"))
        return self._coerce_object(payload, f"app {app_name}")

    def get_plugin_app_root(self, plugin_name: str) -> dict[str, Any]:
        """Return the API root for a plugin app."""

        return self.get_app_root(f"plugins/{plugin_name.strip('/')}")

    def get_plugin_endpoint(self, plugin_name: str, endpoint_name: str) -> Any:
        """Return JSON from a plugin endpoint path."""

        plugin_path = f"plugins/{plugin_name.strip('/')}/{endpoint_name.strip('/')}"
        return self.get_json(plugin_path)

    def _raise_for_status(self, response: httpx.Response, method: str, path: str) -> None:
        path_display = path.strip("/") or "API root"
        if response.status_code == 400:
            details = self._extract_error_details(response)
            message = f"NetBox rejected request parameters for {method} {path_display}"
            if details:
                message = f"{message}: {details}"
            else:
                message = f"{message}."
            raise InvalidFilterError(
                message
            )
        if response.status_code in {401, 403}:
            raise NetBoxAuthError("NetBox rejected the configured API token.")
        if response.status_code == 404:
            raise InvalidEndpointError(f"NetBox API path not found: {path}")
        if response.is_error:
            raise APIError(
                f"NetBox API request failed with status {response.status_code} for {path}."
            )

    def _coerce_object(self, payload: Any, label: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise APIError(f"NetBox {label} response was not a JSON object.")
        return payload

    def _coerce_string_mapping(self, payload: Any, label: str) -> dict[str, str]:
        data = self._coerce_object(payload, label)
        mapping = {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if not mapping:
            raise APIError(f"NetBox {label} response did not contain any string entries.")
        return mapping

    def _normalize_query_params(self, params: QueryParamsInput | None) -> list[QueryParam]:
        if not params:
            return []

        items = params.items() if isinstance(params, Mapping) else params
        normalized: list[QueryParam] = []
        for key, value in items:
            key_text = str(key)
            if not key_text or value is None:
                continue

            if isinstance(value, (list, tuple)):
                for item in value:
                    if item is None:
                        continue
                    normalized.append((key_text, item))
                continue

            normalized.append((key_text, value))

        return normalized

    def _with_pagination(
        self,
        params: Sequence[QueryParam],
        limit: int,
        offset: int,
    ) -> list[QueryParam]:
        return [
            *params,
            ("limit", limit),
            ("offset", offset),
        ]

    def _effective_page_size(self, limit: int | None, page_size: int) -> int:
        if page_size <= 0:
            raise APIError("Page size must be greater than zero.")
        if limit is None:
            return page_size
        return max(1, min(limit, page_size))

    def _normalize_collection_payload(
        self,
        payload: Any,
        path: str,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        if isinstance(payload, list):
            rows = [self._coerce_row(item, path) for item in payload]
            return rows, len(rows), False

        data = self._coerce_object(payload, f"collection {path}")
        if "results" not in data:
            raise APIError(f"NetBox collection response for {path} did not include results.")

        raw_rows = data.get("results")
        if not isinstance(raw_rows, list):
            raise APIError(f"NetBox collection response for {path} had invalid results data.")

        rows = [self._coerce_row(item, path) for item in raw_rows]
        raw_count = data.get("count", len(rows))
        total_count = raw_count if isinstance(raw_count, int) else len(rows)
        has_next = bool(data.get("next"))
        return rows, max(total_count, len(rows)), has_next

    def _coerce_row(self, value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise APIError(f"NetBox row in {path} response was not a JSON object.")
        return value

    def _extract_error_details(self, response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return self._normalize_error_text(response.text)

        return self._stringify_error_payload(payload)

    def _stringify_error_payload(self, payload: Any) -> str | None:
        if payload is None:
            return None

        if isinstance(payload, dict):
            parts: list[str] = []
            for key, value in payload.items():
                formatted_value = self._stringify_error_payload(value)
                if not formatted_value:
                    continue

                if key in {"detail", "message"} and not isinstance(value, (dict, list)):
                    parts.append(formatted_value)
                    continue

                parts.append(f"{key}: {formatted_value}")

            if parts:
                return "; ".join(parts)
            return self._normalize_error_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=False)
            )

        if isinstance(payload, list):
            parts = [
                formatted_value
                for item in payload
                for formatted_value in [self._stringify_error_payload(item)]
                if formatted_value
            ]
            if parts:
                return "; ".join(parts)
            return self._normalize_error_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=False)
            )

        return self._normalize_error_text(str(payload))

    def _normalize_error_text(self, value: str) -> str | None:
        normalized = " ".join(value.split())
        if not normalized:
            return None
        if len(normalized) <= 400:
            return normalized
        return f"{normalized[:397]}..."
