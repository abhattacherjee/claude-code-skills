---
name: check-items
description: "Cross-project sweep to detect and check off completed open items in the Obsidian vault. Scans all session notes for unchecked `- [ ]` items, gathers evidence from recent sessions per project, proposes matches, and flips confirmed items to `- [x]`. Use when: (1) /check-items command, (2) /check-items <Nd> for custom scan window (default 14 days), (3) cleaning up the open-items dashboard."
metadata:
  version: 1.0.0
---

# Check Items — Cross-Project Open Item Sweep

Scans all session notes across all projects for unchecked `- [ ]` items in `## Open Questions / Next Steps` sections, gathers evidence from recent sessions per project, proposes completed items, and flips them to `- [x]` after user confirmation.

**Tools needed:** Bash, Grep, Read, Edit

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Load config

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

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

### Step 2 — Validate vault access

Run:

```bash
test -d "$VAULT_PATH/$SESSIONS_FOLDER" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user:

> The sessions folder `$VAULT_PATH/$SESSIONS_FOLDER` does not exist. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 3 — Parse scan window argument

Inspect the argument passed after `/check-items`. Default is `14d` (14 days).

- `/check-items` → `SCAN_DAYS=14`
- `/check-items 30d` → `SCAN_DAYS=30`
- `/check-items 7d` → `SCAN_DAYS=7`

If the argument is not in `Nd` format, tell the user the format and use the default.

Compute the cutoff date:

```bash
SCAN_CUTOFF=$(date -v-${SCAN_DAYS}d +%Y-%m-%d 2>/dev/null || date -d "-${SCAN_DAYS} days" +%Y-%m-%d)
```

(The first form is macOS, the fallback is Linux.)

### Step 4 — Collect all open items

Use Grep:

```
pattern: ^- \[ \] 
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: content
-n: true
```

For each match line, extract the file path. To verify the match is under `## Open Questions / Next Steps` (not some other section), use Grep on the same file:

```
pattern: ## Open Questions
path: <each matched file>
output_mode: content
-n: true
```

For each open item match, check that the line number of the `- [ ]` match is greater than the most recent `## Open Questions / Next Steps` line number AND less than the next `## ` heading (if any). Items not in the right section are discarded.

