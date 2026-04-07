"""Configuration loading, validation, and persistence."""

from __future__ import annotations

import json
import os
import stat
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigFileNotFoundError, ConfigPermissionError, ConfigValidationError
from .settings import AppPaths, LoadedSettings, NetBoxSettings

APP_NAME = "netbox-cli"
CONFIG_FILE_NAME = "config.toml"
HISTORY_FILE_NAME = "shell-history"
CONFIG_FILE_MODE = 0o600
DIR_MODE = 0o700
VALID_OUTPUT_FORMATS = {"table", "json", "csv"}


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
    force: bool = False,
    app_paths: AppPaths | None = None,
) -> Path:
    """Create a new config file in the user-specific config directory."""

    paths = app_paths or resolve_app_paths()
    if paths.config_path.exists() and not force:
        raise ConfigValidationError(
            f"Config already exists at {paths.config_path}. Re-run with --force to overwrite it."
        )

    settings = NetBoxSettings(
        url=url.strip(),
        token=token.strip(),
        default_format=default_format,  # type: ignore[arg-type]
        default_limit=default_limit,
        timeout_seconds=timeout_seconds,
        verify_tls=verify_tls,
    )
    validate_settings(settings)

    paths.config_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    paths.cache_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    paths.history_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)

    paths.config_path.write_text(_serialize_settings(settings), encoding="utf-8")
    os.chmod(paths.config_path, CONFIG_FILE_MODE)
    return paths.config_path


def load_settings(*, app_paths: AppPaths | None = None) -> LoadedSettings:
    """Load settings from disk, then apply environment variable overrides."""

    paths = app_paths or resolve_app_paths()
    file_settings: dict[str, object] = {}
    file_exists = paths.config_path.exists()

    if file_exists:
        validate_file_permissions(paths.config_path)
        file_settings = _load_file_settings(paths.config_path)

    env_overrides = _load_environment_overrides()
    raw_settings = {**file_settings, **env_overrides}

    if not raw_settings:
        raise ConfigFileNotFoundError(
            f"No configuration found. Run `netbox init` to create {paths.config_path}."
        )

    settings = NetBoxSettings(
        url=str(raw_settings.get("url", "")).strip(),
        token=str(raw_settings.get("token", "")).strip(),
        default_format=str(raw_settings.get("default_format", "table")),  # type: ignore[arg-type]
        default_limit=int(raw_settings.get("default_limit", 15)),
        timeout_seconds=float(raw_settings.get("timeout_seconds", 10.0)),
        verify_tls=bool(raw_settings.get("verify_tls", True)),
    )
    validate_settings(settings)

    if file_exists and env_overrides:
        source = "file+env"
    elif file_exists:
        source = "file"
    else:
        source = "env"

    return LoadedSettings(
        settings=settings,
        source=source,
        config_path=paths.config_path if file_exists else None,
    )


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


def _serialize_settings(settings: NetBoxSettings) -> str:
    return "\n".join(
        [
            f"url = {json.dumps(settings.url)}",
            f"token = {json.dumps(settings.token)}",
            f"default_format = {json.dumps(settings.default_format)}",
            f"default_limit = {settings.default_limit}",
            f"timeout_seconds = {settings.timeout_seconds}",
            f"verify_tls = {'true' if settings.verify_tls else 'false'}",
            "",
        ]
    )


def _load_file_settings(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(f"Could not parse config file {path}: {exc}") from exc


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
