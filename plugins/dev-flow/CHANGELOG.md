# Changelog

All notable changes to the **dev-flow** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#165). It merges the bare `worktree` (1.0.1) and `changelog-keeper` (1.1.1) skills. Two skills under short names: `worktree` (was `worktree`) and `changelog` (was `changelog-keeper`). Invoke them as `/dev-flow:worktree` and `/dev-flow:changelog`. The old names still match as trigger phrases.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`, which now covers this plugin in CI): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. The old text used `~/.claude/skills/<skill>/scripts/...` and a `SCRIPT=` variable, which only worked from a loose copy.
- `worktree/scripts/validate-skill.sh` and `changelog/scripts/validate-skill.sh` are copies of the repo-root `scripts/validate-skill.sh`.

### Fixed

- `changelog`: `update-changelog.sh` read the starting point from the first `## [...]` heading of CHANGELOG.md and passed it to `git rev-parse`, `git log` and `git diff` unchecked, so a heading such as `## [--output=x]` reached git as an option and created a file. A heading is now used only if it is a plain name (letters, digits, `.`, `_`, `-`, and not starting with `-`) that resolves with `git rev-parse --verify` to a commit. The script uses the resolved SHA from then on, and falls back to the whole history if there is no usable tag. `--since` gets the same check.
- It wrote CHANGELOG.md through a symlink (`cat >` on a dangling link created the target outside the repo). It now exits 1 with a message when CHANGELOG.md is a symlink, and writes through a temp file in the same directory that is renamed over the file. The file mode is kept.
- A backslash in a commit subject was read as an escape: `echo -e` turned `\n` and `\t` into whitespace, and `awk -v` stopped with `newline in string` (exit 2) when the entry had a newline written that way. Subjects now come through as typed.
- `--since <ref>` with a ref git did not know printed "No new commits" and exited 0. It now exits 1 with a message. The help text no longer says `--since` takes a date, which never worked.
- The starting point was the newest tag of any kind (`git describe`), so a tag like `sync-2026-10-01` hid every commit before it. This is the pitfall the SKILL.md already describes. It now takes the newest `v1.2.3` or `1.2.3` tag reachable from HEAD.
- With no tag, the first commit of the history was left out (`root..HEAD`), so a repo with one commit reported "No new commits". It is included now.
- In a linked worktree (`.git` is a file) it said "not a git repository". It asks git instead.
- A section was glued to the bullets above it with no blank line, so the heading ran into the list. A blank line now separates them.
- `--since` or `--version` as the last argument stopped with `unbound variable`. It now exits 1 with a message.

### Deprecated

- The bare `worktree` and `changelog-keeper` skills. They stay in the repo until #167. Install `dev-flow`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/worktree/CHANGELOG.md` and `skills/changelog/CHANGELOG.md`.
