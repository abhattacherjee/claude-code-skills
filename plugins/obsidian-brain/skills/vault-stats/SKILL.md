---
name: vault-stats
description: "Vault health diagnostics and usage analytics — signal coverage, access patterns, importance distribution, top accessed notes. Saves report to vault for trend tracking. Use when: (1) /vault-stats command, (2) user wants to check vault health, (3) user wants to see access patterns or signal effectiveness."
metadata:
  version: 1.0.0
---

# Vault Stats — Health Diagnostics & Usage Analytics

Shows vault-wide health metrics and current project usage analytics, then saves the report as a vault note for trend tracking.

**Tools needed:** Bash, Write

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Load config, derive project, compute stats

Run a single call that loads config, derives the project name, and computes all stats:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, json
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
from vault_index import ensure_index
from vault_stats import compute_stats
c = load_config()
if not c.get("vault_path"):
    print("ERROR=vault_path not configured. Run /obsidian-setup first.")
    sys.exit(0)
vp = c["vault_path"]
folders = [c.get("sessions_folder", "claude-sessions"), c.get("insights_folder", "claude-insights")]
db = ensure_index(vp, folders)
project = os.path.basename(os.getcwd()).lower().replace(" ", "-")
result = compute_stats(db, project)
print("VAULT=" + vp)
print("INS=" + c.get("insights_folder", "claude-insights"))
print("PROJECT=" + project)
print("STATS_JSON=" + result)
'
```

Parse each output line as KEY=VALUE, splitting on the first `=`.

If an `ERROR` key is present, display its value and stop.

If `STATS_JSON` contains `"error"`, display the error message and stop.

Parse `STATS_JSON` as JSON into a variable `STATS`.

### Step 2 — Check for empty/missing data

If `STATS.vault_wide.total_notes == 0`:

> No notes indexed. Run `/vault-reindex` first.

Stop here.

If `STATS.vault_wide.access_log_entries == 0`, note this for later — display the stats tables normally but append a note at the end.

### Step 3 — Format and display

Format the JSON into markdown tables and display to the user. Use this structure:

**Vault-wide section:**

```
## Vault Health

| Metric | Value |
|---|---|
| Total notes | <total_notes> |
| DB size | <db_size_bytes formatted: >= 1048576 → "X.X MB", >= 1024 → "X.X KB", else "N bytes"> |
| access_log entries | <access_log_entries with commas> |
| Oldest access | <oldest_access or "None yet"> |

## Signal Coverage

| Signal | Coverage | Notes |
|---|---|---|
| Activation (access history) | <pct>% (<has_activation>/<total_notes>) | <total_notes - has_activation> notes never accessed |
| Importance (non-default) | <pct>% (<has_importance>/<total_notes>) | <total_notes - has_importance> notes at default 5 |
| Both signals active | <pct>% (<has_both>/<total_notes>) | Full 7-signal scoring |
| Neither signal | <pct>% (<has_neither>/<total_notes>) | Using 5-signal fallback |

## Access Patterns (last 30 days)

| Context | Count | % |
|---|---|---|
| <for each entry in access_by_context, sorted by count desc> |

## Top 10 Most Accessed Notes

| # | Note | Accesses | Activation | Importance |
|---|---|---|---|---|
| <for each entry in top_accessed, numbered 1-N> |

## Importance Distribution

| Score | Count |
|---|---|
| 1-3 (trivial) | <trivial> |
| 4-6 (standard) | <standard> |
| 7-8 (significant) | <significant> |
| 9-10 (critical) | <critical> |
```

**Project section:**

```
---

## Project: <project.name>

| Metric | Value |
|---|---|
| Notes | <total_notes> |
| Access events | <access_events> |
| Avg accesses/note | <avg_accesses> |
| Notes with activation | <notes_with_activation> (<pct>%) |
| Notes with importance != 5 | <notes_with_importance> (<pct>%) |

## Recent Activity (last 7 days)

| Context | Count |
|---|---|
| <for each entry in recent_activity, sorted by count desc> |

## Top 5 Most Accessed (this project)

| # | Note | Accesses | Activation | Importance |
|---|---|---|---|---|
| <for each entry in project.top_accessed, numbered 1-N> |
```

Compute percentages: `round(count / denominator * 100)` — show as integer with `%`. For any percentage, if the denominator is 0, show `0%`. This applies to all tables (signal coverage uses total_notes, access patterns uses sum of counts).

Format large numbers with commas (e.g. `1,832`).

If `access_log_entries == 0`, append after the tables:

> Access tracking is active. Run `/vault-search` and `/recall` to start building history.

### Step 4 — Save vault note

Generate filename:
1. Date: today's date `YYYY-MM-DD`
2. Hash: 4-character hex from `date +%s | md5 | cut -c29-32` (macOS) or `date +%s | md5sum | cut -c1-4` (Linux). Do NOT use `tail -c 4`.
3. Filename: `YYYY-MM-DD-vault-stats-<hash>.md`

Compose the full note: frontmatter + the markdown output from Step 3.

Frontmatter:

```yaml
---
type: claude-stats
date: YYYY-MM-DD
project: <PROJECT>
tags:
  - claude/stats
  - claude/project/<PROJECT>
---
```

Use the **Write** tool to save to `$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-vault-stats-<hash>.md`.

Then set permissions:

```bash
chmod 600 "$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-vault-stats-<hash>.md"
```

### Step 5 — Confirm

Print:

> Stats saved to `<full path>`. View in Obsidian to track trends over time.
