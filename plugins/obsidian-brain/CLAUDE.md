# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Obsidian Brain is a Claude Code plugin that turns an Obsidian vault into a persistent knowledge base across sessions. It auto-logs sessions, captures curated knowledge, and enables project-scoped context resume via structured markdown notes.

**Integration pattern:** Direct filesystem writes only — no MCP server, no REST API, no Obsidian plugins required (except Dataview for dashboards).

## Development Commands

There is no build step, test suite, or linter. This is a pure Python (stdlib only) + Markdown plugin. Validation is manual:

```bash
# Verify hook registration is valid JSON
python3 -c "import json; json.load(open('hooks/hooks.json'))"

# Verify plugin manifest
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"

# Test a hook script directly (requires config at ~/.claude/obsidian-brain-config.json)
python3 hooks/obsidian_session_log.py
python3 hooks/obsidian_session_hint.py
python3 hooks/obsidian_context_snapshot.py
```

## Architecture

### Two execution modes

1. **Hooks (auto-running Python scripts)** — Triggered by Claude Code lifecycle events. Registered in `hooks/hooks.json`. Must exit 0, use only Python stdlib, and write atomically (temp file + rename).
2. **Skills (prompt-based procedures)** — Each `skills/*/SKILL.md` is a step-by-step prompt that Claude Code follows. No code files — skills use standard CC tools (Bash, Read, Write, Grep). Changes to SKILL.md directly change skill behavior.

### Key files

- `hooks/obsidian_utils.py` — Shared utility module (~655 lines) used by all three hooks. Contains transcript parsing, metadata extraction, summarization (shells out to `claude -p --model haiku`), and atomic vault writes.
- `hooks/obsidian_session_log.py` — SessionEnd: writes raw session note immediately, then attempts AI summarization (15s timeout, best-effort).
- `hooks/obsidian_session_hint.py` — SessionStart: injects last-session context hint for the current project.
- `hooks/obsidian_context_snapshot.py` — PreCompact: saves context snapshot before compression.
- `templates/` — Markdown templates for each note type (session, insight, decision, error-fix, snapshot, imported-session).
- `dashboards/` — Dataview query templates installed to the user's vault.

### Data flow

Sessions are logged with a **write-first pattern**: the raw note (with conversation excerpts, tool usage, metadata) is always saved to the vault immediately. AI summarization is attempted as a best-effort upgrade. Unsummarized notes get upgraded later when `/recall` is invoked.

### Configuration

Machine-local config at `~/.claude/obsidian-brain-config.json` (outside the vault, outside this repo). Created by `/obsidian-setup`. Contains vault path, folder names, filtering thresholds, and feature flags.

### Tag convention

All frontmatter tags use the `claude/` prefix: `claude/session`, `claude/insight`, `claude/decision`, `claude/error-fix`, `claude/snapshot`, `claude/imported`, `claude/standup`, `claude/retro`, `claude/project/<name>`, `claude/topic/<topic>`, `claude/auto`.

## Conventions

- **Commits:** Use conventional commit format — `feat(obsidian-brain):`, `fix:`, `chore:`, `docs:`
- **Python:** stdlib only, no pip dependencies. All hooks must be deterministic and safe to run at session boundaries.
- **Atomic writes:** All vault writes must use temp file + rename pattern (see `write_vault_note()` in `obsidian_utils.py`).
- **Version:** Bump in both `.claude-plugin/plugin.json` and update `CHANGELOG.md` for releases.
- **Branching:** Never commit directly to develop/main — use feature branches.

## Git Flow Rules

- Never commit directly to `main` or `develop` — use feature branches
- Branch naming: `feature/*`, `release/*`, `hotfix/*`
- Features branch from and merge to `develop`
- Releases branch from `develop`, merge to both `main` and `develop`
- Hotfixes branch from `main`, merge to both `main` and `develop`
- Run `./scripts/commit-preflight.sh` before every commit
