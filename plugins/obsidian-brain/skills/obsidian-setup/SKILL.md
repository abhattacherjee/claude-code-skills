---
name: obsidian-setup
description: "First-run configuration and upgrade for the Obsidian Brain plugin. Sets up vault path, creates folders, copies dashboard templates, configures hookify nudges, and writes config. Idempotent — safe to re-run to pick up new features without overwriting existing config or dashboards. Use when: (1) first time installing obsidian-brain, (2) changing vault path, (3) /obsidian-setup command, (4) upgrading to a new version."
metadata:
  version: 1.3.0
---

# Obsidian Brain Setup

Configure the obsidian-brain plugin for first use. This skill validates prerequisites, creates vault folders, installs dashboard templates, writes the config file, and verifies everything works.

**Tools needed:** Bash, Write, Read

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Check for existing installation

Check for existing config:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
c = load_config()
vp = c.get("vault_path", "")
if vp:
    sess = c.get("sessions_folder", "claude-sessions")
    ins = c.get("insights_folder", "claude-insights")
    dash = c.get("dashboards_folder", "claude-dashboards")
    print(f"EXISTING VAULT={vp} SESS={sess} INS={ins} DASH={dash}")
else:
    print("NO_CONFIG")
'
```

**If the output starts with `EXISTING`**, extract `VAULT_PATH` and present:

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

**If the output is `NO_CONFIG`**: store `MODE=fresh`. Proceed to Step 2 (Ask for vault path) — first-time setup.

### Step 1.5 — Permission pre-flight check

Before any out-of-workspace writes, test whether Claude Code can write to `~/.claude/`:

```bash
echo "test" > ~/.claude/.obsidian-brain-canary 2>&1 && rm -f ~/.claude/.obsidian-brain-canary && echo "OK" || echo "FAIL"
```

If **OK**: proceed silently to Step 2.

If **FAIL**: present the following message using AskUserQuestion:

> **Heads up — setup needs write access outside this project directory.**
>
> Obsidian Brain writes config to `~/.claude/` and notes to your Obsidian vault. Your current Claude Code permissions block writes outside the working directory.
>
> Choose how to fix this:
>
> 1. **Switch permission mode (recommended)** — Press `Shift+Tab` to switch to "accept edits" mode for this session. Or use `/config` to change `permissions.defaultMode` permanently. Then re-run `/obsidian-setup`.
>
> 2. **Whitelist paths permanently** — Add `$HOME/.claude` and your vault's parent directory to `sandbox.filesystem.allowWrite` in `~/.claude/settings.json`. **Use absolute paths** — `~` is not expanded inside JSON string values:
>    ```json
>    {
>      "sandbox": {
>        "filesystem": {
>          "allowWrite": ["/Users/you/.claude", "/Users/you/Documents/vault-parent"]
>        }
>      }
>    }
>    ```
>    Replace `/Users/you` with your actual home directory (run `echo $HOME` to find it). Then re-run `/obsidian-setup`.
>
> 3. **I'll handle it myself** — Continue setup and approve or fix writes as they come up.

**Behavior per option:**
- **Option 1:** Print the instruction, then stop. User changes mode and re-runs `/obsidian-setup`.
- **Option 2:** Print the JSON snippet with absolute paths. In upgrade mode (`MODE=upgrade`), substitute the known vault parent path from the existing config. In fresh mode, show only the `$HOME/.claude` entry with a note that the vault parent must be added after the user provides the vault path. Then stop. User edits settings and re-runs.
- **Option 3:** Continue with setup as normal. Writes may fail and the user deals with each one.

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

First, test that the vault path is writable:

```bash
echo "test" > "$VAULT_PATH/.obsidian-brain-canary" 2>&1 && rm -f "$VAULT_PATH/.obsidian-brain-canary" && echo "OK" || echo "FAIL"
```

If **FAIL**, tell the user:

> **Cannot write to your vault at `$VAULT_PATH`.** This is likely a sandbox restriction. Add your vault's parent directory to `sandbox.filesystem.allowWrite` in `~/.claude/settings.json`, or switch to "accept edits" mode (`Shift+Tab`), then re-run `/obsidian-setup`.

Stop here if FAIL.

If **OK**, create the folders:

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

**File: `$VAULT_PATH/claude-dashboards/open-items.md`**

```markdown
# Open Items — All Projects

