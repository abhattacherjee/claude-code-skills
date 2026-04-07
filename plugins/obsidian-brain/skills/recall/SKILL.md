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

Read `~/.claude/obsidian-brain-config.json`:

```bash
cat ~/.claude/obsidian-brain-config.json
```

If the file does not exist or is not valid JSON, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing. Otherwise, extract `vault_path`, `sessions_folder` (default `claude-sessions`), and `insights_folder` (default `claude-insights`).

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

1. **Read the raw note in full** with the Read tool. Preserve frontmatter exactly. Extract the `session_id` value from the frontmatter and **store it as `SESSION_ID`** — the Bash snippet in sub-step 3 references this exact variable name.

2. **No raw-note turn count needed.** Earlier revisions of this skill counted `^\*\*User:\*\*` / `^\*\*Assistant:\*\*` markers in the raw note to detect truncation, but that count is unreliable. The raw fallback's `## Conversation (raw)` section filters out system noise (`<task-notification>`, `<local-command…>`, "Base directory for this skill:", …) before emitting a `**User:**` line. Its `turn` counter is incremented whenever a `**User:**` OR `**Assistant:**` line is actually written, with user lines sometimes skipped due to noise filtering. So the marker count in a written raw note does not necessarily correspond to the underlying user/assistant message count in the transcript — filtered user messages are invisible. Use the shared `raw_note_max_turns` constant returned by the helper in sub-step 3 instead — it is the only deterministic truncation signal.

3. **Locate the source JSONL and re-parse it in one shot.** Invoke the helper via argv (no shell interpolation of paths — pass `SESSION_ID` as an argument so session_ids with unusual characters cannot break the quoting). The parsed JSON is printed directly to stdout — no temp files, no traps:

   Run the following Bash command from the obsidian-brain project root. It prints the parsed transcript JSON **directly to stdout** — no temp files, no traps, no `$TMPFILE` that would need to persist across tool invocations. Capture the stdout from the Bash tool result in the next step:

   ```bash
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   python3 -c '
   import sys, json
   sys.path.insert(0, "hooks")
   from obsidian_utils import find_transcript_jsonl, parse_full_transcript, RAW_NOTE_MAX_TURNS
   p = find_transcript_jsonl(sys.argv[1])
   if p is None:
       # Emit the same schema as the success branch so downstream steps
       # do not need to special-case missing fields. All fields present,
       # lists empty, booleans False.
       print(json.dumps({
           "jsonl_path": None,
           "user_msgs": [], "assistant_msgs": [], "tool_uses": [],
           "files_touched": [], "errors": [],
           "truncated": False,
           "warnings": [],
           "raw_note_max_turns": RAW_NOTE_MAX_TURNS,
           "raw_note_would_truncate": False,
       }))
   else:
       data = parse_full_transcript(p)
       data["jsonl_path"] = str(p)
       print(json.dumps(data))
   ' "$SESSION_ID"
   ```

   The Bash tool's stdout result is the JSON payload. Parse it directly from the tool response — it contains either `{"jsonl_path": null}` (not found) or the full parsed transcript plus `jsonl_path`, `truncated`, and `warnings`. Very large transcripts can produce multi-MB JSON; if the Bash tool truncates the output, fall back to writing to a known path such as `$VAULT_PATH/.obsidian-brain-transcript-cache.json` and reading it with the Read tool (this file is not in the vault's git repo and is safe to overwrite).

4. **Decide which source to summarize from.** Two independent signals mean "raw note is incomplete":
   - **`raw_note_would_truncate: true`** — `parse_full_transcript` simulates the exact same write loop as `build_raw_fallback` (including the system-noise filter that skips filtered user messages without incrementing the cap counter). This field is true iff that simulation would have bailed on the cap before consuming all messages. It is the fully deterministic signal — immune to false positives from noise filtering or false negatives from cap drift.
   - **`truncated: true`** — the transcript exceeded the 5 MB byte budget and was sliced into head+tail halves. In that case some real content is missing from the middle regardless of the cap simulation, so this must be OR'd with the cap signal.

   Decision branches:
   - **`jsonl_path` is null** → use the raw note as the input. Append to the Summary section: `_(Source transcript not found on disk — summary built from the raw session note; fidelity depends on whether the raw note was itself capped at write time.)_`
   - **`jsonl_path` is set AND (`raw_note_would_truncate == true` OR `truncated == true`)** → re-parse path engages. Use the parsed `user_msgs`, `assistant_msgs`, `tool_uses`, `files_touched`, and `errors` as the summarization input. If `truncated == true`, note that the summary reflects only the head and tail of the transcript.
   - **`jsonl_path` is set AND `raw_note_would_truncate == false` AND `truncated == false`** → the raw note captured everything; use it instead.
   - **If the parsed data's `warnings` list is non-empty** (regardless of which branch), prepend a visible callout section `## ⚠️ Transcript re-parse warnings` at the top of the upgraded note (above `# <title>`), listing each warning as a bullet. This surfaces partial-line losses, malformed JSONL records, unknown block types, and byte-budget slicing so the user knows what's in the summary and what isn't.

