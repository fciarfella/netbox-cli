"""Configuration loading, validation, and persistence."""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .errors import ConfigFileNotFoundError, ConfigPermissionError, ConfigValidationError
from .settings import AppPaths, ConfiguredProfile, LoadedSettings, NetBoxSettings

APP_NAME = "netbox-cli"
CONFIG_FILE_NAME = "config.toml"
HISTORY_FILE_NAME = "shell-history"
CONFIG_FILE_MODE = 0o600
DIR_MODE = 0o700
VALID_OUTPUT_FORMATS = {"table", "json", "csv"}
DEFAULT_PROFILE_NAME = "default"
_PROFILE_SETTING_KEYS = {
    "url",
    "token",
    "default_format",
    "default_limit",
    "timeout_seconds",
    "verify_tls",
}


@dataclass(slots=True)
class _ConfigState:
    profiles: dict[str, NetBoxSettings]
    current_profile: str | None = None
    legacy_profile_name: str | None = None


def resolve_app_paths() -> AppPaths:
    """Return the user-specific filesystem paths for config, cache, and history."""

    config_dir = _resolve_config_dir()
    config_path = _resolve_config_path(config_dir)
    cache_dir = _resolve_cache_dir()
    history_dir = _resolve_history_dir()
    history_path = _resolve_history_path(history_dir)

    return AppPaths(
        config_dir=config_dir,
        config_path=config_path,
        cache_dir=cache_dir,
        history_dir=history_dir,
        history_path=history_path,
    )


def init_config(
    *,
    url: str,
    token: str,
    default_format: str = "table",
    default_limit: int = 15,
    timeout_seconds: float = 10.0,
    verify_tls: bool = True,
    profile_name: str | None = None,
    force: bool = False,
    app_paths: AppPaths | None = None,
) -> Path:
    """Create or update one named profile in the user config file."""

    paths = app_paths or resolve_app_paths()
    target_profile = _normalize_profile_name(profile_name)
    new_settings = _settings_from_values(
        url=url,
        token=token,
        default_format=default_format,
        default_limit=default_limit,
        timeout_seconds=timeout_seconds,
        verify_tls=verify_tls,
    )

    if force or not paths.config_path.exists():
        state = _ConfigState(
            profiles={target_profile: new_settings},
            current_profile=target_profile,
        )
    else:
        validate_file_permissions(paths.config_path)
        state = _load_config_state(paths.config_path)
        state.profiles[target_profile] = new_settings
        if not state.current_profile:
            state.current_profile = (
                state.legacy_profile_name
                or target_profile
            )

    _prepare_runtime_dirs(paths)
    _write_config_state(paths.config_path, state)
    return paths.config_path


def load_settings(
    *,
    app_paths: AppPaths | None = None,
    profile_name: str | None = None,
) -> LoadedSettings:
    """Load settings from disk, then apply environment variable overrides."""

    paths = app_paths or resolve_app_paths()
    file_exists = paths.config_path.exists()
    state: _ConfigState | None = None
    env_overrides = _load_environment_overrides()

    if file_exists:
        validate_file_permissions(paths.config_path)
        state = _load_config_state(paths.config_path)

    selected_profile_name: str | None = None
    selected_settings: NetBoxSettings | None = None
    is_legacy_profile = False

    if state is not None:
        selected_profile_name, selected_settings, is_legacy_profile = _resolve_profile_selection(
            state,
            explicit_profile_name=profile_name,
        )

    if selected_settings is None:
        if profile_name is not None:
            raise ConfigValidationError(f"Profile {profile_name!r} is not configured.")
        if not env_overrides:
            raise ConfigFileNotFoundError(
                f"No configuration found. Run `netbox profile add {DEFAULT_PROFILE_NAME}` "
                f"to create {paths.config_path}."
            )
        settings = _settings_from_mapping(env_overrides)
        source = "env"
        config_path = None
        available_profiles: tuple[str, ...] = ()
        current_profile = None
    else:
        merged = {
            **_settings_to_mapping(selected_settings),
            **env_overrides,
        }
        settings = _settings_from_mapping(merged)
        source = "file+env" if env_overrides else "file"
        config_path = paths.config_path
        available_profiles = tuple(state.profiles.keys()) if state is not None else ()
        current_profile = state.current_profile if state is not None else None

    return LoadedSettings(
        settings=settings,
        source=source,
        config_path=config_path,
        profile_name=selected_profile_name,
        current_profile=current_profile,
        available_profiles=available_profiles,
        is_legacy_profile=is_legacy_profile,
    )


