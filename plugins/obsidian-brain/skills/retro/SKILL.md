---
name: retro
description: "Generates honest session retrospectives analyzing what worked, what didn't, key learnings, and actionable process improvements. Use when: (1) /retro command at end of session, (2) user wants to reflect on session quality and outcomes."
metadata:
  version: 1.0.0
---

# Retro — Generate Honest Session Retrospective

Analyze the current conversation candidly and save a structured retrospective to the Obsidian vault. The goal is honest reflection — not self-congratulation — so future sessions can improve.

**Tools needed:** Bash, Write, Read

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
print("VAULT=" + c["vault_path"] + " SESS=" + c.get("sessions_folder", "claude-sessions") + " INS=" + c.get("insights_folder", "claude-insights"))
'
```

Parse the output line to extract `VAULT_PATH`, `SESSIONS_FOLDER`, and `INSIGHTS_FOLDER`.

If the file does not exist or is invalid JSON, tell the user:

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

### Step 3 — Analyze the session honestly

Review the full current conversation. Be **candid**, not defensive or self-congratulatory.

The **"What Didn't Work"** section is the MOST valuable part of this retrospective — invest the most analysis there.

Evaluate the session across these five dimensions:

1. **What approaches worked?** — Successful strategies, good tool choices, efficient workflows, moments where the approach was clearly right.
2. **What didn't work?** — Be specific: wrong assumptions that led to dead ends, approaches that were abandoned partway through, time wasted on the wrong path, tools that failed or were misused, misunderstandings of the user's intent, overcomplicated solutions when a simple one existed, factual errors or hallucinations Claude produced.
3. **What did the user correct or redirect?** — Any moment the user said "no, that's wrong" or steered the conversation back — these are especially valuable signals.
4. **Key learnings** — Non-obvious insights that would be genuinely useful in future sessions. Not generic advice; specific to what happened here.
5. **Process improvements** — Concrete and actionable changes. Not vague ("be more careful") but specific ("check existing tests before writing new ones", "ask for the schema before generating SQL").

### Step 4 — Structure the retrospective

Draft the note body using this exact structure:

```markdown
## What Went Well
- <specific thing that worked, with enough context to be meaningful>

## What Didn't Work
- <dead end: what was tried, why it failed, time impact>
- <wrong assumption: what was assumed, what was actually true>
- <user correction: what Claude did wrong, what user redirected to>

## Key Learnings
- <non-obvious insight with enough context to be useful later>

## Process Improvements
- [ ] <specific actionable change for future sessions>
```

**Important:** "What Didn't Work" should have MORE items than "What Went Well." If the session went smoothly with no obvious failures, still find at least one improvement opportunity — there is always something.

### Step 5 — Derive session ID and backlinks

Get session context via the shared helper:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config, get_session_context
c = load_config()
ctx = get_session_context(c["vault_path"], c.get("sessions_folder", "claude-sessions"))
print("SID=" + ctx["session_id"] + " HASH=" + ctx["hash"] + " PROJECT=" + ctx["project"] + " SESSION_NOTE=" + ctx["session_note_name"])
'
```

Parse the output to get `SESSION_ID`, `HASH`, `PROJECT`, and `SESSION_NOTE`.

**Important:** If `SESSION_ID` is `unknown`, use `unknown` for `source_session` and omit `source_session_note` entirely.

### Step 6 — Show preview and ask for edits

Present the full note to the user including frontmatter:

```
---
type: claude-retro
date: YYYY-MM-DD
source_session: <current-session-id>
source_session_note: "[[<session-note-filename>]]"
project: <project-name>
tags:
  - claude/retro
  - claude/project/<project-name>
---

# Session Retrospective: <project-name> (<date>)

## What Went Well
...

## What Didn't Work
...

## Key Learnings
...

## Process Improvements
...
```

Where:
- `YYYY-MM-DD` is today's date
- `<current-session-id>` and `<session-note-filename>` are derived from Step 5
- `<project-name>` is derived from the current working directory name (basename of the git repo root or cwd)
- The `source_session_note` field creates an Obsidian backlink from the retro to its source session

Ask the user:

> Preview above. Would you like to:
> - **save** as-is
> - **edit content** — tell me what to change
> - **cancel** — discard this note

Wait for the user's response. Apply any requested edits and show the updated preview. Repeat until the user says **save** or **cancel**.

If cancel, stop here.

### Step 7 — Generate filename and write

Construct the filename:

1. **Date:** `YYYY-MM-DD` (today)
2. **Slug:** `retro` (fixed — no title slug needed for retrospectives)
3. **Hash:** 4-character hex hash from current timestamp:
   - macOS: `date +%s | md5 | cut -c1-4`
   - Linux: `date +%s | md5sum | cut -c1-4`

Final filename: `YYYY-MM-DD-retro-<hash>.md`

Example: `2026-04-05-retro-a3f2.md`

Run:

```bash
mkdir -p "$VAULT_PATH/$INSIGHTS_FOLDER"
```

Then use the **Write** tool to write the full note (frontmatter + body) to:

```
$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-retro-<hash>.md
```

Then set permissions:

```bash
chmod 644 "$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-retro-<hash>.md"
```

### Step 8 — Confirm

Print:

> **Retrospective saved!**
> - File: `$VAULT_PATH/$INSIGHTS_FOLDER/<filename>`
> - Tags: `claude/retro`, `claude/project/<name>`
> - Open in Obsidian to review and track process improvements over time.
