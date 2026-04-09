# NetBox CLI

[![PyPI](https://img.shields.io/pypi/v/netbox-explorer.svg)](https://pypi.org/project/netbox-explorer/)
[![License](https://img.shields.io/github/license/fciarfella/netbox-cli.svg)](https://github.com/fciarfella/netbox-cli/blob/main/LICENSE)

## What It Is

`netbox-cli` is a Python CLI for NetBox discovery, queries, and explicit create/update operations.

Published on PyPI as `netbox-explorer`. Installed command: `netbox`.

It provides two aligned interfaces:

- a standard command line for automation, documentation, and copy/paste use
- an interactive shell for faster exploration, using the same service layer and command semantics

The CLI is the primary interface. 

![CLI demo](docs/demo-cli.gif)

The shell is a convenience layer on top of it.

![Shell demo](docs/demo-shell.gif)


## Features

- explicit multi-profile configuration with `netbox profile add`, `netbox profile list`, and `netbox profile use`
- config validation and connectivity checks with `netbox config test`
- discovery of apps, endpoints, filters, and known choices from the NetBox API
- `list`, `get`, grouped global `search`, plus minimal `create` and `update`
- Rich tables for interactive terminal output
- JSON and CSV output for automation and piping
- interactive shell with history, contextual navigation, and autocomplete
- local metadata caching for API root, schema, and endpoint `OPTIONS`

## Install

Using a virtual environment is the recommended install path.

### Install from PyPI

Use this for the normal published package install.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install netbox-explorer
```

### Install from GitHub

Use this when you want to try the tool quickly without cloning the repository.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install "git+https://github.com/fciarfella/netbox-cli.git"
```

### Install a tagged release from GitHub

Use a tagged release when you want a specific published GitHub version, such as `v0.6.0`.

```bash
python3 -m pip install "git+https://github.com/fciarfella/netbox-cli.git@v0.6.0"
```

### Install from a local clone

Use a local clone when you want to develop the project or make local changes.

```bash
git clone https://github.com/fciarfella/netbox-cli.git
cd netbox-cli
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

### Install development dependencies

```bash
python3 -m pip install -e ".[dev]"
```

### Verify the install

```bash
netbox --help
netbox --version
```

### Reactivate the environment

If you open a new shell later, reactivate the environment first:

```bash
source .venv/bin/activate
```

## Configuration

`config.toml` is the primary configuration source for the tool. Environment variables are supported as optional overrides, but normal usage should start with an explicit config file.

The CLI now supports multiple named profiles with a persisted active profile. Resolution order is:

1. explicit `--profile <name>`
2. persisted `current_profile`
3. legacy single-profile config fallback

Examples in this README assume you have access to a reachable NetBox instance and a valid API token. DNS plugin examples apply only when that plugin is installed and exposed by your NetBox API.

Create config:

```bash
netbox profile add nb01
```

Example:

```bash
netbox profile add nb01 \
  --url https://netbox.example.com \
  --token YOUR_TOKEN \
  --default-format table \
  --default-limit 25
```

List configured profiles and switch the active one:

```bash
netbox profile list
netbox profile use nb01
```

Override the profile for one command or one shell session without changing the active profile:

```bash
netbox --profile nb02 list dcim/devices
netbox --profile nb02 shell
```

Typical multi-profile config:

```toml
current_profile = "nb01"

[profiles.nb01]
url = "https://netbox01.example.com"
token = "abc123"

[profiles.nb02]
url = "https://netbox02.example.com"
token = "def456"
```

Validate config, token, and connectivity:

```bash
netbox config test
```

Show config, cache, and history paths:

```bash
netbox config paths
```

Clear cached metadata:

```bash
netbox cache clear
```

Typical paths:

```text
~/.config/netbox-cli/config.toml
~/.cache/netbox-cli/
~/.local/state/netbox-cli/shell-history
```

Optional environment variable overrides:

```text
NETBOX_URL
NETBOX_TOKEN
NETBOX_CLI_DEFAULT_FORMAT
NETBOX_CLI_DEFAULT_LIMIT
NETBOX_CLI_TIMEOUT
NETBOX_CLI_VERIFY_TLS
NETBOX_CLI_CONFIG
NETBOX_CLI_CONFIG_DIR
NETBOX_CLI_CACHE_DIR
NETBOX_CLI_HISTORY_DIR
NETBOX_CLI_HISTORY_PATH
```

## CLI Quick Start

Common first commands:

```bash
netbox config test
netbox profile list
netbox list
netbox list dcim
netbox list dcim/devices
netbox filters dcim/devices
netbox list dcim/devices status=active
netbox list dcim/devices q=router01 --cols name,site,status
netbox get dcim/devices id=1490
netbox create dcim/sites name=lab slug=lab --dry-run
netbox update dcim/devices id=1490 status=active --dry-run
netbox search router01 --cols id,name,site,status
```

## CLI Examples

Explore progressively with `list`:

```bash
netbox list
netbox list dcim
netbox list dcim/devices
```

Inspect endpoint filters and known choices:

```bash
netbox filters dcim/devices
```

List rows from an endpoint:

```bash
netbox list
netbox list dcim
netbox list dcim/devices
netbox list dcim/devices status=active
netbox list dcim/devices router01
netbox list dcim/devices router 01
netbox list dcim/devices router01 status=active
netbox list dcim/devices site=dc1 site=lab
netbox list dcim/devices status=active status=offline
netbox list dcim/devices q=router01
netbox list dcim/devices name__ic=router
netbox list dcim/devices q=router01 --cols name,site,status
netbox list plugins/netbox_dns/records q=198.51.100.10 --cols zone,name,type,value,status
```

The CLI `list` command is the canonical exploration flow and follows the same shorthand as the shell:

```bash
netbox list
netbox list dcim
netbox list dcim/devices
```

Inside an endpoint path, bare terms are treated as `q=...`:

```bash
netbox list dcim/devices router01
```

This behaves like:

```bash
netbox list dcim/devices q=router01
```

Fetch exactly one object:

```bash
netbox get dcim/devices id=1490
```

Create one object:

```bash
netbox create dcim/sites name=lab slug=lab --yes
netbox create dcim/devices --file payload.json --yes
netbox create dcim/devices --file payload.yaml --dry-run
```

Update one object by id:

```bash
netbox update dcim/devices id=1490 status=active --yes
netbox update dcim/devices id=1490 --file patch.json --yes
netbox update dcim/devices id=1490 --file patch.yml --dry-run
```

`create` and `update` are available in both the classic CLI and the REPL. In the REPL, they only work in an endpoint context.

In the classic CLI, real writes require `--yes`. Without `--yes`, the command fails locally instead of prompting. `--dry-run` never requires `--yes`.

Table-mode write output adds a short created or updated summary before the full detail view. Successful updates also show an `Updated fields` summary.

`create` and `update` accept exactly one payload input method:

- inline `key=value` fields
- or `--file`

Supported payload file types:

- `.json`
- `.yaml`
- `.yml`

`--dry-run` previews the final method, endpoint, optional target id, and payload without sending the POST or PATCH request.

Inline `key=value` payload values are sent as strings. Use JSON or YAML files when you need structured or typed payload data.

When NetBox exposes required POST fields in endpoint `OPTIONS` metadata, `create` checks for missing required fields locally before preview, confirmation, or POST.

Run global search across curated endpoints:

```bash
netbox search router01
netbox search router01 --cols id,name,site,status
```

`--cols` takes a comma-separated list of fields and overrides the default profile columns for `list` and `search`.

Use `netbox search <term>` when you want a broad search across multiple object types.

Use `netbox list` as the single exploration command:

- `netbox list` shows top-level apps
- `netbox list <app>` shows endpoints for that app
- `netbox list <app>/<endpoint>` lists records from that endpoint

Use `netbox list <app>/<endpoint> q=<term>` when you already know the endpoint you want to search inside.

Examples:

```bash
netbox search router01
netbox list dcim/devices q=router01
```

Actual supported filters depend on the target endpoint and the schema exposed by your NetBox instance. For endpoint-specific lookups, `netbox filters <app>/<endpoint>` shows what the tool has discovered.

For multi-value filters, repeat the parameter instead of using a comma-separated value:

```bash
netbox list dcim/devices site=dc1 site=lab
```

This is separate from NetBox options like `ordering`, where comma-separated values are still the normal form:

```bash
netbox list dcim/devices ordering=name,-serial
```

## Search Behavior

`netbox search <term>` searches a curated set of endpoints and groups results by object type.

The v1 search set includes:

- `dcim/devices`
- `virtualization/virtual-machines`
- `ipam/ip-addresses`
- `ipam/prefixes`
- `ipam/vlans`
- `dcim/sites`
- `dcim/racks`
- `plugins/netbox_dns/records` when available

Ranking prefers:

1. exact matches
2. prefix matches
3. substring matches

Search output is grouped by endpoint and shows the endpoint path, match count, and a useful default column set for each group.

## Interactive Shell

Launch the shell:

```bash
netbox shell
```

The prompt shows the effective profile and current path. The right side still shows the output format and row limit:

```text
nb01:/>
```

Typical session:

```text
nb01:/> list
nb01:/> cd dcim
nb01:/dcim> list
nb01:/dcim> cd devices
nb01:/dcim/devices> filters
nb01:/dcim/devices> list status=active
nb01:/dcim/devices> open 1
```

Change output format and row limit:

```text
nb01:/dcim/devices> format json
nb01:/dcim/devices> limit 5
nb01:/dcim/devices> get name=router01
```

Search and open:

```text
nb01:/> search router01
nb01:/> open 2
```

Inside an endpoint context, `list` supports a shorthand search term:

```text
nb01:/dcim/devices> list web01
```

This behaves like:

```text
nb01:/dcim/devices> list q=web01
```

Quoted values work the same way:

```text
nb01:/dcim/devices> list "router 01"
```

This behaves like:

```text
nb01:/dcim/devices> list q="router 01"
```

Mixed shorthand and explicit filters also work:

```text
nb01:/dcim/devices> list web01 status=active
```

This behaves like:

```text
nb01:/dcim/devices> list q=web01 status=active
```

If `q=...` is already present explicitly, the shell does not add a second `q`.

Repeated filters are supported in the shell the same way they are in the CLI:

```text
nb01:/dcim/devices> list site=dc1 site=lab
nb01:/dcim/devices> list web01 site=dc1 site=lab
```

In an endpoint context, the shell also supports the same write syntax as the CLI:

```text
nb01:/dcim/devices> create name=leaf-01 status=active --dry-run
nb01:/dcim/devices> create --file payload.yaml
nb01:/dcim/devices> update id=1490 status=offline --dry-run
nb01:/dcim/devices> update id=1490 --file patch.json
```

Real shell writes show a short human-readable summary before confirmation, then ask before sending POST or PATCH. `--dry-run` only previews the request and does not prompt.

Shell commands:

Navigation:

```text
cd [path]
```

Inspection:

```text
filters
list [term] [k=v ...]
get k=v [...]
create [k=v ...] [--file path] [--dry-run]
update id=<id> [k=v ...] [--file path] [--dry-run]
search <term>
open <index>
```

Session controls:

```text
cols
cols a,b,c
cols reset
format <table|json|csv>
limit <n>
exit
help
```

## Autocomplete

Shell completion is contextual.

It uses the current shell state plus cached metadata to suggest:

- shell commands
- app names
- endpoint path segments
- prioritized filter names for `list` and `get`, with common fields suggested first
- known choice values and common related-object values for filters such as `site`, `tenant`, `role`, `platform`, `device_type`, and `manufacturer`
- writable field names for `create` and `update`, with required/common fields suggested first
- known choice values and common related-object values for writable fields such as `site`, `tenant`, `role`, and `platform`
- `--file`, `--dry-run`, and local JSON/YAML payload files for write commands
- known and default columns
- simple enum values such as output formats

Examples:

```text
cd d<TAB>                  -> dcim
cd /plugins/ne<TAB>        -> /plugins/netbox_dns
cd net<TAB>                -> netbox_dns
list <TAB>                 -> q= id= name= slug= status= site= ...
list st<TAB>               -> status=
list site=<TAB>            -> dc1 dc2 ...
list status=<TAB>          -> active offline planned
get <TAB>                  -> id= name= slug= status= site= role= ...
get manufacturer=<TAB>     -> cisco juniper ...
create st<TAB>             -> status=
create site=<TAB>          -> dc1 dc2 ...
create --file <TAB>        -> payload.json payload.yaml
update id=22 status=<TAB>  -> active offline planned
cols na<TAB>               -> name
format j<TAB>              -> json
```

Completion is driven by shell state and cached metadata. If metadata for the current context is missing, the shell may fetch it lazily once and then reuse it for later completions.

## Output Formats

CLI and shell share the same renderers.

Available formats:

- `table`
- `json`
- `csv`

Use table output for interactive work:

```bash
netbox list dcim/devices status=active
```

Use JSON when you want machine-readable output:

```bash
netbox get dcim/devices id=1490 --format json
netbox list dcim/devices q=router01 --cols name,site,status --format json
```

Use CSV when you want simple pipe-friendly rows:

```bash
netbox list dcim/devices status=active --format csv
netbox search router01 --cols id,name,site,status --format csv
```

In the shell, numbered results are mainly meant for table-mode exploration with `open <index>`. JSON and CSV still include the index for consistency, but the primary workflow is interactive table output plus `open`.

## Cache

The tool caches a small amount of discovery metadata locally:

- API root
- schema
- endpoint `OPTIONS` metadata

This cache improves discovery, filter help, choice lookups, and autocomplete responsiveness.

Use this command to clear it:

```bash
netbox cache clear
```

`netbox cache clear` is the supported reset path. There is no `--no-cache` flag.

## Project Layout

The codebase is split by responsibility:

```text
netbox_cli/
  app.py
  client.py
  config.py
  discovery.py
  mutations.py
  query.py
  search.py
  render.py
  cache.py
  profiles.py
  repl/
    shell.py
    state.py
    commands.py
    completer.py
    metadata.py
tests/
  ...
```

## Known Limitations

- write support is intentionally minimal: `create`, `update`, and `--dry-run` only
- REPL write support is intentionally small and endpoint-scoped
- delete is intentionally out of scope
- the shell is line-oriented, not a full-screen TUI
- autocomplete is best-effort when metadata is incomplete or unavailable
- plugin endpoints are handled gracefully, but depend on what your NetBox instance exposes
- endpoint-specific filter support depends on the schema and metadata provided by your NetBox instance
