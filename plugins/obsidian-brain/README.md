# Obsidian Brain

A Claude Code plugin that turns your Obsidian vault into a persistent brain across sessions. Auto-logs sessions, captures curated knowledge, enables project-scoped context resume, and provides fast search across all historical context.

## Why

Claude Code sessions are ephemeral — when you close a session, the context is gone. Your existing CLAUDE.md and memory system help, but they lack:

- **Structured search** across hundreds of past sessions
- **Cross-project pattern discovery** (what approaches have I used before?)
- **Curated knowledge capture** (decisions, error fixes, insights)
- **Visual dashboards** of your coding history

Obsidian Brain bridges this gap by writing structured markdown notes to your Obsidian vault, where Dataview turns them into a queryable knowledge base.

## How It Works

```
CC Session Lifecycle
    |
    |-- SessionStart --> Injects last-session context hint
    |-- PreCompact ---> Saves context snapshot before compression
    |-- /compress ----> You curate & save specific insights
    |-- /recall ------> Loads project context from vault
    |-- /vault-search > Searches across all sessions & insights
    |-- /standup -----> Generates daily/weekly project summaries
    |-- /standup deep > Evidence-based open-item consolidation
    |-- /emerge ------> Cross-project pattern discovery
    |-- /link --------> Cross-references notes with wikilinks
    |-- /retro -------> Session retrospective & process improvements
    |-- /vault-ask ---> Synthesized answers from vault knowledge
    +-- SessionEnd ---> Auto-logs session to vault
```

All data flows are **one-directional filesystem writes** — no MCP server, no REST API, no Obsidian plugins required (except Dataview for dashboards). A local SQLite + FTS5 index enables fast full-text search as the vault scales. Works even when Obsidian isn't running.

## Installation

```bash
# Add the marketplace (if not already added)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install the plugin
/plugin install obsidian-brain@claude-code-skills

# First-run setup
/obsidian-setup
```

### Prerequisites

