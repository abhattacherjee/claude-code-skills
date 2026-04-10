---
name: compress
description: "Interactively saves curated insights from the current Claude Code session to the Obsidian vault. Use when: (1) /compress command to save session insights, (2) /compress <topic> to extract a specific topic, (3) user wants to capture decisions, patterns, solutions, or error fixes from the current session."
metadata:
  version: 1.0.0
---

# Compress — Save Session Insights to Obsidian

Analyze the current conversation, extract valuable insights, and save them as structured notes in the Obsidian vault. Supports both interactive multi-insight selection and targeted single-topic extraction.

**Tools needed:** Bash, Write, Read

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Read config

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import load_config
c = load_config()
if not c.get("vault_path"):
    print("ERROR: vault_path not configured", file=sys.stderr)
    sys.exit(1)
print("VAULT=" + c["vault_path"] + " SESS=" + c.get("sessions_folder", "claude-sessions") + " INS=" + c.get("insights_folder", "claude-insights"))
'
```

Parse the output line to extract `VAULT_PATH`, `SESSIONS_FOLDER`, and `INSIGHTS_FOLDER`.

If the output is empty or errors, tell the user:

> Config not found. Please run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

### Step 2 — Validate vault access

Run:

```bash
test -d "$VAULT_PATH/$INSIGHTS_FOLDER" && test -w "$VAULT_PATH/$INSIGHTS_FOLDER" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user:

> The insights folder `$VAULT_PATH/$INSIGHTS_FOLDER` does not exist or is not writable. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 3 — Determine mode

Check if the user provided a topic argument after `/compress`.

- **With argument** (e.g. `/compress rate limiting strategy`): Go to Step 4A.
- **Without argument** (bare `/compress`): Go to Step 4B.

### Step 4A — Single-topic extraction

Analyze the current conversation for content related to the user's specified topic. Draft a note that includes:

- **Summary:** 2-4 sentence overview of the topic as discussed in this session
- **Details:** Key points, code snippets, configurations, or commands relevant to the topic
- **Context:** Why this came up, what problem it solved, any trade-offs discussed

Skip to Step 5.

### Step 4B — Multi-insight suggestion

**First, check for claudeception output** using layered detection:

**Layer 1 — High-confidence structured markers** (check first):

Scan the current conversation for these patterns. If found, extract the skill/knowledge name and a one-line summary:

- The `MANDATORY SKILL EVALUATION REQUIRED` banner (from the claudeception activator hook)
- `Result: PASS` or `Result: FAIL` (from the claudeception skill validator)
- Skill file paths matching `~/.claude/skills/*/SKILL.md` or `.claude/skills/*/SKILL.md`

If any Layer 1 markers are found, create a candidate for each and label it `[from claudeception]`.

**Layer 2 — Broad phrase scanning** (fallback, only if Layer 1 found nothing):

Scan the conversation for these phrases:
- "created skill", "new skill at", "skill file written"
- "extracted knowledge", "pattern identified", "reusable insight"
- Output from a `/claudeception` invocation

If any Layer 2 phrases are found, create a candidate for each and label it `[possibly from claudeception]`.

**Then, perform standard insight discovery:**

Analyze the full conversation and identify 3-5 additional candidate insights (beyond any claudeception candidates). Each candidate should be one of these types:

- **Decision** — an architectural or design choice made during the session
- **Pattern** — a reusable approach, technique, or workflow discovered
- **Solution** — a specific problem solved with a clear fix
- **Error Fix** — a bug or error diagnosed and resolved
- **Discovery** — a new finding about a tool, API, library, or system behavior

**Present all candidates** as a numbered list, with claudeception candidates first:

> **Insights found in this session:**
>
> 1. [from claudeception] [Discovery] Rate limiter pattern — extracted as reusable skill
> 2. [possibly from claudeception] [Pattern] Retry with exponential backoff — identified across 3 sessions
> 3. [Decision] Chose Redis for session store — trade-off analysis
> 4. [Solution] Fixed CORS issue with Safari — root cause in preflight handling
>
> Which would you like to save? (e.g. `1,3` or `all`)

