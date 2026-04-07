"""Prompt Toolkit shell loop and prompt formatting."""

from __future__ import annotations

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

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.document import Document
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.styles import Style
except ImportError:  # pragma: no cover - fallback for environments without prompt_toolkit
    PromptSession = None  # type: ignore[assignment]
    Document = None  # type: ignore[assignment]
    KeyBindings = None  # type: ignore[assignment]

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
    console: Console | None = None,
) -> None:
    """Run the interactive shell session."""

    if PromptSession is None or FileHistory is None or patch_stdout is None:
        raise FeatureNotReadyError(
            "prompt_toolkit is not available in this environment."
        )

    console = console if console is not None else get_stdout_console()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_provider = CompletionMetadataProvider(client)
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
                    client,
                    console=console,
                )
            except NetBoxCLIError as exc:
                console.print(f"[bold red]Error:[/] {exc}")
                continue

            if result.should_exit:
                break


def build_prompt(state: ShellState) -> str:
    """Return the plain left prompt text for the current shell state."""

    return build_left_prompt_text(state)


def build_left_prompt_text(state: ShellState) -> str:
    """Return the plain left prompt text."""

    return f"netbox:{state.current_path}> "


def build_right_prompt_text(state: ShellState) -> str:
    """Return the plain right prompt text."""

    return f"{state.output_format} | {state.limit}"


def build_left_prompt(state: ShellState) -> Any:
    """Return the styled left prompt fragments for prompt_toolkit."""

    return FormattedText(
        [
            ("class:prompt.shell", "netbox"),
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


def accept_selected_completion(buffer: Any) -> bool:
    """Apply the selected completion, if any, instead of executing the buffer."""

    complete_state = getattr(buffer, "complete_state", None)
    if complete_state is None:
        return False

    completion = getattr(complete_state, "current_completion", None)
    if completion is None:
        return False

    buffer.apply_completion(completion)
    if getattr(completion, "text", "").endswith("="):
        buffer.start_completion(
            select_first=False,
            insert_common_part=False,
        )
    return True


def handle_context_help(event: Any, completer: NetBoxShellCompleter) -> None:
    """Trigger contextual help without inserting a literal question mark."""

    text_before_cursor = event.current_buffer.document.text_before_cursor
    if not get_context_help_suggestions(completer, text_before_cursor):
        event.app.output.bell()
        return

    event.current_buffer.start_completion(
        select_first=False,
        insert_common_part=False,
    )


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
