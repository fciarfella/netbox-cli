## Project Overview

This repository contains a read-only NetBox CLI with two aligned interfaces:

- a classic CLI for documentation, automation, and copy/paste use
- an interactive shell (REPL) built on the same service layer

The shell is a convenience layer. It must not evolve into a separate command language.

## Architecture Rules

- Keep `app.py` thin. Command handlers should parse options and delegate.
- Keep HTTP access in `client.py`.
- Keep discovery logic in `discovery.py`.
- Keep endpoint-scoped list/get behavior in `query.py`.
- Keep curated global search behavior in `search.py`.
- Keep all rendering in `render.py`.
- Keep REPL command handling in `repl/commands.py`.
- Keep autocomplete behavior in `repl/completer.py` and `repl/metadata.py`.
- Keep endpoint-specific default columns in `profiles.py`.
- Do not move output formatting into service modules.
- Do not move HTTP logic into renderers.
- Do not call Typer command handlers from the REPL.

## CLI/REPL Alignment Rules

- Keep CLI and REPL semantics aligned wherever possible.
- Keep `search` global in both interfaces.
- Keep `get` strict and deterministic in both interfaces.
- Keep `list` endpoint-scoped in both interfaces.
- Keep `list` shorthand aligned in both interfaces:
  - `list foo` -> `q=foo`
  - `list foo bar` -> `q="foo bar"`
  - `list foo status=active` -> `q=foo` plus explicit filters
- Keep repeated-key filters aligned in both interfaces.
- Only keep shell-specific behavior where it depends on interactive state, such as:
  - `cd`
  - `open <index>`
  - persistent REPL column state
  - autocomplete

## Testing Expectations

- Run `pytest` before considering work complete.
- Keep compileability intact.
- Add or update tests for behavior changes.
- Prefer regression tests for bug fixes.
- Test both CLI and REPL behavior when semantics are meant to stay aligned.

## Change Discipline

- Understand the current path through CLI, services, renderers, and REPL before changing it.
- Change the smallest correct layer.
- Avoid duplicating logic when a shared helper can express the behavior cleanly.
- Keep the project read-only unless explicitly asked to change that.
- Update `README.md` when user-facing behavior changes.
