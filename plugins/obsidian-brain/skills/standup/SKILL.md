---
name: standup
description: "Generates daily/weekly standup summaries across all projects from the Obsidian vault. Includes a Closed This Period section listing items checked off during the window, grouped by project. Use when: (1) /standup for today's summary, (2) /standup this week for weekly summary, (3) /standup <date range> for custom range."
metadata:
  version: 1.1.0
---

# Standup — Generate Standup Summaries from Obsidian Vault

Searches the Obsidian vault for session notes and insights within a date range, upgrades any unsummarized notes with AI summaries, groups findings by project, and generates a structured standup note.

**Tools needed:** Bash, Grep, Read, Write

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
print("VAULT=" + c["vault_path"] + " SESS=" + c.get("sessions_folder", "claude-sessions") + " INS=" + c.get("insights_folder", "claude-insights"))
'
```

Parse the output line to extract `VAULT_PATH`, `SESSIONS_FOLDER`, and `INSIGHTS_FOLDER`.

If the command exits non-zero or prints ERROR, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

### Step 2 — Validate vault access

Run:

```bash
test -d "$VAULT_PATH/$SESSIONS_FOLDER" && test -d "$VAULT_PATH/$INSIGHTS_FOLDER" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user:

> The vault folders do not exist or are not accessible. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 3 — Parse date range from arguments

Inspect the argument passed after `/standup`. Calculate `START_DATE` and `END_DATE` as `YYYY-MM-DD` strings using bash `date` commands.

**No argument (bare `/standup`):** today only.

```bash
START_DATE=$(date +%Y-%m-%d)
END_DATE=$START_DATE
```

**`yesterday`:**

```bash
# macOS
START_DATE=$(date -v-1d +%Y-%m-%d)
END_DATE=$START_DATE

# Linux fallback
START_DATE=$(date -d "yesterday" +%Y-%m-%d)
END_DATE=$START_DATE
```

**`this week`:** Monday of the current week through today.

```bash
# macOS
DOW=$(date +%u)   # 1=Mon … 7=Sun
DAYS_BACK=$((DOW - 1))
START_DATE=$(date -v-${DAYS_BACK}d +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)

# Linux fallback
START_DATE=$(date -d "last Monday" +%Y-%m-%d 2>/dev/null || date -d "$(date +%Y-%m-%d) -$(date +%u)-1 days" +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
```

**`last week`:** Monday through Sunday of the previous week.

```bash
# macOS
DOW=$(date +%u)
START_DATE=$(date -v-${DOW}d -v-6d +%Y-%m-%d)
END_DATE=$(date -v-${DOW}d +%Y-%m-%d)

# Linux fallback
START_DATE=$(date -d "last week Monday" +%Y-%m-%d)
END_DATE=$(date -d "last week Sunday" +%Y-%m-%d)
```

**`YYYY-MM-DD to YYYY-MM-DD`:** use the two dates directly as `START_DATE` and `END_DATE`.

Store both dates. Also compute `IS_RANGE` = true if `START_DATE != END_DATE`, false otherwise. This controls the filename slug in Step 11.

**Validate the parsed dates:** Check that `START_DATE` and `END_DATE` are non-empty and match `YYYY-MM-DD` format. If either is empty or malformed, tell the user:

> Could not parse the date range from your input. Supported formats:
> - `/standup` (today)
> - `/standup yesterday`
> - `/standup this week`
> - `/standup last week`
> - `/standup 2026-03-25 to 2026-03-31`

Stop here if validation fails.

Also verify that `START_DATE <= END_DATE`. If not, tell the user the start date must be before or equal to the end date.

### Step 4 — Search for notes in date range (parallel)

Run two Grep searches in parallel to find notes whose `date:` frontmatter field falls within the range.

**Search A — Sessions:**

```
pattern: "^date: "
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: content
glob: "*.md"
```

**Search B — Insights:**

```
pattern: "^date: "
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: content
glob: "*.md"
```

