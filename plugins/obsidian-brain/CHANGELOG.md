# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.0] - 2026-04-07

### Added

- **Cross-project open items dashboard** — New `claude-dashboards/open-items.md` Dataview dashboard installed by `/obsidian-setup`. Shows all unchecked `- [ ]` items from session notes' `## Open Questions / Next Steps` sections, grouped by project, with separate "Recent (7d)" and "Items from sessions 30-90 days ago" views plus stats. Scoped to the last 90 days for performance.
- **`/check-items` skill** — Cross-project sweep that scans all session notes for unchecked items (unbounded), gathers evidence from sessions in the last 14 days per project, proposes matches via substring + completion-phrase heuristics, and flips confirmed items from `- [ ]` to `- [x]` in the source notes. The 14-day window applies only to the evidence pool used for matching; open-item collection itself is unbounded. Configurable via `/check-items <Nd>`.
- **`/recall` auto-detect** — `/recall` now detects open items from the current project that may have been completed in the most recent loaded session. Proposes candidates with evidence snippets; user confirms before any edits.
- **`/standup` Closed This Period section** — Standup notes now include a section listing items checked off during the standup window, grouped by project. Detected via file modification time. Omitted if zero items closed.

### Changed

- **`obsidian-setup` skill** — Now installs the new `open-items.md` dashboard. Skill version bumped to 1.3.0.
- **`recall` skill** — New Step 7.5 detects completed open items. Skill version bumped to 1.1.0.
- **`standup` skill** — New "Closed This Period" section. Skill version bumped to 1.1.0.

## [1.5.3] - 2026-04-06

### Added

- **Permission pre-flight check in `/obsidian-setup`** — Detects restrictive Claude Code permission modes via canary write before attempting out-of-workspace writes. Presents three options: switch mode (`Shift+Tab`), whitelist paths in settings, or continue manually.
- **Vault path canary** — Tests vault writability in `/obsidian-setup` Step 5 before creating folders, catching cases where `~/.claude/` is writable but the vault is not.
- **README troubleshooting section** — Covers silent setup failures (permission modes), `python` not found on macOS, and vault path not writable.

### Changed

- **Auto-logging description** — README now accurately reflects deferred summarization (removed reference to in-hook `claude -p` subprocess).

## [1.5.2] - 2026-04-06

### Added

- **Standup highlights summary** — `/standup` now generates a highlights summary and key open items section at the top of standup notes for quick scanning.

### Fixed

- **Python 3.9 compatibility** — Added `from __future__ import annotations` to `obsidian_utils.py` so `X | None` type hints (PEP 604) work on macOS system Python 3.9.6. Previously caused `TypeError` at import time, breaking all hooks.
- **SessionEnd hook cancellation** — Removed in-hook AI summarization (`claude -p` subprocess) from `obsidian_session_log.py`. SessionEnd hooks are fire-and-forget; the slow subprocess was killed when Claude Code's process tree exited. Summarization is now fully deferred to `/recall`.

## [1.5.1] - 2026-04-05

### Fixed

- **Hookify nudge scope** — `/obsidian-setup` now writes the claudeception-compress nudge rule to `~/.claude/` (global) instead of the project's `.claude/` directory, so the nudge triggers in any project where claudeception runs. Also fixes the existence check to look for the `.local.md` rule file instead of grepping `settings.json`.
- **Changelog PR hook now detects stale entries** — The `update-changelog-before-pr` hook now diffs CHANGELOG.md against the base branch instead of just checking for any entries under `[Unreleased]`. Stale entries from previous releases no longer cause false passes.

## [1.5.0] - 2026-04-05

### Added

- **Claudeception-to-Compress bridge** — `/compress` now detects `/claudeception` output in the conversation and surfaces extracted skills/knowledge as top-priority insight candidates. Uses layered detection: high-confidence structured markers (skill validator output, skill file paths) first, broad phrase scanning as fallback. Claudeception candidates are labeled `[from claudeception]` or `[possibly from claudeception]` and included when the user selects `all`.
- **Hookify nudge via `/obsidian-setup`** — New idempotent step in `/obsidian-setup` configures a hookify nudge that reminds users to run `/compress` after claudeception produces output. Existing users can re-run `/obsidian-setup` to pick up the nudge.

### Changed

- **`/obsidian-setup` is now idempotent** — Detects existing installations and offers upgrade/reconfigure/cancel. In upgrade mode, preserves existing config and user-customized dashboards while adding new features (dashboards, hookify nudges). Safe to re-run anytime.

## [1.4.0] - 2026-04-05

### Added