Cross-project view of all unchecked `- [ ]` items from session notes' `## Open Questions / Next Steps` sections, scoped to the last 90 days. Items older than 90 days fall off this view — use `/check-items` (unbounded) or `/vault-search` to find them.

\```dataviewjs
// Single-pass: scan all sessions in the last 90 days exactly once,
// build a master list, then render each section from in-memory data.

const cutoff90 = dv.date("today").minus(dv.duration("90 days"));
const cutoff30 = dv.date("today").minus(dv.duration("30 days"));
const cutoff7  = dv.date("today").minus(dv.duration("7 days"));

const pages = dv.pages('"claude-sessions"')
    .where(p => p.type === "claude-session" && p.date && p.date >= cutoff90);

const allItems = [];
for (const p of pages) {
    const content = await dv.io.load(p.file.path);
    if (!content) continue;
    // CRLF-tolerant: \r?\n in lookahead, split on /\r?\n/
    const match = content.match(/## Open Questions[^\r\n]*\r?\n([\s\S]*?)(?=\r?\n## |\r?\n# |$)/);
    if (!match) continue;
    const lines = match[1].split(/\r?\n/);
    for (const line of lines) {
        const m = line.match(/^- \[ \] (.+?)\s*$/);
        if (m) {
            allItems.push({
                project: p.project || "unknown",
                item: m[1],
                date: p.date,
                file: p.file.link
            });
        }
    }
}

// ----- By Project -----
dv.header(2, "By Project");

if (allItems.length === 0) {
    dv.paragraph("No open items in the last 90 days.");
} else {
    const byProject = {};
    for (const i of allItems) {
        if (!byProject[i.project]) byProject[i.project] = [];
        byProject[i.project].push(i);
    }
    const projectNames = Object.keys(byProject).sort();
    for (const project of projectNames) {
        const items = byProject[project];
        dv.header(3, project + " (" + items.length + ")");
        // Render as table to preserve clickable file link
        dv.table(
            ["Item", "Source"],
            items.map(i => [i.item, i.file])
        );
    }
}

// ----- Recent (last 7 days) -----
dv.header(2, "Recent (last 7 days)");

const recent = allItems.filter(i => i.date >= cutoff7);
if (recent.length === 0) {
    dv.paragraph("No open items from sessions in the last 7 days.");
} else {
    dv.table(
        ["Project", "Item", "Source"],
        recent.map(i => [i.project, i.item, i.file])
    );
}

// ----- Items from sessions 30-90 days ago -----
dv.header(2, "Items from sessions 30-90 days ago");
dv.paragraph("These are unchecked items captured in session notes that are 30-90 days old. The same item may also appear in a more recent session — in that case it will also show in the \"Recent\" section above. Filter is by source session date, not by item-tracking duration.");

const stale = allItems
    .filter(i => i.date < cutoff30)
    .sort((a, b) => a.date - b.date);
if (stale.length === 0) {
    dv.paragraph("No items from sessions 30-90 days ago.");
} else {
    dv.table(
        ["Project", "Item", "From", "Source"],
        stale.map(i => [i.project, i.item, i.date.toFormat("yyyy-MM-dd"), i.file])
    );
}

// ----- Stats -----
dv.header(2, "Stats");

const statsByProject = {};
let oldestDate = null;
for (const i of allItems) {
    statsByProject[i.project] = (statsByProject[i.project] || 0) + 1;
    if (!oldestDate || i.date < oldestDate) oldestDate = i.date;
}

dv.paragraph("**Total open items (last 90 days):** " + allItems.length);
dv.paragraph("**Projects with open items:** " + Object.keys(statsByProject).length);
if (oldestDate) {
    dv.paragraph("**Oldest open item from:** " + oldestDate.toFormat("yyyy-MM-dd"));
}

if (Object.keys(statsByProject).length > 0) {
    dv.table(
        ["Project", "Open Items"],
        Object.entries(statsByProject).sort((a, b) => b[1] - a[1])
    );
}
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
> - Dashboards installed: `sessions-overview.md`, `project-index.md`, `weekly-review.md`, `learning-velocity.md`, `decision-timeline.md`, `open-items.md`
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
