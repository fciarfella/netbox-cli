from __future__ import annotations

import json
import re
from io import StringIO

from netbox_cli.discovery import ChoiceDefinition, FilterDefinition
from netbox_cli.profiles import get_default_columns
from netbox_cli.query import QueryResult, RecordResult
from netbox_cli.render import (
    create_console,
    render_apps,
    render_filters,
    render_query_result,
    render_record_result,
    render_search_groups,
)
from netbox_cli.search import SearchGroup


class TtyBuffer(StringIO):
    def isatty(self) -> bool:
        return True


ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def make_console(*, tty: bool = False) -> tuple[object, StringIO]:
    buffer = TtyBuffer() if tty else StringIO()
    console = create_console(file=buffer, force_plain=not tty, width=120)
    return console, buffer


def strip_ansi(value: str) -> str:
    return ANSI_PATTERN.sub("", value)


def test_render_query_result_json_smoke() -> None:
    console, buffer = make_console()
    result = QueryResult(
        endpoint_path="dcim/devices",
        rows=[{"id": 1, "name": "leaf-01"}],
        total_count=1,
    )

    render_query_result(result, "json", console=console)

    payload = json.loads(buffer.getvalue())
    assert payload["endpoint_path"] == "dcim/devices"
    assert payload["results"][0]["name"] == "leaf-01"
    assert "\x1b[" not in buffer.getvalue()
    assert "?[" not in buffer.getvalue()


def test_render_query_result_json_uses_rich_highlighting_on_tty() -> None:
    console, buffer = make_console(tty=True)
    result = QueryResult(
        endpoint_path="dcim/devices",
        rows=[{"id": 1, "name": "leaf-01"}],
        total_count=1,
    )

    render_query_result(result, "json", console=console)

    output = buffer.getvalue()
    assert "\x1b[" in output
    payload = json.loads(strip_ansi(output))
    assert payload["endpoint_path"] == "dcim/devices"
    assert payload["results"][0]["name"] == "leaf-01"


def test_render_query_result_json_projects_cols_when_requested() -> None:
    console, buffer = make_console()
    result = QueryResult(
        endpoint_path="dcim/devices",
        rows=[{"id": 1, "name": "leaf-01", "site": {"name": "dc1"}}],
        total_count=1,
    )

    render_query_result(
        result,
        "json",
        columns=("name", "site", "status"),
        project_columns=True,
        console=console,
    )

    payload = json.loads(buffer.getvalue())
    assert payload["results"] == [{"name": "leaf-01", "site": "dc1", "status": "-"}]


def test_render_query_result_numbered_json_includes_index() -> None:
    console, buffer = make_console()
    result = QueryResult(
        endpoint_path="dcim/devices",
        rows=[{"id": 1, "name": "leaf-01"}],
        total_count=1,
    )

    render_query_result(result, "json", numbered=True, console=console)

    payload = json.loads(buffer.getvalue())
    assert payload["results"][0]["index"] == 1


def test_render_query_result_csv_smoke() -> None:
    console, buffer = make_console()
    result = QueryResult(
        endpoint_path="dcim/devices",
        rows=[{"id": 1, "name": "leaf-01", "status": {"value": "active"}}],
        total_count=1,
    )

    render_query_result(result, "csv", console=console)

    output = buffer.getvalue()
    assert "id,name,site,rack,role,status" in output
    assert "leaf-01" in output


def test_dns_default_profile_includes_value_column() -> None:
    assert get_default_columns("plugins/netbox-dns/records") == (
        "id",
        "zone",
        "name",
        "type",
        "value",
        "status",
    )


def test_render_dns_query_result_uses_dns_columns() -> None:
    console, buffer = make_console()
    result = QueryResult(
        endpoint_path="plugins/netbox-dns/records",
        rows=[
            {
                "id": 10,
                "zone": {"name": "example.com"},
                "name": "gw1",
                "type": "A",
                "value": "198.51.100.10",
                "status": "active",
            }
        ],
        total_count=1,
    )

    render_query_result(result, "table", console=console)

    output = buffer.getvalue()
    assert "ZONE" in output
    assert "TYPE" in output
    assert "VALUE" in output
    assert "198.51.100.10" in output


