# plan-week

A skill and script that keep the cross-repo "Weekly Focus" GitHub Project
(`users/abhattacherjee/projects/36`) current, and answer "what do I work on next".

- `scripts/weekly-focus.py`: `sync`, `set <Focus> repo#N...` (`pick` = `set "This week"`), `show`. Both `sync` and `show` take `--json`.
- `SKILL.md`: `/github-board:plan-week` and questions like "what should I work on".
- `launchd/`: templates for two agents. `com.abhattacherjee.weekly-focus-sync` runs `scripts/run-sync.sh` at 07:00 and 18:00. `com.abhattacherjee.weekly-focus-watchdog` runs `scripts/watchdog.sh` hourly and at load. No KeepAlive.

The watchdog reinstalls a missing plist, reloads an unloaded sync job, and sends a macOS notification if the last successful sync is more than 26 hours old (each alert at most once per 6 hours). Each sync run also reloads the watchdog if it is not loaded.

## Board setup

`sync` creates the Weekly Focus board if it is missing. A new GitHub project starts with default workflows that GitHub's API cannot change, so turn two of them off by hand (board **⋯ → Workflows**):

- **Auto-add sub-issues to project**: when `sync` adds an epic, GitHub adds its sub-issues with no Focus or Lane.
- **Auto-close issue**: moving a card to Done here would close the real issue and skip that repo's own release flow.

Check with: `gh api graphql -f query='{user(login:"abhattacherjee"){projectV2(number:36){workflows(first:20){nodes{name enabled}}}}}'`

## Install

```bash
~/.claude/skills/weekly-focus/scripts/install-launchd.sh            # both agents
~/.claude/skills/weekly-focus/scripts/install-launchd.sh --only com.abhattacherjee.weekly-focus-watchdog
```

It renders the templates (`__HOME__` becomes `$HOME`) into `~/Library/LaunchAgents/`, creates the log and state directories, then runs `launchctl bootout` and `launchctl bootstrap` for each label.

## Uninstall

```bash
for l in com.abhattacherjee.weekly-focus-sync com.abhattacherjee.weekly-focus-watchdog; do
  launchctl bootout gui/$(id -u)/$l; rm -f ~/Library/LaunchAgents/$l.plist
done
```

## Check

```bash
~/.claude/skills/weekly-focus/scripts/install-launchd.sh --check    # exit 1 if a plist is missing or differs
launchctl print gui/$(id -u)/com.abhattacherjee.weekly-focus-sync
ls -l ~/.local/state/weekly-focus/                                   # last-success, last-error, alert-* stamps
tail ~/Library/Logs/weekly-focus/{sync,watchdog}.log
```

| What | Where |
|---|---|
| Logs | `~/Library/Logs/weekly-focus/{sync,watchdog}.log` and `.err.log` |
| State | `~/.local/state/weekly-focus/` (`last-success` mtime is the heartbeat; `last-error` holds the last failure) |
| Plists | `~/Library/LaunchAgents/com.abhattacherjee.weekly-focus-{sync,watchdog}.plist` |

Tests override `LAUNCHCTL`, `OSASCRIPT`, `PYTHON`, `LA_DIR`, `STATE_DIR`, `LOG_DIR`, `SKILL_DIR` and `NOW`.