- **Obsidian** with the [Dataview](https://github.com/blacksmithgu/obsidian-dataview) community plugin installed
- **Claude Code** CLI available on PATH
- Dataview settings: enable **JavaScript Queries** and **Inline Queries**

## Setup

Run `/obsidian-setup` after installation. It will:

1. Ask for your Obsidian vault path
2. Create folders: `claude-sessions/`, `claude-insights/`, `claude-dashboards/`
3. Copy Dataview dashboard templates into your vault
4. Write machine-local config to `~/.claude/obsidian-brain-config.json`
5. Verify write access with a test file

## Skills

### Core Skills

| Skill | Purpose |
|-------|---------|
| `/obsidian-setup` | First-run vault configuration |
| `/compress` | Curate & save insights from the current session |
| `/recall` | Load project-scoped context from vault history |
| `/vault-search` | Search across all sessions & insights by keyword, tag, or metadata |
| `/decide` | Log architectural decisions (ADR-lite format) |
| `/error-log` | Capture error + root cause + fix for future reference |
| `/vault-import` | Backfill historical sessions (requires `/conversation-search` and `/context-shield`) |
| `/standup` | Generate daily/weekly summary across projects |
| `/standup deep` | Evidence-based open-item consolidation — dedup, classify (COMPLETED/REDUNDANT/STALE/ACTIVE) using git log, GitHub releases, changelogs, and FTS5 search |
| `/emerge` | Cross-project pattern discovery — scans vault notes within a time window and surfaces technical patterns, process patterns, knowledge gaps, and unnamed habits |
| `/link` | Cross-reference related notes with bidirectional wikilinks |
| `/retro` | Session retrospective — what worked, what didn't, process improvements |
| `/vault-ask` | Ask questions and get synthesized answers grounded in vault history |
| `/check-items` | Cross-project sweep for completed open items — auto-checks off matches after user confirmation |
| `/vault-doctor` | Audit and repair the vault — detects stale `source_session` backlinks and other health issues (dry-run by default) |
| `/vault-reindex` | Rebuild the SQLite + FTS5 search index from scratch — use after bulk edits in Obsidian or to recover from a corrupt index |
| `/vault-stats` | Vault health diagnostics and usage analytics — signal coverage, access patterns, importance distribution, top accessed notes. Saves report to vault for trend tracking. |

### Usage Examples

```bash
# Save a specific insight from the current session
/compress the JWT refresh approach we settled on

# Load context when starting work on a project
/recall

# Search across all projects
/vault-search jwt refresh
/vault-search #claude/topic/auth
/vault-search project:api-service type:decision

# Log a decision you just made
/decide chose Redis over Memcached for session store

# Capture an error you just solved
/error-log the CORS issue with Safari

# Import last 30 days of sessions into vault
/vault-import 30d

# Generate today's standup
/standup

# Weekly summary
/standup this week

# Deep analysis — consolidate open items with evidence
/standup deep this week

# Discover patterns across all projects (last 30 days)
/emerge

# Discover patterns for a specific window
/emerge 7d
/emerge 90d

# Auto-suggest note connections
/link

# Link specific notes
/link this session to the redis decision

# Session retrospective
/retro

# Ask a question across all vault history
/vault-ask what patterns have I used for error handling?

# Sweep open items across all projects (default 14-day evidence window)
/check-items

# Sweep with a 30-day evidence window
/check-items 30d
```

## Auto-Logging

Sessions are automatically logged to your vault on every session end (via hooks). No manual action needed. The hook:

1. Reads the session transcript
2. Extracts metadata, user/assistant messages, and tool usage
3. Writes a raw session note immediately (guaranteed, fast)
4. Unsummarized notes are upgraded with AI summaries when `/recall` is invoked

**Smart filtering:** Sessions with fewer than 3 user messages or shorter than 2 minutes are skipped.

## Vault Structure

```
YourVault/
  claude-sessions/       # Auto-logged sessions + context snapshots
  claude-insights/       # Curated insights, decisions, error fixes
  claude-dashboards/     # Dataview query dashboards
```

### Folder Details

#### `claude-sessions/` — Session History

Stores auto-logged session notes and context snapshots. Every Claude Code session that meets the minimum threshold (3+ messages, 2+ minutes) gets a note written here automatically on session end.

**What's in each note:** YAML frontmatter (date, project, branch, duration, tags), conversation excerpts (up to 40 turns), tool usage details (commands run, files edited), and either an AI-generated summary or raw data that gets upgraded later.

**How it gets loaded:** When you run `/recall`, the skill reads the **2 most recent sessions** for the current project in detail (most recent in full, second most recent summary + open items only) and lists the **last 5 sessions** as a history table. Unsummarized notes are upgraded with AI summaries on the fly during `/recall`.

**Automatic context hint:** The `SessionStart` hook reads the most recent session note and injects a one-line summary at the start of every new conversation, so you always have minimal continuity without running any command.

#### `claude-insights/` — Curated Knowledge

Stores hand-picked insights you save via `/compress`, `/decide`, and `/error-log`. These are the high-signal notes — decisions you made, patterns you discovered, errors you solved.

**What's in each note:** YAML frontmatter (date, project, topic tags, source session), and a structured body that varies by type: insights have summary + details + context; decisions have context + options + rationale + consequences; error fixes have error + root cause + fix + prevention.

**How it gets loaded:** When you run `/recall`, **all insights** for the current project are included in the context brief. Insights are curated and always relevant, so none are filtered out. If the context brief exceeds ~2000 tokens, insight bodies are truncated (titles preserved) after older session summaries are trimmed first.

#### `claude-dashboards/` — Dataview Queries

Contains Obsidian Dataview dashboard templates that auto-update as notes are added. These are for browsing your vault visually in Obsidian — they don't get loaded into Claude Code sessions.

**Dashboards included:** Sessions Overview, Project Index, Weekly Review, Learning Velocity, Decision Timeline, Open Items. See the [Dataview Dashboards](#dataview-dashboards) section below for descriptions.

**Requires:** [Dataview](https://github.com/blacksmithgu/obsidian-dataview) community plugin with JavaScript Queries enabled.

### Context Loading Summary

| Trigger | What Gets Loaded | Automatic? |
|---------|-----------------|------------|
| New session starts | One-line hint from last session (SessionStart hook) | Yes |
| `/recall` | 2 recent sessions + all insights for current project (~2000 tokens) | Manual |
| `/recall <project>` | Same as above, scoped to a different project | Manual |
| `/vault-search <query>` | Matching notes across all projects | Manual |
| Context compression | Snapshot saved to vault (PreCompact hook) | Yes |

### Note Types

| Type | Tag | Created By |
|------|-----|------------|
| Session Log | `claude/session` | Auto (SessionEnd hook) |
| Context Snapshot | `claude/snapshot` | Auto (PreCompact hook) |
| Curated Insight | `claude/insight` | `/compress` |
| Decision | `claude/decision` | `/decide` |
| Error Fix | `claude/error-fix` | `/error-log` |
| Imported Session | `claude/imported` | `/vault-import` |
| Standup | `claude/standup` | `/standup` |
| Retrospective | `claude/retro` | `/retro` |

### Tag Convention

All tags use the `claude/` prefix to separate from your existing vault tags:

- `claude/session`, `claude/insight`, `claude/decision`, `claude/error-fix`, `claude/snapshot`, `claude/standup`, `claude/retro`
- `claude/project/<name>` — project scoping
- `claude/topic/<topic>` — domain/technology tags
- `claude/auto` — auto-generated content
- `claude/imported` — backfilled via `/vault-import`

## Dataview Dashboards

Six dashboard templates are installed to `claude-dashboards/`:

- **Sessions Overview** — recent sessions, insights, and active decisions across all projects
- **Project Index** — sessions grouped by project with counts and date ranges
- **Weekly Review** — this week's activity
- **Learning Velocity** — topic frequency from curated insights, recent retrospectives, and error patterns
- **Decision Timeline** — chronological view of all decisions with active/superseded status tracking
- **Open Items** — cross-project view of all unchecked `- [ ]` items from session notes' Open Questions sections, scoped to the last 90 days

These use [Dataview](https://github.com/blacksmithgu/obsidian-dataview) queries that auto-update as new notes are added.

## Configuration

Machine-local config at `~/.claude/obsidian-brain-config.json`:

```json
{
  "vault_path": "/path/to/your/vault",
  "sessions_folder": "claude-sessions",
  "insights_folder": "claude-insights",
  "dashboards_folder": "claude-dashboards",
  "min_messages": 3,
  "min_duration_minutes": 2,
  "summary_model": "haiku",
  "auto_log_enabled": true,
  "snapshot_on_compact": true,
  "snapshot_on_clear": true
}
```

## Multi-Device Support

- **Obsidian Sync:** Works seamlessly — all vault writes are new markdown files (no conflict risk). Config lives at `~/.claude/` (machine-local, outside the vault).
- **New machine setup:** Install the plugin, run `/obsidian-setup` with your vault path on that machine.

## Troubleshooting

### Setup fails silently / writes not working

**Symptom:** `/obsidian-setup` appears to complete but config file, vault folders, or dashboards were not created.

**Cause:** Claude Code's permission mode or filesystem sandbox is blocking writes outside the working directory.

**Fix:** Press `Shift+Tab` and switch to "accept edits" mode, then re-run `/obsidian-setup`. For a permanent fix, use `/config` to change `permissions.defaultMode`, or add paths to `sandbox.filesystem.allowWrite` in `~/.claude/settings.json`. **Use absolute paths** — `~` is not expanded inside JSON string values:

```json
{
  "sandbox": {
    "filesystem": {
      "allowWrite": ["/Users/you/.claude", "/Users/you/Documents/vault-parent"]
    }
  }
}
```

Replace `/Users/you` with your actual home directory (run `echo $HOME` to find it).

### `python` not found on macOS

**Symptom:** Hook scripts fail with "command not found: python".

**Cause:** macOS ships `python3`, not `python`.

**Fix:** The hooks use `python3` by default. If you see this error, check that `python3` is on your PATH (`which python3`). Install via Xcode Command Line Tools (`xcode-select --install`) or Homebrew (`brew install python`).

### Vault path not writable

**Symptom:** Setup reports the vault path is not writable, or session notes fail to save.

**Cause:** Directory permissions, Obsidian Sync lock files, or cloud sync conflicts.

**Fix:** Check `ls -la` on the vault directory. Ensure your user owns it and has write permission. If using Obsidian Sync or iCloud, ensure the sync agent isn't locking files during writes.

## Architecture

- **Integration pattern:** Direct filesystem writes (no MCP, no REST API, no Obsidian plugins needed)
- **Hook scripts:** Pure Python (stdlib only), deterministic behavior
- **Summarization:** Best-effort at SessionEnd, deferred to `/recall` for reliable upgrade
- **Vault index:** SQLite + FTS5 full-text search database (`~/.claude/obsidian-brain-vault.db`) for fast search and context-driven insight ranking. Lazy mtime sync keeps the index current without rebuilding on every access. Powers `/vault-search`, `/vault-ask`, and smart insight ranking in `/recall`.
- **Complements** existing CC memory system — runs alongside, not replacing

## License

MIT
