from __future__ import annotations

from dataclasses import dataclass, field

from netbox_cli.discovery import ChoiceDefinition, FilterDefinition
from netbox_cli.repl.completer import NetBoxShellCompleter
from netbox_cli.repl.metadata import FilterValueSuggestion
from netbox_cli.repl.state import ShellState
from netbox_cli.settings import RecordReference


@dataclass
class StaticMetadataProvider:
    apps: tuple[str, ...] = ("dcim", "ipam", "plugins")
    children: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "dcim": ("devices", "sites"),
            "plugins": ("netbox_dns",),
            "plugins/netbox_dns": ("records",),
        }
    )
    filters: dict[str, tuple[FilterDefinition, ...]] = field(
        default_factory=lambda: {
            "dcim/devices": (
                FilterDefinition(
                    name="status",
                    choices=(
                        ChoiceDefinition(value="active", label="Active"),
                        ChoiceDefinition(value="offline", label="Offline"),
                        ChoiceDefinition(value="planned", label="Planned"),
                    ),
                ),
                FilterDefinition(name="name"),
                FilterDefinition(name="role"),
                FilterDefinition(name="site"),
                FilterDefinition(name="rack"),
            )
        }
    )
    value_suggestions: dict[tuple[str, str], tuple[FilterValueSuggestion, ...]] = field(
        default_factory=lambda: {
            (
                "dcim/devices",
                "status",
            ): (
                FilterValueSuggestion(value="active", label="Active"),
                FilterValueSuggestion(value="offline", label="Offline"),
                FilterValueSuggestion(value="planned", label="Planned"),
            ),
            (
                "dcim/devices",
                "site",
            ): (
                FilterValueSuggestion(value="dc1", label="DC1", source="related"),
            ),
            (
                "dcim/devices",
                "rack",
            ): (
                FilterValueSuggestion(value="rack-a1", label="DC1", source="related"),
                FilterValueSuggestion(value="rack-a2", label="DC1", source="related"),
            ),
        }
    )

    def get_apps(self) -> tuple[str, ...]:
        return self.apps

    def get_child_segments(self, parent_service_path: str) -> tuple[str, ...]:
        return self.children.get(parent_service_path.strip("/"), ())

    def get_filters(self, endpoint_path: str) -> tuple[FilterDefinition, ...]:
        return self.filters.get(endpoint_path.strip("/"), ())

    def get_filter_names(self, endpoint_path: str) -> tuple[str, ...]:
        return tuple(filter_def.name for filter_def in self.get_filters(endpoint_path))

    def get_filter_choices(self, endpoint_path: str, filter_name: str) -> tuple[str, ...]:
        for filter_def in self.get_filters(endpoint_path):
            if filter_def.name == filter_name:
                return tuple(choice.value for choice in filter_def.choices)
        return ()

    def get_filter_value_suggestions(
        self,
        endpoint_path: str,
        filter_name: str,
        prefix: str,
        *,
        recent_results=(),
    ) -> tuple[FilterValueSuggestion, ...]:
        del recent_results
        suggestions = self.value_suggestions.get(
            (endpoint_path.strip("/"), filter_name.strip()),
            (),
        )
        normalized_prefix = prefix.casefold()
        if not normalized_prefix:
            return suggestions
        return tuple(
            suggestion
            for suggestion in suggestions
            if suggestion.value.casefold().startswith(normalized_prefix)
            or (
                suggestion.label is not None
                and suggestion.label.casefold().startswith(normalized_prefix)
            )
        )


@dataclass(frozen=True)
class FakeDocument:
    text_before_cursor: str


def completion_texts(completer: NetBoxShellCompleter, text: str) -> list[str]:
    return [
        completion.text
        for completion in completer.get_completions(FakeDocument(text), None)
    ]


def completion_objects(completer: NetBoxShellCompleter, text: str) -> list[object]:
    return list(completer.get_completions(FakeDocument(text), None))


def completion_meta_text(completion: object) -> str | None:
    meta = getattr(completion, "display_meta", None)
    if meta is None:
        return None
    if isinstance(meta, str):
        return meta

    try:
        from prompt_toolkit.formatted_text import to_plain_text
    except ImportError:  # pragma: no cover - fallback path when prompt_toolkit is unavailable
        return str(meta)

    return to_plain_text(meta)


def test_command_completion_from_root_context() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(),
        metadata_provider=StaticMetadataProvider(),
    )

    assert "help" in completion_texts(completer, "he")
    assert "ls" not in completion_texts(completer, "l")
    assert "pwd" not in completion_texts(completer, "p")
    assert "clear" not in completion_texts(completer, "c")
    assert "back" not in completion_texts(completer, "b")
    assert "home" not in completion_texts(completer, "h")


def test_root_context_path_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "cd d") == ["dcim"]


def test_app_context_path_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "cd de") == ["devices"]


def test_endpoint_filter_name_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "list st") == ["status="]


def test_endpoint_filter_name_completion_allows_repeated_keys() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "list site=dc1 si") == ["site="]


def test_endpoint_filter_choice_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "list status=") == [
        "active",
        "offline",
        "planned",
    ]


def test_endpoint_related_filter_value_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "list site=d") == ["dc1"]


def test_endpoint_related_filter_value_completion_uses_label_as_meta_only() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    completion = completion_objects(completer, "list site=d")[0]

    assert completion.text == "dc1"
    assert completion_meta_text(completion) == "DC1"


def test_endpoint_related_filter_value_completion_with_empty_prefix() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "list router01 site=") == ["dc1"]
    assert completion_texts(completer, "list router01 rack=") == ["rack-a1", "rack-a2"]


def test_columns_completion_uses_known_endpoint_columns() -> None:
    state = ShellState(
        current_path="/dcim/devices",
        last_results=[
            RecordReference(
                endpoint_path="dcim/devices",
                object_id=1,
                display="leaf-01",
                payload={"id": 1, "name": "leaf-01", "serial": "ABC123"},
            )
        ],
    )
    completer = NetBoxShellCompleter(
        state=state,
        metadata_provider=StaticMetadataProvider(),
    )

    texts = completion_texts(completer, "cols na")

    assert "name" in texts


def test_format_completion() -> None:
    completer = NetBoxShellCompleter(
        state=ShellState(current_path="/dcim/devices"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(completer, "format j") == ["json"]


def test_plugin_path_completion_absolute_and_relative() -> None:
    root_completer = NetBoxShellCompleter(
        state=ShellState(),
        metadata_provider=StaticMetadataProvider(),
    )
    plugin_completer = NetBoxShellCompleter(
        state=ShellState(current_path="/plugins/netbox_dns"),
        metadata_provider=StaticMetadataProvider(),
    )

    assert completion_texts(root_completer, "cd /plugins/ne") == ["/plugins/netbox_dns"]
    assert completion_texts(plugin_completer, "cd re") == ["records"]