If no claudeception output was detected, present only the standard candidates (same as before — no labels).

When the user says `all`, all candidates (including claudeception ones) are saved. When the user picks specific numbers, only those are saved — standard selection behavior.

Wait for the user to pick. For each selected insight, draft the note content and continue to Step 5. Process selected insights one at a time.

### Step 5 — Auto-generate topic tags

Based on the note content, generate 1-3 topic tags. Tags should be lowercase, hyphenated, and specific. Examples:

- `claude/topic/rate-limiting`
- `claude/topic/react-hooks`
- `claude/topic/git-workflow`
- `claude/topic/api-design`

### Step 6 — Show preview and ask for edits

Present the full note to the user including frontmatter:

```
---
type: claude-insight
date: YYYY-MM-DD
source_session: <current-session-id>
source_session_note: "[[<session-note-filename>]]"
project: <project-name>
tags:
  - claude/insight
  - claude/project/<project-name>
  - claude/topic/<auto-generated-topic-1>
  - claude/topic/<auto-generated-topic-2>
---

# <Title>

<Note body>
```

Where:
- `YYYY-MM-DD` is today's date
- `<current-session-id>` and `<session-note-filename>` are derived together. Get session context via the shared helper:

  ```bash
  cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  python3 -c '
  import sys
  sys.path.insert(0, "hooks")
  from obsidian_utils import load_config, get_session_context
  c = load_config()
  ctx = get_session_context(c["vault_path"], c.get("sessions_folder", "claude-sessions"))
  print("SID=" + ctx["session_id"] + " HASH=" + ctx["hash"] + " PROJECT=" + ctx["project"] + " SESSION_NOTE=" + ctx["session_note_name"])
  '
  ```

  Parse the output to get `SESSION_ID`, `HASH`, `PROJECT`, and `SESSION_NOTE`. Use these for the frontmatter fields.

  **Important:** If `SESSION_ID` is `unknown`, use `unknown` for `source_session` and omit `source_session_note` entirely.
- `<project-name>` is the `PROJECT` value from `get_session_context()` (lowercased, hyphenated basename of cwd)
- The `source_session_note` field creates an Obsidian backlink from the insight to its source session, enabling bidirectional navigation in the graph view

Ask the user:

> Preview above. Would you like to:
> - **save** as-is
> - **edit tags** — add or remove tags
> - **edit content** — tell me what to change
> - **cancel** — discard this note

Wait for the user's response. Apply any requested edits and show the updated preview. Repeat until the user says **save** or **cancel**.

If cancel, stop here (or move to the next selected insight if processing multiple from Step 4B).

### Step 7 — Generate filename

Construct the filename from these parts:

1. **Date:** `YYYY-MM-DD` (today)
2. **Slug:** The note title, lowercased, spaces replaced with hyphens, non-alphanumeric characters (except hyphens) removed, truncated to 50 characters
3. **Hash:** 4-character hex hash derived from the current timestamp (use the last 4 hex characters of `date +%s | md5` or equivalent)

Final filename: `YYYY-MM-DD-<slug>-<hash>.md`

Example: `2026-04-04-rate-limiting-with-redis-a3f2.md`

### Step 8 — Write the note

Run:

```bash
mkdir -p "$VAULT_PATH/$INSIGHTS_FOLDER"
```

Then use the **Write** tool to write the full note (frontmatter + body) to:

```
$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-<slug>-<hash>.md
```

Then set permissions:

```bash
chmod 644 "$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-<slug>-<hash>.md"
```

### Step 9 — Confirm

Print:

> **Insight saved!**
> - File: `$VAULT_PATH/$INSIGHTS_FOLDER/<filename>`
> - Tags: `claude/insight`, `claude/project/<name>`, `claude/topic/<topic1>`, ...
> - Open in Obsidian to view and link to other notes.

If processing multiple insights from Step 4B, repeat Steps 5-9 for each remaining selected insight.

### Step 10 — Offer follow-up

After all insights are saved, ask:

> Anything else to capture from this session? You can run `/compress` again or `/compress <topic>` for a specific topic.
