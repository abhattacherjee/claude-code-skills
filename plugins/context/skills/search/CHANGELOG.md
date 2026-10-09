# Changelog

All notable changes to the **search** skill (was `conversation-search`) are documented here.

## [1.1.0] - 2026-10-09

### Changed

- The bundled `scripts/validate-skill.sh` (a byte-identical copy of the repo-root validator) has new checks. It fails a SKILL.md body of 500 lines or more (it passed exactly 500, and missed a last line with no newline); a name containing `anthropic` or `claude`; a `.md` file that SKILL.md does not name and no script in `scripts/` reads; and a `.md` file over 100 lines with no `## Contents` heading in its first 30 lines. CONTRIBUTING.md, files under a dot-directory such as `.github/` and files under a top-level `tests/` directory are not checked (#214).

## [1.0.1] - 2026-10-05

### Changed

- The bundled `scripts/validate-skill.sh` changed in comments and help text only: its usage example names a plugin skill path instead of the deleted `changelog-keeper/` directory, and its NOTE names the skills that ship a byte-identical copy and the frozen `skill-authoring` copy as the exception (#167).

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `context` plugin as `context:search` (#163). Same search workflow and script as `conversation-search` 1.1.0. The old name and `/conversation-search` still match as trigger phrases.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`; the skill was also run through headless Claude): `"${CLAUDE_SKILL_DIR}/scripts/search-conversations.sh"`. The old text set `SCRIPT=~/.claude/skills/conversation-search/scripts/search-conversations.sh`, which only worked from a loose copy (#163).
- The summarizer agent now ships in the plugin and is started as `context:conversation-summarizer`. It used to live only in `~/.claude/agents/` and was not in any repo (#163).
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh` (the old copy was older).

### Fixed

- `--deep` with no match, and a bare `--no-color`, stopped with `unbound variable` on bash 3.2 (macOS).
- `--deep` matched the topic as a regular expression; it is now literal text.
- A backslash in `--topic`, `--branch`, `--project`, `--after` or `--before` broke the jq filter, and `\(...)` ran as jq code. Values are escaped now.
- `--before <date>` no longer keeps a conversation created exactly at that midnight.
- The "last Tuesday" example named a Monday (`--after 2025-02-17 --before 2025-02-18`). It now uses 2025-02-18 and 2025-02-19.
- `--limit` ran as jq code (`--limit '0] | {pwned: env.HOME} | .['` printed `$HOME`). `--limit` and `--max-messages` must be non-negative integers (exit 2 otherwise) and go to jq as `--argjson`.
- `--after` and `--before` accept only `YYYY-MM-DD` or a UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`, optionally with `.sss`); `--after garbage` used to return `[]` with exit 0. Anything else, including offsets such as `+05:30`, exits 2 with a message. Both sides are compared in the form `YYYY-MM-DDTHH:MM:SS.sssZ`, so a session at exactly `10:00:00.000Z` matches `--after 2025-02-18T10:00:00Z`.
- `--limit` and `--max-messages` reject leading zeros (`08`, `010`) with exit 2; bash and jq read them differently. They also reject more than 9 digits.
- A sessions-index.json that fails to parse after some entries no longer hides those sessions. The whole index is dropped (one warning) and its sessions are listed as orphans.
- A malformed `sessions-index.json` is still skipped, with `warning: skipping unreadable <path>` on stderr.
- The summarizer example uses `Agent({subagent_type: "context:conversation-summarizer", ...})`, not `Task(...)`.

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
