---
name: recall
description: "Loads historical context from the Obsidian vault for the current project. Summarizes any unsummarized session notes, then presents a context brief with recent sessions, open items, and curated insights. Also auto-detects open items completed in the most recent loaded session and offers to check them off. Use when: (1) /recall command, (2) /recall <project-name>, (3) resuming work on a project and wanting prior context."
metadata:
  version: 1.1.0
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

### Step 3 — Summarize unsummarized notes (deferred summarization)

This is the critical upgrade step. Search for raw/unsummarized session notes matching this project.

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

1. **Read the full file** using the Read tool.
2. **Extract frontmatter** — preserve it exactly as-is (everything between the opening `---` and closing `---`).
3. **Extract the full conversation** — look for all content after frontmatter. The raw note now includes:
   - `## Conversation (raw)` — interleaved user and assistant messages
   - `## Tool Usage` — commands run, files edited, searches performed
   - `## Changes Made` — files touched (from tool_use extraction)
   - `## Errors Encountered` — errors from tool results
   Read ALL of these sections — they provide the context needed for a high-quality summary.

4. **Generate a detailed, specific summary** from the raw content. Be precise — include file paths, function names, config values, and technical specifics. Produce these sections:
   - `## Summary` — 3-5 sentence overview. Include: what problem was being solved, what approach was taken, what was the outcome. Name specific technologies, files, and patterns.
   - `## Key Decisions` — Bulleted list with rationale. Each bullet should explain the decision AND why it was made (e.g., "Chose Redis over Memcached for session store — needed TTL per key for token expiry"). If none, write "None noted."
   - `## Changes Made` — Bulleted list with file paths and descriptions. Be specific: "Modified `src/auth/handler.ts` — added JWT refresh token rotation with 15min access / 7day refresh windows". Include commit messages if visible. If none, write "None noted."
   - `## Errors Encountered` — Bulleted list with error messages, root causes, AND fixes. Be specific: "`TypeError: Cannot read property 'token' of undefined` in handler.ts:42 — caused by null user object when session expired, fixed with optional chaining". If none, write "None."
   - `## Open Questions / Next Steps` — Checkbox list of specific, actionable items. Not vague ("improve performance") but concrete ("Add rate limiting to /api/auth/refresh endpoint, max 10 req/min per user"). If none, write "None."
5. **Preserve the Session Metadata section** at the bottom if it exists (commits, files touched).
6. **Write the upgraded note** using the Write tool — same file path. The structure must be:
   - Original frontmatter (unchanged)
   - `# <title from original note>`
   - The five summary sections generated above
   - The Session Metadata section (if it existed)

**Important:** Do NOT modify frontmatter. Do NOT change the filename. Do NOT add or remove tags.

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
