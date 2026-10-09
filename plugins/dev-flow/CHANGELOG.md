# Changelog

All notable changes to the **dev-flow** plugin are documented here.

## [1.0.3] - 2026-10-09

### Changed

- `changelog` 1.0.2: cut the guidance on writing CHANGELOG scripts (#210).

## [1.0.2] - 2026-10-06

### Changed

- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).

## [1.0.1] - 2026-10-05

### Changed

- The bundled `validate-skill.sh` usage example no longer names the deleted `changelog-keeper/` directory, and its NOTE names the skills that ship a copy and the frozen exception. Comment and help text only (#167). `changelog` and `worktree` are at 1.0.1.

## [1.0.0] - 2026-10-04

### Added

- First release (#165). It merges the bare `worktree` (1.0.1) and `changelog-keeper` (1.1.1) skills. Two skills under short names: `worktree` (was `worktree`) and `changelog` (was `changelog-keeper`). Invoke them as `/dev-flow:worktree` and `/dev-flow:changelog`. The old names still match as trigger phrases.
- Smoke tests for both scripts, in `tests/run-tests.sh`, and a CI job (`dev-flow-tests`, bash 5 and bash 3.2) that runs them. They run each script from a temp project directory with `HOME` on a temp dir and a clean environment, in a plugin copy under a path with a space. For `worktree` they cover `list`, `create`, `create --new`, `remove` and `install` in temp repos: the base of a new branch (`origin/develop` when the local `develop` is ahead, a main-only repo, `origin/HEAD`, no base at all), no upstream on a new branch, the warning for a failed fetch, a branch that is only on `origin`, a dirty worktree that `remove` refuses and `remove --force` deletes, an ignored `.env` that `remove` refuses, also with `status.showUntrackedFiles=no` (a `node_modules/`-only worktree is removed), the printed `remove` and `install` lines pasted in another directory, a branch whose directory is another branch's worktree, a plain directory in the way, a failing and a working `npm` (fakes on `PATH`), and a pasted `cd` line under a path with a space. For `changelog` they cover every category and the file-path fallback, the start point (release-candidate, non-release and out-of-order tags, no tags, the CHANGELOG.md fallback, `--since HEAD~2` and `HEAD^`), `--dry-run` leaving the file alone, that a write keeps every old line in order (hand-written bullets, `## v1.0.0 (...)` sections, footer links), that a second write adds nothing, `--version` promotion and its refusal on a repeat, `--version` with no new commits (promotes, or exits 1 when `[Unreleased]` is empty), a new commit whose subject is already in a released section, two scopes with the same text in one run, a versioned heading with no reachable tag (exit 1, file unchanged, `--since` still works), a CRLF file staying CRLF, a title-only file, a file with no `[Unreleased]`, a directory named `CHANGELOG.md`, bad input, an untrusted `CHANGELOG.md` heading (exit 1, no git option error), a symlinked `CHANGELOG.md` and backslashes in subjects. A python check that crashes is a FAIL line, not an abort. `DEVFLOW_SKILLS` points the suite at another copy of the skills. They also check that every script path in the `SKILL.md` files exists and runs, that `${CLAUDE_SKILL_DIR}` appears only inside fenced code blocks, and that each `validate-skill.sh` matches the repo-root copy.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`, which now covers this plugin in CI): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. The old text used `~/.claude/skills/<skill>/scripts/...` and a `SCRIPT=` variable, which only worked from a loose copy.
- `worktree/scripts/validate-skill.sh` and `changelog/scripts/validate-skill.sh` are copies of the repo-root `scripts/validate-skill.sh`.

### Fixed

- `changelog`: `update-changelog.sh` read the starting point from the first `## [...]` heading of CHANGELOG.md and passed it to `git rev-parse`, `git log` and `git diff` unchecked, so a heading such as `## [--output=x]` reached git as an option and created a file. A heading is now used only through its tag, `v<heading>` or `<heading>`, and only if it is a plain name (see the `--since` entry below for the characters) that resolves with `git rev-parse --verify` to a commit. The script uses the resolved SHA from then on. `--since` gets the same check. Without `--since`, the range starts at that tag of the first versioned heading, whatever its form (`[1.1.0-rc1]` starts at `v1.1.0-rc1`, so the rc's commits are not listed again), and the tag must be reachable from HEAD; if not (say, after `--version` and before the tag), the script exits 1 with "CHANGELOG.md has [X] but there is no tag for it; tag the release or pass --since <ref>" and writes nothing. It used to fall back to an older tag or the whole history and list released commits again. The whole history is used only when CHANGELOG.md has no versioned heading and there is no release tag.
- It wrote CHANGELOG.md through a symlink (`cat >` on a dangling link created the target outside the repo). It now exits 1 with a message when CHANGELOG.md is a symlink, and writes through a temp file in the same directory that is renamed over the file. The file mode is kept.
- A backslash in a commit subject was read as an escape: `echo -e` turned `\n` and `\t` into whitespace, and `awk -v` stopped with `newline in string` (exit 2) when the entry had a newline written that way. Subjects now come through as typed.
- `--since <ref>` with a ref git did not know printed "No new commits" and exited 0. It now exits 1 with a message. The help text no longer says `--since` takes a date, which never worked.
- The starting point was the newest tag of any kind (`git describe`), so a tag like `sync-2026-10-01` hid every commit before it. This is the pitfall the SKILL.md already describes. When CHANGELOG.md has no versioned heading, it now takes the newest `v1.2.3` or `1.2.3` tag reachable from HEAD (see the start-point entry below).
- With no tag, the first commit of the history was left out (`root..HEAD`), so a repo with one commit reported "No new commits". It is included now.
- In a linked worktree (`.git` is a file) it said "not a git repository". It asks git instead.
- A section was glued to the bullets above it with no blank line, so the heading ran into the list. A blank line now separates them.
- `--since` or `--version` as the last argument stopped with `unbound variable`. It now exits 1 with a message.
- `changelog`: write mode replaced the whole `[Unreleased]` block with the generated entry. Hand-written bullets were lost, and so was every later section whose heading did not start with `## [` (such as `## v1.0.0 (2024-01-01)`) and every footer link line (`[Unreleased]: https://...`). It now adds each new bullet under the matching `### <Category>` of the block, or under a new one, skips a bullet already under a heading of the same category in the block (once per copy there; the same text under another category does not count, so a re-run adds nothing, while two commits with the same text in one run give two bullets and a new commit whose subject is in a released section is added), and keeps every other line. Before it replaces the file, it checks that every old line is still there, in order. If not, it exits 1 and leaves the file alone.
- `--version` left the `[Unreleased]` body in place and wrote the bullets again in the new section, and a second run added a second section. It now moves the `[Unreleased]` body and the new bullets into `## [X.Y.Z] - <date>`, leaves `[Unreleased]` empty, and exits 1 when `## [X.Y.Z]` already exists. With no new commits (`--since HEAD`, or HEAD already tagged) it printed "No new commits" and promoted nothing; it now moves the `[Unreleased]` body, and exits 1 with "nothing to release" when that is empty too.
- A CHANGELOG.md with CRLF line endings: `### Added\r` never matched, so a second `### Added` and duplicate bullets were added with LF endings. Lines are now compared without the `\r`, old lines are written back as they were, and new lines get CRLF, so the file has no mixed endings.
- A CHANGELOG.md with no `[Unreleased]` and no blank line after the title (only `# Changelog`) printed "Updated" and wrote nothing. With an intro paragraph, the entry went above the paragraph. A new `[Unreleased]` section now goes before the first `## ` heading or link line, or at the end of the file.
- A `CHANGELOG.md` that was a directory got the temp file moved into it, and the script said "Created" and exited 0. Anything that is not a regular file now exits 1.
- Start point: `v1.1.0-rc1` beat `v1.1.0`, and a tag like `20261001-snap` counted as a version. When CHANGELOG.md has no versioned heading, only `v1.2.3` or `1.2.3` tags count now, newest by version order. With only other tags it said "No tags found". It now says how many tags it found and that none is a release version. The CHANGELOG.md fallback read the first `## [` heading, which is usually `[Unreleased]`, so it never found a version. It now skips `[Unreleased]`. For the whole history it said "since <first commit>", as if that commit was left out. It now says "in the whole history".
- `--since` refused `HEAD~2` and `v1.0.0^`. A ref may now hold letters, digits and `.` `_` `/` `~` `^` `-`, and must not start with `-`. The same rule covers `--since` and the CHANGELOG.md heading, and the error message names it.
- The help text and SKILL.md said commits with no prefix are sorted by file path into Testing and Documentation. The code never did that. The dead code is gone, and the docs say what happens: a commit with no prefix goes to Other. Only when no commit in the range has a prefix, and the range changed `src/`, `lib/` or `scripts/`, do they go to Changed. The help lists Other.
- `worktree`: `remove` always passed `--force` to git, so it deleted uncommitted and untracked work. Git now refuses a dirty worktree, the script prints git's message and exits non-zero, and `remove --force` is the explicit way to discard that work. Git still deletes git-ignored files (`.env`, local config) without a word, so without `--force` the script now refuses (exit 1) a worktree that has ignored files outside `node_modules/`, lists up to 10 and says how many more. It sets the `git status` listing mode on the command line, so `status.showUntrackedFiles=no` in the user's git config cannot hide them.
- Worktrees were found by directory name, so `feature/x/y` and `feature/x-y` shared `repo--x-y`: `create feature/x-y` said it existed, and `remove feature/x-y` removed the other branch's worktree. They are now found by branch (`git worktree list --porcelain`). `create` exits 1 when the directory is another branch's worktree or a plain directory, and `remove` exits 1 when the branch has no worktree.
- `create --new` always branched from `origin/develop`, so it failed in a repo with no `develop` or no `origin`, and a failed fetch was hidden. The base is now `origin/develop`, else `develop`, else the branch `origin/HEAD` names, else `main`, else an error. A failed fetch prints a warning. The new branch is made with `--no-track`, so it does not track `origin/develop`.
- The printed `cd ... && claude`, `code ...` and `remove` lines were not quoted, so a path with a space broke when pasted. They are quoted with `printf %q`. The `remove` and `install` lines named the script by its bare name, which is not on `PATH`, so pasting them gave `command not found`. They now read `cd <repo> && <absolute script path> remove|install <branch>`, so they work when pasted from any directory.
- `npm install` ran only in three hard-coded directories from one project (`backend`, `frontend`, `mcp-events-server`), and a failed install still counted as installed and the worktree as ready. It now runs in the worktree root and in each immediate subdirectory that has a `package.json` and no `node_modules`. It counts only successes, names the failures and exits 1, after printing the `cd` line.

### Deprecated

- The bare `worktree` and `changelog-keeper` skills. They stay in the repo until #167. Install `dev-flow`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/worktree/CHANGELOG.md` and `skills/changelog/CHANGELOG.md`.