For each valid item, extract:
- `file_path` (absolute path)
- `line_number` (where the `- [ ]` appears)
- `item_text` (the text after `- [ ] `)
- `project` (from the file's frontmatter `project:` field — read first 20 lines and grep for `^project:`)

Build a map: `{project → [(file_path, line_number, item_text)]}`.

**Note:** For project-scoped collection (e.g. during cascade in Step 12.5), the Python helper `collect_open_items()` from `open_item_dedup` does single-pass extraction per file. It requires a `project` argument, so it's used per-project in the cascade step, not for the cross-project sweep in this step.

### Step 5 — Skip if zero items

If the map is empty:

```
No open items found across all projects.
```

Stop here.

### Step 6 — Determine evidence pool per project

For each project in the map, find the most recent 3 session notes within the scan window. Use Grep to find files matching `project: $PROJECT_NAME`, then filter to those with a date in the frontmatter `>= $SCAN_CUTOFF`. Sort by date descending, take the top 3.

If a project has zero sessions in the scan window, skip its open items (no evidence to match against).

### Step 7 — Read evidence per project

For each project's evidence sessions, use Read to load the file. Extract the `## Summary`, `## Changes Made`, and `## Errors Encountered` sections. Concatenate as `EVIDENCE_TEXT_<project>`.

### Step 8 — Match items to evidence per project

For each open item in a project, run the same matching logic as `/recall` Step 7.5:

- **Tokenize** the item text into words, lowercase, drop common stopwords (`the`, `a`, `an`, `to`, `for`, `in`, `on`, `of`, `and`, `or`, `but`, `is`, `are`, `was`, `were`, `be`).
- **Substring match:** Count tokens (3+ chars) appearing as substrings in the project's evidence text (lowercased). If count >= 3, candidate.
- **Distinctive token match:** If the item contains a file path (`/` or `.py`/`.md`/`.json`/`.ts`/`.js`/`.tsx`/`.jsx`), PR/issue ref (`#\d+`, `PR \d+`, `issue \d+`), branch name (`feature/`, `release/`, `hotfix/`), or version (`v?\d+\.\d+\.\d+`), and that token appears in evidence, mark as candidate even if substring count < 3.
- **Completion phrase boost:** If a completion phrase (`merged`, `shipped`, `fixed`, `released`, `closed`, `removed`, `implemented`, `deleted`, `done`, `completed`) appears within 100 characters on either side (200 chars total window) of any matched token in evidence, increase confidence.

For each candidate, capture a short evidence snippet (the matching sentence or 60-char window around the match).

### Step 9 — Skip if no candidates

If no candidates across all projects:

```
Scanned <N> open items across <M> projects. No completion candidates found.
```

Stop here.

### Step 10 — Present candidates grouped by project

Print:

```
## obsidian-brain (3 candidates)
1. [x] Merge feature/standup-highlights branch
     Evidence: "Merged as PR #10"
2. [x] Python 3.9 compat fix
     Evidence: "Released in v1.5.2"
3. [x] SessionEnd hook fix
     Evidence: "Released in v1.5.2"

## tiny-vacation-agent (1 candidate)
4. [x] Add rate limiting to /chat endpoint
     Evidence: "Added express-rate-limit middleware"

Confirm checkoffs? (e.g. `1,3,4` or `all` or `none`)
```

Number candidates sequentially across all projects (not per-project) so the user can pick by single number list.

### Step 11 — Wait for user response

Parse the response:
- `none` or empty → stop, no edits
- `all` → check off every candidate
- Comma-separated numbers (e.g. `1,3,4`) → check off only those

### Step 12 — Edit source files for confirmed checkoffs

For each confirmed item, use the Edit tool:

- `file_path`: the source session note path
- `old_string`: `- [ ] <exact item text>`
- `new_string`: `- [x] <exact item text>`
- `replace_all`: false

If the Edit fails because the line is not unique, retry with more context (include the line before and after the target line). If still ambiguous, skip and warn:

```
⚠️  Could not check off "<item text>" in <basename> — line not unique. Edit manually in Obsidian.
```

### Step 12.5 — Cascade check-offs to duplicate items

For each project that had confirmed checkoffs, run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, json
sys.path.insert(0, "hooks")
from open_item_dedup import batch_cascade_checkoff
items = json.loads(sys.argv[4])
summary = batch_cascade_checkoff(sys.argv[1], sys.argv[2], sys.argv[3], items)
print(summary)
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT_NAME" "$CHECKED_ITEMS_JSON"
```

Before running, construct `$CHECKED_ITEMS_JSON` as a JSON array of confirmed item texts for that project from Step 11:
```bash
CHECKED_ITEMS_JSON=$(python3 -c "import json; print(json.dumps([\"Fix bug #42\", \"Land PR #14\"]))")
```
Replace the example items with the actual confirmed texts. Include the cascade summary in the Step 13 report.

### Step 13 — Report

Print:

```
✅ Checked off <N> item(s) across <M> project(s).

Closed:
- **<project A>**: <count> items
- **<project B>**: <count> items

<X> items remain open in the dashboard. View open-items.md in Obsidian for the live list. (Note: the dashboard shows items from the last 90 days only; `/check-items` is unbounded, so checkoffs you just made for items older than 90 days won't appear in the dashboard delta.)
```

### Step 14 — Edge cases

- **Skipped items due to ambiguity:** Report at the bottom of the output. Don't fail the whole skill.
- **File modification race:** If a file changed between Read and Edit, the Edit will fail with a "modified since read" error. Re-run `/check-items` — the next pass will pick up the latest state.
- **Items with markdown formatting:** If `item_text` contains backticks, asterisks, or other markdown, preserve them exactly in the Edit `old_string` and `new_string`.
- **Items spanning multiple lines:** Only the first line is matched (multi-line list items are uncommon in this codebase). If encountered, skip and warn.
