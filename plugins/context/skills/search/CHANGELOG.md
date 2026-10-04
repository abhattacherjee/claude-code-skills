# Changelog

All notable changes to the **search** skill (was `conversation-search`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `context` plugin as `context:search` (#163). Same search workflow and script as `conversation-search` 1.1.0. The old name and `/conversation-search` still match as trigger phrases.
- Every command runs as written from your project directory: `"${CLAUDE_SKILL_DIR}/scripts/search-conversations.sh"`. The old text set `SCRIPT=~/.claude/skills/conversation-search/scripts/search-conversations.sh`, which only worked from a loose copy (#163).
- The summarizer agent now ships in the plugin and is started as `context:conversation-summarizer`. It used to live only in `~/.claude/agents/` and was not in any repo (#163).
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh` (the old copy was older).

## History before 1.0.0 (as `conversation-search`)

### conversation-search 1.1.0 - 2026-02-22

Initial public release.

#### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support