def list_profiles(*, app_paths: AppPaths | None = None) -> tuple[ConfiguredProfile, ...]:
    """Return configured profiles and mark the active one."""

    paths = app_paths or resolve_app_paths()
    if not paths.config_path.exists():
        raise ConfigFileNotFoundError(
            f"No configuration found. Run `netbox profile add {DEFAULT_PROFILE_NAME}` "
            f"to create {paths.config_path}."
        )

    validate_file_permissions(paths.config_path)
    state = _load_config_state(paths.config_path)
    active_name = _default_profile_selection_name(state)

    return tuple(
        ConfiguredProfile(
            name=name,
            settings=settings,
            is_active=name == active_name,
            is_legacy=state.legacy_profile_name == name,
        )
        for name, settings in state.profiles.items()
    )


def use_profile(
    profile_name: str,
    *,
    app_paths: AppPaths | None = None,
) -> Path:
    """Persist the selected profile as the current active profile."""

    paths = app_paths or resolve_app_paths()
    if not paths.config_path.exists():
        raise ConfigFileNotFoundError(
            f"No configuration found. Run `netbox profile add {DEFAULT_PROFILE_NAME}` "
            f"to create {paths.config_path}."
        )

    validate_file_permissions(paths.config_path)
    state = _load_config_state(paths.config_path)
    target_profile = _normalize_profile_name(profile_name)
    if target_profile not in state.profiles:
        raise ConfigValidationError(f"Profile {target_profile!r} is not configured.")

    state.current_profile = target_profile
    _prepare_runtime_dirs(paths)
    _write_config_state(paths.config_path, state)
    return paths.config_path