- `/standup` skill: daily/weekly summary generation across projects with AI summarization, context-shield deep reads, and source note backlinks
- `/link` skill: cross-reference related notes with bidirectional wikilinks and auto-suggestion
- `/retro` skill: honest session retrospective for meta-learning with session backlinks
- `/vault-ask` skill: synthesize answers from vault knowledge with source citations and relevance ranking
- Learning Velocity dashboard: topic frequency from curated insights, retrospective history, error patterns
- Decision Timeline dashboard: chronological decision tracking with active/superseded status views

## [1.3.0] - 2026-04-05

### Fixed

- **SessionStart hook output** — Added required `hookEventName: "SessionStart"` field to `obsidian_session_hint.py` JSON output. Claude Code silently drops `hookSpecificOutput` JSON that omits this field, causing the session hint to never appear at startup.
- **SessionStart hook matcher** — Added explicit `matcher` field to `hooks.json` SessionStart entry for clarity (optional but documents intent).

### Added

- **Session backlinks in insights** — All insight-producing skills (`/compress`, `/error-log`, `/decide`) now derive the current session ID and include a `source_session_note` wikilink in frontmatter, enabling bidirectional navigation between session notes and insights in Obsidian's graph view.
- **Session ID derivation** — Skills now detect the active session by finding the most recently modified `.jsonl` file in the Claude Code project directory, replacing the broken `$CLAUDE_SESSION_ID` environment variable approach.

### Changed

- **Templates updated** — `insight.md`, `error-fix.md`, and `decision.md` templates now include `source_session` and `source_session_note` frontmatter fields.

## [1.2.0] - 2026-04-04

### Added

- **Git Flow enforcement** — Claude Code hooks to prevent direct push to main/develop, validate branch naming (`feature/*`, `release/*`, `hotfix/*`), and require preflight checks before commit
- **Commit preflight system** — `scripts/commit-preflight.sh` with secret scanning, one-time token mechanism, and skip-tests escape hatch
- **Release pipeline** — `scripts/bump-version.sh` (targets `.claude-plugin/plugin.json`) and `scripts/git-flow-finish.sh` for automated release/hotfix completion
- **GitHub Actions CI** — Secret scan on all PRs, changelog check on PRs to main, release verification on main push
- **Branch protection** — Status check enforcement on main and develop (admin-lenient)

### Documentation

- **README vault details** — Added detailed descriptions of each `claude-*` folder, how content gets loaded into sessions, and a context loading summary table

## [1.1.0] - 2026-04-04

### Improved

- **Richer session notes** — raw fallback notes now include assistant messages, tool usage details (commands run, files edited, searches performed), and interleaved conversation (up to 40 turns). System noise (task notifications, skill loading) is filtered out.
- **Better `/recall` summaries** — summarization prompt now demands specific technical details: file paths, function names, decision rationale, error root causes with fixes, and concrete next steps.

### Fixed

- Raw notes previously only captured user messages (15 max). Now captures full conversation with both sides for `/recall` to produce high-quality summaries.

## [1.0.0] - 2026-04-04

### Added

- **Auto-logging** — SessionEnd hook automatically writes structured session notes to your Obsidian vault with YAML frontmatter, tags, and metadata. Uses a write-first pattern: raw note is always saved, AI summary attempted as best-effort upgrade.
- **Context hints** — SessionStart hook injects a one-line summary of the last session for the current project, giving you immediate continuity.
- **Context snapshots** — PreCompact hook saves a snapshot of your current context before compression or clear, preserving context that would otherwise be lost.
- **`/obsidian-setup`** — Interactive first-run configuration. Sets vault path, creates folders, copies Dataview dashboards, writes config.
- **`/compress`** — Curate and save specific insights from the current session. Suggests candidates or accepts a topic argument. Interactive preview with tag editing.
- **`/recall`** — Load project-scoped context from vault history. Finds your last session, open items, and all curated insights. Includes deferred summarization — upgrades raw notes with AI summaries on demand.
- **`/vault-search`** — Search across all sessions and insights by keyword, tag, or structured queries (e.g., `project:api-service type:decision`).
- **`/decide`** — Log architectural decisions in ADR-lite format: Context, Options, Decision, Rationale, Consequences.
- **`/error-log`** — Capture errors with root cause, fix, and prevention steps for future reference.
- **`/vault-import`** — Backfill historical sessions from CC conversation history. Uses `/conversation-search` for discovery and parallel `/context-shield` sub-agents for processing.
- **Dataview dashboards** — 3 ready-to-use dashboards: Sessions Overview, Project Index, Weekly Review.
- **Note templates** — 6 templates for all note types: session, insight, decision, error-fix, snapshot, imported session.
- **Plugin distribution** — Installable via Claude Code plugin system from GitHub.
