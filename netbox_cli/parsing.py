"""Shared command-line filter parsing helpers for CLI and REPL commands."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

ParsedFilter: TypeAlias = tuple[str, str]


class FilterParseError(ValueError):
    """Raised when command filter arguments are malformed."""


class ColumnParseError(ValueError):
    """Raised when column override arguments are malformed."""


def parse_list_filter_tokens(raw_filters: Sequence[str]) -> list[ParsedFilter]:
    """Parse list-style filters, preserving repeated keys and mapping bare terms to q."""

    parsed = _parse_key_value_pairs(raw_filters, strict=False)
    positional_terms = [
        raw.strip()
        for raw in raw_filters
        if "=" not in raw and raw.strip()
    ]
    has_explicit_q = any(key == "q" for key, _ in parsed)

    if positional_terms and not has_explicit_q:
        return [("q", " ".join(positional_terms)), *parsed]

    return parsed


def parse_get_filter_tokens(raw_filters: Sequence[str]) -> dict[str, str]:
    """Parse strict get-style filters and reject repeated lookup keys."""

    parsed: dict[str, str] = {}
    for key, value in _parse_key_value_pairs(raw_filters, strict=True):
        if key in parsed:
            raise FilterParseError(
                f"Repeated lookup filter {key!r} is not allowed with `get`; use `list` for multi-value filters."
            )
        parsed[key] = value
    return parsed


def parse_column_tokens(raw_columns: str) -> tuple[str, ...]:
    """Parse a comma-separated column override string."""

    return parse_column_parts([raw_columns])


def parse_column_parts(raw_columns: Sequence[str]) -> tuple[str, ...]:
    """Parse one or more comma-separated column fragments."""

    if not any(raw_column.strip() for raw_column in raw_columns):
        raise ColumnParseError(
            "Expected a comma-separated column list, for example `name,site,status`."
        )

    parsed_columns: list[str] = []
    for raw_value in raw_columns:
        for raw_column in raw_value.split(","):
            column_name = raw_column.strip()
            if not column_name:
                raise ColumnParseError(
                    "Column names must not be empty. Use a comma-separated list like `name,site,status`."
                )
            parsed_columns.append(column_name)

    return tuple(parsed_columns)


def _parse_key_value_pairs(
    raw_filters: Sequence[str],
    *,
    strict: bool,
) -> list[ParsedFilter]:
    parsed: list[ParsedFilter] = []
    for raw in raw_filters:
        if "=" not in raw:
            if strict:
                raise FilterParseError(
                    f"Expected filters in key=value form, got {raw!r}."
                )
            continue

        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise FilterParseError(
                f"Expected filters in key=value form, got {raw!r}."
            )
        normalized_value = value.strip()
        if not normalized_value:
            raise FilterParseError(
                f"Incomplete filter: {key}=. Choose a value or remove the filter."
            )
        parsed.append((key, normalized_value))
    return parsed
