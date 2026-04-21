---
name: vault-ask
description: "Asks questions and gets synthesized answers grounded in vault history with source citations. Use when: (1) /vault-ask <question> to reason over vault knowledge, (2) user wants to know what their notes say about a topic, (3) user wants cross-project pattern analysis."
metadata:
  version: 1.0.0
---

# Vault Ask

Synthesizes a reasoned answer to the user's question by searching session and insight notes in the Obsidian vault and citing sources. Returns a grounded answer, not a list of matches.

**Tools needed:** Grep, Read, Bash

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
project = os.path.basename(os.getcwd()).lower().replace(" ", "-")
print("VAULT=" + c["vault_path"])
print("SESS=" + c.get("sessions_folder", "claude-sessions"))
print("INS=" + c.get("insights_folder", "claude-insights"))
print("PROJECT=" + project)
'
```

Parse each output line as KEY=VALUE, splitting on the first `=`.

If the command exits non-zero or prints ERROR, tell the user:

> Config not found. Run `/obsidian-setup` first to configure your Obsidian vault.

Stop here if config is missing.

Construct the two search directories:

- `SESSIONS_DIR` = `<vault_path>/<sessions_folder>`
- `INSIGHTS_DIR` = `<vault_path>/<insights_folder>`

Validate vault access:

```bash
test -d "$SESSIONS_DIR" && test -d "$INSIGHTS_DIR" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user:

> The vault folders do not exist or are not accessible. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 2 — Parse the question

The user provides a question after `/vault-ask`. Extract 3–6 key search terms from it:

- **Technology names** — e.g. `Redis`, `GraphQL`, `JWT`, `Postgres`
- **Concept keywords** — e.g. `error handling`, `rate limiting`, `caching`
- **Action words indicating note types** — e.g. `decided` → look for decision notes, `fixed` → look for error-fix notes

Store the extracted terms as `SEARCH_TERMS`. Keep the original question for use in Step 7.

### Step 3 — FTS pre-filter (fast path)

Before spawning search agents, try the vault index for instant results. Join `SEARCH_TERMS` into a single space-separated string (`SEARCH_TERMS_JOINED`). Then run:

```bash
python3 -c '
import sys, os, json, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
from vault_index import ensure_index, search_vault
c = load_config()
db = ensure_index(c["vault_path"], [c.get("sessions_folder", "claude-sessions"), c.get("insights_folder", "claude-insights")])
results = search_vault(
    db,
    sys.argv[1],
    project=sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "None" else None,
    limit=15,
)
print(json.dumps(results))
' "$SEARCH_TERMS_JOINED" "$PROJECT"
```

If the output is a non-empty JSON array with 5+ results: extract the `path` field from each result and use those file paths as `CANDIDATE_FILES`. Skip Step 4 entirely and proceed directly to Step 5.

If fewer than 5 results or the command fails (non-zero exit, invalid JSON, import error): fall through to Step 4 to cast a wider net with parallel Grep agents.

### Step 4 — Search vault (3 parallel agents)

Launch three Grep searches in parallel — one per agent below. Use the Grep tool (never Bash grep).

**Agent 1 — Session content:**
For each term in `SEARCH_TERMS`, run:
```
Grep(pattern="<term>", path=SESSIONS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)
```
Collect the union of all file paths returned.

**Agent 2 — Insight content:**
For each term in `SEARCH_TERMS`, run:
```
Grep(pattern="<term>", path=INSIGHTS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)
```
Collect the union of all file paths returned.

**Agent 3 — Tag search (both folders):**
For each term in `SEARCH_TERMS`, run two Grep calls:
```
Grep(pattern="claude/topic/.*<term>", path=SESSIONS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)
Grep(pattern="claude/topic/.*<term>", path=INSIGHTS_DIR, glob="*.md", output_mode="files_with_matches", -i=true)
```
Collect all file paths returned.

Combine results from all three agents. Deduplicate by file path. Store as `CANDIDATE_FILES`.

If `CANDIDATE_FILES` is empty, tell the user:

> No vault notes found matching your question. Try `/vault-search` with individual keywords to explore what's available.

Stop here.

### Step 5 — Rank results

Score each file in `CANDIDATE_FILES` using these rules:

| Condition | Points |
|-----------|--------|
| Each search term found in content (Agent 1 or 2 match) | +2 per term |
| Note type is `claude-insight`, `claude-decision`, or `claude-error-fix` | +3 |
| Note type is `claude-session` | +1 |
| File date is within the last 30 days (relative to today) | +1 |
| Matching tag found (Agent 3 match) | +2 |

