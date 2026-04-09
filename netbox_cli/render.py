"""Terminal rendering helpers built on Rich."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from rich import box
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .discovery import DiscoveredEndpoint, FilterDefinition
from .mutations import MutationRequest
from .profiles import get_default_columns
from .query import QueryResult, RecordResult, get_record_field, stringify_value
from .search import SearchGroup
from .settings import AppPaths, ConfiguredProfile, LoadedSettings, NetBoxSettings, OutputFormat


def create_console(
    *,
    file: TextIO | None = None,
    stderr: bool = False,
    force_plain: bool | None = None,
    width: int | None = None,
) -> Console:
    """Create a Rich console that respects whether the target stream is a TTY."""

    stream = file if file is not None else (sys.stderr if stderr else sys.stdout)
    is_tty = _stream_is_tty(stream)
    use_styling = is_tty and not bool(force_plain)
    console = Console(
        file=stream,
        stderr=stderr,
        force_terminal=use_styling,
        color_system="auto" if use_styling else None,
        no_color=not use_styling,
        width=width,
    )
    if use_styling and console.color_system is None:
        console = Console(
            file=stream,
            stderr=stderr,
            force_terminal=True,
            color_system="standard",
            no_color=False,
            width=width,
        )
    return console


def get_stdout_console(*, force_plain: bool | None = None) -> Console:
    """Return a console bound to the current stdout policy."""

    return create_console(force_plain=force_plain)


def get_stderr_console(*, force_plain: bool | None = None) -> Console:
    """Return a console bound to the current stderr policy."""

    return create_console(stderr=True, force_plain=force_plain)


def print_error(message: str) -> None:
    get_stderr_console().print(f"[bold red]Error:[/] {message}")


def print_warning(message: str) -> None:
    get_stdout_console().print(f"[bold yellow]Warning:[/] {message}")


def print_success(message: str) -> None:
    get_stdout_console().print(f"[bold green]{message}[/]")


@dataclass(frozen=True, slots=True)
class MutationFieldSummary:
    field: str
    before: str
    after: str
    changed: bool


def render_config_created(
    paths: AppPaths,
    settings: NetBoxSettings,
    *,
    profile_name: str | None = None,
    current_profile: str | None = None,
) -> None:
    console = get_stdout_console()
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Config", str(paths.config_path))
    if profile_name is not None:
        table.add_row("Profile", profile_name)
    if current_profile is not None:
        table.add_row("Active profile", current_profile)
    table.add_row("URL", settings.url)
    table.add_row("Token", mask_secret(settings.token))
    table.add_row("Cache", str(paths.cache_dir))
    table.add_row("History dir", str(paths.history_dir))
    table.add_row("History", str(paths.history_path))
    console.print(Panel.fit(table, title="Config written", border_style="green"))


def render_config_test(loaded: LoadedSettings, api_root: dict[str, object]) -> None:
    console = get_stdout_console()
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Source", loaded.source)
    if loaded.profile_name is not None:
        table.add_row("Profile", loaded.profile_name)
    table.add_row("Config", str(loaded.config_path) if loaded.config_path else "<environment>")
    table.add_row("Apps discovered", ", ".join(sorted(str(key) for key in api_root.keys())) or "<none>")
    console.print(Panel.fit(table, title="Config test passed", border_style="green"))


def render_paths(paths: AppPaths) -> None:
    console = get_stdout_console()
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Config", str(paths.config_path))
    table.add_row("Cache", str(paths.cache_dir))
    table.add_row("History dir", str(paths.history_dir))
    table.add_row("History", str(paths.history_path))
    console.print(Panel.fit(table, title="Runtime paths", border_style="blue"))


def render_profiles(
    profiles: Sequence[ConfiguredProfile],
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    table = Table(title="Configured Profiles", box=box.SIMPLE_HEAVY)
    table.add_column("ACTIVE", justify="center")
    table.add_column("PROFILE")
    table.add_column("URL", overflow="fold")
    table.add_column("NOTE", overflow="fold")

    for profile in profiles:
        note = "legacy fallback" if profile.is_legacy else ""
        table.add_row(
            "[bold green]*[/]" if profile.is_active else "",
            profile.name,
            profile.settings.url,
            note,
        )

    console.print(table)


def render_apps(
    apps: Sequence[str],
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    if output_format == "json":
        _write_json(console, list(apps))
        return
    if output_format == "csv":
        _write_csv(console, [{"app": app_name} for app_name in apps], ("app",))
        return

    table = Table(title="NetBox Apps", box=box.SIMPLE_HEAVY)
    table.add_column("APP", overflow="fold")
    for app_name in apps:
        table.add_row(app_name)
    console.print(table)


def render_endpoints(
    endpoints: Sequence[DiscoveredEndpoint],
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    rows = [
        {
            "app": endpoint.app,
            "endpoint": endpoint.endpoint,
            "path": endpoint.path,
            "url": endpoint.url,
        }
        for endpoint in endpoints
    ]

    if output_format == "json":
        _write_json(console, rows)
        return
    if output_format == "csv":
        _write_csv(console, rows, ("app", "endpoint", "path", "url"))
        return

    table = Table(title="Discovered Endpoints", box=box.SIMPLE_HEAVY)
    table.add_column("ENDPOINT")
    table.add_column("PATH")
    for row in rows:
        table.add_row(row["endpoint"], row["path"])
    console.print(table)


def render_filters(
    filters: Sequence[FilterDefinition],
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    json_rows = [
        {
            "name": filter_def.name,
            "required": filter_def.required,
            "type": filter_def.value_type or "",
            "choices": [
                {"value": choice.value, "label": choice.label}
                for choice in filter_def.choices
            ],
            "description": filter_def.description,
        }
        for filter_def in filters
    ]
    table_rows = [
        {
            "name": filter_def.name,
            "required": filter_def.required,
            "type": filter_def.value_type or "",
            "choices": ", ".join(choice.label for choice in filter_def.choices),
            "description": filter_def.description,
        }
        for filter_def in filters
    ]

    if output_format == "json":
        _write_json(console, json_rows)
        return
    if output_format == "csv":
        _write_csv(console, table_rows, ("name", "required", "type", "choices", "description"))
        return

    table = Table(title="Available Filters", box=box.SIMPLE_HEAVY)
    table.add_column("FILTER")
    table.add_column("TYPE")
    table.add_column("REQUIRED")
    table.add_column("CHOICES")
    table.add_column("DESCRIPTION", overflow="fold")
    for row in table_rows:
        table.add_row(
            row["name"],
            stringify_value(row["type"]) or "-",
            "yes" if row["required"] else "no",
            row["choices"] or "-",
            row["description"] or "-",
        )
    console.print(table)


def render_query_result(
    result: QueryResult,
    output_format: OutputFormat,
    *,
    columns: Sequence[str] | None = None,
    project_columns: bool = False,
    numbered: bool = False,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    selected_columns = tuple(columns or get_default_columns(result.endpoint_path))
    display_rows = _with_row_numbers(result.rows) if numbered else list(result.rows)
    projected_rows = (
        _project_rows(display_rows, ("index", *selected_columns) if numbered else selected_columns)
        if project_columns
        else display_rows
    )

    if output_format == "json":
        _write_json(
            console,
            {
                "endpoint_path": result.endpoint_path,
                "total_count": result.total_count,
                "results": projected_rows,
            },
        )
        return
    if output_format == "csv":
        csv_columns = ("index", *selected_columns) if numbered else selected_columns
        csv_rows = (
            projected_rows
            if project_columns
            else _rows_for_columns(display_rows, csv_columns)
        )
        _write_csv(console, csv_rows, csv_columns)
        return

    title = f"{result.endpoint_path} ({len(result.rows)} shown, {result.total_count} matched)"
    table_columns = ("index", *selected_columns) if numbered else selected_columns
    table = _build_table(table_columns, title=title)
    for row in display_rows:
        table.add_row(*_row_cells(row, table_columns))
    console.print(table)
    if numbered:
        _print_open_hint(console)


def render_record_result(
    result: RecordResult,
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    if output_format == "json":
        _write_json(console, result.row)
        return
    if output_format == "csv":
        detail_rows = [
            {"property": key, "value": stringify_value(value)}
            for key, value in result.row.items()
        ]
        _write_csv(console, detail_rows, ("property", "value"))
        return

    table = Table(title=f"{result.endpoint_path} detail", box=box.SIMPLE_HEAVY)
    table.add_column("PROPERTY")
    table.add_column("VALUE", overflow="fold")
    for key, value in result.row.items():
        table.add_row(str(key), stringify_value(value) or "-")
    console.print(table)


def render_create_result(
    request: MutationRequest,
    result: RecordResult,
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    if output_format != "table":
        render_record_result(result, output_format, console=console)
        return

    console.print(_mutation_status_text("Created", request.endpoint_path, result.row))
    render_record_result(result, output_format, console=console)


def render_update_result(
    request: MutationRequest,
    before_row: dict[str, Any] | None,
    result: RecordResult,
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    if output_format != "table":
        render_record_result(result, output_format, console=console)
        return

    console.print(_mutation_status_text("Updated", request.endpoint_path, result.row))
    if before_row is not None:
        changes = _field_summaries_for_result(
            before_row,
            result.row,
            request.payload.keys(),
        )
        console.print(_build_change_table(changes, title="Updated fields"))
    render_record_result(result, output_format, console=console)


def render_mutation_confirmation_preview(
    request: MutationRequest,
    *,
    before_row: dict[str, Any] | None = None,
    console: Console | None = None,
) -> None:
    """Render a human-friendly confirmation preview before a live write."""

    console = _resolve_console(console)
    if request.method == "POST":
        console.print(_build_payload_table(request.payload, title="New fields"))
        return

    if before_row is None:
        return
    changes = _field_summaries_for_payload(before_row, request.payload)
    console.print(_build_change_table(changes, title="Planned changes"))


def mutation_confirmation_prompt(request: MutationRequest) -> Text:
    """Return a friendly confirmation prompt for a live mutation."""

    if request.method == "POST":
        return Text(f"Create new object in {request.endpoint_path}? [y/N]")

    object_label = request.object_id or "?"
    return Text(f"Update {request.endpoint_path} #{object_label}? [y/N]")


def render_mutation_preview(
    request: MutationRequest,
    output_format: OutputFormat,
    *,
    console: Console | None = None,
) -> None:
    """Render a dry-run preview for a create or update request."""

    console = _resolve_console(console)
    preview_payload: dict[str, Any] = {
        "method": request.method,
        "endpoint": request.endpoint_path,
        "payload": request.payload,
    }
    if request.object_id is not None:
        preview_payload["target_id"] = request.object_id

    if output_format == "json":
        _write_json(console, preview_payload)
        return
    if output_format == "csv":
        detail_rows = [
            {"property": "method", "value": request.method},
            {"property": "endpoint", "value": request.endpoint_path},
        ]
        if request.object_id is not None:
            detail_rows.append({"property": "target_id", "value": request.object_id})
        detail_rows.append(
            {
                "property": "payload",
                "value": json.dumps(
                    request.payload,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            }
        )
        _write_csv(console, detail_rows, ("property", "value"))
        return

    table = Table(title="Dry-run preview", box=box.SIMPLE_HEAVY)
    table.add_column("PROPERTY")
    table.add_column("VALUE", overflow="fold")
    table.add_row("method", request.method)
    table.add_row("endpoint", request.endpoint_path)
    if request.object_id is not None:
        table.add_row("target_id", request.object_id)
    console.print(table)
    console.print(
        Panel(
            _json_renderable(console, request.payload),
            title="Payload",
            border_style="cyan",
        )
    )


def render_search_groups(
    groups: Sequence[SearchGroup],
    output_format: OutputFormat,
    *,
    columns: Sequence[str] | None = None,
    project_columns: bool = False,
    numbered: bool = False,
    console: Console | None = None,
) -> None:
    console = _resolve_console(console)
    display_groups = _with_group_row_numbers(groups) if numbered else list(groups)

    if output_format == "json":
        _write_json(
            console,
            [
                {
                    "title": group.title,
                    "endpoint_path": group.endpoint_path,
                    "total_count": group.total_count,
                    "results": _project_rows(
                        group.rows,
                        ("index", *(columns or get_default_columns(group.endpoint_path)))
                        if numbered
                        else (columns or get_default_columns(group.endpoint_path)),
                    )
                    if project_columns
                    else group.rows,
                }
                for group in display_groups
            ],
        )
        return
    if output_format == "csv":
        flattened_rows: list[dict[str, Any]] = []
        csv_columns: list[str] = ["title", "endpoint_path", "total_count"]
        if numbered:
            csv_columns.append("index")
        for group in display_groups:
            group_columns = list(columns or get_default_columns(group.endpoint_path))
            for column in group_columns:
                if column not in csv_columns:
                    csv_columns.append(column)
            for row in group.rows:
                flattened_row = {
                    "title": group.title,
                    "endpoint_path": group.endpoint_path,
                    "total_count": group.total_count,
                }
                if numbered:
                    flattened_row["index"] = get_record_field(row, "index")
                flattened_row.update(
                    {
                        column: stringify_value(get_record_field(row, column)) or "-"
                        for column in group_columns
                    }
                )
                flattened_rows.append(flattened_row)
        _write_csv(console, flattened_rows, tuple(csv_columns))
        return

    for group in display_groups:
        console.print(
            Panel.fit(
                f"path: {group.endpoint_path}\nmatched: {group.total_count}",
                title=group.title,
                border_style="cyan",
            )
        )
        table_group_columns = tuple(columns or get_default_columns(group.endpoint_path))
        table_columns = ("index", *table_group_columns) if numbered else table_group_columns
        table = _build_table(table_columns, title=group.endpoint_path)
        for row in group.rows:
            table.add_row(*_row_cells(row, table_columns))
        console.print(table)
    if numbered:
        _print_open_hint(console)


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def path_label(path: Path | None) -> str:
    return str(path) if path is not None else "<not configured>"


def _build_table(columns: Sequence[str], *, title: str) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    for column in columns:
        table.add_column(column.upper().replace("_", " "), overflow="fold")
    return table


def _build_payload_table(
    payload: dict[str, Any],
    *,
    title: str,
) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("FIELD", style="cyan")
    table.add_column("VALUE", overflow="fold")
    for field_name, value in payload.items():
        table.add_row(field_name, stringify_value(value) or "-")
    return table


def _build_change_table(
    changes: Sequence[MutationFieldSummary],
    *,
    title: str,
) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("FIELD")
    table.add_column("BEFORE", overflow="fold")
    table.add_column("AFTER", overflow="fold")
    for change in changes:
        field_cell = Text(change.field, style="cyan")
        after_style = "green" if change.changed else ""
        after_cell = Text(change.after, style=after_style)
        table.add_row(field_cell, change.before, after_cell)
    return table


def _row_cells(row: dict[str, Any], columns: Sequence[str]) -> list[str]:
    return [stringify_value(get_record_field(row, column)) or "-" for column in columns]


def _rows_for_columns(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
) -> list[dict[str, str]]:
    return [
        {
            column: stringify_value(get_record_field(row, column))
            for column in columns
        }
        for row in rows
    ]


def _project_rows(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
) -> list[dict[str, str]]:
    return [
        {
            column: stringify_value(get_record_field(row, column)) or "-"
            for column in columns
        }
        for row in rows
    ]


def _with_row_numbers(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"index": index, **row}
        for index, row in enumerate(rows, start=1)
    ]


def _with_group_row_numbers(groups: Sequence[SearchGroup]) -> list[SearchGroup]:
    numbered_groups: list[SearchGroup] = []
    next_index = 1
    for group in groups:
        numbered_rows: list[dict[str, Any]] = []
        for row in group.rows:
            numbered_rows.append({"index": next_index, **row})
            next_index += 1
        numbered_groups.append(
            SearchGroup(
                title=group.title,
                endpoint_path=group.endpoint_path,
                rows=numbered_rows,
                total_count=group.total_count,
            )
        )
    return numbered_groups


def _write_json(console: Console, payload: Any) -> None:
    if _console_supports_styled_json(console):
        console.print(
            JSON.from_data(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    console.file.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    console.file.write("\n")


def _json_renderable(console: Console, payload: Any) -> Any:
    if _console_supports_styled_json(console):
        return JSON.from_data(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _field_summaries_for_payload(
    before_row: dict[str, Any],
    payload: dict[str, Any],
) -> list[MutationFieldSummary]:
    return [
        MutationFieldSummary(
            field=field_name,
            before=stringify_value(get_record_field(before_row, field_name)) or "-",
            after=stringify_value(new_value) or "-",
            changed=(
                stringify_value(get_record_field(before_row, field_name)) or "-"
            ) != (stringify_value(new_value) or "-"),
        )
        for field_name, new_value in payload.items()
    ]


def _field_summaries_for_result(
    before_row: dict[str, Any],
    after_row: dict[str, Any],
    fields: Sequence[str],
) -> list[MutationFieldSummary]:
    summaries: list[MutationFieldSummary] = []
    for field_name in fields:
        before_value = stringify_value(get_record_field(before_row, field_name)) or "-"
        after_value = stringify_value(get_record_field(after_row, field_name)) or "-"
        summaries.append(
            MutationFieldSummary(
                field=field_name,
                before=before_value,
                after=after_value,
                changed=before_value != after_value,
            )
        )
    return summaries


def _mutation_status_text(
    verb: str,
    endpoint_path: str,
    row: dict[str, Any],
) -> Text:
    text = Text()
    text.append(f"{verb} ", style="bold green")
    text.append(endpoint_path, style="bold")
    object_id = _extract_object_id(row)
    if object_id is not None:
        text.append(" ")
        text.append(f"#{object_id}", style="bold green")
    return text


def _extract_object_id(row: dict[str, Any]) -> int | str | None:
    object_id = row.get("id")
    if isinstance(object_id, (int, str)):
        return object_id
    return None


def _write_csv(
    console: Console,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
) -> None:
    writer = csv.DictWriter(console.file, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                column: stringify_value(row.get(column))
                for column in columns
            }
        )


def _print_open_hint(console: Console) -> None:
    console.print("[dim]Tip: run `open <index>` to inspect a result.[/]")


def _resolve_console(console: Console | None) -> Console:
    return console if console is not None else get_stdout_console()


def _console_supports_styled_json(console: Console) -> bool:
    return console.color_system is not None and not console.no_color


def _stream_is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False
