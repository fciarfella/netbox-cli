from __future__ import annotations

import httpx
import pytest
import respx

from netbox_cli.client import NetBoxClient
from netbox_cli.errors import (
    APIError,
    InvalidEndpointError,
    InvalidFilterError,
    NetBoxAuthError,
    NetBoxConnectionError,
)


@respx.mock
def test_get_api_root_uses_auth_headers_and_cache(netbox_settings, metadata_cache) -> None:
    route = respx.get("https://netbox.example.com/api/").mock(
        return_value=httpx.Response(
            200,
            json={"dcim": "https://netbox.example.com/api/dcim/"},
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    first = client.get_api_root()
    second = client.get_api_root()

    assert first == {"dcim": "https://netbox.example.com/api/dcim/"}
    assert second == first
    assert route.call_count == 1
    assert route.calls.last.request.headers["Authorization"] == "Token abc123token"


@respx.mock
def test_get_schema_falls_back_and_uses_cache(netbox_settings, metadata_cache) -> None:
    openapi_route = respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(404)
    )
    json_route = respx.get("https://netbox.example.com/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json={"paths": {}})
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    first = client.get_schema()
    second = client.get_schema()

    assert first == {"paths": {}}
    assert second == first
    assert openapi_route.call_count == 1
    assert json_route.call_count == 1


@respx.mock
def test_get_options_uses_options_request_and_cache(netbox_settings, metadata_cache) -> None:
    route = respx.options("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"actions": {"POST": {}}})
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    first = client.get_options("dcim/devices")
    second = client.get_options("dcim/devices")

    assert first == {"actions": {"POST": {}}}
    assert second == first
    assert route.call_count == 1


@respx.mock
def test_get_plugin_endpoint_access(netbox_settings) -> None:
    route = respx.get("https://netbox.example.com/api/plugins/netbox_dns/records/").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": []})
    )
    client = NetBoxClient(netbox_settings)

    payload = client.get_plugin_endpoint("netbox_dns", "records")

    assert payload == {"count": 1, "results": []}
    assert route.call_count == 1


@respx.mock
def test_invalid_endpoint_raises_structured_error(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/does-not-exist/").mock(
        return_value=httpx.Response(404)
    )
    client = NetBoxClient(netbox_settings)

    with pytest.raises(InvalidEndpointError):
        client.get_json("does-not-exist")


@respx.mock
def test_auth_failure_raises_structured_error(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/").mock(return_value=httpx.Response(403))
    client = NetBoxClient(netbox_settings)

    with pytest.raises(NetBoxAuthError):
        client.get_api_root(use_cache=False)


@respx.mock
def test_connection_error_raises_structured_error(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/").mock(
        side_effect=httpx.ConnectError("boom")
    )
    client = NetBoxClient(netbox_settings)

    with pytest.raises(NetBoxConnectionError):
        client.get_api_root(use_cache=False)


@respx.mock
def test_schema_endpoint_missing_raises_api_error(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://netbox.example.com/api/schema/?format=json").mock(
        return_value=httpx.Response(404)
    )
    client = NetBoxClient(netbox_settings)

    with pytest.raises(APIError):
        client.get_schema(use_cache=False)


@respx.mock
def test_paginate_preserves_repeated_query_parameters(netbox_settings) -> None:
    route = respx.get("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={"count": 0, "next": None, "results": []},
        )
    )
    client = NetBoxClient(netbox_settings)

    client.paginate(
        "dcim/devices",
        params=[("site", "dc1"), ("site", "lab"), ("status", "active")],
        limit=5,
    )

    request = route.calls.last.request
    assert request.url.params.get_list("site") == ["dc1", "lab"]
    assert request.url.params.get("status") == "active"
    assert request.url.params.get("limit") == "5"
    assert request.url.params.get("offset") == "0"


@respx.mock
def test_invalid_filter_error_includes_json_validation_details(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(
            400,
            json={
                "site": [
                    "Select a valid choice. That choice is not one of the available choices."
                ]
            },
        )
    )
    client = NetBoxClient(netbox_settings)

    with pytest.raises(InvalidFilterError) as exc_info:
        client.get_json("dcim/devices", params={"site": "bad-site"})

    message = str(exc_info.value)
    assert "NetBox rejected request parameters for GET dcim/devices" in message
    assert "site: Select a valid choice." in message


@respx.mock
def test_invalid_filter_error_includes_plain_text_body(netbox_settings) -> None:
    respx.get("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(
            400,
            text="Bad filter value provided.",
        )
    )
    client = NetBoxClient(netbox_settings)

    with pytest.raises(InvalidFilterError) as exc_info:
        client.get_json("dcim/devices", params={"site": "bad-site"})

    message = str(exc_info.value)
    assert "NetBox rejected request parameters for GET dcim/devices" in message
    assert "Bad filter value provided." in message
