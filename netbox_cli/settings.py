"""Typed settings and shared data models for the NetBox CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

OutputFormat = Literal["table", "json", "csv"]


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Filesystem locations used by the CLI."""

    config_dir: Path
    config_path: Path
    cache_dir: Path
    history_dir: Path
    history_path: Path


@dataclass(frozen=True, slots=True)
class NetBoxSettings:
    """User-configurable runtime settings."""

    url: str
    token: str
    default_format: OutputFormat = "table"
    default_limit: int = 15
    timeout_seconds: float = 10.0
    verify_tls: bool = True


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    """Resolved settings plus the source they came from."""

    settings: NetBoxSettings
    source: str
    config_path: Path | None = None
    profile_name: str | None = None
    current_profile: str | None = None
    available_profiles: tuple[str, ...] = ()
    is_legacy_profile: bool = False


@dataclass(frozen=True, slots=True)
class ConfiguredProfile:
    """One configured profile exposed to CLI and shell flows."""

    name: str
    settings: NetBoxSettings
    is_active: bool = False
    is_legacy: bool = False


@dataclass(frozen=True, slots=True)
class RecordReference:
    """Endpoint-specific reference to a NetBox object."""

    endpoint_path: str
    object_id: int | str | None
    display: str
    payload: dict[str, Any] = field(default_factory=dict)
