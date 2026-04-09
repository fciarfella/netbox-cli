"""Static help text for the interactive shell."""

from __future__ import annotations

REPL_COMMANDS: tuple[str, ...] = (
    "help",
    "cd",
    "profile",
    "filters",
    "list",
    "get",
    "create",
    "update",
    "search",
    "open",
    "cols",
    "format",
    "limit",
    "exit",
)

REPL_HELP_TEXT = """
NetBox shell

Navigate:
  cd [path]         Change context; supports /, ., .., and relative paths

Inspect:
  filters           Show filters for the current endpoint
  list [term] [k=v ...]
                    In root/app contexts, list child apps or endpoints
                    In endpoint contexts, list rows; bare terms are treated as q=<term>
  get k=v [...]     Fetch one row; errors if the lookup is ambiguous
  create ...        In endpoint context, create one row from key=value fields or --file
  update ...        In endpoint context, update one row by id=<id> from fields or --file
  search <term>     Search curated endpoints and number the results
  open <index>      Open a numbered row from the last list or search

Session:
  profile list      Show configured profiles and mark the active one
  profile use NAME  Persist and switch to a different profile in this shell
  cols              Show active columns for the current endpoint
  cols a,b,c        Override columns for the current endpoint
  cols reset        Restore default endpoint columns
  format <name>     Set table, json, or csv
  limit <n>         Set the current row limit
  exit              Leave the shell

Writes support --dry-run. Real REPL writes ask for confirmation before sending POST or PATCH.
`profile add` stays in the classic CLI as `netbox profile add <name>`.

Use TAB for contextual completion. Run `help`, `help create`, `help update`, or `help profile` any time to see this summary again.
""".strip()

CREATE_HELP_TEXT = """
Create one row in the current endpoint context.

Usage:
  create key=value [key=value ...] [--dry-run]
  create --file payload.yaml|json [--dry-run]

Choose exactly one payload input method: inline key=value fields or --file.
Real writes ask for confirmation. `--dry-run` only previews the request.
""".strip()

UPDATE_HELP_TEXT = """
Update one row in the current endpoint context.

Usage:
  update id=<id> key=value [key=value ...] [--dry-run]
  update id=<id> --file patch.yaml|json [--dry-run]

Choose exactly one payload input method: inline key=value fields or --file.
Real writes ask for confirmation. `--dry-run` only previews the request.
""".strip()

PROFILE_HELP_TEXT = """
Manage configured profiles inside the current shell session.

Usage:
  profile list
  profile use <name>

`profile use` switches the current shell session and updates the persisted active profile.
If the shell was started with `netbox --profile <name> shell`, interactive profile switching is disabled for that session.
Use `netbox profile add <name>` in the classic CLI to create or update profiles.
""".strip()

REPL_COMMAND_HELP: dict[str, str] = {
    "create": CREATE_HELP_TEXT,
    "profile": PROFILE_HELP_TEXT,
    "update": UPDATE_HELP_TEXT,
}
