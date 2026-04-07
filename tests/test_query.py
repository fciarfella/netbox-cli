from __future__ import annotations

import httpx
import pytest
import respx

from netbox_cli.client import NetBoxClient
from netbox_cli.discovery import FilterDefinition
from netbox_cli.errors import InvalidFilterError, MultipleResultsError, NoResultsError
from netbox_cli.query import get_record, list_records


@respx.mock
def test_list_records_handles_paginated_responses(netbox_settings, metadata_cache) -> None:
    schema_route = respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/dcim/devices/": {
                        "get": {
                            "parameters": [
                                {
                                    "name": "status",
                                    "in": "query",
                                    "schema": {"type": "string"},
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    options_route = respx.options("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    first_page = respx.get(
        "https://netbox.example.com/api/dcim/devices/",
        params__contains={"status": "active", "limit": "5", "offset": "0"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "next": "https://netbox.example.com/api/dcim/devices/?limit=2&offset=2",
                "results": [
                    {"id": 1, "name": "leaf-01"},
                    {"id": 2, "name": "leaf-02"},
                ],
            },
        )
    )
    second_page = respx.get(
        "https://netbox.example.com/api/dcim/devices/",
        params__contains={"status": "active", "limit": "3", "offset": "2"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "next": None,
                "results": [
                    {"id": 3, "name": "leaf-03"},
                ],
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    result = list_records(client, "dcim/devices", {"status": "active"}, limit=5)

    assert result.total_count == 3
    assert [row["name"] for row in result.rows] == ["leaf-01", "leaf-02", "leaf-03"]
    assert schema_route.call_count == 1
    assert options_route.call_count == 1
    assert first_page.call_count == 1
    assert second_page.call_count == 1


@respx.mock
def test_list_records_handles_direct_json_lists(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/ipam/vlans/": {
                        "get": {
                            "parameters": []
                        }
                    }
                }
            },
        )
    )
    respx.options("https://netbox.example.com/api/ipam/vlans/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    respx.get(
        "https://netbox.example.com/api/ipam/vlans/",
        params__contains={"limit": "3", "offset": "0"},
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 10, "name": "blue"},
                {"id": 20, "name": "green"},
            ],
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    result = list_records(client, "ipam/vlans", limit=3)

    assert result.total_count == 2
    assert [row["name"] for row in result.rows] == ["blue", "green"]


@respx.mock
def test_get_record_requires_deterministic_match(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/dcim/devices/": {
                        "get": {
                            "parameters": [
                                {
                                    "name": "name",
                                    "in": "query",
                                    "schema": {"type": "string"},
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    respx.options("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    respx.get(
        "https://netbox.example.com/api/dcim/devices/",
        params__contains={"name": "leaf", "limit": "2", "offset": "0"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "results": [
                    {"id": 1, "name": "leaf-01"},
                    {"id": 2, "name": "leaf-02"},
                ],
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    with pytest.raises(MultipleResultsError):
        get_record(client, "dcim/devices", {"name": "leaf"})


@respx.mock
def test_get_record_raises_for_missing_results(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/dcim/sites/": {
                        "get": {
                            "parameters": [
                                {
                                    "name": "slug",
                                    "in": "query",
                                    "schema": {"type": "string"},
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    respx.options("https://netbox.example.com/api/dcim/sites/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    respx.get(
        "https://netbox.example.com/api/dcim/sites/",
        params__contains={"slug": "missing", "limit": "2", "offset": "0"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"count": 0, "next": None, "results": []},
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    with pytest.raises(NoResultsError):
        get_record(client, "dcim/sites", {"slug": "missing"})


@respx.mock
def test_list_records_rejects_invalid_filters(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/dcim/devices/": {
                        "get": {
                            "parameters": [
                                {
                                    "name": "status",
                                    "in": "query",
                                    "schema": {"type": "string"},
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    respx.options("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    with pytest.raises(InvalidFilterError):
        list_records(client, "dcim/devices", {"bogus": "value"}, limit=5)


def test_list_records_preserves_repeated_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubClient:
        def paginate(self, path, *, params=None, limit=None):  # noqa: ANN001
            captured["path"] = path
            captured["params"] = params
            captured["limit"] = limit
            return type(
                "Pagination",
                (),
                {
                    "rows": [{"id": 1, "name": "leaf-01"}],
                    "total_count": 1,
                },
            )()

    monkeypatch.setattr(
        "netbox_cli.query.list_filters",
        lambda client, endpoint_path: [FilterDefinition(name="site")],
    )

    result = list_records(
        StubClient(),  # type: ignore[arg-type]
        "dcim/devices",
        [("site", "dc1"), ("site", "lab")],
        limit=5,
    )

    assert result.total_count == 1
    assert captured["path"] == "dcim/devices"
    assert captured["params"] == [("site", "dc1"), ("site", "lab")]
    assert captured["limit"] == 5


def test_get_record_rejects_repeated_lookup_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        "netbox_cli.query.list_filters",
        lambda client, endpoint_path: [FilterDefinition(name="site")],
    )

    class StubClient:
        def paginate(self, path, *, params=None, limit=None):  # noqa: ANN001
            raise AssertionError("paginate should not be called when filters are invalid")

    with pytest.raises(InvalidFilterError) as exc_info:
        get_record(
            StubClient(),  # type: ignore[arg-type]
            "dcim/devices",
            [("site", "dc1"), ("site", "lab")],
        )

    assert "Repeated lookup filters" in str(exc_info.value)