To determine note type and date without reading the full file, run:
```
Read(file_path="<path>", limit=40)
```
to get frontmatter fields (`type:`, `date:`). Use 40 lines because some notes (e.g., standups with large `source_notes` arrays) have frontmatter exceeding 20 lines. If `type:` or `date:` is not found within the first 40 lines, read the full frontmatter.

Sort `CANDIDATE_FILES` by score descending. Take the top 10. Store as `RANKED_FILES`.

### Step 6 — Read top notes (context shield)

Read the top 5–10 files from `RANKED_FILES`. Apply the following size-based strategy:

- **Files under ~100 lines:** Read directly with the Read tool.
- **Files over ~100 lines:** Use the `/context-shield` skill (parallel, one sub-agent per file). Each sub-agent reads the file in isolation and returns a distilled summary relevant to the question.

For each file, extract:
- Note type (session, insight, decision, error-fix, snapshot)
- Date
- Key content relevant to the question — decisions made, patterns observed, errors and fixes
- Exact filename (without path) for use as a wikilink citation

**Snapshot-aware reading.** If a ranked file has `type: claude-snapshot`, also resolve its parent session via the `source_session_note` frontmatter wikilink and include the parent session body in the synthesis pool — the snapshot alone only captures a mid-session fragment. If a ranked file has `type: claude-session` and has associated snapshots, fetch those snapshot summaries via the shared helper and include them alongside the session body:

```bash
python3 -c '
import sys, os, json, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from pathlib import Path
from obsidian_utils import fetch_snapshot_summaries
snaps = fetch_snapshot_summaries(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4])
print(json.dumps([{"hhmmss": s["hhmmss"], "trigger": s["trigger"], "summary": s["summary"]} for s in snaps]))
' "$SESSIONS_DIR" "$SESSION_ID" "$DATE" "$PROJECT"
```

The goal is that an answer synthesized from a session hit reflects the full session arc (pre-compact + post-compact), not only the tail transcript.

Store all extracted content as `NOTE_SUMMARIES`.

### Step 7 — Synthesize answer

Using `NOTE_SUMMARIES`, synthesize a comprehensive answer to the user's question. Follow these rules strictly:

1. **Lead with the answer, not the methodology.** Do not begin with "I searched your vault..." — begin with the actual answer.

2. **Cite sources inline using wikilinks.** Reference the note filename (without extension) as a wikilink:
   > "You chose Redis over Memcached ([[2026-04-04-use-redis-a3f2-decision]]) because TTL-per-key was required for token expiry."

3. **Distinguish certainty levels** based on the evidence:
   - `"You explicitly decided..."` — use when a decision note clearly records the choice
   - `"Based on your sessions, it appears..."` — use when the pattern is inferred from session content
   - `"Limited context available..."` — use when only one or two notes weakly touch the topic

4. **End with a Sources section:**
   ```markdown
   ### Sources
   - [[note-filename-1]] — <what this note contributed to the answer>
   - [[note-filename-2]] — <what this note contributed to the answer>
   ```

5. **Cite snapshot parents.** When a snapshot note contributes to the answer, cite BOTH the snapshot and its parent session so the user can navigate up:
   > "Mid-session you sketched the API shape ([[2026-04-18-demo-aa-snapshot-140000]]; parent: [[2026-04-18-demo-aa]])."

If the notes contain contradictory information (e.g. a decision was changed later), surface that explicitly:
> "You initially chose X ([[older-note]]), but later switched to Y ([[newer-note]])."

### Step 8 — Present answer

Display the synthesized answer from Step 7 in the conversation.

Do NOT write anything to the vault — this skill is read-only.

If the user asks a follow-up question, return to Step 2 with the new question.

## Key distinction

`/vault-search` returns a ranked list of matching notes.
`/vault-ask` returns a reasoned, cited answer synthesized from note content.

Use `/vault-ask` when the user wants to know _what_ their notes say, not _which_ notes match.

## Edge Cases

- **Single result:** Synthesize from that one source. Be explicit about limited coverage: "Only one relevant note was found..."
- **All results are old (>90 days):** Mention this: "Your most recent notes on this topic are from `<date>`."
- **Question is ambiguous (multiple interpretations):** Answer each interpretation with a subheading, or ask the user to clarify before proceeding.
- **No matching tags, only content matches:** That is fine — tag matches are bonus scoring, not required.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
