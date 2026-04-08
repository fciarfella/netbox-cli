"""Parsing and execution helpers for the interactive shell."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from ..client import NetBoxClient
from ..discovery import list_apps, list_endpoints, list_filters
from ..errors import CommandUsageError, InvalidEndpointError
from ..mutations import (
    MutationInputError,
    MutationRequest,
    WRITE_CANCELLED_MESSAGE,
    create_record,
    fetch_update_before_row,
    parse_mutation_command_tokens,
    prepare_create_request,
    prepare_update_request,
    update_record,
    validate_create_required_fields,
)
from ..parsing import (
    ColumnParseError,
    FilterParseError,
    parse_column_parts,
    parse_get_filter_tokens,
    parse_list_filter_tokens,
)
from ..query import (
    RecordResult,
    get_record,
    get_record_by_id,
    list_records,
    stringify_record_field,
)
from ..render import (
    render_apps,
    render_create_result,
    render_endpoints,
    render_filters,
    render_mutation_confirmation_preview,
    render_mutation_preview,
    render_query_result,
    render_record_result,
    render_search_groups,
    render_update_result,
    mutation_confirmation_prompt,
)
from ..search import SearchGroup, global_search
from ..settings import OutputFormat, RecordReference
from .help import REPL_COMMANDS, REPL_COMMAND_HELP, REPL_HELP_TEXT
from .state import ShellState

VALID_OUTPUT_FORMATS: tuple[OutputFormat, ...] = ("table", "json", "csv")


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Normalized shell command line."""

    name: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of executing one shell command."""

    should_exit: bool = False


def parse_command(line: str) -> ParsedCommand | None:
    """Parse a raw shell line into a normalized command structure."""

    stripped = line.strip()
    if not stripped:
        return None

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        raise CommandUsageError(f"Could not parse command: {exc}.") from exc

    if not tokens:
        return None

    return ParsedCommand(
        name=tokens[0].strip().lower(),
        args=tuple(token.strip() for token in tokens[1:] if token.strip()),
    )


def execute_command(
    state: ShellState,
    line: str,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    """Parse and execute a single shell command."""

    command = parse_command(line)
    if command is None:
        return CommandResult()

    handlers = {
        "help": _handle_help,
        "cd": _handle_cd,
        "filters": _handle_filters,
        "list": _handle_list,
        "get": _handle_get,
        "create": _handle_create,
        "update": _handle_update,
        "search": _handle_search,
        "open": _handle_open,
        "cols": _handle_cols,
        "format": _handle_format,
        "limit": _handle_limit,
        "exit": _handle_exit,
    }
    handler = handlers.get(command.name)
    if handler is None:
        available = ", ".join(REPL_COMMANDS)
        raise CommandUsageError(
            f"Unknown command {command.name!r}. Available commands: {available}."
        )

    return handler(state, command, client, console=console)


def _handle_help(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    del state, client
    if not command.args:
        _render_help_panel(console, REPL_HELP_TEXT, title="Shell Help")
        return CommandResult()

    if len(command.args) != 1:
        raise CommandUsageError("Usage: help [create|update]")

    topic = command.args[0].lower()
    help_text = REPL_COMMAND_HELP.get(topic)
    if help_text is None:
        raise CommandUsageError(
            "Unknown help topic "
            f"{command.args[0]!r}. Available help topics: {', '.join(sorted(REPL_COMMAND_HELP))}."
        )

    _render_help_panel(console, help_text, title=f"{topic} help")
    return CommandResult()


def _handle_cd(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    next_path = _resolve_cd_destination(state, command)
    _validate_context_path(client, next_path)
    state.set_path(next_path)
    _print_context(console, state.current_path)
    return CommandResult()


def _handle_filters(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if command.args:
        raise CommandUsageError("Usage: filters")
    _require_endpoint_context(state, "filters")

    render_filters(
        list_filters(client, state.service_path),
        state.output_format,
        console=console,
    )
    return CommandResult()


def _handle_list(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if not state.is_endpoint_context:
        if command.args:
            raise CommandUsageError("Usage: list")
        return _handle_context_list(state, client, console=console)

    filters = parse_list_filter_args(command.args)
    result = list_records(
        client,
        state.service_path,
        filters,
        limit=state.limit,
    )
    render_query_result(
        result,
        state.output_format,
        columns=state.columns,
        numbered=True,
        console=console,
    )
    state.remember_results(_record_references_for_rows(result.endpoint_path, result.rows))
    return CommandResult()


def _handle_get(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    _require_endpoint_context(state, "get")
    result = get_record(
        client,
        state.service_path,
        parse_get_filter_args(command.args),
    )
    render_record_result(result, state.output_format, console=console)
    return CommandResult()


def _handle_search(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if not command.args:
        raise CommandUsageError("Usage: search <term>")

    groups = global_search(
        client,
        " ".join(command.args),
        limit_per_group=state.limit,
    )
    render_search_groups(
        groups,
        state.output_format,
        numbered=True,
        console=console,
    )
    state.remember_results(_record_references_for_groups(groups))
    return CommandResult()


def _handle_create(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if not command.args or _is_explicit_help_request(command.args):
        _render_command_help(console, "create")
        return CommandResult()

    _require_endpoint_context(state, "create")
    parsed = parse_mutation_args(command.args)
    try:
        request = prepare_create_request(
            state.service_path,
            parsed.fields,
            parsed.payload_file,
        )
        validate_create_required_fields(client, request)
    except MutationInputError as exc:
        raise CommandUsageError(str(exc)) from exc

    if parsed.dry_run:
        render_mutation_preview(request, state.output_format, console=console)
        return CommandResult()

    render_mutation_confirmation_preview(request, console=console)
    if not _confirm_mutation(console, request):
        console.print(f"[bold yellow]{WRITE_CANCELLED_MESSAGE}[/]")
        return CommandResult()

    render_create_result(
        request,
        create_record(client, request),
        state.output_format,
        console=console,
    )
    return CommandResult()


def _handle_update(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if not command.args or _is_explicit_help_request(command.args):
        _render_command_help(console, "update")
        return CommandResult()

    _require_endpoint_context(state, "update")
    parsed = parse_mutation_args(command.args)
    try:
        request = prepare_update_request(
            state.service_path,
            parsed.fields,
            parsed.payload_file,
        )
    except MutationInputError as exc:
        raise CommandUsageError(str(exc)) from exc

    if parsed.dry_run:
        render_mutation_preview(request, state.output_format, console=console)
        return CommandResult()

    before_row = fetch_update_before_row(client, request)
    render_mutation_confirmation_preview(
        request,
        before_row=before_row,
        console=console,
    )
    if not _confirm_mutation(console, request):
        console.print(f"[bold yellow]{WRITE_CANCELLED_MESSAGE}[/]")
        return CommandResult()

    render_update_result(
        request,
        before_row,
        update_record(client, request),
        state.output_format,
        console=console,
    )
    return CommandResult()


def _handle_open(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if len(command.args) != 1:
        raise CommandUsageError("Usage: open <index>")
    if not state.last_results:
        raise CommandUsageError("No numbered results are available. Run `list` or `search` first.")

    try:
        index = int(command.args[0])
    except ValueError as exc:
        raise CommandUsageError("`open` requires a numeric index, for example `open 1`.") from exc

    if index < 1 or index > len(state.last_results):
        raise CommandUsageError(
            f"Result index {index} is out of range. Choose a value between 1 and {len(state.last_results)}."
        )

    reference = state.last_results[index - 1]
    state.set_path(f"/{reference.endpoint_path}")
    if state.output_format == "table":
        console.print(
            f"[dim]Opened {index}: {reference.display}[/]"
        )
        _print_context(console, state.current_path)

    if reference.object_id is None:
        result = RecordResult(reference.endpoint_path, dict(reference.payload))
    else:
        result = get_record_by_id(client, reference.endpoint_path, reference.object_id)

    render_record_result(result, state.output_format, console=console)
    return CommandResult()


def _handle_cols(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    del client
    _require_endpoint_context(state, "cols")

    if not command.args:
        console.print(", ".join(state.columns) or "<none>")
        return CommandResult()

    if len(command.args) == 1 and command.args[0].lower() in {"reset", "default"}:
        state.set_columns(None)
        console.print(", ".join(state.columns) or "<none>")
        return CommandResult()

    columns = _parse_columns(command.args)
    if not columns:
        raise CommandUsageError("Usage: cols <col1,col2,...> or cols reset")

    state.set_columns(columns)
    console.print(", ".join(state.columns))
    return CommandResult()


def _handle_format(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    del client
    if not command.args:
        console.print(state.output_format)
        return CommandResult()
    if len(command.args) != 1:
        raise CommandUsageError("Usage: format <table|json|csv>")

    raw_value = command.args[0].lower()
    if raw_value not in VALID_OUTPUT_FORMATS:
        expected = ", ".join(VALID_OUTPUT_FORMATS)
        raise CommandUsageError(f"Unsupported format {raw_value!r}. Expected one of {expected}.")

    state.set_output_format(raw_value)  # type: ignore[arg-type]
    console.print(state.output_format)
    return CommandResult()


def _handle_limit(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    del client
    if not command.args:
        console.print(str(state.limit))
        return CommandResult()
    if len(command.args) != 1:
        raise CommandUsageError("Usage: limit <positive-integer>")

    try:
        new_limit = int(command.args[0])
    except ValueError as exc:
        raise CommandUsageError("`limit` requires a positive integer.") from exc
    if new_limit <= 0:
        raise CommandUsageError("`limit` requires a positive integer.")

    state.set_limit(new_limit)
    console.print(str(state.limit))
    return CommandResult()


def _handle_exit(
    state: ShellState,
    command: ParsedCommand,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    _require_no_args(command, "exit")
    del state, client, console
    return CommandResult(should_exit=True)


def parse_list_filter_args(raw_filters: Sequence[str]) -> list[tuple[str, str]]:
    """Parse shell list tokens with shared CLI-equivalent semantics."""

    try:
        return parse_list_filter_tokens(raw_filters)
    except FilterParseError as exc:
        raise CommandUsageError(str(exc)) from exc


def parse_get_filter_args(raw_filters: Sequence[str]) -> dict[str, str]:
    """Parse strict shell lookup filters in key=value form."""

    try:
        return parse_get_filter_tokens(raw_filters)
    except FilterParseError as exc:
        raise CommandUsageError(str(exc)) from exc


def parse_mutation_args(raw_tokens: Sequence[str]):
    """Parse shell write tokens with shared CLI-equivalent mutation semantics."""

    try:
        return parse_mutation_command_tokens(raw_tokens)
    except MutationInputError as exc:
        raise CommandUsageError(str(exc)) from exc


def _parse_columns(raw_columns: Sequence[str]) -> tuple[str, ...]:
    try:
        return parse_column_parts(raw_columns)
    except ColumnParseError as exc:
        raise CommandUsageError(str(exc)) from exc


def _resolve_cd_destination(state: ShellState, command: ParsedCommand) -> str:
    if not command.args:
        return state.resolve_path("/")
    if len(command.args) != 1:
        raise CommandUsageError("Usage: cd [path]")
    return state.resolve_path(command.args[0])


def _handle_context_list(
    state: ShellState,
    client: NetBoxClient,
    *,
    console: Console,
) -> CommandResult:
    if state.is_root_context:
        render_apps(list_apps(client), state.output_format, console=console)
        return CommandResult()

    render_endpoints(
        list_endpoints(client, state.service_path),
        state.output_format,
        console=console,
    )
    return CommandResult()


def _require_endpoint_context(state: ShellState, command_name: str) -> None:
    if not state.is_endpoint_context:
        raise InvalidEndpointError(
            f"`{command_name}` requires an endpoint context. Use `cd <app>/<endpoint>` first."
        )


def _require_no_args(command: ParsedCommand, command_name: str) -> None:
    if command.args:
        raise CommandUsageError(f"Usage: {command_name}")


def _render_command_help(console: Console, command_name: str) -> None:
    help_text = REPL_COMMAND_HELP.get(command_name)
    if help_text is None:
        raise CommandUsageError(f"No help is available for {command_name!r}.")
    _render_help_panel(console, help_text, title=f"{command_name} help")


def _render_help_panel(console: Console, text: str, *, title: str) -> None:
    console.print(Panel.fit(Text(text), title=title, border_style="blue"))


def _is_explicit_help_request(args: Sequence[str]) -> bool:
    return len(args) == 1 and args[0] in {"--help", "-h"}


def _confirm_mutation(console: Console, request: MutationRequest) -> bool:
    return bool(
        Confirm.ask(
            mutation_confirmation_prompt(request),
            console=console,
            default=False,
            show_choices=False,
            show_default=False,
        )
    )


def _print_context(console: Console, current_path: str) -> None:
    console.print(f"[dim]Context: {current_path}[/]")


def _validate_context_path(client: NetBoxClient, shell_path: str) -> None:
    service_path = shell_path.strip("/")
    if not service_path:
        return

    if _is_app_path(service_path):
        list_endpoints(client, service_path)
        return

    list_filters(client, service_path)


def _is_app_path(service_path: str) -> bool:
    parts = tuple(part for part in service_path.split("/") if part)
    if not parts:
        return False
    if parts[0] == "plugins":
        return len(parts) <= 2
    return len(parts) == 1


def _record_references_for_groups(groups: Sequence[SearchGroup]) -> list[RecordReference]:
    references: list[RecordReference] = []
    for group in groups:
        references.extend(_record_references_for_rows(group.endpoint_path, group.rows))
    return references


def _record_references_for_rows(
    endpoint_path: str,
    rows: Sequence[dict[str, Any]],
) -> list[RecordReference]:
    return [
        RecordReference(
            endpoint_path=endpoint_path,
            object_id=_extract_object_id(row),
            display=_record_display(row),
            payload=dict(row),
        )
        for row in rows
    ]


def _extract_object_id(row: dict[str, Any]) -> int | str | None:
    raw_id = row.get("id")
    if isinstance(raw_id, (int, str)):
        return raw_id
    return None


def _record_display(row: dict[str, Any]) -> str:
    for field_name in ("display", "name", "address", "prefix", "value", "id"):
        value = stringify_record_field(row, field_name)
        if value:
            return value
    return "<record>"
