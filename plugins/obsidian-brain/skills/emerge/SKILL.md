---
name: emerge
description: "Surface unnamed patterns across vault notes. Use when: (1) /emerge for last 30 days, (2) /emerge 14d for custom window, (3) /emerge this week."
metadata:
  version: 1.0.0
---
# Emerge — Discover Patterns Across Your Obsidian Vault

**Tools needed:** Bash, Agent, Write, Read

## Procedure

### Step 0 — Create task manifest

```
TaskCreate: subject="Collect and upgrade vault corpus", activeForm="Collecting vault corpus"
TaskCreate: subject="Analyze patterns across notes", activeForm="Analyzing patterns"
TaskCreate: subject="Build emerge report", activeForm="Building report"
TaskCreate: subject="Write vault note", activeForm="Writing vault note"
TaskCreate: subject="Present results", activeForm="Presenting results"
```
Track task IDs. Set task #1 to `in_progress`.

### Step 1 — Parse args + upgrade + collect corpus
Parse DAYS: no arg=30, `Nd`/`N days`=N, `this week`=days since Monday.

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from emerge_cli import run_corpus; run_corpus(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
' "$DAYS"
```

If STATUS starts with `CACHED:`, report "Using cached corpus (< 15 min old, same window)" and skip to Step 2.

Parse STATUS (`OK:<total>:<upgraded>:<failed>` or `EMPTY:0:0:0`). EMPTY -> tell user to widen window, stop. Report upgrades. If `failed > 0` -> Step 1f, else Step 2. Mark task #1 `completed`.
### Step 1f — Sub-agent fallback (skip if no failures)
Spawn parallel sub-agents for failed notes using /recall Path C Wave 2-3 pattern (read note, write summary to temp, write back via `upgrade_note_with_summary`). Re-collect:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from emerge_cli import run_recollect; run_recollect(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
' "$DAYS"
```

### Step 2 — Pattern synthesis
Set task #2 to `in_progress`. Spawn one Agent:
```
Agent({
  description: "Analyze vault corpus for cross-cutting patterns",
  prompt: "Read ~/.claude/obsidian-brain/emerge-corpus.json. Analyze and write to ~/.claude/obsidian-brain/emerge-analysis.md with these 5 categories:\n\n## Recurring Technical Patterns\nPatterns in approaches, tools, or architecture across 2+ sessions.\n\n## Error Clusters\nRepeated error types, common root causes, or failure modes.\n\n## Decision Trends\nDirectional shifts in technical decisions over time.\n\n## Cross-Project Connections\nShared themes between projects. Skip if only 1 project.\n\n## Emergent Practices\nImplicit conventions that formed organically but aren't documented.\n\nFor each pattern: descriptive name, 2-3 examples with note references, confidence (strong/moderate/tentative).\n\nWrite using the Write tool. Return ONLY: WRITTEN:~/.claude/obsidian-brain/emerge-analysis.md"
})
```

If no `WRITTEN:` response, report failure and stop. Mark task #2 `completed`.

### Step 3 — Build output + write note
```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from emerge_cli import run_build_note; run_build_note()
' 2>&1
```

Parse `SAVED:<path>` and everything after `---REPORT---`. Mark tasks #3-#4 `completed`.

### Step 4 — Present to user
Display report prefixed with **Pattern Discovery Results:**. Confirm saved path. Mark task #5 `completed`.

## Edge Cases
- **No notes in window:** Suggest widening (e.g., `/emerge 60d`).
- **Only 1 project:** Sub-agent skips Cross-Project Connections.
- **Very large corpus (200+):** Python distills to ~25k tokens JSON, fits one sub-agent.
- **Config not found:** Tell user to run `/obsidian-setup` first.
