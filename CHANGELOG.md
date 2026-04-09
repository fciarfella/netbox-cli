# Changelog

## 0.6.0 - 2026-04-09

### netbox-explorer 0.6.0

This release adds the first multi-profile foundation for working with multiple NetBox instances and finalizes the profile-management UX across both the CLI and the REPL.

### Added

- Added first-class support for multiple named NetBox profiles.
- Added persisted `current_profile` selection.
- Added global `--profile <name>` override for per-command and REPL session use.
- Added grouped profile-management commands:
  - `netbox profile add <name>`
  - `netbox profile list`
  - `netbox profile use <name>`
- Added REPL support for:
  - `profile list`
  - `profile use <name>`
- REPL prompts now show the effective profile, for example `nb01:/dcim/devices>`.

### Changed

- Profile-management commands are now grouped under `netbox profile`.
- The temporary top-level commands used during the initial multi-profile milestone have been removed:
  - `netbox init --profile ...`
  - `netbox profiles`
  - `netbox use ...`
- REPL profile switching now refreshes the active client, prompt, and profile-scoped metadata state without restarting the shell.

### Compatibility

- Existing legacy single-profile config continues to work through a compatibility path.
- Profile resolution order is:
  1. explicit `--profile`
  2. persisted `current_profile`
  3. legacy single-profile fallback

### Notes

- `profile add` remains CLI-only.
- If the REPL is started with `--profile <name>`, interactive `profile use` is intentionally blocked for that session.

## 0.5.1 - 2026-04-09

- fixed REPL completion for `update` after `id=<id>`
- `update <TAB>` suggests `id=`, `--file`, and `--dry-run`
- `update id=25<TAB>` now suggests writable fields
- `update id=25 nam<TAB>` now completes to `name=`
- the shell now inserts the separator before opening completions after an exact `update id=<id>` token
