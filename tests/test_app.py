from __future__ import annotations

import json
from pathlib import Path

from netbox_cli import __version__
from netbox_cli.app import cli
from netbox_cli.discovery import ResolvedListPath
from netbox_cli.errors import APIError
from netbox_cli.query import QueryResult, RecordResult
from netbox_cli.settings import AppPaths
from netbox_cli.search import SearchGroup
from netbox_cli.settings import LoadedSettings, NetBoxSettings


class StubRuntimeClient:
    def __init__(
        self,
        *,
        options_payload: dict[str, object] | None = None,
        options_error: Exception | None = None,
        detail_row: dict[str, object] | None = None,
    ) -> None:
        self.options_payload = (
            {"actions": {"POST": {}}}
            if options_payload is None
            else options_payload
        )
        self.options_error = options_error
        self.detail_row = {"id": 1} if detail_row is None else detail_row

    def get_options(
        self,
        endpoint_path: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, object]:
        del endpoint_path, use_cache
        if self.options_error is not None:
            raise self.options_error
        return self.options_payload

    def get_json(self, path: str, *, params=None):  # type: ignore[no-untyped-def]
        del path, params
        return dict(self.detail_row)


def patch_list_resolution(monkeypatch, app_module, *, kind: str, path: str | None = None) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        app_module,
        "resolve_list_path",
        lambda client, raw_path: ResolvedListPath(kind=kind, path=path),
    )


def patch_runtime(  # type: ignore[no-untyped-def]
    monkeypatch,
    app_module,
    *,
    client=None,
    default_format: str = "table",
):
    runtime_client = StubRuntimeClient() if client is None else client
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
                settings=NetBoxSettings(
                    url="https://netbox.example.com",
                    token="abc",
                    default_format=default_format,  # type: ignore[arg-type]
                ),
                source="file",
            ),
            runtime_client,
        ),
    )
    return runtime_client


def test_package_import_exposes_version() -> None:
    assert __version__ == "0.5.1"


