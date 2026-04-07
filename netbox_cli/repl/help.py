"""Static help text for the interactive shell."""

REPL_COMMANDS: tuple[str, ...] = (
    "help",
    "cd",
    "filters",
    "list",
    "get",
    "search",
    "open",
    "cols",
    "format",
    "limit",
    "exit",
)

REPL_HELP_TEXT = """
Read-only NetBox shell

Navigate:
  cd [path]         Change context; supports /, ., .., and relative paths

Inspect:
  filters           Show filters for the current endpoint
  list [term] [k=v ...]
                    In root/app contexts, list child apps or endpoints
                    In endpoint contexts, list rows; bare terms are treated as q=<term>
  get k=v [...]     Fetch one row; errors if the lookup is ambiguous
  search <term>     Search curated endpoints and number the results
  open <index>      Open a numbered row from the last list or search

Session:
  cols              Show active columns for the current endpoint
  cols a,b,c        Override columns for the current endpoint
  cols reset        Restore default endpoint columns
  format <name>     Set table, json, or csv
  limit <n>         Set the current row limit
  exit              Leave the shell

Use TAB for contextual completion. Run `help` any time to see this summary again.
""".strip()
