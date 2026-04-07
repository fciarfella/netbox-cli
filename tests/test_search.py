from __future__ import annotations

import pytest

from netbox_cli.errors import InvalidEndpointError, NoResultsError
from netbox_cli.search import SearchTarget, global_search


class StubSearchClient:
    def __init__(
        self,
        payloads: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[list[dict[str, object]], int]],
    ) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, tuple[tuple[str, str], ...] | None]] = []

    def paginate(self, path: str, *, params=None, limit=None):  # noqa: ANN001
        del limit
        normalized_params = None
        if params is not None:
            if isinstance(params, dict):
                normalized_params = tuple((str(key), str(value)) for key, value in params.items())
            else:
                normalized_params = tuple((str(key), str(value)) for key, value in params)
        self.calls.append((path, normalized_params))
        rows, total_count = self.payloads.get((path, normalized_params or ()), ([], 0))
        return type(
            "Pagination",
            (),
            {
                "rows": rows,
                "total_count": total_count,
            },
        )()


def test_global_search_groups_results_and_ranks_them() -> None:
    targets = (
        SearchTarget(
            title="Devices",
            endpoint_path="dcim/devices",
            filter_builder=lambda term: {"q": term},
            match_fields=("name",),
        ),
        SearchTarget(
            title="Sites",
            endpoint_path="dcim/sites",
            filter_builder=lambda term: {"q": term},
            match_fields=("name",),
        ),
    )
    client = StubSearchClient(
        {
            ("dcim/devices", (("q", "router"),)): (
                [
                    {"name": "router-10"},
                    {"name": "router"},
                    {"name": "edge-router"},
                ],
                3,
            ),
            ("dcim/sites", (("q", "router"),)): (
                [
                    {"name": "router-farm"},
                ],
                1,
            ),
        }
    )

    groups = global_search(client, "router", limit_per_group=2, search_targets=targets)

    assert [group.endpoint_path for group in groups] == ["dcim/devices", "dcim/sites"]
    assert groups[0].total_count == 3
    assert [row["name"] for row in groups[0].rows] == ["router", "router-10"]


def test_global_search_dns_matches_record_value_and_dedupes(monkeypatch) -> None:
    from netbox_cli import search as search_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        if endpoint_path == "plugins/netbox-dns/records":
            return [
                type("Filter", (), {"name": "value"})(),
                type("Filter", (), {"name": "value__ic"})(),
                type("Filter", (), {"name": "name__ic"})(),
                type("Filter", (), {"name": "q"})(),
            ]
        raise InvalidEndpointError(endpoint_path)

    monkeypatch.setattr(search_module, "list_filters", fake_list_filters)

    client = StubSearchClient(
        {
            ("plugins/netbox-dns/records", (("value", "198.51.100.10"),)): (
                [
                    {
                        "id": 10,
                        "zone": {"name": "example.com"},
                        "name": "gw1",
                        "type": "A",
                        "value": "198.51.100.10",
                        "status": "active",
                    }
                ],
                1,
            ),
            ("plugins/netbox-dns/records", (("value__ic", "198.51.100.10"),)): (
                [
                    {
                        "id": 10,
                        "zone": {"name": "example.com"},
                        "name": "gw1",
                        "type": "A",
                        "value": "198.51.100.10",
                        "status": "active",
                    },
                    {
                        "id": 11,
                        "zone": {"name": "example.com"},
                        "name": "gw1-backup",
                        "type": "A",
                        "value": "198.51.100.10/32",
                        "status": "active",
                    },
                ],
                2,
            ),
            ("plugins/netbox-dns/records", (("name__ic", "198.51.100.10"),)): ([], 0),
            ("plugins/netbox-dns/records", (("q", "198.51.100.10"),)): ([], 0),
        }
    )

    groups = global_search(client, "198.51.100.10")

    assert [group.endpoint_path for group in groups] == ["plugins/netbox-dns/records"]
    assert groups[0].total_count == 2
    assert [row["id"] for row in groups[0].rows] == [10, 11]
    assert ("plugins/netbox-dns/records", (("value", "198.51.100.10"),)) in client.calls
    assert ("plugins/netbox-dns/records", (("value__ic", "198.51.100.10"),)) in client.calls


def test_global_search_dns_uses_alias_path_when_needed(monkeypatch) -> None:
    from netbox_cli import search as search_module

    def fake_list_filters(client, endpoint_path):  # type: ignore[no-untyped-def]
        if endpoint_path == "plugins/netbox-dns/records":
            raise InvalidEndpointError(endpoint_path)
        return [
            type("Filter", (), {"name": "value"})(),
            type("Filter", (), {"name": "q"})(),
        ]

    monkeypatch.setattr(search_module, "list_filters", fake_list_filters)

    client = StubSearchClient(
        {
            ("plugins/netbox_dns/records", (("value", "198.51.100.10"),)): (
                [
                    {
                        "id": 99,
                        "zone": {"name": "example.net"},
                        "name": "gw2",
                        "type": "A",
                        "value": "198.51.100.10",
                    }
                ],
                1,
            ),
            ("plugins/netbox_dns/records", (("q", "198.51.100.10"),)): ([], 0),
        }
    )

    groups = global_search(client, "198.51.100.10")

    assert groups[0].endpoint_path == "plugins/netbox_dns/records"
    assert groups[0].rows[0]["id"] == 99


def test_global_search_skips_missing_targets() -> None:
    targets = (
        SearchTarget(
            title="Devices",
            endpoint_path="dcim/devices",
            filter_builder=lambda term: {"q": term},
            match_fields=("name",),
        ),
    )
    client = StubSearchClient({("dcim/devices", (("q", "router"),)): ([], 0)})

    with pytest.raises(NoResultsError):
        global_search(client, "router", search_targets=targets)
