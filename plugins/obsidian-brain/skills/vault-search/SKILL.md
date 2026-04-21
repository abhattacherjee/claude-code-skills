---
name: vault-search
description: "Searches the Obsidian vault by keyword, tag, or structured query across session and insight notes. Use when: (1) /vault-search command, (2) user asks to find past notes, decisions, or error fixes, (3) user wants to recall something from their vault."
metadata:
  version: 1.0.0
---

# Vault Search

Search the entire Obsidian vault by keyword, tag, or structured field query. Returns ranked results with snippets from both `claude-sessions/` and `claude-insights/` folders.

**Tools needed:** Grep, Read, Bash

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Load config

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

If the file does not exist, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your vault path.

Stop here if config is missing.

Construct the two search directories:

- `SESSIONS_DIR` = `<vault_path>/<sessions_folder>`
- `INSIGHTS_DIR` = `<vault_path>/<insights_folder>`

### Step 2 — Parse the query

The user provides a query after `/vault-search`. Determine the search mode:

**Tag mode** — query starts with `#` (e.g. `#claude/topic/auth`):
- Strip the leading `#`
- The search target is frontmatter `tags` fields
- Pattern: the tag string as a literal grep pattern
- Search only within the first 30 lines of each file (frontmatter region)

**Structured mode** — query contains `key:value` pairs (e.g. `project:api-service type:decision`):
- Parse each `key:value` pair
- Each pair maps to a frontmatter field grep: pattern `^key:.*value` (case-insensitive)
- All pairs must match in the same file (intersection)

**Keyword mode** — everything else (e.g. `jwt refresh`):
- Treat the entire query as a content search
- Grep for the full phrase first; if zero results, grep for each word individually and intersect

### Step 3 — Try FTS search (fast path)

Before falling back to Grep, try the vault index:

```bash
python3 -c '
import sys, os, json, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
from vault_index import ensure_index, search_vault
c = load_config()
db = ensure_index(c["vault_path"], [c.get("sessions_folder", "claude-sessions"), c.get("insights_folder", "claude-insights")])
results = search_vault(
    db,
    sys.argv[1],
    project=sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "None" else None,
    limit=20,
)
print(json.dumps(results))
' "$QUERY" "$PROJECT"
```

If the output is a non-empty JSON array: parse and present results (path, title, type, date, excerpt) using the format in Step 6. Skip Steps 4 and 5 below.

If the output is `[]` or the command fails: print a note that the vault index returned no results, then fall through to Step 4. If the command failed because the DB does not exist, also suggest running `/vault-reindex` to build the index.

### Step 4 — Search both folders in parallel

Use the Grep tool (never Bash grep) for all searching. Launch searches across both `SESSIONS_DIR` and `INSIGHTS_DIR` in parallel.

**For tag mode:**
Run two parallel Grep calls:
- `Grep(pattern="<tag>", path=SESSIONS_DIR, glob="*.md", output_mode="files_with_matches")`
- `Grep(pattern="<tag>", path=INSIGHTS_DIR, glob="*.md", output_mode="files_with_matches")`

**For structured mode:**
For each `key:value` pair, run two parallel Grep calls (one per folder):
- `Grep(pattern="^<key>:.*<value>", path=<folder>, glob="*.md", output_mode="files_with_matches", -i=true)`

Then intersect results across all pairs — only files matching every pair are kept.

**For keyword mode:**
Run two parallel Grep calls:
- `Grep(pattern="<query>", path=SESSIONS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)`
- `Grep(pattern="<query>", path=INSIGHTS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)`

If zero results and query has multiple words, retry by grepping each word separately and intersecting the file lists.

### Step 5 — Extract metadata from matches

For each matched file (up to 20 files), use Read to read the first 40 lines. Extract from frontmatter:

- **date** — the `date:` field
- **type** — the `type:` field (e.g. `claude-session`, `claude-insight`, `claude-decision`, `claude-error-fix`, `claude-snapshot`)
- **project** — the `project:` field
- **session_id** — the `session_id:` field (used below to attach snapshots to session hits)
- **source_session_note** — the `source_session_note:` wikilink on snapshots (the parent session stem, enclosed in `[[...]]`)
- **title** — the first `# ` heading, or the filename without extension

Also extract a **snippet**: the first 200 characters of content after the frontmatter closing `---`.

If there are more than 20 matched files, sort by filename (which contains the date in YYYY-MM-DD format) descending and take only the 20 most recent.

**Performance note:** If there are 10 or fewer matches, read all files in parallel. If there are 11-20, read in two parallel batches.

### Step 5b — Augment session hits with snapshot data

For each result whose `type` is `claude-session`, query its snapshots once via the shared Python helper `fetch_snapshot_summaries()`:

```bash
python3 -c '
import sys, os, json, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from pathlib import Path
from obsidian_utils import fetch_snapshot_summaries
snaps = fetch_snapshot_summaries(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4])
print(json.dumps([{"hhmmss": s["hhmmss"], "trigger": s["trigger"]} for s in snaps]))
' "$SESSIONS_DIR" "$SESSION_ID" "$DATE" "$PROJECT"
```

If the returned JSON array is non-empty, remember the snapshot count `N` and each snapshot's `hhmmss` + `trigger` for that result. If batching many sessions, run these queries in parallel (same pattern as Step 5's metadata reads).

For results whose `type` is `claude-snapshot`, remember the `source_session_note` wikilink stem (strip `[[...]]`) as the parent pointer.

### Step 6 — Sort and present results

Sort results by date descending (most recent first). Present in this format:

```
Found <N> notes matching "<query>":

1. <icon> <title> (<type-label>, <date>)
   "<snippet>..."

2. <icon> <title> (<type-label>, <date>)
   "<snippet>..."
```

Use these icons for type labels:
- `claude-session` → session
- `claude-insight` → insight
- `claude-decision` → decision
- `claude-error-fix` → error-fix
- `claude-snapshot` → snapshot
- anything else → note

Truncate snippets at 200 characters, ending with `...` if truncated.

**Snapshot markers on session hits:** If Step 5b found `N >= 1` snapshots for a session result, append `· 📸 N` to the type-label block — e.g. `(session · 📸 2, 2026-04-18)`. Under the snippet, list each snapshot as a nested bullet:

```
   ↳ 📸 <hhmmss> (<trigger>)
```

**Parent pointer on snapshot hits:** For a `claude-snapshot` result, append `→ [[<parent-stem>]]` after the date — e.g. `(snapshot, 2026-04-18 → [[2026-04-18-demo-aa]])`. Only include the marker when `source_session_note` is set.

After the list, tell the user:

> Pick a number to load the full note, or refine your search.

### Step 7 — Handle user selection

If the user picks a number, read the full content of that file using the Read tool and present it in the conversation.

**Session-depth loading applies to snapshot picks too.** If the user picks a snapshot result, load the parent session body AND all its snapshot summaries (re-use `fetch_snapshot_summaries()`), not just the snapshot file alone — so the answer reflects the full session arc, not the mid-session fragment. Resolve the parent via the `source_session_note` stem captured in Step 5.

If the user provides a new query, go back to Step 2.

