---
name: obsidian-setup
description: "First-run configuration and upgrade for the Obsidian Brain plugin. Sets up vault path, creates folders, copies dashboard templates, configures hookify nudges, and writes config. Idempotent — safe to re-run to pick up new features without overwriting existing config or dashboards. Use when: (1) first time installing obsidian-brain, (2) changing vault path, (3) /obsidian-setup command, (4) upgrading to a new version."
metadata:
  version: 1.1.0
---

# Obsidian Brain Setup

Configure the obsidian-brain plugin for first use. This skill validates prerequisites, creates vault folders, installs dashboard templates, writes the config file, and verifies everything works.

**Tools needed:** Bash, Write, Read

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Check for existing installation

Read `~/.claude/obsidian-brain-config.json`:

```bash
cat ~/.claude/obsidian-brain-config.json 2>/dev/null
```

**If the file exists and is valid JSON**, extract `vault_path` and present:

> **Existing obsidian-brain installation detected.**
> - Vault path: `<vault_path from config>`
>
> Would you like to:
> - **upgrade** — add new features (dashboards, nudges) without touching existing config or dashboards
> - **reconfigure** — start fresh (will overwrite config and dashboards)
> - **cancel** — exit setup

If **upgrade**: store `MODE=upgrade`. Store `VAULT_PATH` from the existing config's `vault_path` field. Also extract `sessions_folder` (default `claude-sessions`), `insights_folder` (default `claude-insights`), and `dashboards_folder` (default `claude-dashboards`). Skip to Step 5 (Create vault folders — `mkdir -p` is already safe). In upgrade mode:
- Step 5 (Create vault folders): runs normally (`mkdir -p` is idempotent)
- Step 6 (Install dashboards): only write dashboard files that do NOT already exist (`test -f` before each write)
- Step 7 (Write config): SKIP entirely — preserve existing config
- Step 8 (Verify vault access): runs normally
- Step 9 (Configure claudeception nudge): runs normally (has its own idempotency check)
- Step 10 (Print success message): show upgrade-specific message

If **reconfigure**: store `MODE=reconfigure`. Proceed to Step 2 (Ask for vault path) as normal — full setup flow.

If **cancel**: stop here.

**If the file does not exist or is invalid JSON**: store `MODE=fresh`. Proceed to Step 2 (Ask for vault path) — first-time setup.

### Step 2 — Ask for vault path

Ask the user:

> What is the absolute path to your Obsidian vault? (e.g. `/Users/you/obsidian/my-vault`)

Store the response as `VAULT_PATH`. Strip any trailing slash.

### Step 3 — Validate the vault path

Run:

```bash
test -d "$VAULT_PATH" && test -w "$VAULT_PATH" && echo "OK" || echo "FAIL"
```

If FAIL, tell the user the path does not exist or is not writable and ask them to correct it. Repeat until OK.

### Step 4 — Check claude CLI availability

Run:

```bash
which claude && echo "OK" || echo "FAIL"
```

If FAIL, warn the user:

> The `claude` CLI was not found on PATH. Hook-based AI summarization will not work until it is installed. You can continue setup, but session notes will be raw (unsummarized) until `claude` is available.

Continue regardless — this is a warning, not a blocker.

### Step 5 — Create vault folders

Run:

```bash
mkdir -p "$VAULT_PATH/claude-sessions" "$VAULT_PATH/claude-insights" "$VAULT_PATH/claude-dashboards"
```

### Step 6 — Install dashboard templates

For each dashboard file below, check if it already exists before writing:

```bash
test -f "$VAULT_PATH/claude-dashboards/<filename>" && echo "EXISTS" || echo "MISSING"
```

If EXISTS and `MODE=upgrade`, skip this file — preserve user customizations.
Otherwise (MISSING, or `MODE=fresh`, or `MODE=reconfigure`), write the file using the Write tool.

**Dashboard files to install:**

**File: `$VAULT_PATH/claude-dashboards/sessions-overview.md`**

```markdown
# Claude Sessions Overview

## Recent Sessions
\```dataview
TABLE date, project, git_branch, duration_minutes
FROM "claude-sessions"
WHERE type = "claude-session"
SORT date DESC
LIMIT 20
\```

## Recent Insights
\```dataview
TABLE date, project, tags
FROM "claude-insights"
WHERE type = "claude-insight"
SORT date DESC
LIMIT 10
\```

## Active Decisions
\```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-decision" AND status = "active"
SORT date DESC
\```
```

**File: `$VAULT_PATH/claude-dashboards/project-index.md`**

```markdown
# Project Index

## Sessions by Project
\```dataview
TABLE length(rows) AS "Sessions", min(rows.date) AS "First", max(rows.date) AS "Last"
FROM "claude-sessions"
WHERE type = "claude-session"
GROUP BY project
SORT length(rows) DESC
\```

## Error Fixes (troubleshooting library)
\```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-error-fix"
SORT date DESC
\```
```

**File: `$VAULT_PATH/claude-dashboards/weekly-review.md`**

```markdown
# This Week in Claude

\```dataview
TABLE date, project, type
FROM "claude-sessions" OR "claude-insights"
WHERE date >= date(today) - dur(7 days)
SORT date DESC
\```
```

**File: `$VAULT_PATH/claude-dashboards/learning-velocity.md`**

