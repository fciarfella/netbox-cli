"""Terminal rendering helpers built on Rich."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from rich import box
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from .discovery import DiscoveredEndpoint, FilterDefinition
from .profiles import get_default_columns
from .query import QueryResult, RecordResult, get_record_field, stringify_value
from .search import SearchGroup
from .settings import AppPaths, LoadedSettings, NetBoxSettings, OutputFormat


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


def render_config_created(paths: AppPaths, settings: NetBoxSettings) -> None:
    console = get_stdout_console()
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Config", str(paths.config_path))
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
