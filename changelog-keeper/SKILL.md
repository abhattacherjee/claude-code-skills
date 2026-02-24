---
name: changelog-keeper
description: "Keeps CHANGELOG.md up to date by generating categorized entries from git commit history. Use when: (1) user asks to update the changelog, (2) before committing changes that should be documented, (3) preparing a release and need changelog entries, (4) user says 'update changelog' or 'what changed since last release', (5) a commit is about to be pushed and the changelog hasn't been updated."
metadata:
  version: 1.1.0
---

# Changelog Keeper

Generates and maintains CHANGELOG.md entries from git commit history. Categorizes changes automatically using conventional commit prefixes and file path patterns.

## Quick Reference

```bash
SCRIPT=~/.claude/skills/changelog-keeper/scripts/update-changelog.sh

# Preview changelog entry (dry run)
$SCRIPT --dry-run

# Update [Unreleased] section
$SCRIPT

# Create a versioned entry
$SCRIPT --version 2.0.0

# Changes since a specific tag/commit
$SCRIPT --since v1.0.0

# For a different repo
$SCRIPT --dry-run /path/to/repo
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
~/.claude/skills/changelog-keeper/scripts/update-changelog.sh --dry-run
```

The script:
- Auto-detects the last version tag or changelog entry as the starting point
- Reads all commits since that point
- Categorizes by conventional commit prefix (`feat:` → Added, `fix:` → Fixed, etc.)
- Falls back to file-path categorization for non-conventional commits
- Outputs a Keep-a-Changelog formatted entry

### Step 2: Review and Refine

After the script generates the raw entry:
- **Consolidate** related entries (e.g., multiple fix commits for the same issue → one bullet)
- **Improve wording** — commit messages are developer-facing; changelog entries should be user-facing
- **Remove noise** — drop entries for internal refactoring, CI changes, or typo fixes that don't affect users
- **Add context** — link to issues/PRs if relevant

### Step 3: Write to CHANGELOG.md

```bash
# Update the [Unreleased] section
~/.claude/skills/changelog-keeper/scripts/update-changelog.sh

# Or create a versioned entry for a release
~/.claude/skills/changelog-keeper/scripts/update-changelog.sh --version 1.2.0
```

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
| (no prefix) | File-path fallback | Categorized by which files changed |

### File-Path Fallback

When commits don't use conventional prefixes, the script examines changed files:
- `src/`, `lib/`, `scripts/` → Changed
- `*.test.*`, `tests/`, `__tests__/` → Testing
- `*.md`, `docs/`, `README*` → Documentation

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

## Multi-Script CHANGELOG Coordination

When multiple scripts modify the same CHANGELOG (e.g., a sync script + a release script), they must recognize each other's entry format to avoid clobbering.

### The Problem

Script A generates `## [2026-02-24] — Monorepo sync` entries.
Script B promotes them to `## [1.1.0] - 2026-02-24` entries.

If Script A runs after Script B, it doesn't recognize `[1.1.0]` as "already handled" and prepends a new generic entry, burying or duplicating the release entry.

### The Fix: Format-Aware Detection

Each script must detect the other's entry format before writing:

```bash
FIRST_ENTRY=$(awk '/^## \[/{print; exit}' CHANGELOG.md)

# Detect sync entry (replace it)
if echo "$FIRST_ENTRY" | grep -q "Monorepo sync"; then
  # Replace with fresh sync or release entry
  ...

# Detect versioned release (preserve it)
elif echo "$FIRST_ENTRY" | grep -qE '## \[[0-9]+\.[0-9]+\.[0-9]+\]'; then
  # Skip — release entry is the audit record
  ...

# Neither — prepend new entry
else
  ...
fi
```

### Bash Newline Pitfall

When building CHANGELOG content via string concatenation, bash `echo` strips trailing newlines from variable expansion. This causes:

```
Format: Monorepo-level events only.## [1.1.0] - 2026-02-24   ← MISSING BLANK LINE
```

Fix: Use `printf '%s\n\n' "$HEADER"` instead of relying on embedded newlines in heredoc-assigned variables.

### Semver Tag Filtering

`git describe --tags --abbrev=0` picks up ANY tag (including non-semver like `sync-2026-02-24`). For version detection, filter explicitly:

```bash
# Wrong — picks up non-semver tags
git describe --tags --abbrev=0

# Right — only semver v* tags, newest first
git tag -l 'v[0-9]*' --sort=-v:refname | head -1
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Conventional commits first | Parse prefixes before file paths | More accurate when available |
| Keep-a-Changelog format | Standard sections (Added/Changed/Fixed/...) | Widely recognized, machine-parseable |
| Dry-run default in workflow | Always preview first | Prevents accidental overwrites |
| No AI dependency | Pure git + sed/awk | Works offline, deterministic, fast |
| Scope stripping | `fix(auth):` → body only | Scopes are for commits, not changelogs |
