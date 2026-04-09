---
name: recall
description: "Loads historical context from the Obsidian vault for the current project. Summarizes any unsummarized session notes, then presents a context brief with recent sessions, open items, and curated insights. Also auto-detects open items completed in the most recent loaded session and offers to check them off. Use when: (1) /recall command, (2) /recall <project-name>, (3) resuming work on a project and wanting prior context."
metadata:
  version: 1.2.0
---

# Recall — Load Project Context from Obsidian Vault

Searches the Obsidian vault for session notes and insights matching the current project, upgrades any unsummarized notes with AI summaries, and presents a concise context brief.

**Tools needed:** Bash, Grep, Read, Write

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
print(f"VAULT={c[\"vault_path\"]} SESS={c.get(\"sessions_folder\",\"claude-sessions\")} INS={c.get(\"insights_folder\",\"claude-insights\")}")
'
```

Parse the output line to extract `VAULT_PATH`, `SESSIONS_FOLDER`, and `INSIGHTS_FOLDER`.

If the output is empty or errors, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

### Step 2 — Derive project name

If the user passed a project name argument (e.g. `/recall my-project`), use that.

Otherwise, derive from the current working directory:

```bash
basename "$(pwd)"
```

Store as `PROJECT`. Normalize: lowercase, hyphens for spaces.

### Step 3 — Summarize unsummarized notes (deferred summarization, truncation-aware)

> ⚠️ **THIS STEP IS MANDATORY. DO NOT SKIP IT.**
>
> If Grep finds any file matching both "AI summary unavailable" AND `project: $PROJECT`, you **must** produce an upgraded summary for every such file before proceeding to Step 4. "Skipping to save context" or "the other session covers it" is a bug, not an optimization — the user ran `/recall` specifically to get current-session context, and stale unsummarized notes are exactly what they asked you to fix.
>
> **Large-note handling:** If the `Read` tool errors because the raw note exceeds the 10k token limit, use `offset` + `limit` to read it in chunks (e.g. `limit: 80` repeatedly) and concatenate mentally. Do NOT use that error as a reason to skip the upgrade.
>
> **Missing-JSONL fallback:** If `find_transcript_jsonl` returns null, you still produce a summary — from the raw note itself, with the fallback disclaimer specified in sub-step 4. Null JSONL is not a skip signal.
>
> **Visibility requirement:** Before Step 4, emit a one-line status: `Step 3: processing N unsummarized note(s) for $PROJECT` (or `Step 3: no unsummarized notes for $PROJECT` if the intersection is empty). This makes the decision auditable in the tool trace.

This is the critical upgrade step. Search for raw/unsummarized session notes matching this project, and prefer the original Claude Code transcript JSONL over the truncated raw note when the JSONL has more data.

Use Grep to find notes containing the "AI summary unavailable" marker in the sessions folder:

```
pattern: "AI summary unavailable"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
```

For each file found, use Grep to confirm it matches the current project:

```
pattern: "project: $PROJECT"
path: <each matched file>
output_mode: content
```

For each file that matches BOTH conditions (unsummarized AND belongs to this project):

1. **Run the upgrade pipeline in Python** — a single Bash call that handles JSONL lookup, transcript parsing, source decision, AI summarization, dedup, and atomic write:

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

   Where `$NOTE_PATH` is the full path of the unsummarized note. The function returns a one-line status like:
   - `"Upgraded 2026-04-07-obsidian-brain-aeb5.md (source: JSONL transcript), deduped 2 item(s)"`
   - `"Failed: AI summarization returned empty for 2026-04-07-obsidian-brain-aeb5.md"`

   Report the status to the user. If it starts with "Failed:", **collect the note path into a fallback list** but continue to the next unsummarized note.

2. **Sub-agent fallback for failed notes.** If any notes returned "Failed:" status:

   For each failed note, spawn a sub-agent in parallel using the Agent tool:

   ```
   Agent({
     description: "Summarize session note <basename>",
     prompt: "Read the session note at <NOTE_PATH>. Produce a structured summary with these exact markdown sections:\n\n## Summary\n1-3 sentence overview of what was accomplished.\n\n## Key Decisions\n- Bullet list of important technical decisions. Write \"None noted.\" if none.\n\n## Changes Made\n- Bullet list of files modified/created with brief description. Write \"None noted.\" if none.\n\n## Errors Encountered\n- Bullet list of errors and how resolved. Write \"None.\" if none.\n\n## Open Questions / Next Steps\n- [ ] Checkbox list of unresolved items. Write \"None.\" if none.\n\nReturn ONLY these markdown sections. No preamble, no commentary."
   })
   ```

   Invoke multiple Agent tool calls in the same response turn (one per failed note) so they run in parallel. When each sub-agent returns its structured summary text:

   - If the sub-agent returned an error or empty output, skip that note — log the failure and continue.
   - Otherwise, pass the returned summary text to the Python pipeline via a heredoc. The Agent tool's return value is text in your context — write it into the heredoc verbatim:

   ```bash
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   python3 -c '
   import sys
   sys.path.insert(0, "hooks")
   from obsidian_utils import upgrade_note_with_summary
   summary = sys.stdin.read()
   status = upgrade_note_with_summary(sys.argv[1], summary, sys.argv[2], sys.argv[3], sys.argv[4])
   print(status)
   ' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" <<'SUMMARY_EOF'
