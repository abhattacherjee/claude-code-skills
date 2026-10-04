# Changelog

All notable changes to the **context** plugin are documented here.

## [1.0.1] - 2026-10-04

### Changed

- `context:shield` names `ui-design:figma` (was `figma-ui-designer`), after the skill moved into the `ui-design` plugin (#164). `shield` is at 1.0.1.

## [1.0.0] - 2026-10-04

### Added

- First release (#163, #176). It merges the `context-shield` plugin and the bare `conversation-search` skill. Two skills under short names: `shield` (was `context-shield`) and `search` (was `conversation-search`). Invoke them as `/context:shield` and `/context:search`. The old names still match as trigger phrases.
- Two agents ship with the plugin: `content-distiller` (from `context-shield`) and `conversation-summarizer`. The summarizer was only in `~/.claude/agents/` and was not in any repo until now. The skills start them as `context:content-distiller` and `context:conversation-summarizer`.
- Smoke tests for the scripts, in `tests/run-tests.sh`, and a CI job (`context-tests`, bash 5 and bash 3.2) that runs them. They run each script from a temp project directory with `HOME` on a temp dir, check that both skills start their agents as `context:<agent>` and never name `~/.claude/agents`, and check that `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` appear only inside fenced code blocks.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<OUTPUT_DIR>` for the run directory. The old text used `$SCRIPTS` and `SCRIPT=~/.claude/skills/...`, which only worked from a loose copy.
- `shield` and `search` no longer point at `~/.claude/agents/`. The agent files are part of the plugin.
- `search/scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`. The old copy was older.

### Fixed

- `shield`: `manage-manifest.sh` built objects with an unquoted `label` key and a `$label` variable, both syntax errors in jq 1.6 (Debian 12, Ubuntu 22.04), so `create` and every command after it failed there. The key is quoted and the variable is now `$lbl`.
- `shield`: `next-batch` printed items without the manifest's `task`, so the distiller never saw it. Each item now carries `task`.
- `shield`: `mark-done --index 5` on a 2-source manifest printed `Marked done: [5] null`, padded the manifest and reported `1/6 done`; `--index -1` hit the last source on jq 1.7. Both commands now accept only an integer from 0 to the last index (no leading zeros: `08` is bad octal in bash and `010` is 10 to jq), and fail without touching the file.
- `shield`: there was no way to record a source that could not be read, so a 404 or login wall was stored as a finding and `STATUS: BLOCKED` could not happen. New `mark-failed --index N --reason TEXT` sets the status to `failed`. `next-batch` skips failed sources, `summaries` lists them apart from the summaries, `status` reports `BLOCKED`, `mark-done` clears a failure (the retry path) and `reset` clears reasons. The distiller starts its reply with `FAILED: <reason>` when it cannot read a source, and `SKILL.md` Step 3 maps that to `mark-failed`.
- `shield`: `visualize.sh` stopped with `unbound variable` on bash 3.2 for `--labels ""` and for a global option with no scene. It now exits 0 and 1 (`Unknown scene`) as on bash 5.
- `search`: `--after` and `--before` take `YYYY-MM-DD` or a UTC timestamp (`...SSZ`, optional `.sss`) and compare in one canonical form, so a session at exactly `10:00:00.000Z` matches `--after ...T10:00:00Z`. Offsets are rejected with exit 2. `--limit` and `--max-messages` reject leading zeros. An index that fails to parse part-way is dropped whole, and its sessions are listed as orphans instead of vanishing.
- `search`: `--limit` was pasted into a jq program, so `--limit '0] | {pwned: env.HOME} | .['` ran code and printed `$HOME`. `--limit` and `--max-messages` must now be non-negative integers (else exit 2 with a message) and reach jq as `--argjson`. The session ID in `show` also goes in with `--arg`.
- `search`: `--after garbage` returned `[]` and `--after 2025-2-18` excluded everything, both with exit 0. `--after` and `--before` now accept only `YYYY-MM-DD` or a UTC timestamp (see the entry above), and anything else exits 2 with a message.
- `search`: a malformed `sessions-index.json` was skipped without a word. It is still skipped, but `warning: skipping unreadable <path>` goes to stderr.
- `search`: the Step 4 example used the old `Task(...)` tool name. It now uses `Agent({subagent_type: "context:conversation-summarizer", ...})`, like `shield`.
- Tests: the jq-interpolation test could not fail (`\(1+1)` gives `2`, which nothing contains); it now uses a word the fixture holds and a `--branch` case with a backslash. The status checks pin the done count, `summaries` and `reset` are checked on a partly done manifest, the `foo(bar` check (which passed without `grep -F`) is gone, and `--help` runs through the clean-env helper.

- `search`: `search --deep` with no match, and a bare `--no-color`, stopped with `unbound variable` on bash 3.2 (the macOS default). They now exit 0 with the normal output.
- `search`: `--deep` passed the topic to `grep` as a regular expression, so `zebr.corn` matched `zebracorn`. It now matches the text literally.
- `search`: `--topic`, `--branch`, `--project`, `--after` and `--before` were pasted into a jq program with only `"` escaped. A backslash in the value (`C:\temp`) made jq fail with a syntax error, and `\(...)` ran as jq code. The value is now escaped before it goes in.
- `search`: `--before <date>` kept a conversation created exactly at that midnight, so a one-day range could include the next day's first second. It now stops before it.
- `search`: the "last Tuesday" example gave `--after 2025-02-17 --before 2025-02-18`, which is a Monday. It now gives 2025-02-18 and 2025-02-19.
- `search`: the `--project` examples used a real project name; they say `my-app`.

### Deprecated

- The `context-shield` plugin, and the bare `context-shield` and `conversation-search` skills. They stay in the repo until #167. Install `context`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/shield/CHANGELOG.md` and `skills/search/CHANGELOG.md`.
