---
name: recall
description: "Loads historical context from the Obsidian vault for the current project. Summarizes any unsummarized session notes, then presents a context brief with recent sessions, open items, and curated insights. Also auto-detects open items completed in the most recent loaded session and offers to check them off. Use when: (1) /recall command, (2) /recall <project-name>, (3) resuming work on a project and wanting prior context."
metadata:
  version: 1.5.0
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
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
c = load_config()
if not c.get("vault_path"):
    print("ERROR: vault_path not configured", file=sys.stderr)
    sys.exit(1)
project = os.path.basename(os.getcwd()).lower().replace(" ", "-")
print("VAULT=" + c["vault_path"])
print("SESS=" + c.get("sessions_folder", "claude-sessions"))
print("INS=" + c.get("insights_folder", "claude-insights"))
print("PROJECT=" + project)
'
```

Parse each output line as KEY=VALUE, splitting on the first `=`.

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
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
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

#### Path B: N>=1 (parallel Haiku pipelines with sub-agent fallback)

**Task management threshold:** If N <= 5, create a sub-task per note. If N > 5, skip per-note sub-tasks — use a single progress update on task #2 instead. This saves ~15-20s of parent round-trip overhead at large N.

##### Phase 1 — Parallel Haiku upgrades (single batch call)

If N <= 5, create a sub-task for each note:

```
TaskCreate: subject="Upgrade: <basename>", activeForm="Upgrading <basename> via Haiku"
```

**Single Bash tool call** — `upgrade_batch()` fans out N Haiku invocations in parallel inside one Python process via `concurrent.futures.ThreadPoolExecutor`. This sidesteps the Claude Code harness's serialization of parallel Bash tool calls for subprocess-blocking work:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
printf '%s' "$UNSUMMARIZED_PATHS_JSON" | python3 -c '
import sys, os, json
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import upgrade_batch
paths = json.loads(sys.stdin.read())
results = upgrade_batch(paths, sys.argv[1], sys.argv[2], sys.argv[3])
print(json.dumps([{"path": p, "status": s} for p, s in results]))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT"
```

Parse the returned JSON array. For each entry:
- `status` starts with `Upgraded ` → mark as succeeded
- anything else (including `Failed: ...`, empty, or unexpected prefix) → add to the Phase 2 fallback list

If N <= 5: update each sub-task accordingly (succeeded or `Failed: <basename>`).
If N > 5: update task #2 subject to `Upgrade N notes: M succeeded, F pending fallback`.

> **Why a single Bash call, not N parallel calls?** The Claude Code harness serializes parallel Bash tool calls through a limited shell pool when each subprocess blocks on I/O (e.g., `claude -p --model haiku` taking 5-30s). Dispatching 10 Bash calls in one message still executes them one at a time — wall time ≈ Σ per-call. Pushing fan-out into a single Python process with `ThreadPoolExecutor` gives true concurrency (the GIL releases during subprocess waits), so wall time ≈ max per-call. See `claude-insights/2026-04-21-recall-parallel-bash-dispatch-runs-sequentially-fbee-error.md` and GH #69.

##### Phase 2 — Sub-agent fallback (only for failed notes)

If no failures, skip this phase entirely.

For each failed note, spawn a sub-agent. If multiple notes failed, spawn all sub-agents in a **single message turn**:

```
Agent({
  description: "Summarize session note <basename>",
  prompt: "Read the session note at <NOTE_PATH>. Produce a structured summary with these exact markdown sections:\n\n## Summary\n1-3 sentence overview of what was accomplished.\n\n## Key Decisions\n- Bullet list of important technical decisions. Write \"None noted.\" if none.\n\n## Changes Made\n- Bullet list of files modified/created with brief description. Write \"None noted.\" if none.\n\n## Errors Encountered\n- Bullet list of errors and how resolved. Write \"None.\" if none.\n\n## Open Questions / Next Steps\n- [ ] Checkbox list of unresolved items. Write \"None.\" if none.\n\nWrite the summary to ~/.claude/obsidian-brain/summary-<basename>.md using the Write tool. After the summary sections, add a final line:\nIMPORTANCE: N\nwhere N is 1-10. 1-3: trivial (config, interrupted). 4-6: standard work. 7-8: key decisions or error resolutions. 9-10: major releases or security audits.\n\nReturn ONLY the single line: WRITTEN:~/.claude/obsidian-brain/summary-<basename>.md"
})
```

