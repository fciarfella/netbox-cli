from __future__ import annotations

import os
from pathlib import Path

import pytest

from netbox_cli.config import init_config, load_settings, resolve_app_paths, validate_file_permissions
from netbox_cli.errors import ConfigPermissionError, ConfigValidationError


def test_init_config_writes_file_and_loads_it(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        app_paths=paths,
    )

    assert paths.config_path.exists()
    if os.name == "posix":
        assert oct(paths.config_path.stat().st_mode & 0o777) == "0o600"

    loaded = load_settings(app_paths=paths)
    assert loaded.source == "file"
    assert loaded.settings.url == "https://netbox.example.com"
    assert loaded.settings.token == "abc123token"
    assert paths.history_dir.exists()


def test_load_settings_applies_environment_overrides(
    temp_app_paths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = temp_app_paths
    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        app_paths=paths,
    )

    monkeypatch.setenv("NETBOX_URL", "https://override.example.com")
    monkeypatch.setenv("NETBOX_TOKEN", "override-token")
    monkeypatch.setenv("NETBOX_CLI_DEFAULT_LIMIT", "25")

    loaded = load_settings(app_paths=paths)
    assert loaded.source == "file+env"
    assert loaded.settings.url == "https://override.example.com"
    assert loaded.settings.token == "override-token"
    assert loaded.settings.default_limit == 25


def test_load_settings_applies_format_and_tls_environment_overrides(
    temp_app_paths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = temp_app_paths
    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        app_paths=paths,
    )

    monkeypatch.setenv("NETBOX_CLI_DEFAULT_FORMAT", "json")
    monkeypatch.setenv("NETBOX_CLI_VERIFY_TLS", "false")

    loaded = load_settings(app_paths=paths)

    assert loaded.source == "file+env"
    assert loaded.settings.default_format == "json"
    assert loaded.settings.verify_tls is False


def test_load_settings_supports_environment_only(
    temp_app_paths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = temp_app_paths

    monkeypatch.setenv("NETBOX_URL", "https://env-only.example.com")
    monkeypatch.setenv("NETBOX_TOKEN", "env-only-token")

    loaded = load_settings(app_paths=paths)
    assert loaded.source == "env"
    assert loaded.config_path is None
    assert loaded.settings.url == "https://env-only.example.com"


def test_validate_file_permissions_rejects_world_readable_file(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("Permission checks are POSIX-specific.")

    config_path = tmp_path / "config.toml"
    config_path.write_text("url = \"https://netbox.example.com\"\n", encoding="utf-8")
    os.chmod(config_path, 0o644)

    with pytest.raises(ConfigPermissionError):
        validate_file_permissions(config_path)


def test_init_config_rejects_invalid_url(temp_app_paths) -> None:
    paths = temp_app_paths

    with pytest.raises(ConfigValidationError):
        init_config(url="not-a-url", token="abc123token", app_paths=paths)


def test_resolve_app_paths_uses_separate_locations(
    temp_paths_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(temp_paths_root / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(temp_paths_root / "xdg-cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(temp_paths_root / "xdg-state"))

    paths = resolve_app_paths()

    assert paths.config_path == temp_paths_root / "xdg-config" / "netbox-cli" / "config.toml"
    assert paths.cache_dir == temp_paths_root / "xdg-cache" / "netbox-cli"
    assert paths.history_dir == temp_paths_root / "xdg-state" / "netbox-cli"
    assert paths.history_path == temp_paths_root / "xdg-state" / "netbox-cli" / "shell-history"
