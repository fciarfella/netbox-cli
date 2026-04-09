"""Typer entrypoint for the NetBox CLI."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .cache import MetadataCache, clear_metadata_cache
from .client import NetBoxClient
from .config import (
    init_config,
    list_profiles,
    load_settings,
    resolve_app_paths,
    use_profile,
)
from .discovery import list_apps, list_endpoints, list_filters, resolve_list_path
from .errors import ConfigError, NetBoxCLIError
from .mutations import (
    MutationInputError,
    MutationRequest,
    MutationSafetyError,
    create_record,
    fetch_update_before_row,
    prepare_create_request,
    prepare_update_request,
    require_cli_yes_for_live_write,
    update_record,
    validate_create_required_fields,
)
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
    render_profiles,
    render_create_result,
    render_mutation_preview,
    render_paths,
    render_query_result,
    render_record_result,
    render_search_groups,
    render_update_result,
)
from .search import global_search
from .settings import AppPaths, LoadedSettings, NetBoxSettings, OutputFormat

cli = typer.Typer(
    name="netbox",
    add_completion=False,
    help="NetBox CLI for discovery, endpoint queries, grouped search, selective create/update, and an interactive shell.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Create, inspect, and validate explicit CLI configuration.")
cache_app = typer.Typer(help="Inspect and clear local metadata cache.")
profile_app = typer.Typer(help="Manage named NetBox profiles.")
cli.add_typer(config_app, name="config")
cli.add_typer(cache_app, name="cache")
cli.add_typer(profile_app, name="profile")


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
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            help="Show the package version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help="Use a named profile for this invocation or shell session without changing the active profile.",
        ),
    ] = None,
) -> None:
    del version
    ctx.obj = {"profile_name": profile}


@profile_app.command("add")
def profile_add_command(
    profile_name: Annotated[
        str,
        typer.Argument(help="Profile name to create or update."),
    ],
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
        typer.Option("--force", help="Replace any existing config with only this profile."),
    ] = False,
) -> None:
    """Create or update one named profile."""

    paths = resolve_app_paths()
    try:
        config_path = init_config(
            url=url,
            token=token,
            default_format=default_format,
            default_limit=default_limit,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
            profile_name=profile_name,
            force=force,
            app_paths=paths,
        )
        loaded = load_settings(app_paths=paths)
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
    render_config_created(
        paths,
        settings,
        profile_name=profile_name,
        current_profile=loaded.current_profile or loaded.profile_name,
    )
    print_success(f"Profile {profile_name!r} written to {config_path}.")


@profile_app.command("list")
def profile_list_command() -> None:
    """List configured NetBox profiles and mark the active one."""

    paths = resolve_app_paths()
    try:
        render_profiles(list_profiles(app_paths=paths))
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@profile_app.command("use")
def profile_use_command(
    profile_name: Annotated[
        str,
        typer.Argument(help="Configured profile name to persist as active."),
    ],
) -> None:
    """Persist the selected profile as the active profile."""

    paths = resolve_app_paths()
    try:
        use_profile(profile_name, app_paths=paths)
    except NetBoxCLIError as exc:
        _exit_with_error(exc)

    print_success(f"Active profile set to {profile_name!r}.")


@config_app.command("test")
def config_test_command(ctx: typer.Context) -> None:
    """Validate config loading, token, and API connectivity."""

    try:
        paths, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
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


@cli.command("filters")
def filters_command(
    ctx: typer.Context,
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
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
        filters = list_filters(client, endpoint_path)
        render_filters(
            filters,
            _resolve_output_format(output_format, loaded.settings.default_format),
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("list")
def list_command(
    ctx: typer.Context,
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
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
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
    ctx: typer.Context,
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
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
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
    ctx: typer.Context,
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
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
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


@cli.command("create")
def create_command(
    ctx: typer.Context,
    endpoint_path: Annotated[
        str,
        typer.Argument(help="Endpoint path in app/endpoint form."),
    ],
    fields: Annotated[
        list[str] | None,
        typer.Argument(help="Inline payload fields in key=value form."),
    ] = None,
    payload_file: Annotated[
        Path | None,
        typer.Option("--file", help="Path to a JSON or YAML payload file."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview the POST request without sending it."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Execute the POST request. Required for live writes."),
    ] = False,
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """Create one object with inline fields or a JSON/YAML payload file."""

    try:
        request = parse_create_args(endpoint_path, fields or [], payload_file)
        validate_cli_write_safety(yes=yes, dry_run=dry_run)
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
        validate_create_request_fields(client, request)
        resolved_output = _resolve_output_format(output_format, loaded.settings.default_format)
        if dry_run:
            render_mutation_preview(request, resolved_output)
            return

        render_create_result(
            request,
            create_record(client, request),
            resolved_output,
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("update")
def update_command(
    ctx: typer.Context,
    endpoint_path: Annotated[
        str,
        typer.Argument(help="Endpoint path in app/endpoint form."),
    ],
    fields: Annotated[
        list[str] | None,
        typer.Argument(help="id=<id> selector plus inline payload fields in key=value form."),
    ] = None,
    payload_file: Annotated[
        Path | None,
        typer.Option("--file", help="Path to a JSON or YAML payload file."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview the PATCH request without sending it."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Execute the PATCH request. Required for live writes."),
    ] = False,
    output_format: Annotated[
        CLIOutputFormat | None,
        typer.Option("--format", "-f", help="Output format."),
    ] = None,
) -> None:
    """Update one object by id with inline fields or a JSON/YAML patch file."""

    try:
        request = parse_update_args(endpoint_path, fields or [], payload_file)
        validate_cli_write_safety(yes=yes, dry_run=dry_run)
        _, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
        resolved_output = _resolve_output_format(output_format, loaded.settings.default_format)
        if dry_run:
            render_mutation_preview(request, resolved_output)
            return

        before_row = (
            fetch_update_before_row(client, request)
            if resolved_output == "table"
            else None
        )
        render_update_result(
            request,
            before_row,
            update_record(client, request),
            resolved_output,
        )
    except NetBoxCLIError as exc:
        _exit_with_error(exc)


@cli.command("shell")
def shell_command(ctx: typer.Context) -> None:
    """Launch the interactive shell with contextual autocomplete."""

    try:
        paths, loaded, client = _build_runtime(profile_name=_requested_profile_name(ctx))
        launch_shell(
            client,
            history_path=paths.history_path,
            initial_state=ShellState.from_settings(
                loaded.settings,
                profile_name=loaded.profile_name,
            ),
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


def parse_create_args(
    endpoint_path: str,
    fields: list[str],
    payload_file: Path | None,
):
    try:
        return prepare_create_request(endpoint_path, fields, payload_file)
    except MutationInputError as exc:
        raise typer.BadParameter(str(exc)) from exc


def parse_update_args(
    endpoint_path: str,
    fields: list[str],
    payload_file: Path | None,
):
    try:
        return prepare_update_request(endpoint_path, fields, payload_file)
    except MutationInputError as exc:
        raise typer.BadParameter(str(exc)) from exc


def validate_cli_write_safety(*, yes: bool, dry_run: bool) -> None:
    try:
        require_cli_yes_for_live_write(yes=yes, dry_run=dry_run)
    except MutationSafetyError as exc:
        raise typer.BadParameter(str(exc), param_hint="--yes") from exc


def validate_create_request_fields(
    client: NetBoxClient,
    request: MutationRequest,
) -> None:
    try:
        validate_create_required_fields(client, request)
    except MutationInputError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


def _build_runtime(
    profile_name: str | None = None,
) -> tuple[AppPaths, LoadedSettings, NetBoxClient]:
    paths = resolve_app_paths()
    loaded = load_settings(app_paths=paths, profile_name=profile_name)
    client = NetBoxClient(
        loaded.settings,
        metadata_cache=MetadataCache(paths.cache_dir),
    )
    return paths, loaded, client


def _requested_profile_name(ctx: typer.Context | None) -> str | None:
    if ctx is None:
        return None
    obj = getattr(ctx, "obj", None)
    if not isinstance(obj, dict):
        return None
    profile_name = obj.get("profile_name")
    if not isinstance(profile_name, str):
        return None
    normalized = profile_name.strip()
    return normalized or None


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
