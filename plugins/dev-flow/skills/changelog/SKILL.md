---
name: changelog
description: "Was the changelog-keeper skill (changelog-keeper still works as a phrase). Keeps CHANGELOG.md up to date by generating categorized entries from git commit history. Use when: (1) user asks to update the changelog, (2) before committing changes that should be documented, (3) preparing a release and need changelog entries, (4) user says 'update changelog' or 'what changed since last release', (5) a commit is about to be pushed and the changelog hasn't been updated."
metadata:
  version: 1.0.2
---

# Changelog Keeper

Generates and maintains CHANGELOG.md entries from git commit history. Categorizes changes by conventional commit prefix, with a file-path fallback when no commit has a prefix. Writing only adds lines: it never removes or rewrites what is already in CHANGELOG.md.

## Quick Reference

```bash
# Preview changelog entry (dry run)
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --dry-run

# Add the new bullets to the [Unreleased] section
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh"

# Promote [Unreleased] and the new bullets to a versioned entry
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --version 2.0.0

# Changes since a specific tag/commit (HEAD~2 and v1.0.0^ work too)
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --since v1.0.0

# For a different repo
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --dry-run <REPO_DIR>
```

## Workflow

### When to Run

Run the changelog update script in these situations:

1. **Before a commit** — when the user has staged changes and is about to commit, generate a changelog entry to include in the same commit
2. **Before a release** — use `--version X.Y.Z` to promote unreleased changes to a versioned entry
3. **On demand** — when the user asks "what changed?" or "update the changelog"
4. **After multiple commits** — to catch up the changelog with recent work

### Step 1: Generate Changelog Entry

```bash
# Always preview first
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --dry-run
```

The script:
- Picks the starting point, in this order: `--since <ref>`; the tag of the first versioned heading of CHANGELOG.md (`[Unreleased]` skipped), `v<heading>` or `<heading>`, reachable from HEAD, whatever its form (`[1.1.0-rc1]` starts at `v1.1.0-rc1`); when CHANGELOG.md has no versioned heading, the newest release tag (`v1.2.3` or `1.2.3`, so not `v1.2.3-rc1` or `20261001-snap`) reachable from HEAD, by version order; else the whole history, first commit included. It prints which one it used. Without `--since`, that first versioned heading must have its tag reachable from HEAD. If not (say, after `--version 1.1.0` and before the `v1.1.0` tag), it exits 1 with "CHANGELOG.md has [1.1.0] but there is no tag for it; tag the release or pass --since <ref>" and writes nothing, so released commits are not listed again.
- Reads all commits since that point
- Categorizes by conventional commit prefix (`feat:` → Added, `fix:` → Fixed, etc.)
- Puts commits with no prefix under Other (see File-Path Fallback for the one exception)
- Outputs a Keep-a-Changelog formatted entry

A ref (from `--since` or the CHANGELOG.md heading) may use letters, digits and `.` `_` `/` `~` `^` `-`, and must not start with `-`.

### Step 2: Review and Refine

After the script generates the raw entry:
- **Consolidate** related entries (e.g., multiple fix commits for the same issue → one bullet)
- **Improve wording** — commit messages are developer-facing; changelog entries should be user-facing
- **Remove noise** — drop entries for internal refactoring, CI changes, or typo fixes that don't affect users
- **Add context** — link to issues/PRs if relevant

### Step 3: Write to CHANGELOG.md

```bash
# Add the new bullets to the [Unreleased] section
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh"

# Or promote [Unreleased] to a versioned entry for a release
"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh" --version 1.2.0
```

What a write does:
- Each new bullet goes under the matching `### <Category>` of the `[Unreleased]` block, after the bullets already there. A missing `### <Category>` is added at the end of the block. A bullet already in the block under a heading of the same category is skipped, once per copy there, so running it twice adds nothing. The same text under another category does not count: an existing Fixed `- retry` does not stop a new Added `- retry`. Released sections are not checked: a new commit whose subject is already in one is added. Two commits with the same text in one run (`fix(api): retry` and `fix(ui): retry`; the scope is dropped) give two bullets.
- The block ends at the next `## ` heading or link reference line (`[Unreleased]: https://...`). Hand-written bullets, other sections (`## v1.0.0 (2024-01-01)` too) and footer links are kept.
- With no `[Unreleased]` section, one is added before the first `## ` heading or link reference, or at the end of the file.
- `--version X.Y.Z` adds `## [X.Y.Z] - <today>` right under `## [Unreleased]`, so the old `[Unreleased]` body and the new bullets become the release section, and `[Unreleased]` is left empty. It is refused (exit 1) if `## [X.Y.Z]` already exists. With no new commits it still moves the `[Unreleased]` body into the release section; if `[Unreleased]` is empty too, it exits 1 with "nothing to release". Without `--version`, no new commits prints "No new commits" and exits 0.
- A `CHANGELOG.md` with CRLF line endings keeps them: lines are compared without the `\r`, old lines are written back as they were, and new lines get CRLF.
- Before it replaces the file, the script checks that every line of the old file is still there, in order. If not, it exits 1 and leaves the file alone. A `CHANGELOG.md` that is a symlink, a directory or anything else that is not a regular file is refused (exit 1).

### Step 4: Include in Commit

Stage the updated CHANGELOG.md with the rest of the changes:

```bash
git add CHANGELOG.md
# Then commit as usual
```

## Categorization Rules

The script categorizes commits using conventional commit prefixes:

| Prefix | Category | Example |
|--------|----------|---------|
| `feat`, `add` | **Added** | `feat: add dark mode toggle` |
| `fix` | **Fixed** | `fix: resolve login timeout` |
| `docs` | **Documentation** | `docs: update API reference` |
| `test` | **Testing** | `test: add unit tests for auth` |
| `refactor`, `perf`, `style`, `chore`, `build`, `ci` | **Changed** | `refactor: simplify auth flow` |
| `revert` | **Removed** | `revert: remove experimental flag` |
| (no prefix, or any other prefix) | **Other** | `Update README` |

### File-Path Fallback

Only when **no** commit in the range has a prefix from the table, the script looks at the files the range changed. If any is under `src/`, `lib/` or `scripts/`, the commits go to **Changed** instead of **Other**. Otherwise they stay in **Other**.

In a range that mixes prefixed and unprefixed commits, the unprefixed ones always go to **Other**.

## Format

The script follows [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

## [Unreleased]

### Added
- New feature description

### Fixed
- Bug fix description

## [1.0.0] - 2026-02-24

### Added
- Initial release features
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Conventional commits first | Parse prefixes before file paths | More accurate when available |
| Keep-a-Changelog format | Standard sections (Added/Changed/Fixed/...) | Widely recognized, machine-parseable |
| Dry-run default in workflow | Always preview first | Prevents accidental overwrites |
| No AI dependency | Pure git + sed/awk | Works offline, deterministic, fast |
| Scope stripping | `fix(auth):` → body only | Scopes are for commits, not changelogs |
