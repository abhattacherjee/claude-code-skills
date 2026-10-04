# Changelog

All notable changes to the **changelog** skill (was `changelog-keeper`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `dev-flow` plugin as `dev-flow:changelog` (#165). Same workflow and script as `changelog-keeper` 1.1.1. The old name still matches as a trigger phrase.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh"`, with `<REPO_DIR>` for another repo. The old text set `SCRIPT=~/.claude/skills/changelog-keeper/...` in one block and read `$SCRIPT` in others, which only worked from a loose copy (#165).
- The newline-pitfall example sets `EXISTING` and `NEW_ENTRY`, so the block runs on its own.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

### Fixed

- `update-changelog.sh` read the starting point from the first `## [...]` heading of CHANGELOG.md and passed it to `git rev-parse`, `git log` and `git diff` unchecked, so a heading such as `## [--output=x]` reached git as an option and created a file. A heading is now used only if it is a plain name (letters, digits, `.`, `_`, `-`, and not starting with `-`) that resolves with `git rev-parse --verify` to a commit. The script uses the resolved SHA from then on, and falls back to the whole history if there is no usable tag. `--since` gets the same check.
- It wrote CHANGELOG.md through a symlink (`cat >` on a dangling link created the target outside the repo). It now exits 1 with a message when CHANGELOG.md is a symlink, and writes through a temp file in the same directory that is renamed over the file. The file mode is kept.
- A backslash in a commit subject was read as an escape: `echo -e` turned `\n` and `\t` into whitespace, and `awk -v` stopped with `newline in string` (exit 2) when the entry had a newline written that way. Subjects now come through as typed.
- `--since <ref>` with a ref git did not know printed "No new commits" and exited 0. It now exits 1 with a message. The help text no longer says `--since` takes a date, which never worked.
- The starting point was the newest tag of any kind (`git describe`), so a tag like `sync-2026-10-01` hid every commit before it. This is the pitfall the SKILL.md already describes. It now takes the newest `v1.2.3` or `1.2.3` tag reachable from HEAD.
- With no tag, the first commit of the history was left out (`root..HEAD`), so a repo with one commit reported "No new commits". It is included now.
- In a linked worktree (`.git` is a file) it said "not a git repository". It asks git instead.
- A section was glued to the bullets above it with no blank line, so the heading ran into the list. A blank line now separates them.
- `--since` or `--version` as the last argument stopped with `unbound variable`. It now exits 1 with a message.

## History before 1.0.0 (as `changelog-keeper`)

### changelog-keeper 1.1.1 - 2026-02-24

- **Bash Newline Pitfall** — corrected the fix: `printf '%s\n\n'` inside `$()` also loses trailing newlines. The real fix is adding blank lines at the concatenation point, not in the variable assignment.

### changelog-keeper 1.1.0 - 2026-02-24

- **Multi-Script CHANGELOG Coordination** section — patterns for when multiple scripts (sync + release) modify the same CHANGELOG:
  - Format-aware detection to prevent sync entries from clobbering release entries
  - Bash newline pitfall with `printf` fix
  - Semver tag filtering (`git tag -l 'v[0-9]*'` vs `git describe --tags`)

### changelog-keeper 1.0.0 - 2026-02-24

Initial public release.

- **SKILL.md** — keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/update-changelog.sh** — the generator.