5. **Generate a detailed, specific summary** from whichever input source was chosen above. Be precise — include file paths, function names, config values, and technical specifics. Produce these sections (unchanged from before):
   - `## Summary` — 3-5 sentences
   - `## Key Decisions` — bulleted list with rationale
   - `## Changes Made` — bulleted list with file paths
   - `## Errors Encountered` — bulleted list with messages, root causes, fixes
   - `## Open Questions / Next Steps` — checkbox list of concrete actionable items

6. **Write the upgraded note** with the Write tool to the same file path. Preserve original frontmatter unchanged but flip `status: auto-logged` to `status: summarized`. Structure:
   - Original frontmatter (unchanged except `status`)
   - `# <title from original note>`
   - The five summary sections
   - The existing `## Tool Usage` / `## Changes Made` / `## Errors Encountered` / `## Conversation (raw)` sections from the raw note (preserve them as the audit trail — only the leading summary changes)
   - The Session Metadata section if present

**Important:** Do NOT modify frontmatter fields other than `status`. Do NOT change the filename. Do NOT add or remove tags.

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

- **Most recent session** — read in full (this is the primary context)
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

1. **Collect open items for the current project.** **Re-use the project-scoped file list from Step 4** (the result of Search A — sessions matching `project: $PROJECT`). For each file in that list, run a per-file Grep:

```
pattern: ^- \[ \] 
path: <each session file from Step 4>
output_mode: content
-n: true
```

This avoids an O(vault size) Grep across the entire sessions folder — we already have the project-scoped file list and reuse it directly.

For each match, extract `(file_path, line_number, item_text)` tuples for items appearing under a `## Open Questions / Next Steps` section. To verify the section context, read 30 lines before each match and confirm the most recent `## ` heading is `## Open Questions / Next Steps`.

2. **Skip if zero open items.** If no items found, skip to Step 8 silently.

3. **Use loaded context as evidence pool.** The most recent session was already read in full during Step 5. Concatenate the text of its `## Summary`, `## Changes Made`, and `## Errors Encountered` sections — store as `EVIDENCE_TEXT`.

4. **Match items to evidence.** For each open item:
   - **Tokenize** the item text into words, lowercase, drop common stopwords (`the`, `a`, `an`, `to`, `for`, `in`, `on`, `of`, `and`, `or`, `but`, `is`, `are`, `was`, `were`, `be`).
   - **Substring match:** Count how many tokens (3+ characters) appear as substrings in `EVIDENCE_TEXT` (also lowercased). If count >= 3, mark as candidate.
   - **Distinctive token match:** If the item contains any of these distinctive tokens and they appear in evidence, mark as candidate even if substring count < 3:
     - File paths (contains `/` or `.py`/`.md`/`.json`/`.ts`/`.js`/`.tsx`/`.jsx`)
     - PR/issue references (matches `#\d+` or `PR \d+` or `issue \d+`)
     - Branch names (contains `feature/` or `release/` or `hotfix/`)
     - Version numbers (matches `v?\d+\.\d+\.\d+`)
   - **Completion phrase boost:** If a completion phrase (`merged`, `shipped`, `fixed`, `released`, `closed`, `removed`, `implemented`, `deleted`, `done`, `completed`) appears within 200 characters of any matched token in evidence, increase confidence.

5. **Skip if no candidates.** Fast path: if zero items match, skip to Step 8.

6. **Present candidates to user.** Print:

```
I noticed these open items may now be done:

1. [x] <item text>
     From: <basename of source file>
     Evidence: "<short snippet from EVIDENCE_TEXT showing the match>"

2. [x] <item text>
     ...

Confirm checkoff? (e.g. `1` or `1,2` or `all` or `none`)
```

7. **Wait for user response.** Parse the response:
   - `none` or empty → skip checkoff entirely, proceed to Step 8
   - `all` → check off all candidates
   - Comma-separated numbers (e.g. `1,3`) → check off only those

8. **For each confirmed checkoff, edit the source file.** Use Read to load the full source file. Find the exact line containing `- [ ] <item text>`. Replace it with `- [x] <item text>`. Use the Edit tool with `replace_all: false` and provide enough context (the full line plus the line before and after if available) to ensure uniqueness within the file. If the line is ambiguous (multiple matches), skip that item and warn:

```
⚠️  Could not check off item "<item text>" — line is not unique in <file>. Edit manually in Obsidian.
```

9. **Confirm checkoffs to user.** Print:

```
✅ Checked off N item(s) across <list of files>.
```

Then proceed to Step 8.

### Step 8 — Offer options

Ask:

> Want me to load this context? Or focus on a specific session/insight?

If the user says yes or wants to load it, the context brief is already in the conversation — it is loaded. Confirm:

> Context loaded. Ready to continue where you left off.

If the user asks about a specific session or insight, use the Read tool to load that specific file and present its full contents.

## Edge Cases

- **No sessions found:** Tell the user no session history was found for this project. Suggest they start a session and it will be logged automatically.
- **No insights found:** Omit the "Curated Insights" section. Mention: "No curated insights yet for this project."
- **Very large vault (50+ sessions):** Only grep, never glob the entire folder. Limit reads to the most recent 5 sessions + all insights.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
