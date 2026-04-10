---
name: recall
description: "Loads historical context from the Obsidian vault for the current project. Summarizes any unsummarized session notes, then presents a context brief with recent sessions, open items, and curated insights. Also auto-detects open items completed in the most recent loaded session and offers to check them off. Use when: (1) /recall command, (2) /recall <project-name>, (3) resuming work on a project and wanting prior context."
metadata:
  version: 1.4.0
---

# Recall — Load Project Context from Obsidian Vault

Searches the Obsidian vault for session notes and insights matching the current project, upgrades any unsummarized notes with AI summaries, and presents a concise context brief.

**Tools needed:** Bash, Grep, Read, Write

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Load config and derive project

Run a single call that loads config and derives the project name (saves one parent round):

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
sys.path.insert(0, "hooks")
from obsidian_utils import load_config
c = load_config()
if not c.get("vault_path"):
    print("ERROR: vault_path not configured", file=sys.stderr)
    sys.exit(1)
project = os.path.basename(os.getcwd()).lower().replace(" ", "-")
print("VAULT=" + c["vault_path"] + " SESS=" + c.get("sessions_folder", "claude-sessions") + " INS=" + c.get("insights_folder", "claude-insights") + " PROJECT=" + project)
'
```

Parse the output to extract `VAULT_PATH`, `SESSIONS_FOLDER`, `INSIGHTS_FOLDER`, and `PROJECT`.

If the user passed a project name argument (e.g. `/recall my-project`), override `PROJECT` with that value.

If the output is empty or errors, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

**Create the task manifest** for the full `/recall` flow:

```
TaskCreate: subject="Find unsummarized notes", activeForm="Searching for unsummarized notes"
TaskCreate: subject="Summarize unsummarized notes", activeForm="Summarizing notes"
TaskCreate: subject="Build context brief", activeForm="Building context brief"
TaskCreate: subject="Present results and detect completed items", activeForm="Presenting results"
```

Track the returned task IDs — you will update them as each step completes. Immediately set task #1 to `in_progress` via TaskUpdate.

### Step 2 — Summarize unsummarized notes (deferred summarization, truncation-aware)

> ⚠️ **THIS STEP IS MANDATORY. DO NOT SKIP IT.**
>
> If Grep finds any file matching both `status: auto-logged` AND `project: $PROJECT`, you **must** produce an upgraded summary for every such file before proceeding to Step 3. "Skipping to save context" or "the other session covers it" is a bug, not an optimization — the user ran `/recall` specifically to get current-session context, and stale unsummarized notes are exactly what they asked you to fix.
>
> **Visibility requirement:** Before Step 3, emit a one-line status: `Step 2: processing N unsummarized note(s) for $PROJECT` (or `Step 2: no unsummarized notes for $PROJECT` if the intersection is empty). This makes the decision auditable in the tool trace.

Find unsummarized notes for this project in a single Python call (replaces multiple Grep rounds):

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import find_unsummarized_notes
print(find_unsummarized_notes(sys.argv[1], sys.argv[2], sys.argv[3]))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT"
```

Parse the JSON output: `{"unsummarized": ["/path/to/note1.md", ...], "auto_fixed": N}`.

The function handles project filtering, defense-in-depth (skips notes with real `## Summary` but stale `auto-logged` status, auto-fixes them), and returns only genuinely unsummarized note paths.

If `auto_fixed > 0`, report: `Auto-fixed N note(s) with stale status.`

Store the length of `unsummarized` as `N`.

Update task #1 to completed. Update task #2 subject to `Summarize N unsummarized note(s)` and set to `in_progress`.

#### Path A: N=0 (no unsummarized notes)

Update task #2 subject to `No unsummarized notes found` and set to `completed`. Skip to Step 3.

#### Path B: N=1 (single note — Python pipeline)

Create a sub-task for the note:

```
TaskCreate: subject="Haiku pipeline: <basename>", activeForm="Summarizing <basename> via Haiku"
```

