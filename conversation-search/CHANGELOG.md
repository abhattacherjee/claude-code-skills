# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-02-22

Initial public release.

### Included

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
