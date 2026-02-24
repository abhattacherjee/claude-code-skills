---
name: conversation-search
description: "Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries. Use when: (1) user asks to find a past conversation, (2) user wants to recall what was discussed on a topic or date, (3) user asks to search conversation history, (4) /conversation-search command."
metadata:
  version: 1.1.0
---

# Conversation Search

Searches all Claude Code conversation history stored in `~/.claude/projects/`. Returns matching
conversations with metadata, verbatim content, and optionally AI-generated summaries.

## Quick Reference

```bash
SCRIPT=~/.claude/skills/conversation-search/scripts/search-conversations.sh

# List recent conversations
$SCRIPT list
$SCRIPT list --limit 5 --project "tiny-vacation"

# Search by topic (index-based, fast)
$SCRIPT search --topic "catalog" --after 2025-06-01
$SCRIPT search --topic "deploy" --branch "main"

# Deep search (scans JSONL content, slower)
$SCRIPT search --topic "CSRF" --deep

# Show a specific conversation (supports ID prefix)
$SCRIPT show 0be99c26
$SCRIPT show 0be99c26 --max-messages 50

# JSON output (for agent consumption)
$SCRIPT show 0be99c26 --json --max-messages 100

# Statistics
$SCRIPT stats
```

## Workflow

### Step 1: Parse the User's Query

Map natural language to script flags:

| User says | Script flags |
|---|---|
| "Find conversations about catalog maintenance" | `search --topic "catalog maintenance"` |
| "What did I discuss last Tuesday?" | `search --after 2025-02-17 --before 2025-02-18` |
| "Show my work on the feature/story-6.5 branch" | `search --branch "story-6.5"` |
| "Find where I debugged CSRF errors" | `search --topic "CSRF" --deep` |
| "Recent conversations in tiny-vacation project" | `list --project "tiny-vacation" --limit 10` |

**When to use `--deep`:** Only when the topic is unlikely to appear in the conversation's
`firstPrompt` or `summary` fields (e.g., specific error messages, function names, obscure terms).
Start without `--deep` first — it's much faster.

### Step 2: Present Results

Run the script and present the results to the user. The script outputs formatted text by default.
Show the list and ask which conversation(s) the user wants to explore further.

### Step 3: Show Conversation Detail

When the user selects a conversation:
- Run `show <session-id>` to display the verbatim conversation
- Use `--max-messages` to control output size (default 200)
- For very long conversations, start with `--max-messages 50` and increase if needed

### Step 4: Summarize (Optional)

If the user requests a summary, launch the `conversation-summarizer` agent:

```
Task(subagent_type="conversation-summarizer", prompt=<JSON from show --json>)
```

Pass the JSON output from `show --json` as the prompt. The agent returns a structured summary
with: key topics, decisions made, code changes, outcomes, and open items.

## Tips

- **Session ID prefix matching**: You can use just the first 8 characters of a session ID
  (e.g., `0be99c26` instead of the full UUID).
- **Date formats**: Both `YYYY-MM-DD` and full ISO 8601 are supported.
- **Large conversations**: Some conversations have 10,000+ messages. Use `--max-messages`
  to avoid overwhelming output. Start with 50-100, increase if the user needs more context.
- **Multiple criteria**: Combine filters — `search --topic "deploy" --branch "main" --after 2025-01-01`
- **JSON mode**: Use `--json` when feeding results to the summarizer agent.

## See Also

- **GitHub**: https://github.com/abhattacherjee/conversation-search — install instructions, changelog, license
