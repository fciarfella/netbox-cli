from __future__ import annotations

from netbox_cli.repl.state import ShellState
from netbox_cli.settings import NetBoxSettings


def test_shell_state_uses_cli_defaults() -> None:
    state = ShellState.from_settings(
        NetBoxSettings(
            url="https://netbox.example.com",
            token="abc123",
            default_format="json",
            default_limit=25,
        )
    )

    assert state.current_path == "/"
    assert state.output_format == "json"
    assert state.limit == 25


def test_shell_state_resolves_paths_and_navigation() -> None:
    state = ShellState()

    state.set_path("dcim")
    assert state.current_path == "/dcim"
    assert state.is_app_context is True

    state.set_path("devices")
    assert state.current_path == "/dcim/devices"
    assert state.is_endpoint_context is True

    state.go_back()
    assert state.current_path == "/dcim"

    state.set_path("/plugins/netbox_dns/records")
    assert state.current_path == "/plugins/netbox_dns/records"
    assert state.is_endpoint_context is True

    state.go_back()
    assert state.current_path == "/plugins/netbox_dns"
    assert state.is_app_context is True

    state.go_home()
    assert state.current_path == "/"
    assert state.is_root_context is True


def test_shell_state_tracks_endpoint_column_overrides() -> None:
    state = ShellState()
    state.set_path("/dcim/devices")

    assert state.columns == ("id", "name", "site", "rack", "role", "status")

    state.set_columns(("name", "status"))
    assert state.columns == ("name", "status")

    state.set_columns(None)
    assert state.columns == ("id", "name", "site", "rack", "role", "status")
