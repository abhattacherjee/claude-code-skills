# Changelog

All notable changes to the **statusline** plugin are documented here.

## [1.0.0] - 2026-10-03

### Added

- First release (#158). Three skills under short names: `install` (was `install-statusline` in the `custom-statusline` plugin), `create` (was `statusline-creator`) and `context-bar`. Every SKILL.md command spells the full `"${CLAUDE_SKILL_DIR}/scripts/..."` path.
- `lib/write-statusline.sh`, shared by `install` and `create`. Every script the plugin writes carries `# managed-by: statusline-plugin` on line 2. An existing script without it is left untouched (exit 3) unless `--force` is passed. Every replaced file is first backed up to `<file>.bak-<UTC time>` (a `-N` suffix keeps two backups made in the same second). Writes go to a temp file in the same directory, are compared byte for byte, then moved into place.
- `install.sh --force` and `--help`; `generate-statusline.sh --force`.
- Exit codes for both installers: 0 done; 1 failed (a write failed, `jq` is missing, or `settings.json` cannot be read); 2 bad input; 3 refused. `settings.json` is checked before the script is written, so a bad or unreadable file never leaves the script installed without the setting.
- A pytest suite under `tests/`, run by the `statusline-tests` CI job on Ubuntu (bash 5) and macOS (bash 3.2). Every test uses a temporary `HOME`.
- Marketplace entry `statusline`. The `context-bar`, `custom-statusline` and `statusline-creator` entries stay one release, marked deprecated.

### Fixed

- `install` and `create` no longer overwrite a statusline script they did not write. Before, both replaced `~/.claude/statusline-command.sh` with no check and no backup, and `create` did so even without `--install`.
- `settings.json` updates check the file first. Missing or blank counts as `{}`. Anything that is not exactly one JSON object (invalid JSON, `[]`, two documents) stops the install with exit 2 before any file is written, and the file stays byte-identical. Before, `create --install` piped jq output straight over it. The file's mode is kept, a symlinked file is updated through its link, and a file that already points at the script is not rewritten.
- `create` exits 2 on an unknown flag or item, a flag with no value, or `--lines` outside 1-3. Before, an unknown flag printed the help and exited 0, and an unknown item was skipped with a warning.
- `create --output` with a relative path is made absolute, and a path with spaces or quotes is quoted in the `statusLine` command. `--items "model, cost"` renders every item; the Python half used to drop items after a space.
- `create --install` with the default output keeps the command `bash ~/.claude/statusline-command.sh` instead of writing the expanded home path.
- A missing `jq` stops both installers with exit 1 before anything is written. Before, `create --install` printed a warning and exited 0.
- `context-bar` finds the current session's transcript directory from the working directory, using Claude Code's own naming rule: every character that is not an ASCII letter or digit becomes `-`, and a name over 200 characters is matched by its 200-character prefix. It reads `$CLAUDE_CODE_SESSION_ID.jsonl` when that exists, else the newest transcript, and honours `CLAUDE_CONFIG_DIR`. Before, it read one hardcoded project's directory, whatever the session. With no matching directory or transcript it says so and exits 1 instead of printing a bar.
- `context-bar` turns red at 80%, as documented. It used to turn red at 75%.
- `install`'s statusline shows a directory whose name has spaces or quotes in full. It used to pass the path through `xargs basename`, which showed `my` for `my project` and nothing for `it's`.
- `create`: `git-sync` works with or without `git` and in any order. The git data is built once, before every item; before, `git-sync` rendered empty unless `git` came first.
- Both installers honour `CLAUDE_CONFIG_DIR`: the script, `settings.json` and the `statusLine` command all use it. Before, they wrote `~/.claude` and reported success.
- Both statuslines print `statusline: jq not on PATH` when jq is missing, and `statusline: no session data` when stdin is not a JSON object, instead of a confident 0%.
- An unreadable existing script is reported as unreadable (exit 1), not as "not written by the plugin, use --force".
- A failed `settings.json` write after the script was written says so: `statusline script written; settings.json unchanged`. The temp file for `settings.json` is made next to it, not in `$TMPDIR`. A `settings.json` that is a symlink to a missing file stops the install (exit 1) before anything is written.
- `create` without `python3` exits 1 with a message, not 127.
- `context-bar` notes on stderr when `$CLAUDE_CODE_SESSION_ID.jsonl` is missing and it falls back to the newest transcript. Its doc states the fixed 1M-token window and `CLAUDE_CONFIG_DIR`.
- The git cache stores one value per line, so a `|` in a branch name no longer shifts the fields.
- Re-running an install whose script already has the same bytes and mode writes nothing and makes no backup.
- `settings.json` updates keep other `statusLine` keys (such as `padding`) and print the old command when it changes.
- `model` and `model-full` print nothing, not `null`, when the session JSON has no model.
- `item-recipes.md` wraps every value from the session JSON in `num` or `clean`, as the generator does, and its Git Sync recipe shows nothing outside a repo.

### Security

- `create`'s git cache moved from the shared, predictable `/tmp/statusline-git-cache` (another user could pre-create it as a symlink, or read your branch names) to `${XDG_CACHE_HOME:-~/.cache}/claude-statusline/` with mode 700. It holds one file per working directory, keyed by a hash of the path, written through a temp file and `mv`, and a cache path that is a symlink is never read or written. Two sessions in different repos no longer show each other's branch. The file stores its own timestamp, so the macOS/Linux `stat` split is gone, and a timestamp from the future (clock set back) counts as stale.
- Terminal escape injection: model, directory, branch, remote, worktree, agent, style and session names are stripped of control characters and backslashes before `echo -e` prints them, and `git-link` emits an OSC 8 hyperlink only for `http(s)` remotes; other remotes print as plain text.
- `install`'s 3-tier statusline no longer puts values in printf format strings. Colors are real escape bytes and every `printf` uses a constant format, so a `%` in a directory name prints as `%`. Directory, branch, model and percentage are stripped of control characters. Output for ordinary input is byte-identical to before (48 recorded cases, bash 3.2 and 5).
- Both statuslines run git as `git -c core.fsmonitor=false -c core.untrackedCache=false --no-optional-locks`, so a repo's `core.fsmonitor` cannot run a program on every prompt. (`git diff` runs only with `--numstat`, which never calls `diff.external`.)
- Numbers from the session JSON reach shell arithmetic only as digits: a crafted `used_percentage` such as `a[$(cmd)]` no longer runs `cmd`, and a value whose product with the bar width overflows 64 bits no longer hangs the bar loop. In `install`'s statusline the bar's percentage is clamped to 0-100; the printed percentage is shown as received, stripped of control characters.
- Every git call the statuslines make was swept for ways a repo can make it run code; the README "Security" table lists each call, its vectors and how each is closed. Status and diff are skipped where a repo controls a filter driver (any scope but global or system, read with `--includes --show-scope`, so `include.path` and worktree config count) or in a partial clone (lazy fetch runs the remote's transport), and when the config lookup fails. `status` and `diff` pass `--ignore-submodules=all` (a submodule's own filters and fsmonitor), `diff` passes `--no-textconv --no-ext-diff`, and every call runs with `--no-pager` and `GIT_NO_LAZY_FETCH=1`. A global filter (git-lfs) is the user's own, so change counts stay there.

### Removed

- `context-bar`'s own `statusline-command.sh`. `/statusline:create` builds the same bar with its `context-bar` item.
