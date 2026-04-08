from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from netbox_cli.client import PaginatedResponse
from netbox_cli.discovery import ChoiceDefinition, DiscoveredEndpoint, FilterDefinition
from netbox_cli.errors import NetBoxConnectionError
from netbox_cli.repl.metadata import CompletionMetadataProvider
from netbox_cli.settings import RecordReference


@dataclass
class FakeClient:
    rows_by_path: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    error_by_path: dict[str, Exception] = field(default_factory=dict)
    options_by_endpoint: dict[str, dict[str, Any]] = field(default_factory=dict)
    options_error_by_endpoint: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any], int | None]] = field(default_factory=list)
    options_calls: list[str] = field(default_factory=list)

    def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        page_size: int = 100,
    ) -> PaginatedResponse:
        del page_size
        normalized = path.strip("/")
        self.calls.append((normalized, dict(params or {}), limit))
        if normalized in self.error_by_path:
            raise self.error_by_path[normalized]
        rows = self.rows_by_path.get(normalized, [])
        return PaginatedResponse(
            rows=rows[:limit] if limit is not None else list(rows),
            total_count=len(rows),
        )

    def get_options(
        self,
        endpoint_path: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        del use_cache
        normalized = endpoint_path.strip("/")
        self.options_calls.append(normalized)
        if normalized in self.options_error_by_endpoint:
            raise self.options_error_by_endpoint[normalized]
        return self.options_by_endpoint.get(normalized, {"actions": {}})


def test_completion_metadata_provider_caches_apps_endpoints_and_filters(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    calls = {"apps": 0, "endpoints": 0, "filters": 0}

    def fake_list_apps(client):  # type: ignore[no-untyped-def]
        calls["apps"] += 1
        return ["dcim", "ipam", "plugins"]

    def fake_list_endpoints(client, app_name):  # type: ignore[no-untyped-def]
        calls["endpoints"] += 1
        return [
            DiscoveredEndpoint(
                app=app_name,
                endpoint="devices",
                path=f"{app_name}/devices",
                url="https://netbox.example.com/api/dcim/devices/",
            )
        ]

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        calls["filters"] += 1
        return [
            FilterDefinition(
                name="status",
                choices=(ChoiceDefinition(value="active", label="Active"),),
            )
        ]

    monkeypatch.setattr(metadata_module, "list_apps", fake_list_apps)
    monkeypatch.setattr(metadata_module, "list_endpoints", fake_list_endpoints)
    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    provider = CompletionMetadataProvider(FakeClient())

    assert provider.get_apps() == ("dcim", "ipam", "plugins")
    assert provider.get_apps() == ("dcim", "ipam", "plugins")
    assert provider.get_child_segments("dcim") == ("devices",)
    assert provider.get_child_segments("dcim") == ("devices",)
    assert provider.get_filter_names("dcim/devices") == ("status",)
    assert provider.get_filter_choices("dcim/devices", "status") == ("active",)
    assert provider.get_filters("dcim/devices")[0].name == "status"

    assert calls == {"apps": 1, "endpoints": 1, "filters": 1}


def test_related_value_suggestions_cover_multiple_fields(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [
            FilterDefinition(
                name="status",
                choices=(
                    ChoiceDefinition(value="active", label="Active"),
                    ChoiceDefinition(value="offline", label="Offline"),
                ),
            ),
            FilterDefinition(name="site"),
            FilterDefinition(name="rack"),
            FilterDefinition(name="tenant"),
            FilterDefinition(name="role"),
            FilterDefinition(name="platform"),
        ]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(
        rows_by_path={
            "dcim/sites": [{"slug": "dc1", "name": "DC1"}],
            "dcim/racks": [{"name": "rack-a1", "site": {"name": "DC1"}}],
            "tenancy/tenants": [{"slug": "tenant-a", "name": "Tenant A"}],
            "dcim/device-roles": [{"slug": "server", "name": "Server"}],
            "dcim/platforms": [{"slug": "platform-a", "name": "Platform A"}],
        }
    )
    provider = CompletionMetadataProvider(client)

    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "site",
            "d",
        )
    ) == ("dc1",)
    site_suggestions = provider.get_filter_value_suggestions("dcim/devices", "site", "d")
    assert site_suggestions[0].value == "dc1"
    assert site_suggestions[0].label == "DC1"
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "rack",
            "r",
        )
    ) == ("rack-a1",)
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "tenant",
            "t",
        )
    ) == ("tenant-a",)
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "role",
            "S",
        )
    ) == ("server",)
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "platform",
            "pa",
        )
    ) == ("platform-a",)
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions(
            "dcim/devices",
            "status",
            "",
        )
    ) == ("active", "offline")


