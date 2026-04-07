"""Contextual prompt_toolkit completion for the interactive shell."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..profiles import get_default_columns
from .help import REPL_COMMANDS
from .metadata import CompletionMetadataProvider, FilterValueSuggestion
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


@dataclass(frozen=True, slots=True)
class CompletionInput:
    """Tokenized user input up to the cursor position."""

    completed_tokens: tuple[str, ...]
    current_token: str


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
            yield from self._complete_filters(args_before_current, current_token)
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
        args_before_current: Sequence[str],
        current_token: str,
    ) -> Iterable[Completion]:
        if self.metadata_provider is None or not self.state.is_endpoint_context:
            return
        del args_before_current

        endpoint_path = self.state.service_path
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

        available_filters = [
            f"{filter_name}="
            for filter_name in self.metadata_provider.get_filter_names(endpoint_path)
        ]
        yield from self._yield_matches(current_token, available_filters)

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


def _starts_with(value: str, prefix: str, *, normalized: bool = False) -> bool:
    if normalized:
        return value.casefold().startswith(prefix)
    return value.casefold().startswith(prefix.casefold())
