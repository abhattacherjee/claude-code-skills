---
name: link
description: "Cross-references related Obsidian vault notes with bidirectional wikilinks. Use when: (1) /link to auto-suggest connections for the current session, (2) /link <description> to link specific notes, (3) user wants to connect related notes."
metadata:
  version: 1.0.0
---

# Link — Cross-Reference Vault Notes with Bidirectional Wikilinks

Search the Obsidian vault for notes related to the current session or a specific description, then create bidirectional wikilinks between them in their respective `## Related` sections.

**Tools needed:** Bash, Grep, Read, Write, Edit

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

> The vault folders do not exist. Run `/obsidian-setup` to fix this.

Stop here if FAIL.

### Step 3 — Determine mode

Check if the user provided an argument after `/link`.

- **Without argument** (bare `/link`): Go to Step 4A — auto-suggest connections for the current session.
- **With argument** (e.g. `/link authentication flow notes`): Go to Step 4B — explicit link by description.

### Step 4A — Auto-suggest connections

**4A.1 — Derive project name:**

```bash
basename "$(pwd)"
```

Store as `PROJECT`. Normalize: lowercase, hyphens for spaces.

**4A.2 — Find most recent session note for this project:**

```bash
ls -t "$VAULT_PATH/$SESSIONS_FOLDER"/ | head -20
```

From that list, identify the most recent file whose name contains the project name (or whose frontmatter contains `project: $PROJECT`). If you cannot determine from the filename alone, use Grep:

```
pattern: "project: $PROJECT"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
```

Sort the matched files by modification time and pick the most recent one. This is the **source note**. Read its full content using the Read tool.

**4A.3 — Extract keywords:**

From the current conversation topics and the source note's content, identify 3-5 meaningful keywords or concepts. Prefer: technology names, method names, architectural terms, error types, product feature names. Avoid generic words like "session", "note", "file".

**4A.4 — Search vault for related notes (parallel):**

Run these searches in parallel using Grep, case-insensitive (`-i: true`):

For each keyword (run as parallel searches across both folders):

```
pattern: "<keyword>"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
-i: true
```

```
pattern: "<keyword>"
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: files_with_matches
-i: true
```

Collect all matched files across all keywords. Exclude the source note itself.

**4A.5 — Search by overlapping tags:**

Read the source note's frontmatter and extract its `tags:` list. For each tag that starts with `claude/topic/`, run:

```
pattern: "<tag>"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
```

```
pattern: "<tag>"
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: files_with_matches
```

Add any new matches to your candidate list, excluding the source note.

**4A.6 — Rank candidates:**

Score each candidate file:
- +1 for each keyword match
- +1 for each shared tag
- +2 bonus if the file is in the insights folder (insights/decisions are higher value than raw sessions)

Sort by score descending. Take the top 5.

**4A.7 — Present candidates:**

> **Suggested connections for this session:**
>
> 1. [[note-filename-without-extension]] — <reason: shares topics X and Y>
> 2. [[note-filename-without-extension]] — <reason>
> 3. [[note-filename-without-extension]] — <reason>
>
> Which would you like to link? (e.g. `1,3` or `all` or `none`)

Wait for the user's response. If `none`, stop. For each selected candidate, go to Step 5 with the source note and that candidate as the target.

### Step 4B — Explicit link request

**4B.1 — Identify source note:**

If the user's description contains "this session", "current session", or similar: derive the project name from `basename "$(pwd)"` and find the most recent session note for that project (same as Step 4A.2).

Otherwise, use the user's description to search for a source note:

```
pattern: "<keywords from description>"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
-i: true
```

```
pattern: "<keywords from description>"
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: files_with_matches
-i: true
```

**4B.2 — Identify target note:**

Parse the user's description for target note clues. Search both folders:

```
pattern: "<target keywords>"
path: $VAULT_PATH/$SESSIONS_FOLDER/
output_mode: files_with_matches
-i: true
```

```
pattern: "<target keywords>"
path: $VAULT_PATH/$INSIGHTS_FOLDER/
output_mode: files_with_matches
-i: true
```

**4B.3 — Resolve ambiguity:**

If multiple matches were found for either source or target, present them and ask the user to pick:

> Found multiple matches. Which note did you mean?
>
> 1. [[note-filename-1]]
> 2. [[note-filename-2]]

Wait for the user's selection. Once both source and target are unambiguously identified, go to Step 5.

### Step 5 — Create bidirectional link

For each source-target pair:

**5.1 — Read the source note** using the Read tool.

**5.2 — Check for duplicate link in source:**

Search the source note's content for `[[target-filename]]` (filename without `.md`). If the link already exists in the source, skip writing to the source and note it:

> [[source-note]] already links to [[target-note]] — skipping source.

**5.3 — Add link to source note:**

- If the source note has a `## Related` section: use the Edit tool to append a new line to that section:
  `- [[target-filename]] — <one-line reason for the connection>`
- If no `## Related` section exists: use the Edit tool to append the following to the end of the file:

  ```
  
  ## Related
  
  - [[target-filename]] — <one-line reason for the connection>
  ```

- Use the Write tool only if the note is very short or the Edit tool would be unreliable due to unclear anchor text.

After writing, set permissions:

```bash
chmod 644 "<source-note-path>"
```

**5.4 — Read the target note** using the Read tool.

**5.5 — Check for duplicate link in target:**

Search the target note's content for `[[source-filename]]`. If it already exists, skip writing to the target:

> [[target-note]] already links back to [[source-note]] — skipping target.

**5.6 — Add link to target note** (mirror of 5.3, but reversed — source becomes the linked note):

- If the target note has a `## Related` section: append:
  `- [[source-filename]] — <one-line reason for the connection>`
- If no `## Related` section: append:

  ```
  
  ## Related
  
  - [[source-filename]] — <one-line reason for the connection>
  ```

After writing, set permissions:

```bash
chmod 644 "<target-note-path>"
```

### Step 6 — Confirm

For each linked pair, print:

> **Linked:** [[source-note]] ↔ [[target-note]]
> Reason: <connection reason>
> Links are bidirectional — both notes now reference each other in their Related section.

If multiple pairs were linked, print a summary after all pairs are done:

> **All done.** N bidirectional link(s) created.

## Edge Cases

- **No session note found for current project:** Tell the user no session note was found. Suggest they work in a session so one is auto-logged at session end, then run `/link` again.
- **No candidates found in auto-suggest:** Tell the user no related notes were found for the extracted keywords. Suggest running `/link <specific description>` to search manually.
- **Already linked (both directions):** Tell the user both notes already reference each other — no changes needed.
- **Only one direction already linked:** Add only the missing direction; do not duplicate the existing link.
- **Wikilink format:** Always use the filename without the `.md` extension: `[[2026-04-04-obsidian-brain-297a]]` not `[[2026-04-04-obsidian-brain-297a.md]]`.
- **Large vault (50+ files):** Never glob or read the entire folder. Always use Grep to search — never `ls` the whole folder for matching.
- **Config exists but vault path is invalid:** Warn the user and suggest running `/obsidian-setup` again.