## Summary
1-3 sentence overview from the sub-agent.

## Key Decisions
- Example bullet from the sub-agent.

## Changes Made
- Example bullet from the sub-agent.

## Errors Encountered
None.

## Open Questions / Next Steps
- [ ] Example follow-up item.
SUMMARY_EOF
   ```

   **Important:** Paste the sub-agent summary into the heredoc verbatim with NO leading indentation. Start `## Summary` at column 0, and keep the closing `SUMMARY_EOF` terminator at column 0 as well. Leading spaces before the summary content will cause `upgrade_note_with_summary()` validation to fail, and leading spaces before `SUMMARY_EOF` will prevent the heredoc from terminating correctly.

   Report each result. If the pipeline returns "Failed:", note it but continue — the note stays unsummarized for the next `/recall`.

If no unsummarized notes are found for this project, skip to Step 4.

### Step 4 — Search for project sessions and insights (parallel)

Run these two searches in parallel using Grep:

**Search A — Sessions:**

```
pattern: "project: $PROJECT"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
```

**Search B — Insights:**

```
pattern: "project: $PROJECT"
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: files_with_matches
```

Collect both result sets.

### Step 5 — Rank and select notes

From the session files found, sort by date (extract from frontmatter `date:` field or filename). Select:

- **Most recent session** — read in full (this is the primary context). Store its full path as `MOST_RECENT_SESSION_PATH` for use in Step 7.5.
- **Second most recent session** — read summary + open questions only
- **Last 5 sessions** — collect titles and dates for the session list

From the insights files found, include **all of them** — insights are curated and always relevant.

Read the selected files using the Read tool. For efficiency:
- Read the most recent session in full
- For older sessions, read only the first 50 lines (enough for frontmatter + summary + open questions)
- Read all insight files in full (they are typically short)

### Step 6 — Compose context brief

Build a context brief targeting approximately 2000 tokens. Structure it as follows:

```
## Project Context: $PROJECT

### Last Session ($DATE)
$SUMMARY_FROM_MOST_RECENT_SESSION

**Open Items / Next Steps:**
$OPEN_QUESTIONS_FROM_MOST_RECENT_SESSION

### Previous Session ($DATE)
$BRIEF_SUMMARY_FROM_SECOND_SESSION

### Curated Insights
$ALL_INSIGHTS_CONTENT

### Recent Session History
| Date | Title | Branch |
|------|-------|--------|
| ... last 5 sessions ... |
```

If the brief exceeds ~2000 tokens, trim older session summaries first, then truncate insight bodies (keep titles).

### Step 7 — Present to user

Display:

> **Here's what I found from your Obsidian vault for `$PROJECT`:**

Then output the context brief from Step 6.

If unsummarized notes were upgraded in Step 3, also mention:

> _Upgraded N session note(s) with AI summaries._

### Step 7.5 — Detect completed open items (project-scoped auto-detect)

After presenting the context brief, scan the loaded context for evidence that any open items have been completed.