def test_cli_help_bootstraps(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "NetBox CLI for discovery" in result.stdout
    assert "list" in result.stdout
    assert "create" in result.stdout
    assert "update" in result.stdout
    assert "init" in result.stdout
    assert "cache" in result.stdout
    assert "shell" in result.stdout
    assert "\n│ apps" not in result.stdout
    assert "\n│ endpoints" not in result.stdout


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


def test_create_command_help_mentions_yes(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["create", "--help"])

    assert result.exit_code == 0
    assert "--yes" in result.stdout
    assert "Execute the POST request." in result.stdout
    assert "live writes." in result.stdout


def test_update_command_help_mentions_yes(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["update", "--help"])

    assert result.exit_code == 0
    assert "--yes" in result.stdout
    assert "Execute the PATCH request." in result.stdout
    assert "live writes." in result.stdout


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


def test_legacy_exploration_commands_are_unavailable(cli_runner) -> None:
    apps_result = cli_runner.invoke(cli, ["apps"])
    endpoints_result = cli_runner.invoke(cli, ["endpoints", "dcim"])

    assert apps_result.exit_code != 0
    assert "No such command 'apps'" in apps_result.output
    assert endpoints_result.exit_code != 0
    assert "No such command 'endpoints'" in endpoints_result.output


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


def test_list_command_with_endpoint_path_renders_records(cli_runner, monkeypatch) -> None:
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

    result = cli_runner.invoke(cli, ["list", "dcim/devices", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["endpoint_path"] == "dcim/devices"
    assert payload["results"][0]["name"] == "leaf-01"
    assert captured["filters"] == []


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


def test_create_command_with_inline_payload(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    runtime_client = patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "create_record",
        lambda client, request: captured.update(
            {"client": client, "request": request}
        ) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        [
            "create",
            "dcim/devices",
            "name=leaf-01",
            "status=active",
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert captured["client"] is runtime_client
    assert request.method == "POST"  # type: ignore[union-attr]
    assert request.endpoint_path == "dcim/devices"  # type: ignore[union-attr]
    assert request.payload == {"name": "leaf-01", "status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["name"] == "leaf-01"


def test_create_command_with_json_file(cli_runner, monkeypatch, tmp_path: Path) -> None:
    from netbox_cli import app as app_module

    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"name": "leaf-01", "status": "active"}', encoding="utf-8")

    captured: dict[str, object] = {}
    patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "create_record",
        lambda client, request: captured.update({"request": request}) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(payload_path), "--yes", "--format", "json"],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.payload == {"name": "leaf-01", "status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["status"] == "active"


def test_create_command_with_yaml_file(cli_runner, monkeypatch, tmp_path: Path) -> None:
    from netbox_cli import app as app_module

    payload_path = tmp_path / "payload.yaml"
    payload_path.write_text("name: leaf-01\nstatus: active\n", encoding="utf-8")

    captured: dict[str, object] = {}
    patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "create_record",
        lambda client, request: captured.update({"request": request}) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(payload_path), "--yes", "--format", "json"],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.payload == {"name": "leaf-01", "status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["name"] == "leaf-01"


def test_create_command_rejects_missing_payload(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["create", "dcim/devices"])

    assert result.exit_code != 0
    assert "Choose exactly one payload input method" in result.stderr


def test_create_command_requires_yes_for_live_write(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("create_record should not be called without --yes")

    monkeypatch.setattr(app_module, "create_record", fail_if_called)

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "name=leaf-01"],
    )

    assert result.exit_code != 0
    assert "Live CLI writes require --yes." in result.stderr
    assert "--dry-run" in result.stderr


def test_create_command_rejects_inline_id_field(cli_runner) -> None:
    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "id=1", "name=leaf-01"],
    )

    assert result.exit_code != 0
    assert "Create does not accept id=<id> as an inline field." in result.stderr


def test_create_command_rejects_missing_required_fields_before_live_write(
    cli_runner,
    monkeypatch,
) -> None:
    from netbox_cli import app as app_module

    runtime_client = StubRuntimeClient(
        options_payload={
            "actions": {
                "POST": {
                    "name": {"required": True},
                    "slug": {"required": True},
                    "id": {"required": True, "read_only": True},
                }
            }
        }
    )
    patch_runtime(monkeypatch, app_module, client=runtime_client)

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("create_record should not be called when required fields are missing")

    monkeypatch.setattr(app_module, "create_record", fail_if_called)

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/sites", "name=mynewsite", "--yes"],
    )

    assert result.exit_code != 0
    assert "Missing required fields for dcim/sites: slug" in result.stderr


def test_create_command_with_all_required_fields_proceeds_normally(
    cli_runner,
    monkeypatch,
) -> None:
    from netbox_cli import app as app_module

    runtime_client = StubRuntimeClient(
        options_payload={
            "actions": {
                "POST": {
                    "name": {"required": True},
                    "slug": {"required": True},
                }
            }
        }
    )
    captured: dict[str, object] = {}
    patch_runtime(monkeypatch, app_module, client=runtime_client)
    monkeypatch.setattr(
        app_module,
        "create_record",
        lambda client, request: captured.update(
            {"client": client, "request": request}
        ) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "lab", "slug": "lab"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/sites", "name=lab", "slug=lab", "--yes", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["client"] is runtime_client
    request = captured["request"]
    assert request.payload == {"name": "lab", "slug": "lab"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["slug"] == "lab"


def test_create_command_table_output_includes_created_summary(
    cli_runner,
    monkeypatch,
) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "create_record",
        lambda client, request: RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 22, "name": "lab", "slug": "lab"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/sites", "name=lab", "slug=lab", "--yes"],
    )

    assert result.exit_code == 0
    assert "Created dcim/sites #22" in result.stdout
    assert "dcim/sites detail" in result.stdout


def test_create_command_rejects_inline_payload_with_file(cli_runner, tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"name": "leaf-01"}', encoding="utf-8")

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "name=leaf-01", "--file", str(payload_path)],
    )

    assert result.exit_code != 0
    assert "Choose exactly one payload input method" in result.stderr