def test_render_filters_table_smoke() -> None:
    console, buffer = make_console()
    filters = [
        FilterDefinition(
            name="status",
            description="Device status",
            required=False,
            value_type="string",
            choices=(ChoiceDefinition(value="active", label="Active"),),
        )
    ]

    render_filters(filters, "table", console=console)

    output = buffer.getvalue()
    assert "FILTER" in output
    assert "status" in output


def test_render_record_result_table_smoke() -> None:
    console, buffer = make_console()
    result = RecordResult(
        endpoint_path="dcim/devices",
        row={"id": 1, "name": "leaf-01", "status": {"value": "active"}},
    )

    render_record_result(result, "table", console=console)

    output = buffer.getvalue()
    assert "PROPERTY" in output
    assert "leaf-01" in output


def test_render_search_groups_json_smoke() -> None:
    console, buffer = make_console()
    groups = [
        SearchGroup(
            title="Devices",
            endpoint_path="dcim/devices",
            rows=[{"id": 1, "name": "router-01"}],
            total_count=1,
        )
    ]

    render_search_groups(groups, "json", console=console)

    payload = json.loads(buffer.getvalue())
    assert payload[0]["endpoint_path"] == "dcim/devices"
    assert payload[0]["results"][0]["name"] == "router-01"
    assert "\x1b[" not in buffer.getvalue()


def test_render_search_groups_json_projects_cols_when_requested() -> None:
    console, buffer = make_console()
    groups = [
        SearchGroup(
            title="Devices",
            endpoint_path="dcim/devices",
            rows=[{"id": 1, "name": "router-01", "site": {"name": "dc1"}}],
            total_count=1,
        )
    ]

    render_search_groups(
        groups,
        "json",
        columns=("id", "name", "site", "status"),
        project_columns=True,
        console=console,
    )

    payload = json.loads(buffer.getvalue())
    assert payload[0]["results"] == [
        {"id": "1", "name": "router-01", "site": "dc1", "status": "-"}
    ]


def test_render_search_groups_table_shows_open_hint_when_numbered() -> None:
    console, buffer = make_console()
    groups = [
        SearchGroup(
            title="Devices",
            endpoint_path="dcim/devices",
            rows=[{"id": 1, "name": "router-01"}],
            total_count=1,
        )
    ]

    render_search_groups(groups, "table", numbered=True, console=console)

    output = buffer.getvalue()
    assert "INDEX" in output
    assert "open <index>" in output


def test_render_dns_search_group_uses_dns_columns() -> None:
    console, buffer = make_console()
    groups = [
        SearchGroup(
            title="DNS Records",
            endpoint_path="plugins/netbox-dns/records",
            rows=[
                {
                    "id": 10,
                    "zone": {"name": "example.com"},
                    "name": "gw1",
                    "type": "A",
                    "value": "198.51.100.10",
                    "status": "active",
                }
            ],
            total_count=1,
        )
    ]

    render_search_groups(groups, "table", console=console)

    output = buffer.getvalue()
    assert "ZONE" in output
    assert "TYPE" in output
    assert "VALUE" in output
    assert "198.51.100.10" in output


def test_render_plain_output_does_not_contain_raw_ansi_fragments() -> None:
    console, buffer = make_console()
    groups = [
        SearchGroup(
            title="Devices",
            endpoint_path="dcim/devices",
            rows=[{"id": 1, "name": "router-01"}],
            total_count=1,
        )
    ]

    render_search_groups(groups, "table", numbered=True, console=console)

    output = buffer.getvalue()
    assert "\x1b[" not in output
    assert "?[" not in output
    assert "Tip: run `open <index>` to inspect a result." in output


def test_create_console_enables_color_for_tty_stream() -> None:
    console, _ = make_console(tty=True)

    assert console.color_system is not None


def test_render_apps_csv_smoke() -> None:
    console, buffer = make_console()

    render_apps(["dcim", "ipam"], "csv", console=console)

    output = buffer.getvalue()
    assert "app" in output
    assert "dcim" in output
