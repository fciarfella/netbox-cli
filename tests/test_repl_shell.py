from __future__ import annotations

from dataclasses import dataclass, field

from netbox_cli.discovery import FilterDefinition
from netbox_cli.repl.metadata import FilterValueSuggestion
from netbox_cli.repl.shell import (
    accept_selected_completion,
    build_left_prompt,
    build_left_prompt_text,
    build_prompt,
    build_right_prompt,
    build_right_prompt_text,
    get_context_help_suggestions,
    handle_enter_key,
    handle_context_help,
)
from netbox_cli.repl.completer import NetBoxShellCompleter
from netbox_cli.repl.state import ShellState


def _formatted_text_to_plain_text(value: object) -> str:
    try:
        from prompt_toolkit.formatted_text import to_formatted_text

        fragments = to_formatted_text(value)
    except ImportError:  # pragma: no cover - fallback path when prompt_toolkit is unavailable
        fragments = value

    if isinstance(fragments, str):
        return fragments

    return "".join(fragment[1] for fragment in fragments)


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
                FilterDefinition(name="status"),
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
        if not prefix:
            return suggestions
        normalized_prefix = prefix.casefold()
        return tuple(
            suggestion
            for suggestion in suggestions
            if suggestion.value.casefold().startswith(normalized_prefix)
            or (
                suggestion.label is not None
                and suggestion.label.casefold().startswith(normalized_prefix)
            )
        )


def make_completer(state: ShellState) -> NetBoxShellCompleter:
    return NetBoxShellCompleter(
        state=state,
        metadata_provider=StaticMetadataProvider(),
    )


class FakeOutput:
    def __init__(self) -> None:
        self.bell_count = 0

    def bell(self) -> None:
        self.bell_count += 1


class FakeBuffer:
    def __init__(self, text_before_cursor: str) -> None:
        self.text = text_before_cursor
        self.document = type("Document", (), {"text_before_cursor": text_before_cursor})()
        self.complete_state = None
        self.start_completion_calls: list[dict[str, object]] = []
        self.applied_completions: list[object] = []
        self.validate_and_handle_calls = 0

    def start_completion(self, **kwargs: object) -> None:
        self.start_completion_calls.append(kwargs)

    def apply_completion(self, completion: object) -> None:
        start_position = getattr(completion, "start_position", 0)
        insertion_text = getattr(completion, "text", "")
        prefix_start = len(self.text) + start_position
        self.text = f"{self.text[:prefix_start]}{insertion_text}"
        self.document = type("Document", (), {"text_before_cursor": self.text})()
        self.applied_completions.append(completion)
        self.complete_state = None

    def validate_and_handle(self) -> None:
        self.validate_and_handle_calls += 1


@dataclass
class FakeCompletion:
    text: str
    start_position: int = 0


@dataclass
class FakeCompletionState:
    current_completion: FakeCompletion | None = None


class FakeEvent:
    def __init__(self, text_before_cursor: str, *, completion: FakeCompletion | None = None) -> None:
        self.current_buffer = FakeBuffer(text_before_cursor)
        self.current_buffer.complete_state = FakeCompletionState(completion)
        self.app = type("App", (), {"output": FakeOutput()})()


def test_left_prompt_text_reflects_current_path() -> None:
    state = ShellState(current_path="/dcim/devices")

    assert build_prompt(state) == "netbox:/dcim/devices> "
    assert build_left_prompt_text(state) == "netbox:/dcim/devices> "
    assert _formatted_text_to_plain_text(build_left_prompt(state)) == "netbox:/dcim/devices> "


def test_right_prompt_text_reflects_output_format_and_limit() -> None:
    state = ShellState(current_path="/dcim/devices", output_format="table", limit=15)

    assert build_right_prompt_text(state) == "table | 15"
    assert _formatted_text_to_plain_text(build_right_prompt(state)) == "table | 15"


def test_prompt_helpers_update_after_state_changes() -> None:
    state = ShellState(current_path="/dcim")

    state.set_path("devices")
    state.set_output_format("json")
    state.set_limit(5)

    assert build_left_prompt_text(state) == "netbox:/dcim/devices> "
    assert build_right_prompt_text(state) == "json | 5"
    assert _formatted_text_to_plain_text(build_left_prompt(state)) == "netbox:/dcim/devices> "
    assert _formatted_text_to_plain_text(build_right_prompt(state)) == "json | 5"


def test_context_help_at_empty_prompt_shows_commands() -> None:
    suggestions = get_context_help_suggestions(make_completer(ShellState()), "")

    assert "help" in suggestions
    assert "list" in suggestions
    assert "ls" not in suggestions
    assert "pwd" not in suggestions
    assert "clear" not in suggestions
    assert "back" not in suggestions
    assert "home" not in suggestions


def test_context_help_after_cd_shows_paths() -> None:
    suggestions = get_context_help_suggestions(make_completer(ShellState()), "cd ")

    assert "dcim" in suggestions
    assert "plugins" in suggestions


def test_context_help_after_list_shows_filters() -> None:
    suggestions = get_context_help_suggestions(
        make_completer(ShellState(current_path="/dcim/devices")),
        "list ",
    )

    assert "status=" in suggestions
    assert "site=" in suggestions


def test_context_help_after_filter_equals_shows_values() -> None:
    suggestions = get_context_help_suggestions(
        make_completer(ShellState(current_path="/dcim/devices")),
        "list status=",
    )

    assert suggestions == ("active", "offline")


def test_context_help_does_not_insert_literal_question_mark() -> None:
    completer = make_completer(ShellState(current_path="/dcim/devices"))
    event = FakeEvent("list status=")

    handle_context_help(event, completer)

    assert event.current_buffer.text == "list status="
    assert event.current_buffer.start_completion_calls == [
        {"select_first": False, "insert_common_part": False}
    ]
    assert event.app.output.bell_count == 0


def test_enter_accepts_selected_completion_without_executing() -> None:
    event = FakeEvent("li", completion=FakeCompletion("list", start_position=-2))

    handle_enter_key(event)

    assert event.current_buffer.text == "list"
    assert event.current_buffer.validate_and_handle_calls == 0
    assert event.current_buffer.start_completion_calls == []


def test_enter_with_no_active_completion_executes_command() -> None:
    event = FakeEvent("list status=active", completion=None)
    event.current_buffer.complete_state = None

    handle_enter_key(event)

    assert event.current_buffer.validate_and_handle_calls == 1
    assert event.current_buffer.text == "list status=active"


def test_accepting_filter_completion_ending_with_equals_stays_in_edit_mode() -> None:
    event = FakeEvent(
        "list router01 st",
        completion=FakeCompletion("status=", start_position=-2),
    )

    handle_enter_key(event)

    assert event.current_buffer.text == "list router01 status="
    assert event.current_buffer.validate_and_handle_calls == 0
    assert event.current_buffer.start_completion_calls == [
        {"select_first": False, "insert_common_part": False}
    ]


def test_accept_selected_completion_returns_false_when_no_selection_exists() -> None:
    buffer = FakeBuffer("list router01 status=")

    assert accept_selected_completion(buffer) is False
    assert buffer.text == "list router01 status="


def test_context_help_reuses_same_candidates_as_the_completer() -> None:
    completer = make_completer(ShellState(current_path="/dcim/devices"))
    text_before_cursor = "list st"
    document = type("Document", (), {"text_before_cursor": text_before_cursor})()

    question_mark_suggestions = get_context_help_suggestions(completer, text_before_cursor)
    tab_suggestions = tuple(
        completion.text for completion in completer.get_completions(document, None)
    )

    assert question_mark_suggestions == tab_suggestions