When sub-agents return, for each:

1. If the sub-agent returned `WRITTEN:<path>`, extract the path after `WRITTEN:` and replace the leading `~` with `$HOME` to get an absolute path. Store this as `SUMMARY_TEMP_PATH`. Verify the file exists: `test -f "$SUMMARY_TEMP_PATH" && echo "EXISTS" || echo "MISSING"`.
2. If EXISTS, apply it via Python:

   ```bash
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   python3 -c '
   import sys, os
   import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
   from obsidian_utils import upgrade_note_with_summary
   with open(os.path.expanduser(sys.argv[6]), "r") as f:
       summary = f.read()
   status = upgrade_note_with_summary(sys.argv[1], summary, sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
   print(status)
   ' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" "sub-agent" "$SUMMARY_TEMP_PATH"
   ```

   If the write-back status starts with `Failed:`, count this note as permanently failed — do NOT count it as upgraded. If N <= 5, update the per-note sub-task to `Permanently failed: <basename>`.

   If the write-back succeeds, and N <= 5, update the per-note sub-task to `Fallback succeeded: <basename>`.

3. If MISSING or sub-agent didn't return `WRITTEN:` → note stays unsummarized for next `/recall`. If N <= 5, update the per-note sub-task to `Permanently failed: <basename>`.

**Always** clean up temp files from Phase 2 after all write-backs complete, regardless of outcome. Use the actual `SUMMARY_TEMP_PATH` values collected from each sub-agent's `WRITTEN:` response (not placeholder names):

```bash
rm -f "$SUMMARY_TEMP_PATH_1" "$SUMMARY_TEMP_PATH_2" ...
```

If N > 5: update task #2 subject to reflect final Phase 2 results (e.g. `Upgrade N notes: M Haiku + F fallback succeeded, K failed`).

##### Completion

Mark task #2 as completed. Report results:
- How many upgraded via Haiku pipeline (Phase 1 successes)
- How many upgraded via sub-agent fallback (Phase 2 write-back successes)
- How many permanently failed (notes where both Phase 1 Haiku AND Phase 2 sub-agent fallback failed or were skipped — these stay unsummarized for next `/recall`)

For failed notes: "Note `<basename>` could not be summarized. It will be retried on the next `/recall`."

### Step 3 — Build context brief (Python)

Update task #3 to `in_progress`.

