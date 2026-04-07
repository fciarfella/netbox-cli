"""Session state for the interactive shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..profiles import get_default_columns
from ..settings import NetBoxSettings
from ..settings import OutputFormat, RecordReference

ROOT_PATH = "/"


@dataclass(slots=True)
class ShellState:
    """Mutable state for a shell session."""

    current_path: str = ROOT_PATH
    output_format: OutputFormat = "table"
    limit: int = 15
    _column_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    last_results: list[RecordReference] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: NetBoxSettings) -> ShellState:
        """Build the initial shell state from persisted CLI settings."""

        return cls(
            current_path=ROOT_PATH,
            output_format=settings.default_format,
            limit=settings.default_limit,
        )

    @property
    def service_path(self) -> str:
        """Return the current path without the shell root prefix."""

        return self.current_path.strip("/")

    @property
    def path_parts(self) -> tuple[str, ...]:
        """Return the current path split into normalized components."""

        if self.current_path == ROOT_PATH:
            return ()
        return tuple(part for part in self.current_path.strip("/").split("/") if part)

    @property
    def is_root_context(self) -> bool:
        """Return whether the shell is at the root context."""

        return not self.path_parts

    @property
    def is_endpoint_context(self) -> bool:
        """Return whether the current path points at an endpoint."""

        parts = self.path_parts
        if not parts:
            return False
        if parts[0] == "plugins":
            return len(parts) >= 3
        return len(parts) >= 2

    @property
    def is_app_context(self) -> bool:
        """Return whether the current path points at an app root."""

        parts = self.path_parts
        if not parts:
            return False
        if parts[0] == "plugins":
            return len(parts) <= 2
        return len(parts) == 1

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the active columns for the current endpoint context."""

        if not self.is_endpoint_context:
            return ()
        return self._column_overrides.get(
            self.service_path,
            get_default_columns(self.service_path),
        )

    def resolve_path(self, target: str) -> str:
        """Resolve an absolute or relative shell path."""

        raw_target = target.strip()
        if not raw_target or raw_target == ROOT_PATH:
            return ROOT_PATH

        if raw_target.startswith(ROOT_PATH):
            parts: list[str] = []
            segments = raw_target.split("/")
        else:
            parts = list(self.path_parts)
            segments = raw_target.split("/")

        for segment in segments:
            if not segment or segment == ".":
                continue
            if segment == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(segment)

        return ROOT_PATH if not parts else f"/{'/'.join(parts)}"

    def set_path(self, target: str) -> None:
        """Update the current path."""

        self.current_path = self.resolve_path(target)

    def go_back(self) -> None:
        """Move up a single path segment."""

        self.current_path = self.resolve_path("..")

    def go_home(self) -> None:
        """Return to the root shell context."""

        self.current_path = ROOT_PATH

    def set_output_format(self, output_format: OutputFormat) -> None:
        """Update the active output format."""

        self.output_format = output_format

    def set_limit(self, limit: int) -> None:
        """Update the active result limit."""

        self.limit = limit

    def set_columns(self, columns: Sequence[str] | None) -> None:
        """Store or clear the current endpoint column override."""

        if not self.is_endpoint_context:
            self._column_overrides.clear()
            return

        if not columns:
            self._column_overrides.pop(self.service_path, None)
            return

        normalized = tuple(
            column.strip()
            for column in columns
            if column and column.strip()
        )
        if normalized:
            self._column_overrides[self.service_path] = normalized
        else:
            self._column_overrides.pop(self.service_path, None)

    def remember_results(self, references: Sequence[RecordReference]) -> None:
        """Persist the most recent numbered result set."""

        self.last_results = list(references)

    def clear_results(self) -> None:
        """Forget the current numbered result set."""

        self.last_results.clear()
