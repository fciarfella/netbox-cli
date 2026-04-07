from __future__ import annotations

import json
from io import StringIO

import pytest

from netbox_cli.discovery import FilterDefinition
from netbox_cli.errors import CommandUsageError
from netbox_cli.query import QueryResult, RecordResult
from netbox_cli.repl.commands import execute_command, parse_command
from netbox_cli.render import create_console
from netbox_cli.repl.state import ShellState
from netbox_cli.search import SearchGroup
from netbox_cli.settings import RecordReference


def make_console() -> tuple[object, StringIO]:
    buffer = StringIO()
    console = create_console(file=buffer, force_plain=True, width=120)
    return console, buffer


def test_parse_command_handles_quotes() -> None:
    command = parse_command('search "router 01"')

    assert command is not None
    assert command.name == "search"
    assert command.args == ("router 01",)


def test_help_output_is_plain_when_captured() -> None:
    console, buffer = make_console()

    execute_command(ShellState(), "help", object(), console=console)

    output = buffer.getvalue()
    assert "Read-only NetBox shell" in output
    assert "\x1b[" not in output
    assert "?[" not in output


def test_pwd_is_no_longer_a_supported_command() -> None:
    console, _ = make_console()

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(ShellState(), "pwd", object(), console=console)

    assert "Unknown command 'pwd'" in str(exc_info.value)


def test_clear_is_no_longer_a_supported_command() -> None:
    console, _ = make_console()

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(ShellState(), "clear", object(), console=console)

    assert "Unknown command 'clear'" in str(exc_info.value)


def test_ls_is_no_longer_a_supported_command() -> None:
    console, _ = make_console()

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(ShellState(), "ls", object(), console=console)

    assert "Unknown command 'ls'" in str(exc_info.value)


def test_navigation_commands_update_state(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState()

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: [])
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd dcim", object(), console=console)
    assert state.current_path == "/dcim"

    execute_command(state, "cd devices", object(), console=console)
    assert state.current_path == "/dcim/devices"

    execute_command(state, "cd ..", object(), console=console)
    assert state.current_path == "/dcim"

    execute_command(state, "cd", object(), console=console)
    assert state.current_path == "/"


def test_cd_with_no_args_goes_home(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: [])
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd", object(), console=console)

    assert state.current_path == "/"


def test_cd_special_paths_behave_like_a_shell(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: [])
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd .", object(), console=console)
    assert state.current_path == "/dcim/devices"

    execute_command(state, "cd ..", object(), console=console)
    assert state.current_path == "/dcim"

    execute_command(state, "cd /", object(), console=console)
    assert state.current_path == "/"


def test_cd_supports_relative_and_absolute_paths(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: [])
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd ../sites", object(), console=console)
    assert state.current_path == "/dcim/sites"

    execute_command(state, "cd /plugins", object(), console=console)
    assert state.current_path == "/plugins"


def test_cd_supports_repeated_parent_traversal(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/plugins/netbox_dns/records")

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: [])
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd ../..", object(), console=console)
    assert state.current_path == "/plugins"

    execute_command(state, "cd ../../..", object(), console=console)
    assert state.current_path == "/"