For each result, parse the `date:` value and keep only files where `START_DATE <= date <= END_DATE`. Collect the matching file paths into `MATCHED_FILES`.

If `MATCHED_FILES` is empty, tell the user:

> No session or insight notes found for the range **$START_DATE to $END_DATE**.

Stop here.

### Step 5 — Identify unsummarized session notes

From `MATCHED_FILES`, isolate those in `$SESSIONS_FOLDER/`. Use Grep to check each for the unsummarized frontmatter status (NOT body text — body text matches cause false positives from logged tool usage):

```
pattern: "^status: auto-logged"
path: <each session file>
output_mode: files_with_matches
```

**Defense-in-depth:** For each file matching `^status: auto-logged`, also check if it already has a real `## Summary` section (without `"AI summary unavailable"`). If so, the note was summarized by a legacy code path that never flipped the status. Skip it and fix the status:

```bash
sed -i '' 's/^status: auto-logged/status: summarized/' "$FILE_PATH"
```

Split into:
- `UNSUMMARIZED` — session files with `status: auto-logged` AND no real `## Summary`
- `SUMMARIZED` — all other matched files (sessions + insights + auto-fixed legacy notes)

### Step 6 — Deferred summarization for unsummarized notes

If `UNSUMMARIZED` is empty, skip to Step 7.

