---
name: vault-reindex
description: Rebuild the SQLite FTS5 vault index. Non-destructive by default — preserves Friston activation data (access_log, themes, theme_members); only regenerates derivable tables. Opt into `--full` for a complete wipe.
metadata:
  version: 2.0.0
---

# Vault Reindex — Rebuild FTS5 Index

Regenerates the `notes` and `notes_fts` tables from on-disk state. Use when the index is stale, corrupt, after bulk edits in Obsidian, or to purge leftover rows from pytest fixtures.

**Tools needed:** Bash

## Modes

- **Default (`/vault-reindex`)** — non-destructive. Reconciles the note index with current vault contents via an mtime-incremental sync: newly added notes get indexed, notes deleted from disk are removed, rows with paths outside the current scanned folders (pytest pollution, stale mounts) are cleaned up. **Preserves** `access_log` (ACT-R activation history), `themes`, and `theme_members` (cluster centroids + surprise scores). Orphaned rows whose note paths are no longer in scope are pruned. **Does not** re-tokenise unchanged notes or rebuild FTS/term_df for them — if an existing row is internally corrupted but its on-disk mtime hasn't changed, only `--full` will fix it.
- **`/vault-reindex --full`** — destructive. Deletes the entire `~/.claude/obsidian-brain-vault.db` file and rebuilds from an empty schema. Every Friston field is lost. Required when the schema is corrupt/incompatible or when derivable tables need a clean-slate rebuild.

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Parse arguments and load config

If the user passes `--full`, set `FULL_MODE=true`; otherwise `FULL_MODE=false`.

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

### Step 2 — Confirm full mode (only if `--full`)

If `FULL_MODE=true`, warn the user before proceeding:

> ⚠️ **Full rebuild requested.** This will **delete** `access_log`, `themes`, and `theme_members` (activation history, cluster centroids, surprise scores). These tables do not regenerate automatically — activation signal accumulates over time as you run `/recall`, `/vault-search`, and `/vault-ask`. Themes will be empty until `/consolidate` ships.
>
> Continue? Reply `yes` to confirm, anything else to cancel.

Wait for confirmation. Abort if the user does not reply `yes`. If cancelled, tell them they can run the default `/vault-reindex` (without `--full`) for a non-destructive rebuild.

### Step 3 — Rebuild

Run, passing the config values and `FULL_MODE` as command-line arguments:

```bash
python3 -c '
import sys, os, glob, time, json
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from vault_index import rebuild_index
t0 = time.time()
full = sys.argv[4].lower() == "true"
stats = rebuild_index(sys.argv[1], [sys.argv[2], sys.argv[3]], full=full)
stats["elapsed"] = round(time.time() - t0, 1)
# Derive mode from the returned stats, not the CLI flag — rebuild_index()
# can fall through to a full rebuild internally (missing DB, legacy schema)
# even when the caller asked for preserve mode. Presence of "preserved"
# in the stats dict is the single source of truth.
stats["mode"] = "preserve" if "preserved" in stats else "full"
print(json.dumps(stats))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$INSIGHTS_FOLDER" "$FULL_MODE"
```

If the command fails (non-zero exit or exception in output), tell the user:

> Index rebuild failed. Check that the vault path is accessible and that the plugin is installed. Error: `<stderr>`

Stop here on failure.

### Step 4 — Report

Parse the JSON output from Step 3. Extract:

- `inserted` — total notes indexed
- `skipped` — files without valid frontmatter
- `elapsed` — time in seconds
- `by_type` — dict mapping note type to count
- `mode` — `"preserve"` or `"full"`
- `preserved` — dict with `access_log`, `themes`, `theme_members` counts (non-destructive mode only)
- `pruned_orphans` — dict with `access_log`, `theme_members` pruned counts (non-destructive mode only)

Present this report:

> **Rebuilt vault index** (`<mode>` mode): `<inserted>` notes indexed in `<elapsed>`s
>
> | Type | Count |
> |------|-------|
> | claude-session | `<count>` |
> | claude-insight | `<count>` |
> | ... | ... |
>
> Skipped: `<skipped>` file(s) without frontmatter.

Only include rows in the table for types that appear in `by_type` (omit zero-count types). Sort rows by count descending.

**Additional section — non-destructive mode only:**

> **Friston data preserved:**
> - `access_log`: `<access_log>` activation event(s)
> - `themes`: `<themes>` cluster(s)
> - `theme_members`: `<theme_members>` assignment(s)
>
> Pruned `<pruned_access_log>` orphaned access-log row(s) and `<pruned_theme_members>` orphaned theme-member row(s) referencing notes no longer in the current index scope (either deleted from disk or outside the scanned folders).

If both pruned counts are 0, replace the pruning line with `No orphan rows to prune.`.

**Additional section — full mode only:**

> ⚠️ **Friston data cleared:** `access_log`, `themes`, and `theme_members` are now empty. Activation signal will rebuild as you use the vault.

If `inserted` is 0 and `skipped` is 0, also tell the user:

> No notes found. Verify that `<VAULT>/<SESS>` and `<VAULT>/<INS>` exist and contain markdown files.
