from __future__ import annotations

import json
from pathlib import Path

from netbox_cli import __version__
from netbox_cli.app import cli
from netbox_cli.discovery import ResolvedListPath
from netbox_cli.query import QueryResult, RecordResult
from netbox_cli.settings import AppPaths
from netbox_cli.search import SearchGroup
from netbox_cli.settings import LoadedSettings, NetBoxSettings


def patch_list_resolution(monkeypatch, app_module, *, kind: str, path: str | None = None) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        app_module,
        "resolve_list_path",
        lambda client, raw_path: ResolvedListPath(kind=kind, path=path),
    )


def test_package_import_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_bootstraps(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Read-only NetBox CLI" in result.stdout
    assert "init" in result.stdout
    assert "cache" in result.stdout
    assert "shell" in result.stdout


def test_cli_version_flag_bootstraps(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_config_subcommand_help_bootstraps(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["config", "--help"])

    assert result.exit_code == 0
    assert "test" in result.stdout


def test_cache_subcommand_help_bootstraps(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["cache", "--help"])

    assert result.exit_code == 0
    assert "clear" in result.stdout


def test_shell_command_launches_repl(cli_runner, monkeypatch, tmp_path: Path) -> None:
    from netbox_cli import app as app_module

    launched: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=tmp_path / "config",
                config_path=tmp_path / "config" / "config.toml",
                cache_dir=tmp_path / "cache",
                history_dir=tmp_path / "state",
                history_path=tmp_path / "state" / "shell-history",
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )

    def fake_launch_shell(client, *, history_path, initial_state) -> None:  # type: ignore[no-untyped-def]
        launched["history_path"] = history_path
        launched["initial_state"] = initial_state
        launched["client"] = client

    monkeypatch.setattr(app_module, "launch_shell", fake_launch_shell)

    result = cli_runner.invoke(cli, ["shell"])

    assert result.exit_code == 0
    assert launched["history_path"] == tmp_path / "state" / "shell-history"
    assert launched["initial_state"].current_path == "/"  # type: ignore[union-attr]


def test_apps_command_renders_json(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(app_module, "list_apps", lambda client: ["dcim", "ipam"])

    result = cli_runner.invoke(cli, ["apps", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == ["dcim", "ipam"]


def test_endpoints_command_renders_json(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "list_endpoints",
        lambda client, app_name: [
            type("Endpoint", (), {"app": app_name, "endpoint": "devices", "path": "dcim/devices", "url": "https://netbox.example.com/api/dcim/devices/"})(),
            type("Endpoint", (), {"app": app_name, "endpoint": "sites", "path": "dcim/sites", "url": "https://netbox.example.com/api/dcim/sites/"})(),
        ],
    )

    result = cli_runner.invoke(cli, ["endpoints", "dcim", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["path"] for item in payload] == ["dcim/devices", "dcim/sites"]


def test_list_command_without_path_renders_apps(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(app_module, "list_apps", lambda client: ["dcim", "ipam"])

    result = cli_runner.invoke(cli, ["list", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == ["dcim", "ipam"]


def test_list_command_with_app_path_renders_endpoints(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="app", path="dcim")
    monkeypatch.setattr(
        app_module,
        "list_endpoints",
        lambda client, app_name: [
            type("Endpoint", (), {"app": app_name, "endpoint": "devices", "path": "dcim/devices", "url": "https://netbox.example.com/api/dcim/devices/"})(),
            type("Endpoint", (), {"app": app_name, "endpoint": "sites", "path": "dcim/sites", "url": "https://netbox.example.com/api/dcim/sites/"})(),
        ],
    )

    result = cli_runner.invoke(cli, ["list", "dcim", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["path"] for item in payload] == ["dcim/devices", "dcim/sites"]


def test_list_command_rejects_unknown_path(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module
    from netbox_cli.errors import InvalidEndpointError

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "resolve_list_path",
        lambda client, raw_path: (_ for _ in ()).throw(
            InvalidEndpointError(
                "Unknown NetBox path: unknown. Use `netbox list` to view apps or `netbox list <app>` to view endpoints."
            )
        ),
    )

    result = cli_runner.invoke(cli, ["list", "unknown"])

    assert result.exit_code != 0
    assert "Unknown NetBox path: unknown." in result.stderr


def test_list_command_renders_json(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"endpoint_path": endpoint_path, "filters": filters, "limit": limit}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(cli, ["list", "dcim/devices", "status=active", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["endpoint_path"] == "dcim/devices"
    assert payload["results"][0]["name"] == "leaf-01"
    assert captured["filters"] == [("status", "active")]
    assert "\x1b[" not in result.stdout
    assert "?[" not in result.stdout


def test_list_command_rejects_incomplete_filter_locally(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("list_records should not be called for incomplete filters")

    monkeypatch.setattr(app_module, "list_records", fail_if_called)

    result = cli_runner.invoke(cli, ["list", "dcim/devices", "status="])

    assert result.exit_code != 0
    assert "Invalid value:" in result.stderr
    assert "Incomplete filter: status=." in result.stderr


def test_list_command_passes_cols_override(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01", "site": "dc1", "status": "active"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "render_query_result",
        lambda result, output_format, *, columns=None, project_columns=False, numbered=False, console=None: captured.update(
            {
                "columns": columns,
                "project_columns": project_columns,
                "numbered": numbered,
                "output_format": output_format,
            }
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "q=router01", "--cols", "name,site,status", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["columns"] == ("name", "site", "status")
    assert captured["project_columns"] is True
    assert captured["numbered"] is False


def test_list_command_normalizes_cols_whitespace(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "render_query_result",
        lambda result, output_format, *, columns=None, project_columns=False, numbered=False, console=None: captured.update(
            {"columns": columns}
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "q=router01", "--cols", "name, site, status"],
    )

    assert result.exit_code == 0
    assert captured["columns"] == ("name", "site", "status")


def test_list_command_rejects_invalid_cols_value(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "q=router01", "--cols", "name,,status"],
    )

    assert result.exit_code != 0
    assert "Column names must not be empty" in result.output


def test_list_command_preserves_repeated_filters(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"endpoint_path": endpoint_path, "filters": filters, "limit": limit}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "site=dc1", "site=lab", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["endpoint_path"] == "dcim/devices"
    assert captured["filters"] == [("site", "dc1"), ("site", "lab")]


def test_list_command_preserves_repeated_filters_with_bare_term(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"endpoint_path": endpoint_path, "filters": filters, "limit": limit}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "router01-edge"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "router01", "site=dc1", "site=lab", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["filters"] == [("q", "router01"), ("site", "dc1"), ("site", "lab")]


def test_list_command_supports_bare_search_term(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "router01-edge"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(cli, ["list", "dcim/devices", "router01", "--format", "json"])

    assert result.exit_code == 0
    assert captured["filters"] == [("q", "router01")]


def test_list_command_joins_multiple_bare_terms_into_q(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "foo bar"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(cli, ["list", "dcim/devices", "foo", "bar", "--format", "json"])

    assert result.exit_code == 0
    assert captured["filters"] == [("q", "foo bar")]


def test_list_command_mixes_bare_term_with_explicit_filters(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "router01"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "router01", "status=active", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["filters"] == [("q", "router01"), ("status", "active")]


def test_list_command_does_not_duplicate_explicit_q(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    patch_list_resolution(monkeypatch, app_module, kind="endpoint", path="dcim/devices")
    monkeypatch.setattr(
        app_module,
        "list_records",
        lambda client, endpoint_path, filters, limit: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "router01"}],
            total_count=1,
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["list", "dcim/devices", "q=router01", "status=active", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["filters"] == [("q", "router01"), ("status", "active")]


def test_get_command_rejects_repeated_lookup_filters(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )

    result = cli_runner.invoke(cli, ["get", "dcim/devices", "site=dc1", "site=lab"])

    assert result.exit_code != 0
    assert "Repeated lookup filter" in result.output


def test_get_command_renders_json(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "get_record",
        lambda client, endpoint_path, filters: RecordResult(
            endpoint_path=endpoint_path,
            row={"id": 1, "name": "leaf-01"},
        ),
    )

    result = cli_runner.invoke(cli, ["get", "dcim/devices", "name=leaf-01", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["name"] == "leaf-01"


def test_search_command_renders_json(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "global_search",
        lambda client, term, limit_per_group: [
            SearchGroup(
                title="Devices",
                endpoint_path="dcim/devices",
                rows=[{"id": 1, "name": "router-01"}],
                total_count=1,
            )
        ],
    )

    result = cli_runner.invoke(cli, ["search", "router", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["endpoint_path"] == "dcim/devices"
    assert "\x1b[" not in result.stdout
    assert "?[" not in result.stdout


def test_search_command_passes_cols_override(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda: (
            AppPaths(
                config_dir=Path("/tmp/config"),
                config_path=Path("/tmp/config/config.toml"),
                cache_dir=Path("/tmp/cache"),
                history_dir=Path("/tmp/state"),
                history_path=Path("/tmp/state/shell-history"),
            ),
            LoadedSettings(
                settings=NetBoxSettings(url="https://netbox.example.com", token="abc"),
                source="file",
            ),
            object(),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "global_search",
        lambda client, term, limit_per_group: [
            SearchGroup(
                title="Devices",
                endpoint_path="dcim/devices",
                rows=[{"id": 1, "name": "router01", "site": "dc1", "status": "active"}],
                total_count=1,
            )
        ],
    )
    monkeypatch.setattr(
        app_module,
        "render_search_groups",
        lambda groups, output_format, *, columns=None, project_columns=False, numbered=False, console=None: captured.update(
            {
                "columns": columns,
                "project_columns": project_columns,
                "numbered": numbered,
                "output_format": output_format,
            }
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["search", "router01", "--cols", "id,name,site,status", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["columns"] == ("id", "name", "site", "status")
    assert captured["project_columns"] is True
    assert captured["numbered"] is False


def test_cache_clear_command_reports_removed_files(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    monkeypatch.setattr(
        app_module,
        "resolve_app_paths",
        lambda: AppPaths(
            config_dir=Path("/tmp/config"),
            config_path=Path("/tmp/config/config.toml"),
            cache_dir=Path("/tmp/cache"),
            history_dir=Path("/tmp/state"),
            history_path=Path("/tmp/state/shell-history"),
        ),
    )
    monkeypatch.setattr(app_module, "clear_metadata_cache", lambda cache_dir: 3)

    result = cli_runner.invoke(cli, ["cache", "clear"])

    assert result.exit_code == 0
    assert "Cleared 3 cache file(s)" in result.stdout
    assert "\x1b[" not in result.stdout
    assert "?[" not in result.stdout
