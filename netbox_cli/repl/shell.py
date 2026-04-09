"""Prompt Toolkit shell loop and prompt formatting."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from ..client import NetBoxClient
from ..errors import FeatureNotReadyError, NetBoxCLIError
from ..render import get_stdout_console
from .commands import execute_command
from .completer import NetBoxShellCompleter
from .metadata import CompletionMetadataProvider
from .state import ShellState
from ..settings import AppPaths

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.completion.base import get_common_complete_suffix
    from prompt_toolkit.document import Document
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.styles import Style
except ImportError:  # pragma: no cover - fallback for environments without prompt_toolkit
    PromptSession = None  # type: ignore[assignment]
    CompleteEvent = None  # type: ignore[assignment]
    Document = None  # type: ignore[assignment]
    KeyBindings = None  # type: ignore[assignment]
    get_common_complete_suffix = None  # type: ignore[assignment]

    class FormattedText(list):  # type: ignore[no-redef]
        """Minimal fallback formatted text container."""

    FileHistory = None  # type: ignore[assignment]
    patch_stdout = None  # type: ignore[assignment]

    class Style(dict):  # type: ignore[no-redef]
        """Minimal fallback style container."""

        @classmethod
        def from_dict(cls, data: dict[str, str]) -> "Style":
            return cls(data)


PROMPT_STYLE = Style.from_dict(
    {
        "prompt.shell": "bold ansiblue",
        "prompt.separator": "ansibrightblack",
        "prompt.path": "bold ansicyan",
        "prompt.symbol": "ansibrightblack",
        "prompt.meta": "ansibrightblack",
    }
)


def launch_shell(
    client: NetBoxClient,
    *,
    history_path: Path,
    initial_state: ShellState,
    app_paths: AppPaths,
    console: Console | None = None,
) -> None:
    """Run the interactive shell session."""

    if PromptSession is None or FileHistory is None or patch_stdout is None:
        raise FeatureNotReadyError(
            "prompt_toolkit is not available in this environment."
        )

    console = console if console is not None else get_stdout_console()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    active_client = client
    metadata_provider = CompletionMetadataProvider(active_client)
    completer = NetBoxShellCompleter(
        state=initial_state,
        metadata_provider=metadata_provider,
    )
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=completer,
        key_bindings=build_shell_key_bindings(completer),
    )

    console.print(
        Panel.fit(
            "Read-only NetBox shell.\nType `help` for commands and `exit` to leave.",
            title="NetBox Shell",
            border_style="cyan",
        )
    )

    with patch_stdout():
        while True:
            try:
                line = session.prompt(
                    build_left_prompt(initial_state),
                    rprompt=build_right_prompt(initial_state),
                    style=PROMPT_STYLE,
                )
            except KeyboardInterrupt:
                console.print()
                continue
            except EOFError:
                console.print()
                break

            try:
                result = execute_command(
                    initial_state,
                    line,
                    active_client,
                    console=console,
                    app_paths=app_paths,
                )
            except NetBoxCLIError as exc:
                console.print(f"[bold red]Error:[/] {exc}")
                continue

            if result.next_client is not None:
                active_client = result.next_client
                metadata_provider.replace_client(active_client)

            if result.should_exit:
                break


def build_prompt(state: ShellState) -> str:
    """Return the plain left prompt text for the current shell state."""

    return build_left_prompt_text(state)


def build_left_prompt_text(state: ShellState) -> str:
    """Return the plain left prompt text."""

    prompt_label = state.profile_name or "netbox"
    return f"{prompt_label}:{state.current_path}> "


def build_right_prompt_text(state: ShellState) -> str:
    """Return the plain right prompt text."""

    return f"{state.output_format} | {state.limit}"


def build_left_prompt(state: ShellState) -> Any:
    """Return the styled left prompt fragments for prompt_toolkit."""

    prompt_label = state.profile_name or "netbox"
    return FormattedText(
        [
            ("class:prompt.shell", prompt_label),
            ("class:prompt.separator", ":"),
            ("class:prompt.path", state.current_path),
            ("class:prompt.symbol", "> "),
        ]
    )


def build_right_prompt(state: ShellState) -> Any:
    """Return the styled right prompt fragments for prompt_toolkit."""

    return FormattedText(
        [
            ("class:prompt.meta", build_right_prompt_text(state)),
        ]
    )


def build_shell_key_bindings(completer: NetBoxShellCompleter) -> Any:
    """Return custom shell key bindings."""

    if KeyBindings is None:
        return None

    bindings = KeyBindings()

    @bindings.add("enter")
    def _(event) -> None:  # pragma: no cover - exercised through handle_enter_key
        handle_enter_key(event)

    @bindings.add("tab")
    def _(event) -> None:  # pragma: no cover - exercised through handle_tab_key
        handle_tab_key(event, completer)

    @bindings.add("?")
    def _(event) -> None:  # pragma: no cover - exercised through handle_context_help
        handle_context_help(event, completer)

    return bindings


def handle_enter_key(event: Any) -> None:
    """Accept the selected completion before executing the current buffer."""

    buffer = event.current_buffer
    if accept_selected_completion(buffer):
        return

    buffer.validate_and_handle()


def handle_tab_key(event: Any, completer: NetBoxShellCompleter) -> None:
    """Apply unique completions immediately, otherwise fall back to menu completion."""

    buffer = event.current_buffer
    complete_state = getattr(buffer, "complete_state", None)
    if complete_state is not None:
        buffer.complete_next()
        return

    _insert_mutation_completion_separator(buffer)
    completions = get_buffer_completions(completer, buffer)
    if not completions:
        event.app.output.bell()
        return

    if len(completions) == 1:
        _apply_completion(buffer, completions[0])
        return

    document = _document_for_completion(getattr(buffer, "document", None), buffer)
    if get_common_complete_suffix is not None:
        common_suffix = get_common_complete_suffix(document, completions)
        if common_suffix:
            buffer.insert_text(common_suffix)
            return

    buffer.start_completion(
        select_first=False,
        insert_common_part=False,
    )


def accept_selected_completion(buffer: Any) -> bool:
    """Apply the selected completion, if any, instead of executing the buffer."""

    complete_state = getattr(buffer, "complete_state", None)
    if complete_state is None:
        return False

    completion = getattr(complete_state, "current_completion", None)
    if completion is None:
        return False

    _apply_completion(buffer, completion)
    return True


def handle_context_help(event: Any, completer: NetBoxShellCompleter) -> None:
    """Trigger contextual help without inserting a literal question mark."""

    text_before_cursor = event.current_buffer.document.text_before_cursor
    if not get_context_help_suggestions(completer, text_before_cursor):
        event.app.output.bell()
        return

    _insert_mutation_completion_separator(event.current_buffer)
    event.current_buffer.start_completion(
        select_first=False,
        insert_common_part=False,
    )


def get_buffer_completions(
    completer: NetBoxShellCompleter,
    buffer: Any,
) -> list[object]:
    """Return completion candidates for the current buffer cursor position."""

    document = _document_for_completion(getattr(buffer, "document", None), buffer)
    complete_event = (
        CompleteEvent(completion_requested=True)
        if CompleteEvent is not None
        else None
    )
    return list(completer.get_completions(document, complete_event))


def _document_for_completion(document: Any, buffer: Any) -> Any:
    text_before_cursor = getattr(document, "text_before_cursor", None)
    if isinstance(text_before_cursor, str):
        if Document is not None:
            return Document(
                text=text_before_cursor,
                cursor_position=len(text_before_cursor),
            )
        return document

    buffer_text = getattr(buffer, "text", "")
    if Document is not None:
        return Document(text=buffer_text, cursor_position=len(buffer_text))
    return type("Document", (), {"text_before_cursor": buffer_text})()


def _apply_completion(buffer: Any, completion: object) -> None:
    buffer.apply_completion(completion)
    if getattr(completion, "text", "").endswith("="):
        buffer.start_completion(
            select_first=False,
            insert_common_part=False,
        )


def _insert_mutation_completion_separator(buffer: Any) -> None:
    if not _needs_mutation_completion_separator(buffer):
        return

    buffer.insert_text(" ")


def _needs_mutation_completion_separator(buffer: Any) -> bool:
    document = getattr(buffer, "document", None)
    text_before_cursor = getattr(document, "text_before_cursor", None)
    if not isinstance(text_before_cursor, str):
        text_before_cursor = getattr(buffer, "text", "")

    if not text_before_cursor or text_before_cursor[-1].isspace():
        return False

    try:
        tokens = shlex.split(text_before_cursor)
    except ValueError:
        return False

    if not tokens or tokens[0].lower() != "update":
        return False

    last_token = tokens[-1]
    if "=" not in last_token or last_token.startswith("-"):
        return False

    key, value = last_token.split("=", 1)
    return key.strip() == "id" and bool(value.strip())


def get_context_help_suggestions(
    completer: NetBoxShellCompleter,
    text_before_cursor: str,
) -> tuple[str, ...]:
    """Return contextual suggestions for the current cursor position."""

    if Document is not None:
        document = Document(
            text=text_before_cursor,
            cursor_position=len(text_before_cursor),
        )
    else:  # pragma: no cover - local fallback when prompt_toolkit is unavailable
        document = type(
            "Document",
            (),
            {"text_before_cursor": text_before_cursor},
        )()

    suggestions: list[str] = []
    for completion in completer.get_completions(document, None):
        if completion.text not in suggestions:
            suggestions.append(completion.text)
    return tuple(suggestions)