1. **Match open items against evidence in Python.** Run a single Bash call that collects open items and matches them against the most recent session note:

   ```bash
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   python3 -c '
   import sys, json
   sys.path.insert(0, "hooks")
   from obsidian_utils import match_items_against_evidence
   from open_item_dedup import collect_open_items

   vault_path, sessions_folder, project = sys.argv[1], sys.argv[2], sys.argv[3]
   evidence_file = sys.argv[4]

   try:
       with open(evidence_file, "r") as f:
           content = f.read()
       # Extract only evidence sections (Summary, Changes, Errors) — exclude
       # Open Questions to avoid self-matching open items as candidates
       import re as _re
       evidence_parts = []
       for section in ["Summary", "Key Decisions", "Changes Made", "Errors Encountered"]:
           m = _re.search(rf"## {section}\n(.*?)(?=\n## |\Z)", content, _re.DOTALL)
           if m:
               evidence_parts.append(m.group(1))
       evidence = "\n".join(evidence_parts) if evidence_parts else content
   except OSError as exc:
       print("NO_CANDIDATES")
       sys.exit(0)

   items = collect_open_items(vault_path, sessions_folder, project)
   if not items:
       print("NO_ITEMS")
       sys.exit(0)

   candidates = match_items_against_evidence(evidence, items)
   if not candidates:
       print("NO_CANDIDATES")
   else:
       print(json.dumps(candidates))
   ' "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT" "$MOST_RECENT_SESSION_PATH"
   ```

   Where `$MOST_RECENT_SESSION_PATH` is the path to the most recent session note (already read in Step 5).

2. **Skip if no candidates.** If the output is `NO_ITEMS` or `NO_CANDIDATES`, skip to Step 8 silently.

3. **Parse candidates.** The JSON array contains objects with `file`, `line`, `text`, `evidence`, `confidence`, `has_completion_phrase`. Only present items with `confidence >= 3` to the user.

4. **Present candidates to user.** Print:

```
I noticed these open items may now be done:

1. [x] <item text>
     From: <basename of source file>
     Evidence: "<short snippet from EVIDENCE_TEXT showing the match>"

2. [x] <item text>
     ...

Confirm checkoff? (e.g. `1` or `1,2` or `all` or `none`)
```

5. **Wait for user response.** Parse the response:
   - `none` or empty → skip checkoff entirely, proceed to Step 8
   - `all` → check off all candidates
   - Comma-separated numbers (e.g. `1,3`) → check off only those

6. **For each confirmed checkoff, edit the source file.** Use Read to load the full source file. Find the exact line containing `- [ ] <item text>`. Replace it with `- [x] <item text>`. Use the Edit tool with `replace_all: false` and provide enough context (the full line plus the line before and after if available) to ensure uniqueness within the file. If the line is ambiguous (multiple matches), skip that item and warn:

```
⚠️  Could not check off item "<item text>" — line is not unique in <file>. Edit manually in Obsidian.
```

7. **Confirm checkoffs to user.** Print:

```
✅ Checked off N item(s) across <list of files>.
```

8. **Cascade check-offs to duplicate items in older notes.** Run a single Bash call that collects, matches, and edits files in Python:

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

    Before running, construct `$CHECKED_ITEMS_JSON` as a JSON array of the confirmed item texts from sub-step 5. Use a Bash heredoc or inline Python to build it:
    ```bash
    CHECKED_ITEMS_JSON=$(python3 -c "import json; print(json.dumps([\"Git-flow migration spec pending\", \"Land PR #14\"]))")
    ```
    Replace the example items with the actual confirmed item texts. Then run the cascade command above. Report the cascade summary to the user alongside the checkoff confirmation.

Then proceed to Step 8.

### Step 8 — Show load manifest and offer options

After the context brief, explicitly list what was loaded into the conversation so the user knows exactly what context is available:

> **Loaded into this conversation:**
> - Full session: *"[most recent session title]"* ([date])
> - Summary only: *"[second session title]"* ([date])
> - [N] curated insight(s)
>
> Pick any session from the history table above to load it, or ready to start working?

The session history table from Step 6 serves as a menu — if the user picks a session by name or date, use the Read tool to load that specific file and present its full contents.

If the user says they're ready to work, the context is already loaded — proceed.

## Edge Cases

- **No sessions found:** Tell the user no session history was found for this project. Suggest they start a session and it will be logged automatically.
- **No insights found:** Omit the "Curated Insights" section. Mention: "No curated insights yet for this project."
- **Very large vault (50+ sessions):** Only grep, never glob the entire folder. Limit reads to the most recent 5 sessions + all insights.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
