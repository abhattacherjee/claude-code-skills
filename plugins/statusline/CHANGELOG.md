# Changelog

All notable changes to the **statusline** plugin are documented here.

## [1.0.0] - 2026-10-03

### Added

- First release (#158). Three skills under short names: `install` (was `install-statusline` in the `custom-statusline` plugin), `create` (was `statusline-creator`) and `context-bar`. Every SKILL.md command spells the full `"${CLAUDE_SKILL_DIR}/scripts/..."` path.
- `lib/write-statusline.sh`, shared by `install` and `create`. Every script the plugin writes carries `# managed-by: statusline-plugin` on line 2. An existing script without it is left untouched (exit 3) unless `--force` is passed. Every replaced file is first backed up to `<file>.bak-<UTC time>` (a `-N` suffix keeps two backups made in the same second). Writes go to a temp file in the same directory, are compared byte for byte, then moved into place.
- `install.sh --force` and `--help`; `generate-statusline.sh --force`.
- Exit codes for both installers: 0 done, 1 write failed, 2 bad input, 3 refused.

### Fixed

- `install` and `create` no longer overwrite a statusline script they did not write. Before, both replaced `~/.claude/statusline-command.sh` with no check and no backup, and `create` did so even without `--install`.
- `settings.json` updates check the file first. Missing or blank counts as `{}`. Anything that is not exactly one JSON object (invalid JSON, `[]`, two documents) stops the install with exit 2 before any file is written, and the file stays byte-identical. Before, `create --install` piped jq output straight over it. The file's mode is kept, a symlinked file is updated through its link, and a file that already points at the script is not rewritten.
- `create` exits 2 on an unknown flag or item, a flag with no value, or `--lines` outside 1-3. Before, an unknown flag printed the help and exited 0, and an unknown item was skipped with a warning.
- `create --output` with a relative path is made absolute, and a path with spaces or quotes is quoted in the `statusLine` command. `--items "model, cost"` renders every item; the Python half used to drop items after a space.
- `create --install` with the default output keeps the command `bash ~/.claude/statusline-command.sh` instead of writing the expanded home path.
- A missing `jq` stops both installers with exit 1 before anything is written. Before, `create --install` printed a warning and exited 0.

### Removed

- `context-bar`'s own `statusline-command.sh`. `/statusline:create` builds the same bar with its `context-bar` item.