Run a single Python call that reads all session and insight files, composes the brief, and detects completed open items — no sub-agent needed:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import build_context_brief, check_hook_status
hs = check_hook_status()
status_line = ("[OK] " if hs["ok"] else "[WARN] ") + hs["message"]
print(build_context_brief(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], hook_status_line=status_line))
' "$VAULT_PATH" "$SESSIONS_FOLDER" "$INSIGHTS_FOLDER" "$PROJECT"
```

The first line of the emitted `CONTEXT_BRIEF` is always the hook-status line. If it starts with `[OK]`, omit it from the displayed output — the user doesn't need to see "session logging active" every time. If it starts with `[WARN]`, display it verbatim so the user knows to take action (e.g., run `/obsidian-setup`).

If the command fails (non-zero exit code), print the error and stop — do not fall back to in-context reads.

**Parse the output.** Split on section labels:

1. Extract `<<<OB_CONTEXT_BRIEF>>>` — everything between this delimiter and `<<<OB_LOAD_MANIFEST>>>`. This is the brief to display.
2. Extract `<<<OB_LOAD_MANIFEST>>>` — parse `full_session_title`, `full_session_date`, `full_session_path`, `summary_session_title`, `summary_session_date`, `insight_count`, `snapshot_count` (optional), and all `snapshot:` lines (there may be zero or more, each followed by optional 2-space-indented `key_context` bullets).
3. Extract `<<<OB_MOST_RECENT_SESSION_PATH>>>` — the full path for checkoff edits.
4. Extract `<<<OB_OPEN_ITEM_CANDIDATES>>>` — either `NO_CANDIDATES`, `NO_ITEMS`, or a JSON array.

Update task #3 to `completed`. Update task #4 to `in_progress`.

**Present the brief immediately** (same turn — saves one parent round):

> **Here's what I found from your Obsidian vault for `$PROJECT`:**

Then output the `CONTEXT_BRIEF` section. For the session history table, paraphrase each session's Title column into a concise one-line summary (under ~80 characters) that captures the key accomplishment. Keep all other columns (date, duration, branch) verbatim.

Snapshots appear in the brief as nested indented rows beneath their parent session (rows starting with `↳ HH:MM:SS`). Render them verbatim — do not paraphrase snapshot titles (they're already one-line summaries). Display the `snapshot:` lines from LOAD_MANIFEST as bullet points under the most-recent session in the "Loaded into this conversation" output.

If unsummarized notes were upgraded in Step 2, also mention:

> _Upgraded N session note(s) with AI summaries._

### Step 4 — Detect completed open items and show load manifest

Parse the `OPEN_ITEM_CANDIDATES` section from the Step 3 Python output.

1. **Skip if no candidates.** If the value is `NO_ITEMS` or `NO_CANDIDATES`, skip the rest of Step 4's checkoff sub-steps and proceed directly to the "Show load manifest" block at the end of Step 4 silently.

2. **Parse candidates.** The JSON array contains objects with `file`, `line`, `text`, `evidence`, `confidence`, `has_completion_phrase`.

3. **Present candidates to user.** Branch by N (number of candidates):

   **N ≤ 4 — native multi-select picker:**

   Call `AskUserQuestion` with `multiSelect: true`. Build one `option` per candidate:

   - `label`: first ~40 characters of the candidate's `text` field, ellipsized with `…` if truncated. No paraphrase — take a prefix of the verbatim text.
   - `description`: `<basename(file)>:<line> — "<full verbatim candidate.text>" — Evidence: <short evidence snippet>`

   Example shape:

   ```
   AskUserQuestion({
     questions: [{
       question: "Which open items should I check off?",
       header: "Checkoff",
       multiSelect: true,
       options: [
         {
           label: "File #69: Investigate /recall parallel subpro…",
           description: "2026-04-20-obsidian-brain-7769.md:42 — \"File #69: Investigate /recall parallel subprocess dispatch sequentiality in Claude Code harness\" — Evidence: \"...shipped v2.4.0 ...completing issue #69...\""
         },
         ...
       ]
     }]
   })
   ```

   Record the user's selected options. Empty selection → treat as `none`.

   **N > 4 — verbatim text fallback:**

   Print:

   ```
   I noticed these open items may now be done:

   1. <basename(file)>:<line>
      - [ ] <verbatim candidate.text>
      Evidence: "<short evidence snippet>"

   2. ...

   Confirm checkoff? (e.g. `1` or `1,2` or `all` or `none`)
   ```

   The `- [ ] <verbatim candidate.text>` line MUST be shown in a code block using the exact `candidate.text` content (no paraphrase, no ellipsis). Step 5's match rule then compares this text against the file line after normalizing the file side (strip leading whitespace, `- [ ] ` prefix, and trailing whitespace/newline) — so the presented text is what matches after normalization, not byte-for-byte against raw file bytes.

4. **Wait for user response** (N > 4 branch only — the N ≤ 4 branch returns from `AskUserQuestion`). Parse the response:
   - `none` or empty → skip the remaining checkoff sub-steps (5–7) and proceed directly to the "Show load manifest" block at the end of Step 4
   - `all` → check off all candidates
   - Comma-separated numbers (e.g. `1,3`) → check off only those

   **N ≤ 4 branch:** if the user's `AskUserQuestion` selection is empty, treat it the same way — skip sub-steps 5–7 and proceed to the "Show load manifest" block at the end of Step 4.

5. **For each confirmed checkoff, Read-verify then Edit.** Maintain a `successfully_edited` list (starts empty), a `skipped_drift` counter (starts 0), and a `skipped_other` counter (starts 0).

   **5-pre. Within-batch dedup:** if the confirmed candidate list contains two entries with the same `(file, line)`, keep only the first and drop the rest automatically — they are scan duplicates, not drift. Do not emit per-duplicate warnings or treat them as skips. If any duplicates were removed, print this one-line informational message: `De-duplicated K within-batch candidate(s).`

   For each confirmed candidate:

   a. **Read** the source file at `offset = max(1, candidate.line - 3), limit = 7` (±3 lines context, clamped at file start). This also satisfies the Edit tool's "must Read before Edit" requirement.

   a'. **If Read fails** (file missing, permission denied, or the read region returns empty content): skip this candidate, increment `skipped_other`, and emit:

   ```
   ⚠️  Skipped checkoff "<candidate.text>" — cannot read <basename(file)>:<line>
   (<error class from Read tool>). File may have been moved, deleted, or
   permissions changed. Edit manually in Obsidian.
   ```

   Do NOT append to `successfully_edited`. Continue with next candidate.

   b. **Match check.** Scan the read region for any line that, after stripping leading whitespace, the `- [ ] ` prefix, AND trailing whitespace/newline, equals `candidate.text` byte-for-byte. The candidate text was already normalized by `open_item_dedup.collect_open_items` via `line.strip()` (leading+trailing whitespace removed) followed by `[6:]` (prefix removed), so both sides of the comparison end up as the same fully-stripped item text. The bullet prefix is exactly `- [ ] ` (hyphen, space, open-bracket, space, close-bracket, single trailing space) — `open_item_dedup.collect_open_items` emits only this form, so `- [ ]` with other spacing or `*`/`+` bullets will correctly fail to match and trigger the drift-skip branch.

   c. **If match found:** use `Edit` with `replace_all: false` to update the already-matched raw line in place, preserving any leading whitespace/indentation and changing only its checkbox marker from `[ ]` to `[x]`. Do not reconstruct the line from `candidate.text` — use the raw line as seen in the Read output. Include enough surrounding text in the Edit call to ensure uniqueness. Append `candidate.text` to `successfully_edited`.

   d. **If no match found in the read region:** skip this candidate, increment `skipped_drift`, and emit:

   ```
   ⚠️  Skipped checkoff at <basename(file)>:<line>
       expected: - [ ] <candidate.text>
       found:    <RAW_LINE>
   File changed since /recall Step 3. Edit manually in Obsidian.
   ```

   `<RAW_LINE>` is the raw text (verbatim, leading whitespace preserved) of the line at buffer index `min(3, candidate.line - 1)` in the read region. Use the literal substitute `(line is past EOF)` if the read region is shorter than expected, or `(line is no longer a checkbox)` if the line's content (after stripping leading whitespace) does not start with `- [`. The buffer-index formula follows from Read's clamp `offset = max(1, candidate.line - 3)` — when `candidate.line ≥ 4`, the target line sits at buffer index 3; when `candidate.line ∈ {1,2,3}`, it sits at buffer index `candidate.line - 1`. Do NOT append to `successfully_edited`.

   e. **If the Edit call itself fails** (string not found, ambiguous match, or file-modified-since-read): skip, increment `skipped_other`, and emit the Edit tool's error message verbatim:

   ```
   ⚠️  Could not check off "<candidate.text>" in <basename(file)>:<line> —
   Edit failed: <verbatim Edit error message>. The line may have been edited
   externally since /recall started, or the same text appears multiple times.
   Edit manually in Obsidian.
   ```

   Do NOT append to `successfully_edited`.

   Continue with remaining confirmed candidates regardless of any individual skip.

6. **Confirm checkoffs to user.** Print:

   ```
   ✅ Checked off N item(s) across <list of files>.
   ```

   If `skipped_drift > 0` or `skipped_other > 0`, append:

   ```
   ⚠️  Skipped M item(s) total (drift: <skipped_drift>, other: <skipped_other>) — see warnings above.
   ```

   Where `N = len(successfully_edited)` and `M = skipped_drift + skipped_other`.

7. **Cascade check-offs to duplicate items in older notes.** Run:

    ```bash
    cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    printf '%s' "$CHECKED_ITEMS_JSON" | python3 -c '
    import sys, json, os
    import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
    from open_item_dedup import batch_cascade_checkoff
    items = json.load(sys.stdin)
    summary = batch_cascade_checkoff(sys.argv[1], sys.argv[2], sys.argv[3], items)
    print(summary)
    ' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT"
    ```

    Construct `$CHECKED_ITEMS_JSON` as a JSON array of the `successfully_edited` item texts (the ones where the Read-verify matched AND the Edit succeeded — NOT the originally-confirmed set). Items skipped due to drift or non-unique matches are excluded so we don't cascade a closed state the primary-edit step could not confirm. Pass via stdin to avoid shell quoting issues. Report the cascade summary.

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