def validate_settings(settings: NetBoxSettings) -> None:
    """Validate an in-memory settings object."""

    if not settings.url:
        raise ConfigValidationError("NetBox URL is required.")
    if not settings.token:
        raise ConfigValidationError("NetBox API token is required.")

    parsed = urlparse(settings.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigValidationError(
            "NetBox URL must be an absolute http:// or https:// URL."
        )

    if settings.default_format not in VALID_OUTPUT_FORMATS:
        raise ConfigValidationError(
            f"Unsupported default format: {settings.default_format}."
        )
    if settings.default_limit <= 0:
        raise ConfigValidationError("Default limit must be greater than zero.")
    if settings.timeout_seconds <= 0:
        raise ConfigValidationError("Timeout must be greater than zero.")


def validate_file_permissions(path: Path) -> None:
    """Ensure config files are not readable by group or others on POSIX systems."""

    if os.name != "posix":
        return

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ConfigPermissionError(
            f"Config file {path} must not be readable by group or others; expected mode 600."
        )


def _load_config_state(path: Path) -> _ConfigState:
    raw_settings = _load_file_settings(path)
    return _parse_config_state(raw_settings)


def _parse_config_state(raw_settings: Mapping[str, object]) -> _ConfigState:
    profiles_raw = raw_settings.get("profiles")
    if profiles_raw is not None:
        if not isinstance(profiles_raw, dict):
            raise ConfigValidationError("The `profiles` section must be a table of named profiles.")

        profiles: dict[str, NetBoxSettings] = {}
        for raw_name, raw_profile in profiles_raw.items():
            if not isinstance(raw_name, str):
                raise ConfigValidationError("Profile names must be strings.")
            normalized_name = raw_name.strip()
            if not normalized_name:
                raise ConfigValidationError("Profile names must not be empty.")
            if not isinstance(raw_profile, dict):
                raise ConfigValidationError(
                    f"Profile {normalized_name!r} must be a table of settings."
                )
            profiles[normalized_name] = _settings_from_mapping(
                raw_profile,
                context=f"profile {normalized_name!r}",
            )

        current_profile_raw = raw_settings.get("current_profile")
        current_profile = _normalize_optional_profile_name(current_profile_raw)
        if current_profile is not None and current_profile not in profiles:
            raise ConfigValidationError(
                f"current_profile {current_profile!r} is not defined under `profiles`."
            )

        return _ConfigState(
            profiles=profiles,
            current_profile=current_profile,
        )

    if any(key in raw_settings for key in _PROFILE_SETTING_KEYS):
        legacy_settings = _settings_from_mapping(raw_settings, context="legacy config")
        return _ConfigState(
            profiles={DEFAULT_PROFILE_NAME: legacy_settings},
            legacy_profile_name=DEFAULT_PROFILE_NAME,
        )

    return _ConfigState(profiles={})


def _resolve_profile_selection(
    state: _ConfigState,
    *,
    explicit_profile_name: str | None,
) -> tuple[str | None, NetBoxSettings | None, bool]:
    if explicit_profile_name is not None:
        normalized_name = _normalize_profile_name(explicit_profile_name)
        settings = state.profiles.get(normalized_name)
        if settings is None:
            raise ConfigValidationError(f"Profile {normalized_name!r} is not configured.")
        return normalized_name, settings, state.legacy_profile_name == normalized_name

    if state.current_profile is not None:
        settings = state.profiles.get(state.current_profile)
        if settings is not None:
            return state.current_profile, settings, False

    if state.legacy_profile_name is not None:
        settings = state.profiles.get(state.legacy_profile_name)
        if settings is not None:
            return state.legacy_profile_name, settings, True

    if len(state.profiles) == 1:
        name, settings = next(iter(state.profiles.items()))
        return name, settings, False

    if state.profiles:
        raise ConfigValidationError(
            "No active profile is set. Run `netbox profile use <name>` or pass `--profile <name>`."
        )

    return None, None, False


def _default_profile_selection_name(state: _ConfigState) -> str | None:
    if state.current_profile is not None:
        return state.current_profile
    if state.legacy_profile_name is not None:
        return state.legacy_profile_name
    if len(state.profiles) == 1:
        return next(iter(state.profiles))
    return None


def _write_config_state(path: Path, state: _ConfigState) -> None:
    path.write_text(_serialize_config_state(state), encoding="utf-8")
    os.chmod(path, CONFIG_FILE_MODE)


def _serialize_config_state(state: _ConfigState) -> str:
    lines: list[str] = []
    if state.current_profile:
        lines.append(f"current_profile = {json.dumps(state.current_profile)}")
        lines.append("")

    for index, (name, settings) in enumerate(state.profiles.items()):
        if index:
            lines.append("")
        lines.append(f"[profiles.{json.dumps(name)}]")
        lines.extend(_serialize_settings_lines(settings))

    if lines:
        lines.append("")
    return "\n".join(lines)


def _serialize_settings_lines(settings: NetBoxSettings) -> list[str]:
    return [
        f"url = {json.dumps(settings.url)}",
        f"token = {json.dumps(settings.token)}",
        f"default_format = {json.dumps(settings.default_format)}",
        f"default_limit = {settings.default_limit}",
        f"timeout_seconds = {settings.timeout_seconds}",
        f"verify_tls = {'true' if settings.verify_tls else 'false'}",
    ]


def _load_file_settings(path: Path) -> dict[str, object]:
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(f"Could not parse config file {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigValidationError(f"Config file {path} must decode to a TOML table.")
    return loaded


def _load_environment_overrides() -> dict[str, object]:
    overrides: dict[str, object] = {}

    if value := os.environ.get("NETBOX_URL"):
        overrides["url"] = value
    if value := os.environ.get("NETBOX_TOKEN"):
        overrides["token"] = value
    if value := os.environ.get("NETBOX_CLI_DEFAULT_FORMAT"):
        overrides["default_format"] = value
    if value := os.environ.get("NETBOX_CLI_DEFAULT_LIMIT"):
        overrides["default_limit"] = _parse_int_env("NETBOX_CLI_DEFAULT_LIMIT", value)
    if value := os.environ.get("NETBOX_CLI_TIMEOUT"):
        overrides["timeout_seconds"] = _parse_float_env("NETBOX_CLI_TIMEOUT", value)
    if value := os.environ.get("NETBOX_CLI_VERIFY_TLS"):
        overrides["verify_tls"] = _parse_bool_env("NETBOX_CLI_VERIFY_TLS", value)

    return overrides


def _settings_from_values(
    *,
    url: str,
    token: str,
    default_format: str,
    default_limit: int,
    timeout_seconds: float,
    verify_tls: bool,
) -> NetBoxSettings:
    settings = NetBoxSettings(
        url=url.strip(),
        token=token.strip(),
        default_format=default_format,  # type: ignore[arg-type]
        default_limit=default_limit,
        timeout_seconds=timeout_seconds,
        verify_tls=verify_tls,
    )
    validate_settings(settings)
    return settings


def _settings_from_mapping(
    raw_settings: Mapping[str, object],
    *,
    context: str = "config",
) -> NetBoxSettings:
    try:
        settings = NetBoxSettings(
            url=str(raw_settings.get("url", "")).strip(),
            token=str(raw_settings.get("token", "")).strip(),
            default_format=str(raw_settings.get("default_format", "table")),  # type: ignore[arg-type]
            default_limit=int(raw_settings.get("default_limit", 15)),
            timeout_seconds=float(raw_settings.get("timeout_seconds", 10.0)),
            verify_tls=bool(raw_settings.get("verify_tls", True)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"Invalid settings values in {context}.") from exc
    validate_settings(settings)
    return settings


def _settings_to_mapping(settings: NetBoxSettings) -> dict[str, object]:
    return {
        "url": settings.url,
        "token": settings.token,
        "default_format": settings.default_format,
        "default_limit": settings.default_limit,
        "timeout_seconds": settings.timeout_seconds,
        "verify_tls": settings.verify_tls,
    }


def _normalize_profile_name(profile_name: str | None) -> str:
    if profile_name is None:
        return DEFAULT_PROFILE_NAME
    normalized = profile_name.strip()
    if not normalized:
        raise ConfigValidationError("Profile name must not be empty.")
    return normalized


def _normalize_optional_profile_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigValidationError("current_profile must be a string.")
    normalized = value.strip()
    return normalized or None


def _prepare_runtime_dirs(paths: AppPaths) -> None:
    paths.config_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    paths.cache_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    paths.history_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)


def _resolve_config_dir() -> Path:
    override = os.environ.get("NETBOX_CLI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    config_base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_base.expanduser() / APP_NAME


def _resolve_config_path(config_dir: Path) -> Path:
    override = os.environ.get("NETBOX_CLI_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir / CONFIG_FILE_NAME


def _resolve_cache_dir() -> Path:
    override = os.environ.get("NETBOX_CLI_CACHE_DIR")
    if override:
        return Path(override).expanduser()

    cache_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_base.expanduser() / APP_NAME


def _resolve_history_dir() -> Path:
    override = os.environ.get("NETBOX_CLI_HISTORY_DIR")
    if override:
        return Path(override).expanduser()

    state_base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_base.expanduser() / APP_NAME


def _resolve_history_path(history_dir: Path) -> Path:
    override = os.environ.get("NETBOX_CLI_HISTORY_PATH")
    if override:
        return Path(override).expanduser()
    return history_dir / HISTORY_FILE_NAME


def _parse_int_env(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigValidationError(
            f"{name} must be an integer, got {value!r}."
        ) from exc


def _parse_float_env(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigValidationError(
            f"{name} must be a number, got {value!r}."
        ) from exc


def _parse_bool_env(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigValidationError(
        f"{name} must be one of true/false/1/0/yes/no, got {value!r}."
    )
