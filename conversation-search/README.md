# conversation-search

A Claude Code skill for searching conversation history stored in `~/.claude/projects/`. Find past conversations by topic, date, branch, or project — with optional AI-generated summaries.

## Installation

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/abhattacherjee/conversation-search.git ~/.claude/skills/conversation-search

# Windows
git clone https://github.com/abhattacherjee/conversation-search.git %USERPROFILE%\.claude\skills\conversation-search
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/abhattacherjee/conversation-search.git .claude/skills/conversation-search
```

## Updating

```bash
git -C ~/.claude/skills/conversation-search pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/conversation-search
```

## What It Does

This skill lets you search and recall past Claude Code conversations:

- **List** recent conversations across all projects
- **Search** by topic keyword, date range, git branch, or project name
- **Deep search** inside conversation content (full-text JSONL scanning)
- **Show** verbatim conversation content with metadata
- **Summarize** conversations using an AI-powered summarizer agent
- **Statistics** on your conversation history

### Usage Examples

```bash
# List recent conversations
/conversation-search list

# Search by topic
/conversation-search search for "authentication" conversations

# Find what you discussed on a specific date
/conversation-search what did I work on last Tuesday?

# Search a specific branch
/conversation-search show my work on the feature/auth branch

# Deep search for a specific error message
/conversation-search find where I debugged "CSRF token mismatch"
```

The skill translates natural language into script flags automatically.

## Prerequisites

The search script requires these standard Unix tools:

- **jq** — JSON processing (`brew install jq` on macOS)
- **perl** — text processing (pre-installed on macOS and most Linux)

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
conversation-search/
├── .gitignore
├── CHANGELOG.md
├── LICENSE
├── README.md
├── SKILL.md
└── scripts/
    └── search-conversations.sh
```

## License

[MIT](LICENSE)
