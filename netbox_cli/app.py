"""Typer entrypoint for the NetBox CLI."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

import typer

from . import __version__
from .cache import MetadataCache, clear_metadata_cache
from .client import NetBoxClient
from .config import init_config, load_settings, resolve_app_paths
from .discovery import list_apps, list_endpoints, list_filters, resolve_list_path
from .errors import ConfigError, NetBoxCLIError
from .parsing import (
    ColumnParseError,
    FilterParseError,
    parse_column_tokens,
    parse_get_filter_tokens,
    parse_list_filter_tokens,
)
from .query import get_record, list_records
from .repl.shell import launch_shell
from .repl.state import ShellState
from .render import (
    print_error,
    print_success,
    render_apps,
    render_config_created,
    render_config_test,
    render_endpoints,
    render_filters,
    render_paths,
    render_query_result,
    render_record_result,
    render_search_groups,
)
from .search import global_search
from .settings import AppPaths, LoadedSettings, NetBoxSettings, OutputFormat

cli = typer.Typer(
    name="netbox",
    add_completion=False,
    help="Read-only NetBox CLI for discovery, endpoint queries, grouped search, and an interactive shell.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Create, inspect, and validate explicit CLI configuration.")
cache_app = typer.Typer(help="Inspect and clear local metadata cache.")
cli.add_typer(config_app, name="config")
cli.add_typer(cache_app, name="cache")


class CLIOutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


def version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            help="Show the package version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    del version


@cli.command("init")
def init_command(
    url: Annotated[
        str,
        typer.Option(
            "--url",
            prompt=True,
            help="Base URL for your NetBox instance.",
        ),
    ],
    token: Annotated[
        str,
        typer.Option(
            "--token",
            prompt=True,
            hide_input=True,
            help="NetBox API token.",
        ),
    ],
    default_format: Annotated[
        str,
        typer.Option("--default-format", help="Default output format."),
    ] = "table",
    default_limit: Annotated[
        int,
        typer.Option("--default-limit", help="Default row limit."),
    ] = 15,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = 10.0,
    verify_tls: Annotated[
        bool,
        typer.Option("--verify-tls/--no-verify-tls", help="Enable or disable TLS verification."),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config file."),
    ] = False,
) -> None:
    """Create the explicit user config file."""

    paths = resolve_app_paths()
    try:
        config_path = init_config(
            url=url,
            token=token,
            default_format=default_format,
            default_limit=default_limit,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
            force=force,
            app_paths=paths,
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)

    settings = NetBoxSettings(
        url=url,
        token=token,
        default_format=default_format,  # type: ignore[arg-type]
        default_limit=default_limit,
        timeout_seconds=timeout_seconds,
        verify_tls=verify_tls,
    )
    render_config_created(paths, settings)
    print_success(f"Config written to {config_path}.")


@config_app.command("test")
def config_test_command() -> None:
    """Validate config loading, token, and API connectivity."""

    paths = resolve_app_paths()
    try:
        loaded = load_settings(app_paths=paths)
        client = NetBoxClient(
            loaded.settings,
            metadata_cache=MetadataCache(paths.cache_dir),
        )
        api_root = client.test_connection()
    except NetBoxCLIError as exc:
        _exit_with_error(exc)

    render_config_test(loaded, api_root)


@config_app.command("paths")
def config_paths_command() -> None:
    """Show the user-specific config, cache, and history locations."""

    render_paths(resolve_app_paths())


@cache_app.command("clear")
def cache_clear_command() -> None:
    """Clear local metadata cache files."""

    paths = resolve_app_paths()
    removed_files = clear_metadata_cache(paths.cache_dir)
    if removed_files == 0:
        print_success(f"Cache is already empty at {paths.cache_dir}.")
        return
    print_success(f"Cleared {removed_files} cache file(s) from {paths.cache_dir}.")


@cli.command("apps")
def apps_command(
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """List top-level NetBox apps. `netbox list` is the preferred exploration command."""

    try:
        _, loaded, client = _build_runtime()
        apps = list_apps(client)
        render_apps(
            apps,
            _resolve_output_format(output_format, loaded.settings.default_format),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("endpoints")
def endpoints_command(
    app_name: Annotated[str, typer.Argument(help="NetBox app name, for example dcim.")],
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """List endpoints for a NetBox app. `netbox list <app>` is the preferred exploration command."""

    try:
        _, loaded, client = _build_runtime()
        endpoints = list_endpoints(client, app_name)
        render_endpoints(
            endpoints,
            _resolve_output_format(output_format, loaded.settings.default_format),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("filters")
def filters_command(
    endpoint_path: Annotated[
        str,
        typer.Argument(help="Endpoint path in app/endpoint form, for example dcim/devices."),
    ],
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """Show available filters and known choices for an endpoint."""

    try:
        _, loaded, client = _build_runtime()
        filters = list_filters(client, endpoint_path)
        render_filters(
            filters,
            _resolve_output_format(output_format, loaded.settings.default_format),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("list")
def list_command(
    path_and_filters: Annotated[
        list[str] | None,
        typer.Argument(
            help="Optional app or endpoint path followed by free-text terms and/or key=value filters.",
        ),
    ] = None,
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
    cols: Annotated[
        str | None,
        typer.Option("--cols", help="Comma-separated output columns, for example name,site,status."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum rows to display."),
    ] = None,
) -> None:
    """List apps, app endpoints, or endpoint records depending on the provided path."""

    selected_columns = parse_column_args(cols)
    raw_args = path_and_filters or []
    try:
        _, loaded, client = _build_runtime()
        resolved_target = resolve_list_path(client, raw_args[0] if raw_args else None)
        output = _resolve_output_format(output_format, loaded.settings.default_format)

        if resolved_target.kind == "root":
            _validate_context_list_usage([], cols=cols, limit=limit)
            render_apps(list_apps(client), output)
            return

        if resolved_target.kind == "app":
            _validate_context_list_usage(
                raw_args[1:],
                cols=cols,
                limit=limit,
            )
            render_endpoints(list_endpoints(client, resolved_target.path or ""), output)
            return

        result = list_records(
            client,
            resolved_target.path or "",
            parse_list_filter_args(raw_args[1:]),
            limit=limit or loaded.settings.default_limit,
        )
        render_query_result(
            result,
            output,
            columns=selected_columns,
            project_columns=cols is not None,
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("get")
def get_command(
    endpoint_path: Annotated[
        str,
        typer.Argument(help="Endpoint path in app/endpoint form."),
    ],
    filters: Annotated[
        list[str] | None,
        typer.Argument(help="Lookup filters such as id=123 or name=router01."),
    ] = None,
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """Fetch one object from an endpoint using lookup filters."""

    try:
        _, loaded, client = _build_runtime()
        result = get_record(
            client,
            endpoint_path,
            parse_get_filter_args(filters or []),
        )
        render_record_result(
            result,
            _resolve_output_format(output_format, loaded.settings.default_format),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("search")
def search_command(
    term: Annotated[str, typer.Argument(help="Search term.")],
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
    cols: Annotated[
        str | None,
        typer.Option("--cols", help="Comma-separated output columns, for example id,name,site,status."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum rows to display per group."),
    ] = None,
) -> None:
    """Search curated endpoints and group results by object type."""

    selected_columns = parse_column_args(cols)
    try:
        _, loaded, client = _build_runtime()
        groups = global_search(
            client,
            term,
            limit_per_group=limit or loaded.settings.default_limit,
        )
        render_search_groups(
            groups,
            _resolve_output_format(output_format, loaded.settings.default_format),
            columns=selected_columns,
            project_columns=cols is not None,
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("shell")
def shell_command() -> None:
    """Launch the interactive shell with contextual autocomplete."""

    try:
        paths, loaded, client = _build_runtime()
        launch_shell(
            client,
            history_path=paths.history_path,
            initial_state=ShellState.from_settings(loaded.settings),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


def main() -> None:
    cli()


def parse_list_filter_args(raw_filters: list[str]) -> list[tuple[str, str]]:
    try:
        return parse_list_filter_tokens(raw_filters)
    except FilterParseError as exc:
        raise typer.BadParameter(str(exc)) from exc


def parse_get_filter_args(raw_filters: list[str]) -> dict[str, str]:
    try:
        return parse_get_filter_tokens(raw_filters)
    except FilterParseError as exc:
        raise typer.BadParameter(str(exc)) from exc


def parse_column_args(raw_columns: str | None) -> tuple[str, ...] | None:
    if raw_columns is None:
        return None

    try:
        return parse_column_tokens(raw_columns)
    except ColumnParseError as exc:
        raise typer.BadParameter(str(exc), param_hint="--cols") from exc


def _validate_context_list_usage(
    extra_args: list[str],
    *,
    cols: str | None,
    limit: int | None,
) -> None:
    if extra_args:
        raise typer.BadParameter(
            "Free-text terms and filters are only valid when listing an endpoint path."
        )
    if cols is not None:
        raise typer.BadParameter(
            "`--cols` is only supported when listing endpoint records.",
            param_hint="--cols",
        )
    if limit is not None:
        raise typer.BadParameter(
            "`--limit` is only supported when listing endpoint records.",
            param_hint="--limit",
        )


def _build_runtime() -> tuple[AppPaths, LoadedSettings, NetBoxClient]:
    paths = resolve_app_paths()
    loaded = load_settings(app_paths=paths)
    client = NetBoxClient(
        loaded.settings,
        metadata_cache=MetadataCache(paths.cache_dir),
    )
    return paths, loaded, client


def _resolve_output_format(
    explicit_format: CLIOutputFormat | None,
    default_format: str,
) -> OutputFormat:
    return explicit_format.value if explicit_format is not None else default_format


def _exit_with_error(error: NetBoxCLIError) -> None:
    if isinstance(error, ConfigError):
        print_error(str(error))
    else:
        print_error(str(error))
    raise typer.Exit(code=1)
