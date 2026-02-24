# conversation-search

Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries.

## Installation

### Individual repo (recommended)

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

### Via monorepo (all skills)

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/conversation-search ~/.claude/skills/conversation-search
rm -rf /tmp/claude-code-skills
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

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
conversation-search/
├── .github/
    ├── PULL_REQUEST_TEMPLATE.md
    ├── workflows/
        ├── validate-skill.yml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── scripts/
    ├── search-conversations.sh
    ├── validate-skill.sh
├── SKILL.md
```

## License

[MIT](LICENSE)
