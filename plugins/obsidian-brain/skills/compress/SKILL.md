---
name: compress
description: "Interactively saves curated insights from the current Claude Code session to the Obsidian vault. Use when: (1) /compress command to save session insights, (2) /compress <topic> to extract a specific topic, (3) user wants to capture decisions, patterns, solutions, or error fixes from the current session."
metadata:
  version: 1.1.0
---

# Compress — Save Session Insights to Obsidian

Analyze the current conversation, extract valuable insights, and save them as structured notes in the Obsidian vault. Supports both interactive multi-insight selection and targeted single-topic extraction.

**Tools needed:** Bash, Write, Read, Edit

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Read config

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
c = load_config()
if not c.get("vault_path"):
    print("ERROR: vault_path not configured", file=sys.stderr)
    sys.exit(1)
print("VAULT=" + c["vault_path"])
print("SESS=" + c.get("sessions_folder", "claude-sessions"))
print("INS=" + c.get("insights_folder", "claude-insights"))
'
```

Parse each output line as KEY=VALUE, splitting on the first `=`.

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

- **With argument** (e.g. `/compress rate limiting strategy`): Go to Step 3.5.
- **Without argument** (bare `/compress`): Go to Step 4B.

### Step 3.5 — Search for existing notes on this topic

Run a single Python call to search the vault index for existing notes matching the topic:

~~~bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, json
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from vault_index import ensure_index, search_vault
from obsidian_utils import load_config
try:
    c = load_config()
    vp = c["vault_path"]
    folders = [c.get("sessions_folder", "claude-sessions"), c.get("insights_folder", "claude-insights")]
    db = ensure_index(vp, folders)
    results = search_vault(db, sys.argv[1], note_type="claude-insight", limit=3)
    results += search_vault(db, sys.argv[1], note_type="claude-decision", limit=3)
    # Sort combined results by rank (most negative = best match)
    results.sort(key=lambda r: r["rank"])
    # Apply high-confidence threshold: top result must have rank <= -5.0
    # AND must be significantly ahead of #2 (at least 1.5x better rank)
    if results:
        top = results[0]
        rank_gap_ok = len(results) < 2 or abs(top["rank"]) > abs(results[1]["rank"]) * 1.5
        if top["rank"] <= -5.0 and rank_gap_ok:
            print(json.dumps({"match": True, "path": top["path"], "title": top["title"], "date": top["date"], "tags": top["tags"], "rank": top["rank"]}))
        else:
            print(json.dumps({"match": False}))
    else:
        print(json.dumps({"match": False}))
except Exception as e:
    print(f"Warning: could not search vault index: {e}", file=sys.stderr)
    print(json.dumps({"match": False}))
' "$TOPIC"
~~~

Parse the JSON output. If the script exits non-zero or the output cannot be parsed as JSON, treat it as `{"match": false}` and proceed silently (log a note: "Could not search vault index; creating new note.").

If `match` is `true`, store the `path` field as `MATCH_PATH` and the `title` field as `MATCH_TITLE`. Format `tags` by splitting on commas and joining with `, `. If `tags` is empty or null, display "no tags".

**If `match` is `false`:** No existing note found. Proceed silently to Step 4A (create new note).

**If `match` is `true`:** Present the match to the user:

> Found an existing note on this topic:
> **"<title>"** (<date>, <tags as comma-separated list>)
>
> Would you like to **update** this note or **create new**?

Wait for the user's response:
- **"update"** → Go to Step 4A-update.
- **"create new"** → Go to Step 4A (create new note as before).

### Step 4A — Single-topic extraction

Analyze the current conversation for content related to the user's specified topic. Draft a note that includes:

- **Summary:** 2-4 sentence overview of the topic as discussed in this session
- **Details:** Key points, code snippets, configurations, or commands relevant to the topic
- **Context:** Why this came up, what problem it solved, any trade-offs discussed

Skip to Step 5.

### Step 4A-update — Append to existing note

This step is reached when the user chose "update" in Step 3.5. The matched note path is `$MATCH_PATH`.

#### 4A-update.1 — Read the existing note

Use the Read tool to read the full contents of `$MATCH_PATH`. Note the existing frontmatter tags and whether a `last_updated` field is already present.

#### 4A-update.2 — Draft the update section

Analyze the current conversation for content related to the topic. Draft a dated update section:

~~~markdown
## Update (YYYY-MM-DD)

<New content about this topic from today's session. Include:
- New findings, corrections, or extensions to the original insight
- Code snippets or commands if relevant
- Context on why this update was triggered>
~~~

Where `YYYY-MM-DD` is today's date.

**Important:** Do NOT rewrite or duplicate existing content. The update section captures only what is NEW from this session.

#### 4A-update.3 — Show preview and ask for edits

Present ONLY the new update section (not the full existing note):

> **Update section to append to "< existing note title>":**
>
> (show the drafted `## Update (YYYY-MM-DD)` section)
>
> Preview above. Would you like to:
> - **save** — append this update
> - **edit content** — tell me what to change
> - **cancel** — discard this update

Wait for the user's response. Apply edits and re-show if requested. Repeat until the user says **save** or **cancel**.

If **cancel**, stop here.

#### 4A-update.4 — Append the update section

Use the Edit tool to append the update section to the note body.

**Insertion point:** Scan the note from the bottom for these trailing metadata patterns: `_(Summary source: ...)_`, `## Tool Usage`, `## Conversation (raw)`, `## Session Metadata`, `## Files Touched`. If any are found, insert the update section on a new line immediately BEFORE the first trailing section. If none are found, append at the very end of the file.

Use the Edit tool with the first line of the trailing section (or the last line of the file) as `old_string`, and prepend the update section + a blank line before it.

**Verify:** After the Edit, use the Read tool to confirm the `## Update (YYYY-MM-DD)` heading is present in the note. If it is not, tell the user: "Failed to append update section — file may have unexpected structure. Please edit manually at `$MATCH_PATH`." Do NOT proceed to 4A-update.5 if the append failed.

#### 4A-update.5 — Update frontmatter

Use the Edit tool to update the frontmatter of the existing note:

1. **`last_updated` field:** If `last_updated:` already exists in the frontmatter, replace its value with today's date. If it does not exist, add `last_updated: YYYY-MM-DD` after the `date:` line.

2. **New topic tags:** Generate 1-3 topic tags from the update content (same logic as Step 5). For each new tag, check if it already exists in the `tags:` list. Only append tags that are NOT already present. Add new tags at the end of the tags list, before the closing `---`.

**Do NOT change:** `date`, `source_session`, `source_session_note`, or `type` fields. These record the original creation context.

#### 4A-update.6 — Re-sync vault index

Run:

~~~bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from vault_index import ensure_index
from obsidian_utils import load_config
c = load_config()
vp = c["vault_path"]
folders = [c.get("sessions_folder", "claude-sessions"), c.get("insights_folder", "claude-insights")]
try:
    ensure_index(vp, folders)
    print("OK")
except Exception as e:
    print(f"WARN: re-sync failed (non-fatal): {e}")
'
~~~

#### 4A-update.7 — Confirm

Print:

> **Note updated!**
> - File: `$MATCH_PATH`
> - Added section: "Update (YYYY-MM-DD)"
> - New tags: `<list of newly added tags>` (or "none")

Skip to Step 10 (offer follow-up). Do NOT proceed through Steps 5-9 (those are the create-new flow).

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
  import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
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

> Anything else to capture from this session? You can run `/compress` again or `/compress <topic>` to extract a specific topic (will offer to update if an existing note matches).
