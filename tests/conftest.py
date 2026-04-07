from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from netbox_cli.cache import MetadataCache
from netbox_cli.settings import AppPaths
from netbox_cli.settings import NetBoxSettings


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_paths_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in (
        "NETBOX_CLI_CONFIG",
        "NETBOX_CLI_CONFIG_DIR",
        "NETBOX_CLI_CACHE_DIR",
        "NETBOX_CLI_HISTORY_DIR",
        "NETBOX_CLI_HISTORY_PATH",
        "NETBOX_URL",
        "NETBOX_TOKEN",
        "NETBOX_CLI_DEFAULT_FORMAT",
        "NETBOX_CLI_DEFAULT_LIMIT",
        "NETBOX_CLI_TIMEOUT",
        "NETBOX_CLI_VERIFY_TLS",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)

    return tmp_path


@pytest.fixture
def temp_app_paths(temp_paths_root: Path) -> AppPaths:
    config_dir = temp_paths_root / "config-home" / "netbox-cli"
    cache_dir = temp_paths_root / "cache-home" / "netbox-cli"
    history_dir = temp_paths_root / "state-home" / "netbox-cli"

    return AppPaths(
        config_dir=config_dir,
        config_path=config_dir / "config.toml",
        cache_dir=cache_dir,
        history_dir=history_dir,
        history_path=history_dir / "shell-history",
    )


@pytest.fixture
def netbox_settings() -> NetBoxSettings:
    return NetBoxSettings(
        url="https://netbox.example.com",
        token="abc123token",
    )


@pytest.fixture
def metadata_cache(temp_app_paths: AppPaths) -> MetadataCache:
    return MetadataCache(temp_app_paths.cache_dir)
