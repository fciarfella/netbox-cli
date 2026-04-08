from __future__ import annotations

import json
import re
from io import StringIO

from netbox_cli.discovery import ChoiceDefinition, FilterDefinition
from netbox_cli.mutations import MutationRequest
from netbox_cli.profiles import get_default_columns
from netbox_cli.query import QueryResult, RecordResult
from netbox_cli.render import (
    create_console,
    render_apps,
    render_create_result,
    render_filters,
    render_mutation_confirmation_preview,
    render_query_result,
    render_record_result,
    render_search_groups,
    render_update_result,
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


def test_render_create_result_table_includes_created_summary() -> None:
    console, buffer = make_console()
    request = MutationRequest(
        endpoint_path="dcim/sites",
        method="POST",
        payload={"name": "lab", "slug": "lab"},
    )
    result = RecordResult(
        endpoint_path="dcim/sites",
        row={"id": 22, "name": "lab", "slug": "lab"},
    )

    render_create_result(request, result, "table", console=console)

    output = buffer.getvalue()
    assert "Created dcim/sites #22" in output
    assert "dcim/sites detail" in output


def test_render_update_result_table_shows_summary_before_detail() -> None:
    console, buffer = make_console()
    request = MutationRequest(
        endpoint_path="dcim/sites",
        method="PATCH",
        payload={"name": "new-name"},
        object_id="22",
    )
    before_row = {"id": 22, "name": "old-name", "slug": "lab"}
    result = RecordResult(
        endpoint_path="dcim/sites",
        row={"id": 22, "name": "new-name", "slug": "lab"},
    )

    render_update_result(request, before_row, result, "table", console=console)

    output = buffer.getvalue()
    assert "Updated dcim/sites #22" in output
    assert "Updated fields" in output
    assert "old-name" in output
    assert "new-name" in output
    assert output.index("Updated fields") < output.index("dcim/sites detail")


def test_render_update_result_tty_styles_changed_values() -> None:
    console, buffer = make_console(tty=True)
    request = MutationRequest(
        endpoint_path="dcim/sites",
        method="PATCH",
        payload={"name": "new-name"},
        object_id="22",
    )
    before_row = {"id": 22, "name": "old-name"}
    result = RecordResult(
        endpoint_path="dcim/sites",
        row={"id": 22, "name": "new-name"},
    )

    render_update_result(request, before_row, result, "table", console=console)

    output = buffer.getvalue()
    assert "\x1b[" in output
    stripped = strip_ansi(output)
    assert "Updated fields" in stripped
    assert "old-name" in stripped
    assert "new-name" in stripped


def test_render_mutation_confirmation_preview_for_update_shows_planned_changes() -> None:
    console, buffer = make_console()
    request = MutationRequest(
        endpoint_path="dcim/sites",
        method="PATCH",
        payload={"name": "new-name"},
        object_id="22",
    )

    render_mutation_confirmation_preview(
        request,
        before_row={"id": 22, "name": "old-name"},
        console=console,
    )

    output = buffer.getvalue()
    assert "Planned changes" in output
    assert "old-name" in output
    assert "new-name" in output


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
