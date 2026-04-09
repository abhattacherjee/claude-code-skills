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

Store the extracted terms as `SEARCH_TERMS`. Keep the original question for use in Step 6.

### Step 3 — Search vault (3 parallel agents)

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

### Step 4 — Rank results

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

### Step 5 — Read top notes (context shield)

Read the top 5–10 files from `RANKED_FILES`. Apply the following size-based strategy:

- **Files under ~100 lines:** Read directly with the Read tool.
- **Files over ~100 lines:** Use the `/context-shield` skill (parallel, one sub-agent per file). Each sub-agent reads the file in isolation and returns a distilled summary relevant to the question.

For each file, extract:
- Note type (session, insight, decision, error-fix)
- Date
- Key content relevant to the question — decisions made, patterns observed, errors and fixes
- Exact filename (without path) for use as a wikilink citation

Store all extracted content as `NOTE_SUMMARIES`.

### Step 6 — Synthesize answer

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

If the notes contain contradictory information (e.g. a decision was changed later), surface that explicitly:
> "You initially chose X ([[older-note]]), but later switched to Y ([[newer-note]])."

### Step 7 — Present answer

Display the synthesized answer from Step 6 in the conversation.

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
