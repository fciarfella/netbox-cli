from __future__ import annotations

import os
from pathlib import Path

import pytest

from netbox_cli.config import (
    DEFAULT_PROFILE_NAME,
    init_config,
    list_profiles,
    load_settings,
    resolve_app_paths,
    use_profile,
    validate_file_permissions,
)
from netbox_cli.errors import ConfigPermissionError, ConfigValidationError


def test_init_config_writes_file_and_loads_it(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        profile_name="nb01",
        app_paths=paths,
    )

    assert paths.config_path.exists()
    if os.name == "posix":
        assert oct(paths.config_path.stat().st_mode & 0o777) == "0o600"

    loaded = load_settings(app_paths=paths)
    assert loaded.source == "file"
    assert loaded.profile_name == "nb01"
    assert loaded.current_profile == "nb01"
    assert loaded.settings.url == "https://netbox.example.com"
    assert loaded.settings.token == "abc123token"
    assert paths.history_dir.exists()

    config_text = paths.config_path.read_text(encoding="utf-8")
    assert 'current_profile = "nb01"' in config_text
    assert '[profiles."nb01"]' in config_text


def test_init_config_uses_default_profile_name_when_not_provided(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        app_paths=paths,
    )

    loaded = load_settings(app_paths=paths)

    assert loaded.profile_name == DEFAULT_PROFILE_NAME
    assert loaded.current_profile == DEFAULT_PROFILE_NAME


def test_init_config_adds_profiles_without_replacing_current(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox01.example.com",
        token="token-1",
        profile_name="nb01",
        app_paths=paths,
    )
    init_config(
        url="https://netbox02.example.com",
        token="token-2",
        profile_name="nb02",
        app_paths=paths,
    )

    loaded = load_settings(app_paths=paths)

    assert loaded.profile_name == "nb01"
    assert loaded.current_profile == "nb01"
    assert loaded.available_profiles == ("nb01", "nb02")


def test_load_settings_prefers_explicit_profile_over_current_profile(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox01.example.com",
        token="token-1",
        profile_name="nb01",
        app_paths=paths,
    )
    init_config(
        url="https://netbox02.example.com",
        token="token-2",
        profile_name="nb02",
        app_paths=paths,
    )

    loaded = load_settings(app_paths=paths, profile_name="nb02")

    assert loaded.profile_name == "nb02"
    assert loaded.current_profile == "nb01"
    assert loaded.settings.url == "https://netbox02.example.com"


def test_load_settings_applies_environment_overrides(
    temp_app_paths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = temp_app_paths
    init_config(
        url="https://netbox.example.com",
        token="abc123token",
        profile_name="nb01",
        app_paths=paths,
    )

    monkeypatch.setenv("NETBOX_URL", "https://override.example.com")
    monkeypatch.setenv("NETBOX_TOKEN", "override-token")
    monkeypatch.setenv("NETBOX_CLI_DEFAULT_LIMIT", "25")

    loaded = load_settings(app_paths=paths)
    assert loaded.source == "file+env"
    assert loaded.profile_name == "nb01"
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
        profile_name="nb01",
        app_paths=paths,
    )

    monkeypatch.setenv("NETBOX_CLI_DEFAULT_FORMAT", "json")
    monkeypatch.setenv("NETBOX_CLI_VERIFY_TLS", "false")

    loaded = load_settings(app_paths=paths)

    assert loaded.source == "file+env"
    assert loaded.profile_name == "nb01"
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
    assert loaded.profile_name is None
    assert loaded.settings.url == "https://env-only.example.com"


def test_list_profiles_marks_active_profile(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox01.example.com",
        token="token-1",
        profile_name="nb01",
        app_paths=paths,
    )
    init_config(
        url="https://netbox02.example.com",
        token="token-2",
        profile_name="nb02",
        app_paths=paths,
    )

    profiles = list_profiles(app_paths=paths)

    assert [profile.name for profile in profiles] == ["nb01", "nb02"]
    assert profiles[0].is_active is True
    assert profiles[1].is_active is False


def test_use_profile_switches_current_profile(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox01.example.com",
        token="token-1",
        profile_name="nb01",
        app_paths=paths,
    )
    init_config(
        url="https://netbox02.example.com",
        token="token-2",
        profile_name="nb02",
        app_paths=paths,
    )

    use_profile("nb02", app_paths=paths)
    loaded = load_settings(app_paths=paths)

    assert loaded.profile_name == "nb02"
    assert loaded.current_profile == "nb02"


def test_use_profile_rejects_unknown_name(temp_app_paths) -> None:
    paths = temp_app_paths

    init_config(
        url="https://netbox01.example.com",
        token="token-1",
        profile_name="nb01",
        app_paths=paths,
    )

    with pytest.raises(ConfigValidationError):
        use_profile("missing", app_paths=paths)


def test_load_settings_supports_legacy_single_profile_config(temp_app_paths) -> None:
    paths = temp_app_paths
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text(
        "\n".join(
            [
                'url = "https://legacy.example.com"',
                'token = "legacy-token"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(paths.config_path, 0o600)

    loaded = load_settings(app_paths=paths)
    profiles = list_profiles(app_paths=paths)

    assert loaded.profile_name == DEFAULT_PROFILE_NAME
    assert loaded.current_profile is None
    assert loaded.is_legacy_profile is True
    assert loaded.settings.url == "https://legacy.example.com"
    assert profiles[0].name == DEFAULT_PROFILE_NAME
    assert profiles[0].is_active is True
    assert profiles[0].is_legacy is True


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
