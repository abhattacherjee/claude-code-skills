---
name: vault-import
description: "Backfills the Obsidian vault with historical Claude Code sessions using conversation search and parallel sub-agents. Use when: (1) /vault-import command to import recent sessions, (2) /vault-import 30d to import last 30 days, (3) /vault-import project:api-service 30d to filter by project, (4) user wants to populate vault with past session history."
metadata:
  version: 1.0.0
---

# Vault Import — Backfill Historical Sessions

Discover historical Claude Code sessions, summarize them via parallel sub-agents, and write structured session notes to the Obsidian vault. Skips sessions already present in the vault.

**Tools needed:** Bash, Write, Read, Skill (for /context-shield sub-agents)

**Prerequisites:**
- `/conversation-search` skill must be installed
- `/context-shield` skill must be installed
- Obsidian Brain must be configured (run `/obsidian-setup` if not)

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

If the command exits non-zero or prints ERROR, tell the user:

> Config not found. Please run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

Store the extracted values as `VAULT_PATH` and `SESSIONS_FOLDER` (default `claude-sessions`).

### Step 2 — Validate vault access

Run:

```bash
test -d "$VAULT_PATH/$SESSIONS_FOLDER" && test -w "$VAULT_PATH/$SESSIONS_FOLDER" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user:

> The sessions folder `$VAULT_PATH/$SESSIONS_FOLDER` does not exist or is not writable. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 3 — Parse arguments

Parse the user's invocation to extract:

- **Time range:** A duration like `7d`, `14d`, `30d`. Default is `7d` if not specified.
- **Project filter:** An optional `project:<name>` argument (e.g. `project:api-service`).

Examples:
- `/vault-import` — last 7 days, all projects
- `/vault-import 30d` — last 30 days, all projects
- `/vault-import project:api-service 14d` — last 14 days, only api-service
- `/vault-import project:api-service` — last 7 days, only api-service

Store as `TIME_RANGE` and `PROJECT_FILTER` (empty string if no filter).

### Step 4 — Discover sessions

Use the `/conversation-search` skill's underlying search script to find sessions matching the time range and project filter.

Run:

```bash
bash ~/.claude/skills/conversation-search/scripts/search-conversations.sh --days <TIME_RANGE_NUMBER> --format jsonl
```

If a project filter is specified, add `--project <PROJECT_FILTER>` to the command.

If the script is not found, fall back to manually scanning `~/.claude/projects/` for session JSONL files modified within the time range:

```bash
find ~/.claude/projects/ -name "*.jsonl" -mtime -<TIME_RANGE_NUMBER> -type f 2>/dev/null
```

Parse the output to build a list of sessions. Each session needs:
- `session_id` — extracted from the filename or JSONL content
- `session_path` — absolute path to the JSONL file
- `project` — extracted from the directory path or JSONL content
- `date` — file modification date

If no sessions are found, tell the user:

> No sessions found in the last `<TIME_RANGE>` matching your filters.

Stop here if no sessions found.

### Step 5 — Filter already-imported sessions

Check the vault for existing session notes that match discovered session IDs.

Run:

```bash
grep -rl "session_id:" "$VAULT_PATH/$SESSIONS_FOLDER/" 2>/dev/null | xargs grep -l "<SESSION_ID>" 2>/dev/null
```

More efficiently, build a single grep command:

```bash
for f in "$VAULT_PATH/$SESSIONS_FOLDER/"*.md; do
  head -20 "$f" 2>/dev/null
done | grep "session_id:" | awk '{print $2}'
```

Collect all session IDs already in the vault into a set called `EXISTING_IDS`. Remove any session from the discovered list whose `session_id` is in `EXISTING_IDS`.

Store the remaining sessions as `PENDING_SESSIONS` and the count of skipped sessions as `SKIPPED_COUNT`.

If no pending sessions remain, tell the user:

> All `<TOTAL>` sessions from the last `<TIME_RANGE>` are already in the vault. Nothing to import.

Stop here if nothing to import.

Otherwise, report:

> Found `<TOTAL>` sessions, `<SKIPPED_COUNT>` already imported, `<PENDING_COUNT>` to import.

### Step 6 — Summarize sessions with parallel sub-agents

**This is the performance-critical step. Use parallel sub-agents to maximize throughput.**

For each session in `PENDING_SESSIONS`, delegate to a `/context-shield` sub-agent with this prompt:

> Read the Claude Code session transcript at `<SESSION_PATH>`. Extract and return a structured summary with these exact sections:
>
> - **Summary:** 2-3 sentence overview of what was accomplished
> - **Key Decisions:** Bulleted list of architectural or design choices made
> - **Changes Made:** Bulleted list of files created, modified, or deleted
> - **Errors Encountered:** Bulleted list of errors hit and how they were resolved (or "None")
> - **Next Steps:** Bulleted list of follow-up tasks mentioned (or "None")
> - **Git Info:** Branch name, commit hashes if any (or "None")
>
> Keep the total output under 300 tokens. Return only the structured summary, no preamble.

**Parallelism rules:**
- Launch up to 5 sub-agents in parallel (sessions are independent — no shared state)
- Wait for the batch to complete before launching the next batch
- If a sub-agent fails or times out, log the error and skip that session — do not block the entire import

Collect the distilled summaries. Store each as `SUMMARY` keyed by `session_id`.

### Step 7 — Construct and write session notes

For each successfully summarized session, construct a vault note with this format:

```markdown
---
type: claude-session
date: <YYYY-MM-DD from session date>
session_id: <session_id>
project: <project name>
git_branch: <branch from git info, or empty>
duration_minutes: <estimated from transcript length, or empty>
imported: true
imported_date: <today's date YYYY-MM-DD>
tags:
  - claude/session
  - claude/project/<project-name>
  - claude/imported
---

# <Session Title derived from summary>

<Summary section>

## Key Decisions

<Key decisions bulleted list>

## Changes Made

<Changes bulleted list>

## Errors Encountered

<Errors bulleted list>

## Next Steps

<Next steps bulleted list>

## Git Info

<Git info>
```

Generate the filename using the same convention as other session notes:

1. **Date:** `YYYY-MM-DD` (session date)
2. **Slug:** Title lowercased, spaces to hyphens, non-alphanumeric (except hyphens) removed, truncated to 50 chars
3. **Hash:** 4-character hex hash from the session_id: `echo -n "<session_id>" | md5 | cut -c1-4` (macOS) or `echo -n "<session_id>" | md5sum | cut -c1-4` (Linux). Do NOT use `tail -c 4` — it counts the trailing newline as a byte and returns only 3 visible characters.

Final filename: `YYYY-MM-DD-<slug>-<hash>.md`

Write each note:

```bash
mkdir -p "$VAULT_PATH/$SESSIONS_FOLDER"
```

Use the **Write** tool to write the file, then:

```bash
chmod 644 "$VAULT_PATH/$SESSIONS_FOLDER/<filename>"
```

### Step 8 — Report results

Print a summary report:

> **Vault import complete!**
>
> - **Imported:** `<IMPORTED_COUNT>` sessions
> - **Skipped (already in vault):** `<SKIPPED_COUNT>` sessions
> - **Failed:** `<FAILED_COUNT>` sessions (if any)
> - **Time range:** last `<TIME_RANGE>`
> - **Project filter:** `<PROJECT_FILTER>` (or "all projects")
>
> New notes written to: `$VAULT_PATH/$SESSIONS_FOLDER/`

If any sessions failed, list them:

> **Failed sessions:**
> - `<session_id>`: `<error reason>`

Offer follow-up:

> Run `/vault-import <longer range>` to go further back, or open Obsidian to browse the imported sessions.
