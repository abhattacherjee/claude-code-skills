# Changelog

All notable changes to the **changelog** skill (was `changelog-keeper`) are documented here.

## [1.0.2] - 2026-10-09

### Changed

- Cut "Multi-Script CHANGELOG Coordination": advice on writing scripts that edit a CHANGELOG, which this skill never does; it only runs its own script (#210).

## [1.0.1] - 2026-10-05

### Changed

- The bundled `scripts/validate-skill.sh` changed in comments and help text only: its usage example names a plugin skill path instead of the deleted `changelog-keeper/` directory, and its NOTE names the skills that ship a byte-identical copy and the frozen `skill-authoring` copy as the exception (#167).

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `dev-flow` plugin as `dev-flow:changelog` (#165). Same workflow as `changelog-keeper` 1.1.1; the script fixes are under Fixed. The old name still matches as a trigger phrase.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh"`, with `<REPO_DIR>` for another repo. The old text set `SCRIPT=~/.claude/skills/changelog-keeper/...` in one block and read `$SCRIPT` in others, which only worked from a loose copy (#165).
- The newline-pitfall example sets `EXISTING` and `NEW_ENTRY`, so the block runs on its own.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

### Fixed

- `update-changelog.sh` read the starting point from the first `## [...]` heading of CHANGELOG.md and passed it to `git rev-parse`, `git log` and `git diff` unchecked, so a heading such as `## [--output=x]` reached git as an option and created a file. A heading is now used only through its tag, `v<heading>` or `<heading>`, and only if it is a plain name (see the `--since` entry below for the characters) that resolves with `git rev-parse --verify` to a commit. The script uses the resolved SHA from then on. `--since` gets the same check. Without `--since`, the range starts at that tag of the first versioned heading, whatever its form (`[1.1.0-rc1]` starts at `v1.1.0-rc1`, so the rc's commits are not listed again), and the tag must be reachable from HEAD; if not (say, after `--version` and before the tag), the script exits 1 with "CHANGELOG.md has [X] but there is no tag for it; tag the release or pass --since <ref>" and writes nothing. It used to fall back to an older tag or the whole history and list released commits again. The whole history is used only when CHANGELOG.md has no versioned heading and there is no release tag.
- It wrote CHANGELOG.md through a symlink (`cat >` on a dangling link created the target outside the repo). It now exits 1 with a message when CHANGELOG.md is a symlink, and writes through a temp file in the same directory that is renamed over the file. The file mode is kept.
- A backslash in a commit subject was read as an escape: `echo -e` turned `\n` and `\t` into whitespace, and `awk -v` stopped with `newline in string` (exit 2) when the entry had a newline written that way. Subjects now come through as typed.
- `--since <ref>` with a ref git did not know printed "No new commits" and exited 0. It now exits 1 with a message. The help text no longer says `--since` takes a date, which never worked.
- The starting point was the newest tag of any kind (`git describe`), so a tag like `sync-2026-10-01` hid every commit before it. This is the pitfall the SKILL.md already describes. When CHANGELOG.md has no versioned heading, it now takes the newest `v1.2.3` or `1.2.3` tag reachable from HEAD (see the start-point entry below).
- With no tag, the first commit of the history was left out (`root..HEAD`), so a repo with one commit reported "No new commits". It is included now.
- In a linked worktree (`.git` is a file) it said "not a git repository". It asks git instead.
- A section was glued to the bullets above it with no blank line, so the heading ran into the list. A blank line now separates them.
- `--since` or `--version` as the last argument stopped with `unbound variable`. It now exits 1 with a message.
- Write mode replaced the whole `[Unreleased]` block with the generated entry. Hand-written bullets were lost, and so was every later section whose heading did not start with `## [` (such as `## v1.0.0 (2024-01-01)`) and every footer link line (`[Unreleased]: https://...`). It now adds each new bullet under the matching `### <Category>` of the block, or under a new one, skips a bullet already under a heading of the same category in the block (once per copy there; the same text under another category does not count, so a re-run adds nothing, while two commits with the same text in one run give two bullets and a new commit whose subject is in a released section is added), and keeps every other line. Before it replaces the file, it checks that every old line is still there, in order. If not, it exits 1 and leaves the file alone.
- `--version` left the `[Unreleased]` body in place and wrote the bullets again in the new section, and a second run added a second section. It now moves the `[Unreleased]` body and the new bullets into `## [X.Y.Z] - <date>`, leaves `[Unreleased]` empty, and exits 1 when `## [X.Y.Z]` already exists. With no new commits (`--since HEAD`, or HEAD already tagged) it printed "No new commits" and promoted nothing; it now moves the `[Unreleased]` body, and exits 1 with "nothing to release" when that is empty too.
- A CHANGELOG.md with CRLF line endings: `### Added\r` never matched, so a second `### Added` and duplicate bullets were added with LF endings. Lines are now compared without the `\r`, old lines are written back as they were, and new lines get CRLF, so the file has no mixed endings.
- A CHANGELOG.md with no `[Unreleased]` and no blank line after the title (only `# Changelog`) printed "Updated" and wrote nothing. With an intro paragraph, the entry went above the paragraph. A new `[Unreleased]` section now goes before the first `## ` heading or link line, or at the end of the file.
- A `CHANGELOG.md` that was a directory got the temp file moved into it, and the script said "Created" and exited 0. Anything that is not a regular file now exits 1.
- Start point: `v1.1.0-rc1` beat `v1.1.0`, and a tag like `20261001-snap` counted as a version. When CHANGELOG.md has no versioned heading, only `v1.2.3` or `1.2.3` tags count now, newest by version order. With only other tags it said "No tags found". It now says how many tags it found and that none is a release version. The CHANGELOG.md fallback read the first `## [` heading, which is usually `[Unreleased]`, so it never found a version. It now skips `[Unreleased]`. For the whole history it said "since <first commit>", as if that commit was left out. It now says "in the whole history".
- `--since` refused `HEAD~2` and `v1.0.0^`. A ref may now hold letters, digits and `.` `_` `/` `~` `^` `-`, and must not start with `-`. The same rule covers `--since` and the CHANGELOG.md heading, and the error message names it.
- The help text and SKILL.md said commits with no prefix are sorted by file path into Testing and Documentation. The code never did that. The dead code is gone, and the docs say what happens: a commit with no prefix goes to Other. Only when no commit in the range has a prefix, and the range changed `src/`, `lib/` or `scripts/`, do they go to Changed. The help lists Other.

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
