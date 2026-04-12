---
name: vault-reindex
description: Rebuild the SQLite FTS5 vault index from scratch. Use when the index is stale, corrupt, or after bulk edits in Obsidian.
metadata:
  version: 1.0.0
---

# Vault Reindex — Rebuild FTS5 Index

Rebuilds the vault index from scratch by scanning all vault markdown files. Drops the existing database and re-indexes every note in the configured sessions and insights folders.

**Tools needed:** Bash

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Load config

Run:

```bash
python3 -c '
import sys, os, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
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

If config is missing or the command fails, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your vault path.

Stop here if config is missing.

### Step 2 — Rebuild

Run, passing the config values as command-line arguments (never interpolate into Python source):

```bash
python3 -c '
import sys, os, glob, time, json
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from vault_index import rebuild_index
t0 = time.time()
stats = rebuild_index(sys.argv[1], [sys.argv[2], sys.argv[3]])
stats["elapsed"] = round(time.time() - t0, 1)
print(json.dumps(stats))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$INSIGHTS_FOLDER"
```

If the command fails (non-zero exit or exception in output), tell the user:

> Index rebuild failed. Check that the vault path is accessible and that the plugin is installed. Error: `<stderr>`

Stop here on failure.

### Step 3 — Report

Parse the JSON output from Step 2. Extract:

- `inserted` — total notes indexed
- `skipped` — files without valid frontmatter
- `elapsed` — time in seconds
- `by_type` — dict mapping note type to count (e.g. `{"claude-session": 42, "claude-insight": 7}`)

Present this report:

> **Rebuilt vault index:** `<inserted>` notes indexed in `<elapsed>`s
>
> | Type | Count |
> |------|-------|
> | claude-session | `<count>` |
> | claude-insight | `<count>` |
> | ... | ... |
>
> Skipped: `<skipped>` file(s) without frontmatter.

Only include rows in the table for types that appear in `by_type` (omit zero-count types). Sort rows by count descending.

If `inserted` is 0 and `skipped` is 0, also tell the user:

> No notes found. Verify that `<VAULT>/<SESS>` and `<VAULT>/<INS>` exist and contain markdown files.