```markdown
# Learning Velocity

## Topics by Frequency
\```dataviewjs
let pages = dv.pages('"claude-insights"')
    .where(p => p.tags);

let topics = {};
for (let p of pages) {
    let tags = p.tags || [];
    if (!Array.isArray(tags)) tags = [tags];
    for (let tag of tags) {
        if (typeof tag === 'string' && tag.startsWith("claude/topic/")) {
            let topic = tag.replace("claude/topic/", "");
            topics[topic] = (topics[topic] || 0) + 1;
        }
    }
}

dv.table(
    ["Topic", "Notes"],
    Object.entries(topics)
        .sort((a, b) => b[1] - a[1])
        .map(([topic, count]) => [topic, count])
);
\```

## Recent Retrospectives
\```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-retro"
SORT date DESC
LIMIT 10
\```

## Error Patterns (Most Common)
\```dataviewjs
let pages = dv.pages('"claude-insights"')
    .where(p => p.type === "claude-error-fix");

let topics = {};
for (let p of pages) {
    let tags = p.tags || [];
    if (!Array.isArray(tags)) tags = [tags];
    for (let tag of tags) {
        if (typeof tag === 'string' && tag.startsWith("claude/topic/")) {
            let topic = tag.replace("claude/topic/", "");
            topics[topic] = (topics[topic] || 0) + 1;
        }
    }
}

dv.table(
    ["Error Topic", "Occurrences"],
    Object.entries(topics)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 15)
        .map(([topic, count]) => [topic, count])
);
\```
```

**File: `$VAULT_PATH/claude-dashboards/decision-timeline.md`**

```markdown
# Decision Timeline

## Active Decisions
\```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-decision" AND status = "active"
SORT date DESC
\```

## All Decisions (Chronological)
\```dataview
TABLE date, project, status
FROM "claude-insights"
WHERE type = "claude-decision"
SORT date DESC
\```

## Superseded Decisions
\```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-decision" AND status = "superseded"
SORT date DESC
\```

## Decisions by Project
\```dataview
TABLE length(rows) AS "Decisions", min(rows.date) AS "First", max(rows.date) AS "Last"
FROM "claude-insights"
WHERE type = "claude-decision"
GROUP BY project
SORT length(rows) DESC
\```
```

**Important:** The backslash before the triple backticks above is an escape for this document only. When writing the actual files, use plain triple backticks (no backslash).

### Step 7 — Write config file

**If `MODE=upgrade`:** Skip this step — preserve existing config.

**If `MODE=fresh` or `MODE=reconfigure`:**

Write `~/.claude/obsidian-brain-config.json` with this exact structure:

```json
{
  "vault_path": "<VAULT_PATH value from Step 2>",
  "sessions_folder": "claude-sessions",
  "insights_folder": "claude-insights",
  "dashboards_folder": "claude-dashboards",
  "min_messages": 3,
  "min_duration_minutes": 2,
  "summary_model": "haiku",
  "auto_log_enabled": true,
  "snapshot_on_compact": true,
  "snapshot_on_clear": true
}
```

Replace `<VAULT_PATH value from Step 2>` with the actual vault path. Ensure the file is valid JSON.

First run `mkdir -p ~/.claude` to ensure the directory exists.

### Step 8 — Verify vault access

Run:

```bash
TESTFILE="$VAULT_PATH/claude-sessions/.obsidian-brain-test-$$"
echo "test" > "$TESTFILE" && test -f "$TESTFILE" && rm "$TESTFILE" && echo "OK" || echo "FAIL"
```

If FAIL, warn that vault writes are not working and ask the user to check permissions.

### Step 9 — Configure claudeception nudge (idempotent)

Check if the claudeception-to-compress nudge is already configured **globally** (in `~/.claude/`, not the project `.claude/`):

```bash
test -f ~/.claude/hookify.claudeception-compress-nudge.local.md && echo "EXISTS" || echo "MISSING"
```

If EXISTS, skip this step — the nudge is already configured.

If MISSING, write the hookify rule file directly to `~/.claude/` using the Write tool:

**File: `~/.claude/hookify.claudeception-compress-nudge.local.md`**

```markdown
---
name: claudeception-compress-nudge
enabled: true
event: stop
pattern: Result:\s*PASS|\.claude/skills/[^/]+/SKILL\.md|created skill|skill file written|extracted knowledge
action: warn
---

💡 **Claudeception extracted knowledge from this session.** Run `/compress` to save it to your Obsidian vault.
```

**Important:** This rule MUST be in `~/.claude/` (global), not the project's `.claude/` directory. The nudge should trigger in any project where claudeception runs, not just obsidian-brain.

This is a soft nudge — a non-blocking suggestion, not automatic execution.

### Step 10 — Print success message

**If `MODE=upgrade`:**

> **Obsidian Brain upgraded!**
>
> - Vault path: `<VAULT_PATH>` (unchanged)
> - Config: preserved (unchanged)
> - New dashboards: installed (existing dashboards preserved)
> - Claudeception nudge: configured
>
> Re-run `/obsidian-setup` anytime to pick up new features.

**If `MODE=fresh` or `MODE=reconfigure`:**

> **Obsidian Brain setup complete!**
>
> - Vault path: `<VAULT_PATH>`
> - Config written to: `~/.claude/obsidian-brain-config.json`
> - Folders created: `claude-sessions/`, `claude-insights/`, `claude-dashboards/`
> - Dashboards installed: `sessions-overview.md`, `project-index.md`, `weekly-review.md`, `learning-velocity.md`, `decision-timeline.md`
> - Claudeception nudge: configured (run `/compress` reminder after knowledge extraction)
>
> **Next step — install the Dataview plugin in Obsidian:**
> 1. Open Obsidian Settings > Community Plugins > Browse
> 2. Search for "Dataview" and install it
> 3. Enable the plugin, then go to Dataview settings and turn on:
>    - **Enable JavaScript Queries**
>    - **Enable Inline Queries**
> 4. The dashboards in `claude-dashboards/` will start rendering automatically
>
> Hooks are already registered via `hooks.json` — session logging will begin on your next Claude Code session.
