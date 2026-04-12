---
name: vault-config
description: "Interactive configuration menu for obsidian-brain settings. Use when: (1) /vault-config to view and change settings, (2) user wants to toggle log_raw_messages, (3) user wants to adjust session filtering thresholds."
metadata:
  version: 1.0.0
---

# Vault Config — Manage obsidian-brain Settings

Interactive menu for viewing and changing obsidian-brain configuration, one setting at a time.

**Tools needed:** Bash, Read, Write

## Procedure

### Step 1 — Load current config

Run:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
python3 -c '
import sys, os, json
import glob; sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")), default="hooks"))
from obsidian_utils import load_config
c = load_config()
if not c.get("vault_path"):
    print("ERROR: not configured", file=sys.stderr)
    sys.exit(1)
print(json.dumps(c, indent=2))
'
```

Parse the JSON output into a config dict.

If error, tell the user to run `/obsidian-setup` first. Stop.

### Step 2 — Display settings table

Present the current settings as a numbered table:

```
Obsidian Brain Configuration

1. vault_path             <value>
2. sessions_folder        <value>
3. insights_folder        <value>
4. log_raw_messages       <value>      <- controls raw conversation logging
5. min_turns              <value>      <- minimum turns to log a session
6. min_duration_minutes   <value>      <- minimum duration to log

Enter a number to change, or 'done' to exit.
```

For any key not present in the config, show its default value: `log_raw_messages` defaults to `true`, `min_turns` defaults to `3`, `min_duration_minutes` defaults to `2`.

### Step 3 — Handle user selection

Wait for user input.

- `done` or empty → Stop. Print "Configuration unchanged."
- Number → Go to Step 4 with the selected setting.

### Step 4 — Change setting

- **Boolean settings** (`log_raw_messages`): Toggle the value (true→false, false→true). No prompt needed.
- **String settings** (`vault_path`, `sessions_folder`, `insights_folder`): Show current value, ask for new value.
- **Number settings** (`min_turns`, `min_duration_minutes`): Show current value, ask for new value. Validate it's a positive integer.

### Step 5 — Write updated config

Run:

```bash
python3 -c '
import sys, os, json
config_path = os.path.expanduser("~/.claude/obsidian-brain-config.json")
with open(config_path, "r") as f:
    config = json.load(f)
config[sys.argv[1]] = json.loads(sys.argv[2])
import tempfile
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(config_path), suffix=".tmp")
with os.fdopen(fd, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.rename(tmp, config_path)
print("OK")
' "$KEY" "$JSON_VALUE"
```

Where `$KEY` is the setting name and `$JSON_VALUE` is the new value as a JSON literal (e.g., `"false"`, `"3"`, `'"/path/to/vault"'`).

Confirm the change, then go back to Step 2 to redisplay the table.
