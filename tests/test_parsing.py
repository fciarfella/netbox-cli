from __future__ import annotations

import pytest
import typer

from netbox_cli.app import parse_get_filter_args as parse_cli_get_filters
from netbox_cli.app import parse_list_filter_args as parse_cli_list_filters
from netbox_cli.errors import CommandUsageError
from netbox_cli.parsing import ColumnParseError, parse_column_tokens
from netbox_cli.repl.commands import parse_get_filter_args as parse_repl_get_filters
from netbox_cli.repl.commands import parse_list_filter_args as parse_repl_list_filters


@pytest.mark.parametrize(
    ("raw_filters", "expected"),
    [
        (["router01"], [("q", "router01")]),
        (["foo", "bar"], [("q", "foo bar")]),
        (["router01", "status=active"], [("q", "router01"), ("status", "active")]),
        (["q=router01", "status=active"], [("q", "router01"), ("status", "active")]),
        (["site=dc1", "site=lab"], [("site", "dc1"), ("site", "lab")]),
        (
            ["foo", "bar", "site=dc1", "site=lab"],
            [("q", "foo bar"), ("site", "dc1"), ("site", "lab")],
        ),
    ],
)
def test_cli_and_shell_list_filter_parsers_are_aligned(
    raw_filters: list[str],
    expected: list[tuple[str, str]],
) -> None:
    assert parse_cli_list_filters(raw_filters) == expected
    assert parse_repl_list_filters(raw_filters) == expected


def test_cli_and_shell_get_filter_parsers_remain_strict_for_bare_terms() -> None:
    with pytest.raises(typer.BadParameter):
        parse_cli_get_filters(["router01"])

    with pytest.raises(CommandUsageError):
        parse_repl_get_filters(["router01"])


def test_cli_and_shell_get_filter_parsers_reject_repeated_keys() -> None:
    with pytest.raises(typer.BadParameter):
        parse_cli_get_filters(["site=dc1", "site=lab"])

    with pytest.raises(CommandUsageError):
        parse_repl_get_filters(["site=dc1", "site=lab"])


def test_cli_and_shell_list_filter_parsers_reject_empty_keys() -> None:
    with pytest.raises(typer.BadParameter):
        parse_cli_list_filters(["=broken"])

    with pytest.raises(CommandUsageError):
        parse_repl_list_filters(["=broken"])


def test_cli_and_shell_list_filter_parsers_reject_empty_values() -> None:
    with pytest.raises(typer.BadParameter, match=r"Incomplete filter: status=\."):
        parse_cli_list_filters(["status="])

    with pytest.raises(CommandUsageError, match=r"Incomplete filter: status=\."):
        parse_repl_list_filters(["status="])


def test_cli_and_shell_get_filter_parsers_reject_empty_values() -> None:
    with pytest.raises(typer.BadParameter, match=r"Incomplete filter: status=\."):
        parse_cli_get_filters(["status="])

    with pytest.raises(CommandUsageError, match=r"Incomplete filter: status=\."):
        parse_repl_get_filters(["status="])


def test_shared_column_parser_normalizes_whitespace() -> None:
    assert parse_column_tokens("name, site, status") == ("name", "site", "status")


def test_shared_column_parser_rejects_empty_columns() -> None:
    with pytest.raises(ColumnParseError):
        parse_column_tokens("name,,status")