def test_related_value_suggestions_use_prefix_cache(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="site")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(rows_by_path={"dcim/sites": [{"slug": "dc1", "name": "DC1"}]})
    provider = CompletionMetadataProvider(client)

    first = provider.get_filter_value_suggestions("dcim/devices", "site", "d")
    second = provider.get_filter_value_suggestions("dcim/devices", "site", "d")

    assert tuple(suggestion.value for suggestion in first) == ("dc1",)
    assert tuple(suggestion.value for suggestion in second) == ("dc1",)
    assert client.calls == [
        ("dcim/sites", {"slug__ic": "d"}, 20),
    ]


def test_related_value_suggestions_return_initial_values_for_empty_prefix(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="site"), FilterDefinition(name="rack")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(
        rows_by_path={
            "dcim/sites": [{"slug": "dc1", "name": "DC1"}],
            "dcim/racks": [{"name": "rack-a1", "site": {"name": "DC1"}}],
        }
    )
    provider = CompletionMetadataProvider(client)

    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions("dcim/devices", "site", "")
    ) == ("dc1",)
    assert tuple(
        suggestion.value
        for suggestion in provider.get_filter_value_suggestions("dcim/devices", "rack", "")
    ) == ("rack-a1",)
    assert client.calls == [
        ("dcim/sites", {"ordering": "slug"}, 20),
        ("dcim/racks", {"ordering": "name"}, 20),
    ]


def test_related_value_suggestions_use_empty_prefix_cache(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="site")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(rows_by_path={"dcim/sites": [{"slug": "dc1", "name": "DC1"}]})
    provider = CompletionMetadataProvider(client)

    first = provider.get_filter_value_suggestions("dcim/devices", "site", "")
    second = provider.get_filter_value_suggestions("dcim/devices", "site", "")

    assert tuple(suggestion.value for suggestion in first) == ("dc1",)
    assert tuple(suggestion.value for suggestion in second) == ("dc1",)
    assert client.calls == [
        ("dcim/sites", {"ordering": "slug"}, 20),
    ]


def test_related_value_suggestions_empty_prefix_is_capped(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="site")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(
        rows_by_path={
            "dcim/sites": [
                {"slug": f"site-{index:02d}", "name": f"Site {index:02d}"}
                for index in range(25)
            ]
        }
    )
    provider = CompletionMetadataProvider(client)

    suggestions = provider.get_filter_value_suggestions("dcim/devices", "site", "")

    assert len(suggestions) == 20
    assert suggestions[0].value == "site-00"
    assert suggestions[-1].value == "site-19"


def test_related_value_suggestions_handle_lookup_failure(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="site")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    client = FakeClient(
        error_by_path={
            "dcim/sites": NetBoxConnectionError("boom"),
        }
    )
    provider = CompletionMetadataProvider(client)

    assert provider.get_filter_value_suggestions("dcim/devices", "site", "d") == ()


def test_recent_result_values_are_used_as_fallback(monkeypatch) -> None:
    from netbox_cli.repl import metadata as metadata_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        del client, endpoint_path
        return [FilterDefinition(name="tenant")]

    monkeypatch.setattr(metadata_module, "list_filters", fake_list_filters)

    provider = CompletionMetadataProvider(FakeClient())

    suggestions = provider.get_filter_value_suggestions(
        "dcim/devices",
        "tenant",
        "t",
        recent_results=(
            RecordReference(
                endpoint_path="dcim/devices",
                object_id=1,
                display="router01",
                payload={"tenant": {"name": "Tenant A"}},
            ),
        ),
    )

    assert tuple(suggestion.value for suggestion in suggestions) == ("Tenant A",)


def test_write_field_metadata_is_discovered_from_options_and_cached() -> None:
    client = FakeClient(
        options_by_endpoint={
            "dcim/devices": {
                "actions": {
                    "POST": {
                        "name": {"required": True},
                        "status": {
                            "required": False,
                            "choices": [
                                {"value": "active", "label": "Active"},
                                {"value": "planned", "label": "Planned"},
                            ],
                        },
                        "id": {"read_only": True},
                    }
                }
            }
        }
    )
    provider = CompletionMetadataProvider(client)

    first = provider.get_write_field_names("dcim/devices", "POST")
    second = provider.get_write_field_names("dcim/devices", "POST")
    choices = provider.get_write_value_suggestions(
        "dcim/devices",
        "POST",
        "status",
        "",
    )

    assert first == ("name", "status")
    assert second == first
    assert tuple(suggestion.value for suggestion in choices) == ("active", "planned")
    assert client.options_calls == ["dcim/devices"]


def test_write_field_metadata_handles_options_lookup_failure() -> None:
    client = FakeClient(
        options_error_by_endpoint={
            "dcim/devices": NetBoxConnectionError("boom"),
        }
    )
    provider = CompletionMetadataProvider(client)

    assert provider.get_write_field_names("dcim/devices", "POST") == ()
    assert provider.get_write_value_suggestions(
        "dcim/devices",
        "POST",
        "status",
        "",
    ) == ()
