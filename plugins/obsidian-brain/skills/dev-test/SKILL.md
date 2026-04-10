---
name: dev-test
description: "Install dev version of obsidian-brain into the plugin cache for local testing, or restore the original. Use when: (1) /dev-test install to test unreleased changes, (2) /dev-test restore to put back the original, (3) /dev-test to check current status."
metadata:
  version: 1.0.0
---

# Dev Test — Install/Restore Dev Plugin for Testing

Swaps the installed plugin cache with the current repo working copy for local testing. After install, start a new Claude Code session to pick up the changes.

**Tools needed:** Bash

## Procedure

### Step 1 — Parse argument

Check the argument passed to `/dev-test`:

- `install` → go to Step 2
- `restore` → go to Step 3
- No argument or `status` → go to Step 4

### Step 2 — Install dev version

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
./scripts/test-dev-skill.sh install
```

Report the output. Then tell the user:

> Dev version installed. **Start a new Claude Code session** to pick up the changes. When done testing, run `/dev-test restore`.

Stop here.

### Step 3 — Restore original

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
./scripts/test-dev-skill.sh restore
```

Report the output. Then tell the user:

> Original version restored. **Start a new session** to pick up the restored version.

Stop here.

### Step 4 — Show status

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
./scripts/test-dev-skill.sh status
```

Report the output.