**Always parallelize unsummarized note upgrades.** For each unsummarized note, spawn a sub-agent immediately — even for 1-2 notes. Each sub-agent should call:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import upgrade_unsummarized_note
status = upgrade_unsummarized_note(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
print(status)
' "$NOTE_PATH" "$VAULT_PATH" "$SESSIONS_FOLDER" "$PROJECT"
```

The function returns a one-line status. If the status starts with `Failed:`, note the failure and fall back to the manual procedure below for that note. Collect results from all sub-agents before proceeding.

For each file in `UNSUMMARIZED`, if `upgrade_unsummarized_note()` is unavailable or returns a `Failed:` status, fall back to the manual upgrade procedure:

1. **Read the full file** using the Read tool.
2. **Extract frontmatter** — preserve it exactly as-is (everything between the opening `---` and closing `---`).
3. **Extract the full conversation** — read all content after frontmatter, including:
   - `## Conversation (raw)` — interleaved user and assistant messages
   - `## Tool Usage` — commands run, files edited, searches performed
   - `## Changes Made` — files touched
   - `## Errors Encountered` — errors from tool results
4. **Generate a detailed, specific summary** with these sections:
   - `## Summary` — 3-5 sentence overview: what problem was solved, what approach was taken, what was the outcome. Name specific technologies, files, and patterns.
   - `## Key Decisions` — Bulleted list with rationale. If none, write "None noted."
   - `## Changes Made` — Bulleted list with file paths and descriptions. If none, write "None noted."
   - `## Errors Encountered` — Bulleted list with error messages, root causes, and fixes. If none, write "None."
   - `## Open Questions / Next Steps` — Checkbox list of specific, actionable items. If none, write "None."
5. **Preserve the Session Metadata section** at the bottom if it exists.
6. **Write the upgraded note** using the Write tool to the same file path. Structure:
   - Original frontmatter (unchanged)
   - `# <title from original note>`
   - The five summary sections
   - Session Metadata section (if it existed)
7. Run `chmod 644 <filepath>` after writing.

**Important:** Do NOT modify frontmatter. Do NOT change the filename. Do NOT add or remove tags.

Move all upgraded files from `UNSUMMARIZED` into the working set alongside `SUMMARIZED`. Track the count of upgraded notes as `UPGRADED_COUNT`.

### Step 7 — Read and distill note content

Collect all matched files (now all summarized). Apply the /context-shield rule:

For each note, check its size using `wc -l`. Apply the context-shield rule **per note** based on size:

- **Notes under ~100 lines (~3000 tokens):** Read directly using the Read tool.
- **Notes over ~100 lines:** Spawn a `/context-shield` sub-agent to read in isolation and return a distilled summary.

When multiple notes need sub-agent reads, spawn them in parallel (one sub-agent per note).

From each note (whether read directly or via sub-agent), extract: project name (from frontmatter `project:` field), note type (`type:` field), date, title (first `# Heading`), summary (content of `## Summary` section), decisions (bullets from `## Key Decisions`), errors resolved (bullets from `## Errors Encountered`), open items (checkboxes from `## Open Questions / Next Steps`), and the filename (for wikilinks).

**Also extract closed items for the "Closed This Period" section:** For each session note in the date range, get the file modification time as a YYYY-MM-DD string (in the local timezone, matching how `START_DATE` and `END_DATE` were calculated):

```bash
# Get mtime as epoch, then format. Both forms work cross-platform.
MTIME_DATE=$(date -r "$file" +%Y-%m-%d 2>/dev/null || date -d @"$(stat -c %Y "$file")" +%Y-%m-%d)
```

The first form (`date -r FILE`) works on macOS. The Linux fallback uses `stat -c %Y` for the epoch then `date -d @EPOCH` to format. Both produce a YYYY-MM-DD string in the local timezone, which matches the format of `START_DATE` and `END_DATE`.

If `MTIME_DATE` is lexicographically within the range (`MTIME_DATE >= START_DATE && MTIME_DATE <= END_DATE`), Grep the file for `- \[x\]` lines under the `## Open Questions / Next Steps` section using the same line-range verification as for open items. Collect `(project, item_text)` tuples for each checked item.

Collect all distilled records as `NOTE_DATA`.

### Step 8 — Group by project

Group `NOTE_DATA` by `project` field. Sort projects alphabetically. Within each project, sort notes by `date` ascending (oldest first within the range). Separate sessions from insights within each project group.

If any notes have a missing or empty `project` field, group them under `(unknown project)`.

### Step 9 — Generate standup note body

Build the standup note body using the grouped data. For each project, emit a section:

```markdown
## $PROJECT_NAME

### Sessions
- [[filename-without-extension]] — $TITLE ($DATE)

### Insights
- [[filename-without-extension]] — $TITLE ($DATE)

### Decisions
- $DECISION_1
- $DECISION_2

### Errors Resolved
- $ERROR_1

### Open Items
- [ ] $OPEN_ITEM_1
- [ ] $OPEN_ITEM_2
```

Rules:
- Omit any subsection that has no content (e.g., if no decisions, skip `### Decisions` entirely).
- Omit the `### Insights` subsection if no insight notes exist for that project in the range.
- Wikilinks must use the bare filename without `.md` extension: `[[2026-04-05-my-note-a3f2]]`.
- Decisions and errors should be deduplicated across sessions in the same project.
- Open items should be listed as checkboxes (`- [ ]`).

Precede all project sections with a header block that includes a highlights summary and consolidated open items:

```markdown
# Standup: $START_DATE to $END_DATE

**Range:** $START_DATE → $END_DATE
**Projects covered:** $PROJECT_COUNT
**Sessions:** $SESSION_COUNT | **Insights:** $INSIGHT_COUNT

### Highlights
- **$PROJECT_A** — 1-2 sentences summarizing what was accomplished this period
- **$PROJECT_B** — 1-2 sentences summarizing what was accomplished this period

### Key Open Items
- [ ] $PROJECT_A: $MOST_IMPORTANT_OPEN_ITEM
- [ ] $PROJECT_B: $MOST_IMPORTANT_OPEN_ITEM
```

### Closed This Period

For each project that had at least one item closed within the standup window, render:

- **<project name>** (<N> closed)
  - <item text 1>
  - <item text 2>
  - ...

After the list, append this footnote on its own line in italics:

> _Detected via file modification time — may include items checked off earlier if a session note was edited during this window for unrelated reasons._

If zero items were closed across all projects, **omit this entire section** — do not render an empty header or the footnote.

Order projects alphabetically. Within each project, preserve the order items were extracted (file mtime descending — newest checkoffs first).

Rules for the header sections:
- **Highlights:** Include only projects with substantive work (skip vault-import-only or config-tweak sessions). Write 1-2 sentences per project summarizing the outcome, not the process. Order by impact/significance, not alphabetically.
- **Key Open Items:** Consolidate the most important open items across all projects (max ~5-7 items). Prefix each with the project name. These are the items that should drive next week's work. Skip low-priority or already-in-progress items.
- Both sections are written in the saved note AND presented in the conversation output.

If `IS_RANGE` is false (single day), use `# Standup: $DATE` and omit the "Range:" line. For single-day standups, the Highlights section may be omitted if only 1-2 sessions occurred.

### Step 10 — Build frontmatter

Construct the `source_notes` array from ALL matched filenames (sessions + insights), formatted as wikilinks:

```yaml
---
type: claude-standup
date: YYYY-MM-DD
date_range: "START_DATE to END_DATE"
projects:
  - project-a
  - project-b
source_notes:
  - "[[note-filename-1]]"
  - "[[note-filename-2]]"
tags:
  - claude/standup
  - claude/project/project-a
  - claude/project/project-b
---
```

Where:
- `date` is today's date (the date the standup was generated, not the range start)
- `date_range` is `"$START_DATE to $END_DATE"` (use the same value for single-day standups)
- `projects` lists all unique project names found, sorted alphabetically
- `source_notes` lists every contributing note as a wikilink (filename without `.md`)
- `tags` includes `claude/standup` plus a `claude/project/<name>` tag for each project covered by the standup

### Step 11 — Generate filename

Construct the filename:

1. **Date prefix:** `YYYY-MM-DD` (today's date, i.e., when the standup is generated)
2. **Slug:**
   - If `IS_RANGE` is false (single day): `standup-daily`
   - If `IS_RANGE` is true and the range spans exactly 7 days Mon-Sun: `standup-weekly`
   - Otherwise: `standup-range`
3. **Hash:** last 4 hex characters of the current timestamp hash:
   ```bash
   # macOS
   HASH=$(date +%s | md5 | cut -c29-32)
   # Linux fallback
   HASH=$(date +%s | md5sum | cut -c1-4)
   ```

Final filename: `YYYY-MM-DD-<slug>-<hash>.md`

Example: `2026-04-05-standup-daily-a3f2.md`

### Step 12 — Write the note

Run:

```bash
mkdir -p "$VAULT_PATH/$INSIGHTS_FOLDER"
```

Then use the **Write** tool to write the full note (frontmatter + body) to:

```
$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-<slug>-<hash>.md
```

Then set permissions:

```bash
chmod 644 "$VAULT_PATH/$INSIGHTS_FOLDER/YYYY-MM-DD-<slug>-<hash>.md"
```

### Step 13 — Present to user

Display the full standup in the conversation:

> **Standup for $START_DATE to $END_DATE:**

Then output the standup body (without frontmatter) as formatted markdown.

If `UPGRADED_COUNT > 0`, append:

> _Upgraded $UPGRADED_COUNT session note(s) with AI summaries._

Then confirm the saved file:

> **Saved:** `$VAULT_PATH/$INSIGHTS_FOLDER/<filename>`

## Edge Cases

- **No notes found for range:** Tell the user and suggest narrowing or widening the range, or checking that vault path is correct.
- **All notes are unsummarized:** Summarize all in Step 5 before proceeding — never skip summarization.
- **Single project:** Omit the per-project `## $PROJECT_NAME` heading if there is exactly one project; output the sections directly under the top-level header.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
- **macOS vs Linux date syntax:** Always try macOS syntax (`date -v`) first; fall back to Linux (`date -d`) if it fails.
- **Notes with missing project field:** Group under `(unknown project)` and note this to the user.