def test_create_command_rejects_invalid_file_path(cli_runner, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(missing_path)],
    )

    assert result.exit_code != 0
    assert "Invalid file path" in result.stderr


def test_create_command_rejects_invalid_json_file(cli_runner, tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{broken", encoding="utf-8")

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(payload_path)],
    )

    assert result.exit_code != 0
    assert "Invalid JSON" in result.stderr


def test_create_command_rejects_invalid_yaml_file(cli_runner, tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.yaml"
    payload_path.write_text("name: [broken\n", encoding="utf-8")

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(payload_path)],
    )

    assert result.exit_code != 0
    assert "Invalid YAML" in result.stderr


def test_create_command_rejects_unsupported_file_extension(cli_runner, tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.txt"
    payload_path.write_text("name=leaf-01", encoding="utf-8")

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/devices", "--file", str(payload_path)],
    )

    assert result.exit_code != 0
    assert "Unsupported payload file extension" in result.stderr


def test_create_command_preserves_server_validation_when_options_are_unavailable(
    cli_runner,
    monkeypatch,
) -> None:
    from netbox_cli import app as app_module

    runtime_client = StubRuntimeClient(options_error=APIError("OPTIONS unavailable."))
    patch_runtime(monkeypatch, app_module, client=runtime_client)

    def raise_server_validation(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise APIError("slug: This field is required.")

    monkeypatch.setattr(app_module, "create_record", raise_server_validation)

    result = cli_runner.invoke(
        cli,
        ["create", "dcim/sites", "name=mynewsite", "--yes"],
    )

    assert result.exit_code != 0
    assert "slug: This field is required." in result.stderr


def test_update_command_with_id_and_inline_payload(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    captured: dict[str, object] = {}
    runtime_client = patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "update_record",
        lambda client, request: captured.update(
            {"client": client, "request": request}
        ) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        [
            "update",
            "dcim/devices",
            "id=1",
            "name=leaf-01",
            "status=active",
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert captured["client"] is runtime_client
    assert request.method == "PATCH"  # type: ignore[union-attr]
    assert request.object_id == "1"  # type: ignore[union-attr]
    assert request.payload == {"name": "leaf-01", "status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["id"] == 1


def test_update_command_with_json_file(cli_runner, monkeypatch, tmp_path: Path) -> None:
    from netbox_cli import app as app_module

    payload_path = tmp_path / "patch.json"
    payload_path.write_text('{"status": "active"}', encoding="utf-8")

    captured: dict[str, object] = {}
    patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "update_record",
        lambda client, request: captured.update({"request": request}) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        [
            "update",
            "dcim/devices",
            "id=1",
            "--file",
            str(payload_path),
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.object_id == "1"  # type: ignore[union-attr]
    assert request.payload == {"status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["status"] == "active"


def test_update_command_with_yaml_file(cli_runner, monkeypatch, tmp_path: Path) -> None:
    from netbox_cli import app as app_module

    payload_path = tmp_path / "patch.yml"
    payload_path.write_text("status: active\n", encoding="utf-8")

    captured: dict[str, object] = {}
    patch_runtime(monkeypatch, app_module)
    monkeypatch.setattr(
        app_module,
        "update_record",
        lambda client, request: captured.update({"request": request}) or RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 1, "name": "leaf-01", "status": "active"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        [
            "update",
            "dcim/devices",
            "id=1",
            "--file",
            str(payload_path),
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.object_id == "1"  # type: ignore[union-attr]
    assert request.payload == {"status": "active"}  # type: ignore[union-attr]
    assert json.loads(result.stdout)["name"] == "leaf-01"


def test_update_command_rejects_missing_id(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["update", "dcim/devices", "status=active"])

    assert result.exit_code != 0
    assert "Update requires exactly one id=<id> selector." in result.stderr


def test_update_command_requires_yes_for_live_write(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("update_record should not be called without --yes")

    monkeypatch.setattr(app_module, "update_record", fail_if_called)

    result = cli_runner.invoke(
        cli,
        ["update", "dcim/devices", "id=1", "status=active"],
    )

    assert result.exit_code != 0
    assert "Live CLI writes require --yes." in result.stderr
    assert "--dry-run" in result.stderr


def test_update_command_rejects_missing_payload(cli_runner) -> None:
    result = cli_runner.invoke(cli, ["update", "dcim/devices", "id=1"])

    assert result.exit_code != 0
    assert "Choose exactly one payload input method" in result.stderr


def test_update_command_rejects_multiple_ids(cli_runner) -> None:
    result = cli_runner.invoke(
        cli,
        ["update", "dcim/devices", "id=1", "id=2", "status=active"],
    )

    assert result.exit_code != 0
    assert "exactly one id=<id>" in result.stderr


def test_update_command_rejects_inline_payload_with_file(cli_runner, tmp_path: Path) -> None:
    payload_path = tmp_path / "patch.json"
    payload_path.write_text('{"status": "active"}', encoding="utf-8")

    result = cli_runner.invoke(
        cli,
        [
            "update",
            "dcim/devices",
            "id=1",
            "status=active",
            "--file",
            str(payload_path),
        ],
    )

    assert result.exit_code != 0
    assert "Choose exactly one payload input method" in result.stderr


def test_update_command_table_output_includes_changed_fields_summary(
    cli_runner,
    monkeypatch,
) -> None:
    from netbox_cli import app as app_module

    runtime_client = StubRuntimeClient(detail_row={"id": 22, "name": "old-name", "slug": "lab"})
    patch_runtime(monkeypatch, app_module, client=runtime_client)
    monkeypatch.setattr(
        app_module,
        "update_record",
        lambda client, request: RecordResult(
            endpoint_path=request.endpoint_path,
            row={"id": 22, "name": "new-name", "slug": "lab"},
        ),
    )

    result = cli_runner.invoke(
        cli,
        ["update", "dcim/sites", "id=22", "name=new-name", "--yes"],
    )

    assert result.exit_code == 0
    assert "Updated dcim/sites #22" in result.stdout
    assert "Updated fields" in result.stdout
    assert "old-name" in result.stdout
    assert "new-name" in result.stdout
    assert result.stdout.index("Updated fields") < result.stdout.index("dcim/sites detail")


def test_create_command_dry_run_does_not_send_post(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("create_record should not be called during dry-run")

    monkeypatch.setattr(app_module, "create_record", fail_if_called)

    result = cli_runner.invoke(
        cli,
        [
            "create",
            "dcim/devices",
            "name=leaf-01",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "endpoint": "dcim/devices",
        "method": "POST",
        "payload": {"name": "leaf-01"},
    }


def test_create_command_dry_run_table_preview_is_readable(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)

    result = cli_runner.invoke(
        cli,
        [
            "create",
            "dcim/devices",
            "name=leaf-01",
            "status=active",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Dry-run preview" in result.stdout
    assert "method" in result.stdout
    assert "endpoint" in result.stdout
    assert "Payload" in result.stdout
    assert '"name": "leaf-01"' in result.stdout
    assert '"status": "active"' in result.stdout


def test_update_command_dry_run_does_not_send_patch(cli_runner, monkeypatch) -> None:
    from netbox_cli import app as app_module

    patch_runtime(monkeypatch, app_module)

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("update_record should not be called during dry-run")

    monkeypatch.setattr(app_module, "update_record", fail_if_called)

    result = cli_runner.invoke(
        cli,
        [
            "update",
            "dcim/devices",
            "id=1",
            "status=active",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "endpoint": "dcim/devices",
        "method": "PATCH",
        "payload": {"status": "active"},
        "target_id": "1",
    }


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
