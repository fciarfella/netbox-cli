"""Contextual prompt_toolkit completion for the interactive shell."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ..discovery import FilterDefinition
from ..mutations import SUPPORTED_PAYLOAD_FILE_EXTENSIONS
from ..profiles import get_default_columns
from .help import REPL_COMMANDS
from .metadata import (
    CompletionMetadataProvider,
    FilterValueSuggestion,
    WriteFieldDefinition,
)
from .state import ROOT_PATH, ShellState

try:
    from prompt_toolkit.completion import Completer, Completion
except ImportError:  # pragma: no cover - local fallback when prompt_toolkit is unavailable
    class Completer:  # type: ignore[no-redef]
        """Minimal fallback base class used only when prompt_toolkit is unavailable."""

    class Completion:  # type: ignore[no-redef]
        """Minimal fallback completion object used only when prompt_toolkit is unavailable."""

        def __init__(
            self,
            text: str,
            start_position: int = 0,
            **kwargs: object,
        ) -> None:
            self.text = text
            self.start_position = start_position
            self.display_meta = kwargs.get("display_meta")


OUTPUT_FORMAT_VALUES: tuple[str, ...] = ("table", "json", "csv")
RESET_COLUMN_VALUES: tuple[str, ...] = ("reset", "default")
_COMPLETION_SENTINEL = "__netbox_cli_complete__"
WRITE_OPTION_VALUES: tuple[str, ...] = ("--file", "--dry-run")
COMMON_LIST_FILTER_PRIORITY: tuple[str, ...] = (
    "q",
    "id",
    "name",
    "slug",
    "status",
    "site",
    "role",
    "tenant",
    "platform",
    "rack",
    "device_type",
    "manufacturer",
    "location",
    "region",
    "description",
    "serial",
)
COMMON_GET_FILTER_PRIORITY: tuple[str, ...] = (
    "id",
    "name",
    "slug",
    "status",
    "site",
    "role",
    "tenant",
    "platform",
    "rack",
    "device_type",
    "manufacturer",
    "q",
    "description",
    "serial",
)
COMMON_WRITE_FIELD_PRIORITY: tuple[str, ...] = (
    "name",
    "slug",
    "status",
    "site",
    "tenant",
    "role",
    "platform",
    "rack",
    "device_type",
    "manufacturer",
    "location",
    "region",
    "description",
    "serial",
)


@dataclass(frozen=True, slots=True)
class CompletionInput:
    """Tokenized user input up to the cursor position."""

    completed_tokens: tuple[str, ...]
    current_token: str


@dataclass(frozen=True, slots=True)
class MutationCompletionContext:
    """Derived mutation completion state from tokens before the cursor."""

    used_fields: frozenset[str]
    has_file_payload: bool = False
    has_dry_run: bool = False
    has_valid_id: bool = False
    expecting_file_path: bool = False


@dataclass(frozen=True, slots=True)
class FilterCompletionContext:
    """Derived filter completion state from tokens before the cursor."""

    used_fields: frozenset[str]


class NetBoxShellCompleter(Completer):
    """State-aware prompt_toolkit completer for the shell."""

    def __init__(
        self,
        *,
        state: ShellState,
        metadata_provider: CompletionMetadataProvider | None = None,
    ) -> None:
        self.state = state
        self.metadata_provider = metadata_provider

    def get_completions(self, document, complete_event) -> Iterable[Completion]:
        del complete_event

        parsed = _split_completion_input(document.text_before_cursor)
        completed_tokens = parsed.completed_tokens
        current_token = parsed.current_token

        if not completed_tokens:
            yield from self._complete_commands(current_token)
            return

        command_name = completed_tokens[0].lower()
        args_before_current = completed_tokens[1:]
        if command_name == "cd":
            yield from self._complete_path(current_token)
            return
        if command_name in {"list", "get"}:
            yield from self._complete_filters(
                command_name,
                args_before_current,
                current_token,
            )
            return
        if command_name in {"create", "update"}:
            yield from self._complete_mutation(
                command_name,
                args_before_current,
                current_token,
            )
            return
        if command_name == "cols":
            yield from self._complete_columns(current_token)
            return
        if command_name == "format":
            yield from self._complete_values(current_token, OUTPUT_FORMAT_VALUES)
            return
        if command_name == "open":
            yield from self._complete_open_indices(current_token)
            return

    def _complete_commands(self, prefix: str) -> Iterable[Completion]:
        yield from self._yield_matches(prefix, REPL_COMMANDS)

    def _complete_path(self, prefix: str) -> Iterable[Completion]:
        if self.metadata_provider is None:
            return

        path_context = _resolve_path_completion_context(self.state, prefix)
        if not path_context.parent_service_path:
            child_segments = self.metadata_provider.get_apps()
        else:
            child_segments = self.metadata_provider.get_child_segments(
                path_context.parent_service_path
            )

        if not prefix and not path_context.display_prefix and self.state.current_path != ROOT_PATH:
            yield Completion("..", start_position=0)

        for child in child_segments:
            if not _starts_with(child, path_context.partial_segment):
                continue
            completion_text = f"{path_context.display_prefix}{child}"
            yield Completion(
                completion_text,
                start_position=-len(prefix),
            )

    def _complete_filters(
        self,
        command_name: str,
        args_before_current: Sequence[str],
        current_token: str,
    ) -> Iterable[Completion]:
        if self.metadata_provider is None or not self.state.is_endpoint_context:
            return

        endpoint_path = self.state.service_path
        completion_context = _analyze_filter_completion_args(
            command_name,
            args_before_current,
        )
        if "=" in current_token:
            filter_name, value_prefix = current_token.split("=", 1)
            suggestions = self.metadata_provider.get_filter_value_suggestions(
                endpoint_path,
                filter_name,
                value_prefix,
                recent_results=self.state.last_results,
            )
            yield from self._yield_value_suggestions(value_prefix, suggestions)
            return

        yield from self._yield_filter_matches(
            current_token,
            _prioritized_filters(
                command_name,
                self.metadata_provider.get_filters(endpoint_path),
                used_fields=completion_context.used_fields,
            ),
        )

    def _complete_mutation(
        self,
        command_name: str,
        args_before_current: Sequence[str],
        current_token: str,
    ) -> Iterable[Completion]:
        if self.metadata_provider is None or not self.state.is_endpoint_context:
            return

        completion_context = _analyze_mutation_completion_args(
            command_name,
            args_before_current,
        )
        method = "POST" if command_name == "create" else "PATCH"
        endpoint_path = self.state.service_path

        if current_token.startswith("--file="):
            file_prefix = current_token.split("=", 1)[1]
            yield from self._complete_payload_files(
                file_prefix,
                option_prefix="--file=",
            )
            return

        if completion_context.expecting_file_path:
            yield from self._complete_payload_files(current_token)
            return

        if "=" in current_token and not current_token.startswith("-"):
            field_name, value_prefix = current_token.split("=", 1)
            normalized_field = field_name.strip()
            if (
                command_name == "update"
                and not completion_context.has_valid_id
                and normalized_field != "id"
            ):
                return
            if completion_context.has_file_payload and normalized_field != "id":
                return
            if command_name == "update" and normalized_field == "id":
                if not value_prefix.strip():
                    return
                yield from self._yield_post_mutation_matches(
                    endpoint_path,
                    method,
                    completion_context,
                )
                return
            suggestions = self.metadata_provider.get_write_value_suggestions(
                endpoint_path,
                method,
                normalized_field,
                value_prefix,
            )
            yield from self._yield_value_suggestions(value_prefix, suggestions)
            return

        if current_token and not current_token.startswith("-"):
            if command_name == "update" and not completion_context.has_valid_id:
                update_candidates = [
                    "id=",
                    *_mutation_option_candidates(completion_context),
                ]
                yield from self._yield_matches(current_token, tuple(update_candidates))
                return

            if completion_context.has_file_payload:
                return

            yield from self._yield_post_mutation_matches(
                endpoint_path,
                method,
                completion_context,
                prefix=current_token,
            )
            return

        if current_token.startswith("-"):
            yield from self._yield_matches(
                current_token,
                _mutation_option_candidates(completion_context),
            )
            return

        if command_name == "update" and not completion_context.has_valid_id:
            update_candidates = [
                "id=",
                *_mutation_option_candidates(completion_context),
            ]
            yield from self._yield_matches(current_token, tuple(update_candidates))
            return

        yield from self._yield_post_mutation_matches(
            endpoint_path,
            method,
            completion_context,
            prefix=current_token,
        )

    def _complete_columns(self, prefix: str) -> Iterable[Completion]:
        if not self.state.is_endpoint_context:
            return

        known_columns = _known_columns_for_state(self.state)
        prefix_before_column, column_prefix = _split_csv_prefix(prefix)

        if not prefix_before_column:
            for value in RESET_COLUMN_VALUES:
                if _starts_with(value, column_prefix):
                    yield Completion(value, start_position=-len(prefix))

        for column in known_columns:
            if not _starts_with(column, column_prefix):
                continue
            yield Completion(
                f"{prefix_before_column}{column}",
                start_position=-len(prefix),
            )

    def _complete_open_indices(self, prefix: str) -> Iterable[Completion]:
        candidates = tuple(str(index) for index in range(1, len(self.state.last_results) + 1))
        yield from self._yield_matches(prefix, candidates)

    def _complete_values(
        self,
        prefix: str,
        values: Sequence[str],
    ) -> Iterable[Completion]:
        yield from self._yield_matches(prefix, values)

    def _yield_value_suggestions(
        self,
        prefix: str,
        suggestions: Sequence[FilterValueSuggestion],
    ) -> Iterable[Completion]:
        normalized_prefix = prefix.casefold()
        seen: set[str] = set()
        for suggestion in suggestions:
            key = suggestion.value.casefold()
            if key in seen:
                continue
            seen.add(key)
            if normalized_prefix and not (
                _starts_with(suggestion.value, normalized_prefix, normalized=True)
                or (
                    suggestion.label is not None
                    and _starts_with(suggestion.label, normalized_prefix, normalized=True)
                )
            ):
                continue

            yield Completion(
                suggestion.value,
                start_position=-len(prefix),
                display_meta=suggestion.label,
            )

    def _yield_matches(
        self,
        prefix: str,
        values: Sequence[str],
        *,
        replace_only_current: bool = False,
    ) -> Iterable[Completion]:
        normalized_prefix = prefix.casefold()
        start_position = -len(prefix)
        if replace_only_current:
            start_position = -len(prefix)

        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            if not _starts_with(value, normalized_prefix, normalized=True):
                continue
            yield Completion(value, start_position=start_position)

    def _yield_mutation_field_matches(
        self,
        prefix: str,
        field_definitions: Sequence[WriteFieldDefinition],
    ) -> Iterable[Completion]:
        normalized_prefix = prefix.casefold()
        seen: set[str] = set()
        for field_def in field_definitions:
            completion_text = f"{field_def.name}="
            key = completion_text.casefold()
            if key in seen:
                continue
            seen.add(key)
            if normalized_prefix and not completion_text.casefold().startswith(normalized_prefix):
                continue
            yield Completion(
                completion_text,
                start_position=-len(prefix),
                display_meta=_mutation_field_meta(field_def),
            )

    def _yield_post_mutation_matches(
        self,
        endpoint_path: str,
        method: str,
        completion_context: MutationCompletionContext,
        *,
        prefix: str = "",
    ) -> Iterable[Completion]:
        if not completion_context.has_file_payload:
            yield from self._yield_mutation_field_matches(
                prefix,
                _prioritized_write_fields(
                    self.metadata_provider.get_write_fields(endpoint_path, method),
                    used_fields=completion_context.used_fields,
                ),
            )

        yield from self._yield_matches(
            prefix,
            _mutation_option_candidates(completion_context),
        )

    def _yield_filter_matches(
        self,
        prefix: str,
        filter_definitions: Sequence[FilterDefinition],
    ) -> Iterable[Completion]:
        normalized_prefix = prefix.casefold()
        seen: set[str] = set()
        for filter_def in filter_definitions:
            completion_text = f"{filter_def.name}="
            key = completion_text.casefold()
            if key in seen:
                continue
            seen.add(key)
            if normalized_prefix and not completion_text.casefold().startswith(normalized_prefix):
                continue
            yield Completion(
                completion_text,
                start_position=-len(prefix),
                display_meta=_filter_field_meta(filter_def),
            )

    def _complete_payload_files(
        self,
        prefix: str,
        *,
        option_prefix: str = "",
    ) -> Iterable[Completion]:
        search_dir, display_prefix, file_prefix = _resolve_file_completion_context(prefix)
        if search_dir is None:
            return

        seen: set[str] = set()
        try:
            candidates = sorted(search_dir.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            return

        for candidate in candidates:
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in SUPPORTED_PAYLOAD_FILE_EXTENSIONS:
                continue
            if not _starts_with(candidate.name, file_prefix):
                continue

            completion_text = f"{option_prefix}{display_prefix}{candidate.name}"
            if completion_text in seen:
                continue
            seen.add(completion_text)
            yield Completion(
                completion_text,
                start_position=-len(prefix) - len(option_prefix),
            )


@dataclass(frozen=True, slots=True)
class PathCompletionContext:
    """Derived information for path completion."""

    parent_service_path: str
    display_prefix: str
    partial_segment: str


def _split_completion_input(text_before_cursor: str) -> CompletionInput:
    stripped_text = text_before_cursor
    if not stripped_text.strip():
        return CompletionInput(completed_tokens=(), current_token="")

    if stripped_text.endswith((" ", "\t")):
        return CompletionInput(
            completed_tokens=tuple(_safe_shlex_split(stripped_text)),
            current_token="",
        )

    tokens = _safe_shlex_split(f"{stripped_text}{_COMPLETION_SENTINEL}")
    if tokens and tokens[-1].endswith(_COMPLETION_SENTINEL):
        return CompletionInput(
            completed_tokens=tuple(tokens[:-1]),
            current_token=tokens[-1][: -len(_COMPLETION_SENTINEL)],
        )

    fallback_tokens = _safe_shlex_split(stripped_text)
    if not fallback_tokens:
        return CompletionInput(completed_tokens=(), current_token="")
    return CompletionInput(
        completed_tokens=tuple(fallback_tokens[:-1]),
        current_token=fallback_tokens[-1],
    )


def _safe_shlex_split(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        stripped = value.strip()
        return stripped.split() if stripped else []


def _resolve_path_completion_context(state: ShellState, prefix: str) -> PathCompletionContext:
    absolute = prefix.startswith(ROOT_PATH)
    base_parts = [] if absolute else list(state.path_parts)

    trimmed_prefix = prefix[1:] if absolute else prefix
    raw_segments = trimmed_prefix.split("/")
    if prefix.endswith("/"):
        fixed_segments = raw_segments
        partial_segment = ""
    else:
        fixed_segments = raw_segments[:-1]
        partial_segment = raw_segments[-1] if raw_segments else ""

    parent_parts = list(base_parts)
    for segment in fixed_segments:
        if not segment or segment == ".":
            continue
        if segment == "..":
            if parent_parts:
                parent_parts.pop()
            continue
        parent_parts.append(segment)

    display_prefix = prefix[: len(prefix) - len(partial_segment)] if partial_segment else prefix
    return PathCompletionContext(
        parent_service_path="/".join(parent_parts),
        display_prefix=display_prefix,
        partial_segment=partial_segment,
    )


def _split_csv_prefix(value: str) -> tuple[str, str]:
    if "," not in value:
        return "", value

    prefix, current = value.rsplit(",", 1)
    return f"{prefix},", current


def _known_columns_for_state(state: ShellState) -> tuple[str, ...]:
    if not state.is_endpoint_context:
        return ()

    ordered_columns: list[str] = []
    seen: set[str] = set()

    for column in get_default_columns(state.service_path):
        if column not in seen:
            seen.add(column)
            ordered_columns.append(column)

    for column in state.columns:
        if column not in seen:
            seen.add(column)
            ordered_columns.append(column)

    for reference in state.last_results:
        if reference.endpoint_path != state.service_path:
            continue
        for key in reference.payload:
            if key not in seen:
                seen.add(key)
                ordered_columns.append(key)

    return tuple(ordered_columns)


def _analyze_mutation_completion_args(
    command_name: str,
    args_before_current: Sequence[str],
) -> MutationCompletionContext:
    used_fields: set[str] = set()
    has_file_payload = False
    has_dry_run = False
    has_valid_id = False
    expecting_file_path = False

    index = 0
    while index < len(args_before_current):
        token = args_before_current[index]
        if token == "--dry-run":
            has_dry_run = True
            index += 1
            continue
        if token == "--file":
            if index == len(args_before_current) - 1:
                expecting_file_path = True
                break
            has_file_payload = True
            index += 2
            continue
        if token.startswith("--file="):
            if token.split("=", 1)[1].strip():
                has_file_payload = True
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if "=" not in token:
            index += 1
            continue

        key, value = token.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key:
            index += 1
            continue
        if command_name == "update" and normalized_key == "id":
            if normalized_value:
                has_valid_id = True
            index += 1
            continue
        used_fields.add(normalized_key)
        index += 1

    return MutationCompletionContext(
        used_fields=frozenset(used_fields),
        has_file_payload=has_file_payload,
        has_dry_run=has_dry_run,
        has_valid_id=has_valid_id,
        expecting_file_path=expecting_file_path,
    )


def _analyze_filter_completion_args(
    command_name: str,
    args_before_current: Sequence[str],
) -> FilterCompletionContext:
    used_fields: set[str] = set()
    positional_terms_present = False

    for token in args_before_current:
        if "=" in token:
            key, value = token.split("=", 1)
            if not value.strip():
                continue
            normalized_key = key.strip()
            if normalized_key:
                used_fields.add(normalized_key)
            continue

        if command_name == "list" and token.strip():
            positional_terms_present = True

    if command_name == "list" and positional_terms_present and "q" not in used_fields:
        used_fields.add("q")

    return FilterCompletionContext(used_fields=frozenset(used_fields))


def _mutation_option_candidates(
    completion_context: MutationCompletionContext,
) -> tuple[str, ...]:
    candidates: list[str] = []
    if not completion_context.has_file_payload and not completion_context.used_fields:
        candidates.append("--file")
    if not completion_context.has_dry_run:
        candidates.append("--dry-run")
    return tuple(candidates)


def _prioritized_write_fields(
    field_definitions: Sequence[WriteFieldDefinition],
    *,
    used_fields: frozenset[str],
) -> tuple[WriteFieldDefinition, ...]:
    common_priority_index = {
        field_name: index
        for index, field_name in enumerate(COMMON_WRITE_FIELD_PRIORITY)
    }

    remaining_fields = [
        field_def
        for field_def in field_definitions
        if field_def.name not in used_fields
    ]
    remaining_fields.sort(
        key=lambda field_def: (
            0 if field_def.required else 1,
            common_priority_index.get(field_def.name, len(common_priority_index)),
            field_def.name,
        )
    )
    return tuple(remaining_fields)


def _prioritized_filters(
    command_name: str,
    filter_definitions: Sequence[FilterDefinition],
    *,
    used_fields: frozenset[str],
) -> tuple[FilterDefinition, ...]:
    priority_source = (
        COMMON_LIST_FILTER_PRIORITY
        if command_name == "list"
        else COMMON_GET_FILTER_PRIORITY
    )
    common_priority_index = {
        field_name: index
        for index, field_name in enumerate(priority_source)
    }

    remaining_filters = [
        filter_def
        for filter_def in filter_definitions
        if filter_def.name not in used_fields
    ]
    remaining_filters.sort(
        key=lambda filter_def: (
            common_priority_index.get(filter_def.name, len(common_priority_index)),
            0 if filter_def.required else 1,
            filter_def.name,
        )
    )
    return tuple(remaining_filters)


def _mutation_field_meta(field_def: WriteFieldDefinition) -> str | None:
    return _field_meta_parts(
        required=field_def.required,
        value_type=field_def.value_type,
        has_choices=bool(field_def.choices),
    )


def _filter_field_meta(filter_def: FilterDefinition) -> str | None:
    return _field_meta_parts(
        required=filter_def.required,
        value_type=filter_def.value_type,
        has_choices=bool(filter_def.choices),
    )


def _field_meta_parts(
    *,
    required: bool,
    value_type: str | None,
    has_choices: bool,
) -> str | None:
    parts: list[str] = []
    if required:
        parts.append("required")
    if value_type:
        parts.append(value_type)
    if has_choices:
        parts.append("choices")
    if not parts:
        return None
    return " • ".join(parts)


def _resolve_file_completion_context(
    prefix: str,
) -> tuple[Path | None, str, str]:
    expanded_prefix = Path(prefix).expanduser() if prefix else Path(".")
    if prefix.endswith("/"):
        search_dir = expanded_prefix
        display_prefix = prefix
        file_prefix = ""
    elif prefix:
        search_dir = expanded_prefix.parent
        file_prefix = expanded_prefix.name
        display_prefix = prefix[: len(prefix) - len(file_prefix)]
    else:
        search_dir = Path(".")
        display_prefix = ""
        file_prefix = ""

    if not search_dir.exists() or not search_dir.is_dir():
        return None, display_prefix, file_prefix
    return search_dir, display_prefix, file_prefix


def _starts_with(value: str, prefix: str, *, normalized: bool = False) -> bool:
    if normalized:
        return value.casefold().startswith(prefix)
    return value.casefold().startswith(prefix.casefold())
