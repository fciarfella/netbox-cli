from __future__ import annotations

import httpx
import pytest
import respx

from netbox_cli.client import NetBoxClient
from netbox_cli.discovery import (
    ChoiceDefinition,
    discover_choice_metadata,
    list_apps,
    list_endpoints,
    list_filters,
    resolve_list_path,
)
from netbox_cli.errors import InvalidEndpointError


@respx.mock
def test_list_apps_reads_api_root(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/").mock(
        return_value=httpx.Response(
            200,
            json={
                "ipam": "https://netbox.example.com/api/ipam/",
                "dcim": "https://netbox.example.com/api/dcim/",
                "plugins": "https://netbox.example.com/api/plugins/",
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    assert list_apps(client) == ["dcim", "ipam", "plugins"]


def test_resolve_list_path_identifies_root(monkeypatch) -> None:
    class DummyClient:
        pass

    assert resolve_list_path(DummyClient(), None).kind == "root"


def test_resolve_list_path_identifies_app_and_endpoint(monkeypatch) -> None:
    from netbox_cli import discovery as discovery_module

    class DummyClient:
        pass

    monkeypatch.setattr(
        discovery_module,
        "list_endpoints",
        lambda client, path: ["devices"] if path == "dcim" else (_ for _ in ()).throw(InvalidEndpointError(path)),
    )
    monkeypatch.setattr(
        discovery_module,
        "list_filters",
        lambda client, path: ["status"] if path == "dcim/devices" else (_ for _ in ()).throw(InvalidEndpointError(path)),
    )

    assert resolve_list_path(DummyClient(), "dcim").kind == "app"
    assert resolve_list_path(DummyClient(), "dcim/devices").kind == "endpoint"


def test_resolve_list_path_rejects_unknown_path(monkeypatch) -> None:
    from netbox_cli import discovery as discovery_module

    class DummyClient:
        pass

    monkeypatch.setattr(
        discovery_module,
        "list_endpoints",
        lambda client, path: (_ for _ in ()).throw(InvalidEndpointError(path)),
    )
    monkeypatch.setattr(
        discovery_module,
        "list_filters",
        lambda client, path: (_ for _ in ()).throw(InvalidEndpointError(path)),
    )

    with pytest.raises(InvalidEndpointError, match="Unknown NetBox path: unknown"):
        resolve_list_path(DummyClient(), "unknown")


@respx.mock
def test_list_endpoints_for_app(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/").mock(
        return_value=httpx.Response(
            200,
            json={"dcim": "https://netbox.example.com/api/dcim/"},
        )
    )
    respx.get("https://netbox.example.com/api/dcim/").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": "https://netbox.example.com/api/dcim/devices/",
                "sites": "https://netbox.example.com/api/dcim/sites/",
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    endpoints = list_endpoints(client, "dcim")

    assert [item.path for item in endpoints] == ["dcim/devices", "dcim/sites"]


@respx.mock
def test_list_endpoints_for_plugin_app(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/").mock(
        return_value=httpx.Response(
            200,
            json={"plugins": "https://netbox.example.com/api/plugins/"},
        )
    )
    respx.get("https://netbox.example.com/api/plugins/netbox_dns/").mock(
        return_value=httpx.Response(
            200,
            json={"records": "https://netbox.example.com/api/plugins/netbox_dns/records/"},
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    endpoints = list_endpoints(client, "plugins/netbox_dns")

    assert len(endpoints) == 1
    assert endpoints[0].path == "plugins/netbox_dns/records"


@respx.mock
def test_list_filters_merges_schema_and_options_choices(netbox_settings, metadata_cache) -> None:
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
                                    "description": "Device status",
                                    "required": False,
                                    "schema": {"type": "string"},
                                },
                                {"$ref": "#/components/parameters/role"},
                            ]
                        }
                    }
                },
                "components": {
                    "parameters": {
                        "role": {
                            "name": "role",
                            "in": "query",
                            "description": "Device role",
                            "required": False,
                            "schema": {"$ref": "#/components/schemas/RoleFilter"},
                        }
                    },
                    "schemas": {
                        "RoleFilter": {
                            "type": "string",
                            "enum": ["leaf", "spine"],
                        }
                    },
                },
            },
        )
    )
    respx.options("https://netbox.example.com/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "actions": {
                    "POST": {
                        "status": {
                            "choices": [
                                {"value": "active", "display_name": "Active"},
                                {"value": "offline", "display_name": "Offline"},
                            ]
                        }
                    }
                }
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    filters = list_filters(client, "dcim/devices")

    assert [item.name for item in filters] == ["role", "status"]
    assert filters[0].choices == (
        ChoiceDefinition(value="leaf", label="leaf"),
        ChoiceDefinition(value="spine", label="spine"),
    )
    assert filters[1].choices == (
        ChoiceDefinition(value="active", label="Active"),
        ChoiceDefinition(value="offline", label="Offline"),
    )


@respx.mock
def test_discover_choice_metadata_returns_combined_choices(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(
            200,
            json={
                "paths": {
                    "/api/ipam/prefixes/": {
                        "get": {
                            "parameters": [
                                {
                                    "name": "family",
                                    "in": "query",
                                    "schema": {"type": "integer", "enum": [4, 6]},
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    respx.options("https://netbox.example.com/api/ipam/prefixes/").mock(
        return_value=httpx.Response(
            200,
            json={
                "actions": {
                    "POST": {
                        "status": {
                            "choices": [{"value": "active", "display_name": "Active"}]
                        }
                    }
                }
            },
        )
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    choices = discover_choice_metadata(client, "ipam/prefixes")

    assert choices["family"] == (
        ChoiceDefinition(value="4", label="4"),
        ChoiceDefinition(value="6", label="6"),
    )
    assert choices["status"] == (
        ChoiceDefinition(value="active", label="Active"),
    )


@respx.mock
def test_list_filters_raises_for_unknown_endpoint(netbox_settings, metadata_cache) -> None:
    respx.get("https://netbox.example.com/api/schema/?format=openapi").mock(
        return_value=httpx.Response(200, json={"paths": {}})
    )
    client = NetBoxClient(netbox_settings, metadata_cache=metadata_cache)

    with pytest.raises(InvalidEndpointError):
        list_filters(client, "dcim/unknown")