Run the upgrade pipeline in Python:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import upgrade_unsummarized_note
status = upgrade_unsummarized_note(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
print(status)
' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT"
```

If the status starts with "Failed:", use the sub-agent fallback:

1. Update the sub-task subject to `Sub-agent fallback: <basename>`.
2. Spawn a single sub-agent that writes its summary to a temp file:

   ```
   Agent({
     description: "Summarize session note <basename>",
     prompt: "Read the session note at <NOTE_PATH>. Produce a structured summary with these exact markdown sections:\n\n## Summary\n1-3 sentence overview of what was accomplished.\n\n## Key Decisions\n- Bullet list of important technical decisions. Write \"None noted.\" if none.\n\n## Changes Made\n- Bullet list of files modified/created with brief description. Write \"None noted.\" if none.\n\n## Errors Encountered\n- Bullet list of errors and how resolved. Write \"None.\" if none.\n\n## Open Questions / Next Steps\n- [ ] Checkbox list of unresolved items. Write \"None.\" if none.\n\nWrite the summary to /tmp/ob-summary-<basename>.md using the Write tool. Return ONLY the single line: WRITTEN:/tmp/ob-summary-<basename>.md"
   })
   ```

3. If the sub-agent returns `WRITTEN:<path>`, write back via Python reading the temp file:

   ```bash
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   python3 -c '
   import sys
   sys.path.insert(0, "hooks")
   from obsidian_utils import upgrade_note_with_summary
   with open(sys.argv[5], "r") as f:
       summary = f.read()
   status = upgrade_note_with_summary(sys.argv[1], summary, sys.argv[2], sys.argv[3], sys.argv[4])
   print(status)
   ' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" "/tmp/ob-summary-<basename>.md"
   ```

   Then clean up: `rm -f /tmp/ob-summary-<basename>.md`

Mark the sub-task and task #2 as completed. Report the result.

#### Path C: N>=2 (batch — sub-agent-first, three waves)

**Task management threshold:** If N <= 5, create per-note sub-tasks for each wave (prep, summarize, write-back). If N > 5, skip per-note sub-tasks — use a single progress update on task #2 per wave instead (e.g. `Summarize 10 notes: Wave 1 prep complete`). This saves ~15-20s of parent round-trip overhead at large N.

##### Wave 1 — Prep (parallel Bash calls)

If N <= 5, create a prep sub-task for each note:

```
TaskCreate: subject="Prep: <basename>", activeForm="Prepping <basename>"
```

For each unsummarized note, run a parallel Bash call:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import prepare_summary_input
result = prepare_summary_input(sys.argv[1])
print(result)
' "$NOTE_PATH"
```

Launch all N Bash calls in a single message turn so they run in parallel.

When all return:
- If N <= 5: update each prep sub-task to completed (include result in subject: e.g. `Prep: ...2322.md (RAW_OK)`).
- If N > 5: update task #2 subject to `Summarize N notes: Wave 1 prep complete`.

Parse each result:
- `RAW_OK:<note_path>` → sub-agent will read the raw note path
- `JSONL_PREPPED:<temp_path>:<note_path>` → sub-agent will read the temp file path; track `<note_path>` for Wave 3
- `NO_CONTENT:<note_path>` → skip this note, report to user

##### Wave 2 — Summarize and write to temp files (parallel sub-agents)

If N <= 5, create a summarize sub-task for each note (excluding NO_CONTENT):

```
TaskCreate: subject="Summarize: <basename>", activeForm="Summarizing <basename>"
```

Spawn all sub-agents in a **single message turn** so they run in parallel. Each sub-agent writes its summary to a temp file instead of returning it — this keeps summary text out of the parent context (~800 tokens saved per note):

```
Agent({
  description: "Summarize session note <basename>",
  prompt: "Read the file at <READ_PATH>. Produce a structured summary with these exact markdown sections:\n\n## Summary\n1-3 sentence overview of what was accomplished.\n\n## Key Decisions\n- Bullet list of important technical decisions. Write \"None noted.\" if none.\n\n## Changes Made\n- Bullet list of files modified/created with brief description. Write \"None noted.\" if none.\n\n## Errors Encountered\n- Bullet list of errors and how resolved. Write \"None.\" if none.\n\n## Open Questions / Next Steps\n- [ ] Checkbox list of unresolved items. Write \"None.\" if none.\n\nWrite the summary to the file /tmp/ob-summary-<basename>.md using the Write tool. Return ONLY the single line: WRITTEN:/tmp/ob-summary-<basename>.md"
})
```

Where `<READ_PATH>` is:
- For `RAW_OK` notes: the raw note path
- For `JSONL_PREPPED` notes: the temp file path (e.g. `/tmp/ob-prep-{session_id}.md`)

And `<basename>` is the note filename without extension (e.g. `2026-04-09-obsidian-brain-2322`).

When all sub-agents return, check each result:
- If the sub-agent returned `WRITTEN:<path>`, mark it as succeeded.
- If the sub-agent returned an error, empty output, or anything else, mark it as failed. Exclude this note from Wave 3 — it stays unsummarized for the next `/recall`. Report the failure to the user.

If N <= 5: update each summarize sub-task to completed (or `Failed: <basename>`).
If N > 5: update task #2 subject to `Summarize N notes: Wave 2 complete (M succeeded, F failed)`.

##### Wave 3 — Write back from temp files (parallel Bash calls)

If N <= 5, create a write-back sub-task for each note that got a `WRITTEN:` status:

```
TaskCreate: subject="Write back: <basename>", activeForm="Writing <basename>"
```

For each successful note, call Python to read the temp summary file and apply it — no heredoc needed, summary stays off parent context:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import upgrade_note_with_summary
with open(sys.argv[6], "r") as f:
    summary = f.read()
status = upgrade_note_with_summary(sys.argv[1], summary, sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
print(status)
' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" "sub-agent" "/tmp/ob-summary-<basename>.md"
```

**Important:** `$NOTE_PATH` is always the **original vault note path** (not the temp file), even for JSONL_PREPPED notes.

Launch all write-back Bash calls in a single message turn.

When all return, parse each result:
- If the status does NOT start with "Failed:", mark as succeeded.
- If the status starts with "Failed:", mark as failed. Count it in the failure tally.

If N <= 5: update each write-back sub-task accordingly.
If N > 5: update task #2 subject to `Summarize N notes: Wave 3 complete (M written, F failed)`.

##### Cleanup

Clean up all temp files created in Waves 1 and 2 (specific paths only — avoids racing with concurrent `/recall` invocations):

```bash
rm -f /tmp/ob-prep-<session_id_1>.md /tmp/ob-prep-<session_id_2>.md /tmp/ob-summary-<basename_1>.md /tmp/ob-summary-<basename_2>.md ...
```

Mark task #2 as completed. Report results: how many upgraded, how many skipped (NO_CONTENT), how many failed.

If any sub-agents returned empty or invalid summaries, report those notes as still unsummarized — they will be retried on the next `/recall`.

For `NO_CONTENT` notes, inform the user: "Note `<basename>` has no session_id or conversation content. Manually edit it in Obsidian to add a summary, or delete it if it's empty."

### Step 3 — Build context brief (Python)

Update task #3 to `in_progress`.

Run a single Python call that reads all session and insight files, composes the brief, and detects completed open items — no sub-agent needed:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys
sys.path.insert(0, "hooks")
from obsidian_utils import build_context_brief
print(build_context_brief(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$INSIGHTS_FOLDER" "$PROJECT"
```

If the command fails (non-zero exit code), print the error and stop — do not fall back to in-context reads.

**Parse the output.** Split on section labels:

1. Extract `<<<OB_CONTEXT_BRIEF>>>` — everything between this delimiter and `<<<OB_LOAD_MANIFEST>>>`. This is the brief to display.
2. Extract `<<<OB_LOAD_MANIFEST>>>` — parse `full_session_title`, `full_session_date`, `full_session_path`, `summary_session_title`, `summary_session_date`, `insight_count`.
3. Extract `<<<OB_MOST_RECENT_SESSION_PATH>>>` — the full path for checkoff edits.
4. Extract `<<<OB_OPEN_ITEM_CANDIDATES>>>` — either `NO_CANDIDATES`, `NO_ITEMS`, or a JSON array.

Update task #3 to `completed`. Update task #4 to `in_progress`.

**Present the brief immediately** (same turn — saves one parent round):

> **Here's what I found from your Obsidian vault for `$PROJECT`:**

Then output the `CONTEXT_BRIEF` section verbatim.

If unsummarized notes were upgraded in Step 2, also mention:

> _Upgraded N session note(s) with AI summaries._

### Step 4 — Detect completed open items and show load manifest

Parse the `OPEN_ITEM_CANDIDATES` section from the Step 3 Python output.

1. **Skip if no candidates.** If the value is `NO_ITEMS` or `NO_CANDIDATES`, skip to Step 5 silently.

2. **Parse candidates.** The JSON array contains objects with `file`, `line`, `text`, `evidence`, `confidence`, `has_completion_phrase`.

3. **Present candidates to user.** Print:

```
I noticed these open items may now be done:

1. [x] <item text>
     From: <basename of source file>
     Evidence: "<short snippet from evidence showing the match>"

2. [x] <item text>
     ...

Confirm checkoff? (e.g. `1` or `1,2` or `all` or `none`)
```

4. **Wait for user response.** Parse the response:
   - `none` or empty → skip checkoff entirely, proceed to Step 5
   - `all` → check off all candidates
   - Comma-separated numbers (e.g. `1,3`) → check off only those

5. **For each confirmed checkoff, edit the source file.** Use Read to load the full source file. Find the exact line containing `- [ ] <item text>`. Replace it with `- [x] <item text>`. Use the Edit tool with `replace_all: false` and provide enough context to ensure uniqueness. If the line is ambiguous, skip and warn:

```
⚠️  Could not check off item "<item text>" — line is not unique in <file>. Edit manually in Obsidian.
```

6. **Confirm checkoffs to user.** Print:

```
✅ Checked off N item(s) across <list of files>.
```

7. **Cascade check-offs to duplicate items in older notes.** Run:

    ```bash
    cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    python3 -c '
    import sys, json
    sys.path.insert(0, "hooks")
    from open_item_dedup import batch_cascade_checkoff
    items = json.loads(sys.argv[4])
    summary = batch_cascade_checkoff(sys.argv[1], sys.argv[2], sys.argv[3], items)
    print(summary)
    ' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" "$CHECKED_ITEMS_JSON"
    ```

    Construct `$CHECKED_ITEMS_JSON` as a JSON array of the confirmed item texts. Report the cascade summary.

**Show load manifest** (same step — saves one parent round):

Use the `LOAD_MANIFEST` data to show:

> **Loaded into this conversation:**
> - Full session: *"<full_session_title>"* (<full_session_date>)
> - Summary only: *"<summary_session_title>"* (<summary_session_date>)
> - <insight_count> curated insight(s)
>
> Pick any session from the history table above to load it, or ready to start working?

The session history table from the context brief serves as a menu — if the user picks a session by name or date, use the Read tool to load that specific file from `$VAULT_PATH/$SESSIONS_FOLDER/` and present its full contents.

If the user says they're ready to work, the context is already loaded — proceed.

Update task #4 to `completed`.

## Edge Cases

- **No sessions found:** Tell the user no session history was found for this project. Suggest they start a session and it will be logged automatically.
- **No insights found:** Omit the "Curated Insights" section. Mention: "No curated insights yet for this project."
- **Very large vault (50+ sessions):** Only grep, never glob the entire folder. Limit reads to the most recent 5 sessions + all insights.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
