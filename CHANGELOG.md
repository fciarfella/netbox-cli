# Changelog

## 0.6.0 - 2026-04-09

- added first-class support for multiple named NetBox profiles
- added persisted `current_profile`
- added global `--profile <name>` override
- added grouped profile commands under `netbox profile`
- REPL prompt now shows the effective profile
- removed the temporary top-level commands `init --profile`, `profiles`, and `use`
- legacy single-profile config still works through a compatibility path

## 0.5.1 - 2026-04-09

- fixed REPL completion for `update` after `id=<id>`
- `update <TAB>` suggests `id=`, `--file`, and `--dry-run`
- `update id=25<TAB>` now suggests writable fields
- `update id=25 nam<TAB>` now completes to `name=`
- the shell now inserts the separator before opening completions after an exact `update id=<id>` token