def test_plugin_path_navigation_resolves_step_by_step(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState()

    monkeypatch.setattr(
        commands_module,
        "list_endpoints",
        lambda client, path: [] if path in {"plugins", "plugins/netbox_dns"} else [],
    )
    monkeypatch.setattr(commands_module, "list_filters", lambda client, path: [])

    execute_command(state, "cd /plugins", object(), console=console)
    execute_command(state, "cd netbox_dns", object(), console=console)
    execute_command(state, "cd records", object(), console=console)

    assert state.current_path == "/plugins/netbox_dns/records"


def test_format_limit_and_cols_update_state() -> None:
    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    execute_command(state, "format json", object(), console=console)
    execute_command(state, "limit 25", object(), console=console)
    execute_command(state, "cols name,status", object(), console=console)

    assert state.output_format == "json"
    assert state.limit == 25
    assert state.columns == ("name", "status")


def test_list_root_delegates_to_app_discovery(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState()
    captured: dict[str, object] = {}

    monkeypatch.setattr(commands_module, "list_apps", lambda client: ["dcim", "ipam"])
    monkeypatch.setattr(
        commands_module,
        "render_apps",
        lambda apps, output_format, *, console: captured.update(
            {"apps": apps, "output_format": output_format}
        ),
    )

    execute_command(state, "list", object(), console=console)

    assert captured["apps"] == ["dcim", "ipam"]
    assert captured["output_format"] == "table"


def test_list_app_context_delegates_to_endpoint_discovery(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim")
    captured: dict[str, object] = {}

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: ["devices", "sites"])
    monkeypatch.setattr(
        commands_module,
        "render_endpoints",
        lambda endpoints, output_format, *, console: captured.update(
            {"endpoints": endpoints, "output_format": output_format}
        ),
    )

    execute_command(state, "list", object(), console=console)

    assert captured["endpoints"] == ["devices", "sites"]
    assert captured["output_format"] == "table"


def test_list_plugin_app_context_delegates_to_endpoint_discovery(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/plugins/netbox_dns")
    captured: dict[str, object] = {}

    monkeypatch.setattr(commands_module, "list_endpoints", lambda client, path: ["records"])
    monkeypatch.setattr(
        commands_module,
        "render_endpoints",
        lambda endpoints, output_format, *, console: captured.update(
            {"endpoints": endpoints, "output_format": output_format}
        ),
    )

    execute_command(state, "list", object(), console=console)

    assert captured["endpoints"] == ["records"]
    assert captured["output_format"] == "table"


def test_list_command_delegates_to_query_service(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {
                "service_endpoint_path": endpoint_path,
                "service_filters": filters,
                "service_limit": limit,
            }
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: captured.update(
            {
                "endpoint_path": result.endpoint_path,
                "output_format": output_format,
                "columns": columns,
                "numbered": numbered,
            }
        ),
    )

    execute_command(state, "list status=active", object(), console=console)

    assert captured["endpoint_path"] == "dcim/devices"
    assert captured["service_endpoint_path"] == "dcim/devices"
    assert captured["service_filters"] == [("status", "active")]
    assert captured["service_limit"] == 10
    assert captured["output_format"] == "table"
    assert captured["numbered"] is True
    assert state.last_results[0].endpoint_path == "dcim/devices"


def test_list_command_supports_bare_search_term(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list fifo", object(), console=console)

    assert captured["filters"] == [("q", "fifo")]


def test_list_command_json_output_is_plain_when_captured(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, buffer = make_console()
    state = ShellState(current_path="/dcim/devices", output_format="json", limit=10)

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )

    execute_command(state, "list fifo", object(), console=console)

    payload = json.loads(buffer.getvalue())
    assert payload["endpoint_path"] == "dcim/devices"
    assert payload["results"][0]["name"] == "fifo"
    assert "\x1b[" not in buffer.getvalue()
    assert "?[" not in buffer.getvalue()


def test_list_command_supports_quoted_search_term(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "router 01"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, 'list "router 01"', object(), console=console)

    assert captured["filters"] == [("q", "router 01")]


def test_list_command_mixes_bare_term_with_explicit_filters(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list fifo status=active", object(), console=console)

    assert captured["filters"] == [("q", "fifo"), ("status", "active")]


def test_list_command_does_not_duplicate_explicit_q(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list q=fifo status=active", object(), console=console)

    assert captured["filters"] == [("q", "fifo"), ("status", "active")]


def test_list_command_joins_multiple_bare_terms_into_q(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "foo bar"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list foo bar", object(), console=console)

    assert captured["filters"] == [("q", "foo bar")]


def test_list_command_rejects_incomplete_explicit_filter_locally(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    called = False

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        raise AssertionError("list_records should not be called for incomplete filters")

    monkeypatch.setattr(commands_module, "list_records", fail_if_called)

    with pytest.raises(
        CommandUsageError,
        match=r"Incomplete filter: status=\. Choose a value or remove the filter\.",
    ):
        execute_command(state, "list router01 status=", object(), console=console)

    assert called is False


def test_list_command_preserves_repeated_filter_keys(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "leaf-01"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list site=dc1 site=lab", object(), console=console)

    assert captured["filters"] == [("site", "dc1"), ("site", "lab")]


def test_list_command_preserves_repeated_filter_keys_with_bare_term(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list fifo site=dc1 site=lab", object(), console=console)

    assert captured["filters"] == [("q", "fifo"), ("site", "dc1"), ("site", "lab")]


def test_list_command_preserves_repeated_filter_keys_with_multiple_bare_terms(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "foo bar"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list foo bar site=dc1 site=lab", object(), console=console)

    assert captured["filters"] == [("q", "foo bar"), ("site", "dc1"), ("site", "lab")]


def test_list_command_does_not_inject_duplicate_q_when_repeated_filters_present(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", limit=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_records",
        lambda client, endpoint_path, filters=None, limit=None: captured.update(
            {"filters": filters}
        ) or QueryResult(
            endpoint_path=endpoint_path,
            rows=[{"id": 1, "name": "fifo"}],
            total_count=1,
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_query_result",
        lambda result, output_format, *, columns, numbered, console: None,
    )

    execute_command(state, "list q=fifo site=dc1 site=lab", object(), console=console)

    assert captured["filters"] == [("q", "fifo"), ("site", "dc1"), ("site", "lab")]


def test_filters_command_delegates_to_discovery_service(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "list_filters",
        lambda client, endpoint_path: [FilterDefinition(name="status")],
    )
    monkeypatch.setattr(
        commands_module,
        "render_filters",
        lambda filters, output_format, *, console: captured.update(
            {"count": len(filters), "output_format": output_format}
        ),
    )

    execute_command(state, "filters", object(), console=console)

    assert captured == {"count": 1, "output_format": "table"}


def test_get_command_delegates_to_query_service(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices", output_format="json")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "get_record",
        lambda client, endpoint_path, filters: captured.update(
            {"service_endpoint_path": endpoint_path, "service_filters": filters}
        ) or RecordResult(
            endpoint_path=endpoint_path,
            row={"id": 1, "name": "leaf-01"},
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_record_result",
        lambda result, output_format, *, console: captured.update(
            {"rendered_output_format": output_format, "row": result.row}
        ),
    )

    execute_command(state, "get name=leaf-01", object(), console=console)

    assert captured["service_endpoint_path"] == "dcim/devices"
    assert captured["service_filters"] == {"name": "leaf-01"}
    assert captured["rendered_output_format"] == "json"


def test_get_command_supports_quoted_filter_values(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "get_record",
        lambda client, endpoint_path, filters: captured.update({"filters": filters}) or RecordResult(
            endpoint_path=endpoint_path,
            row={"id": 1, "name": "edge router"},
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_record_result",
        lambda result, output_format, *, console: None,
    )

    execute_command(state, 'get name="edge router"', object(), console=console)

    assert captured["filters"] == {"name": "edge router"}


def test_get_command_keeps_bare_term_strict() -> None:
    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(state, "get fifo", object(), console=console)

    assert "key=value" in str(exc_info.value)


def test_get_command_rejects_repeated_lookup_filters() -> None:
    console, _ = make_console()
    state = ShellState(current_path="/dcim/devices")

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(state, "get site=dc1 site=lab", object(), console=console)

    assert "Repeated lookup filter" in str(exc_info.value)


def test_search_command_stores_results_for_open(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(limit=5)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "global_search",
        lambda client, term, limit_per_group: captured.update(
            {"term": term, "limit_per_group": limit_per_group}
        ) or [
            SearchGroup(
                title="Devices",
                endpoint_path="dcim/devices",
                rows=[{"id": 7, "name": "router-01"}],
                total_count=1,
            )
        ],
    )
    monkeypatch.setattr(
        commands_module,
        "render_search_groups",
        lambda groups, output_format, *, numbered, console: captured.update(
            {
                "groups": groups,
                "output_format": output_format,
                "numbered": numbered,
            }
        ),
    )

    execute_command(state, "search router", object(), console=console)

    assert captured["output_format"] == "table"
    assert captured["numbered"] is True
    assert captured["term"] == "router"
    assert captured["limit_per_group"] == 5
    assert state.last_results == [
        RecordReference(
            endpoint_path="dcim/devices",
            object_id=7,
            display="router-01",
            payload={"id": 7, "name": "router-01"},
        )
    ]


def test_open_command_fetches_detail_and_updates_state(monkeypatch) -> None:
    from netbox_cli.repl import commands as commands_module

    console, _ = make_console()
    state = ShellState(
        current_path="/",
        last_results=[
            RecordReference(
                endpoint_path="dcim/devices",
                object_id=11,
                display="leaf-01",
                payload={"id": 11, "name": "leaf-01"},
            )
        ],
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        commands_module,
        "get_record_by_id",
        lambda client, endpoint_path, object_id: RecordResult(
            endpoint_path=endpoint_path,
            row={"id": object_id, "name": "leaf-01"},
        ),
    )
    monkeypatch.setattr(
        commands_module,
        "render_record_result",
        lambda result, output_format, *, console: captured.update(
            {
                "endpoint_path": result.endpoint_path,
                "row": result.row,
                "output_format": output_format,
            }
        ),
    )

    execute_command(state, "open 1", object(), console=console)

    assert state.current_path == "/dcim/devices"
    assert captured["endpoint_path"] == "dcim/devices"
    assert captured["row"]["id"] == 11


def test_open_command_rejects_missing_results() -> None:
    console, _ = make_console()
    state = ShellState()

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(state, "open 1", object(), console=console)

    assert "No numbered results" in str(exc_info.value)


def test_open_command_rejects_out_of_range_index() -> None:
    console, _ = make_console()
    state = ShellState(
        last_results=[
            RecordReference(
                endpoint_path="dcim/devices",
                object_id=11,
                display="leaf-01",
                payload={"id": 11, "name": "leaf-01"},
            )
        ]
    )

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(state, "open 2", object(), console=console)

    assert "between 1 and 1" in str(exc_info.value)


def test_open_command_rejects_non_numeric_index() -> None:
    console, _ = make_console()
    state = ShellState(
        last_results=[
            RecordReference(
                endpoint_path="dcim/devices",
                object_id=11,
                display="leaf-01",
                payload={"id": 11, "name": "leaf-01"},
            )
        ]
    )

    with pytest.raises(CommandUsageError) as exc_info:
        execute_command(state, "open first", object(), console=console)

    assert "requires a numeric index" in str(exc_info.value)
