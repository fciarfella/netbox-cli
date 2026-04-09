# Changelog

## 0.5.1 - 2026-04-09

- fixed REPL completion for `update` after `id=<id>`
- `update <TAB>` suggests `id=`, `--file`, and `--dry-run`
- `update id=25<TAB>` now suggests writable fields
- `update id=25 nam<TAB>` now completes to `name=`
- the shell now inserts the separator before opening completions after an exact `update id=<id>` token
