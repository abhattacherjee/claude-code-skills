# plan-week

A skill and script that keep a cross-repo "Weekly Focus" GitHub Project current, and answer "what do I work on next". Settings come from the github-board config (`plan-week init` writes it).

- `scripts/weekly-focus.py`: `sync`, `set <Focus> repo#N...` (`pick` = `set "This week"`), `show`, `init`, `config`. `sync` and `show` take `--json`; every command takes `--no-cache`.
- `SKILL.md`: `/github-board:plan-week` and questions like "what should I work on".
- `launchd/`: templates for two agents, labelled `<plan_week.launchd.label_prefix>-sync` (runs `scripts/run-sync.sh` at `plan_week.launchd.times`) and `<prefix>-watchdog` (runs `scripts/watchdog.sh` hourly and at load). No KeepAlive.

The watchdog reinstalls a missing plist, reloads an unloaded sync job, and sends a macOS notification if the last successful sync is more than 26 hours old (each alert, and each label's reinstall failure, at most once per 6 hours). Each sync run also reloads the watchdog if it is not loaded. With `plan_week.launchd.enabled` false, neither job reinstalls anything. If the config is missing or invalid, both jobs record it in `last-error` and notify ("config error", at most once per 6 hours) instead of failing silently.

## Board setup

`sync` creates the board if it is missing. A new GitHub project starts with default workflows that GitHub's API cannot change, so turn two of them off by hand (board **⋯ → Workflows**):

- **Auto-add sub-issues to project**: when `sync` adds an epic, GitHub adds its sub-issues with no Focus or Lane.
- **Auto-close issue**: moving a card to Done here would close the real issue and skip that repo's own release flow.

Check with: `gh api graphql -f query='{user(login:"<owner>"){projectV2(number:<n>){workflows(first:20){nodes{name enabled}}}}}'`

## The copy and the stable link

The installed plugin lives under a versioned path (`~/.claude/plugins/cache/<marketplace>/github-board/<version>/`), and the plugin cache keeps only the current and the previous version. A link into it would dangle after two upgrades and both jobs would fail with nothing left to raise an alert. So `install-launchd.sh` copies what the jobs need (`skills/plan-week/scripts/`, `skills/plan-week/launchd/`, `lib/` and `plugin.json`) into `~/.local/share/github-board/<version>/` (`$GITHUB_BOARD_HOME`), points the link `~/.local/share/github-board/current` at that copy, and the plists run the scripts through the link. Upgrading or removing the plugin never breaks the jobs. **Re-run `install-launchd.sh` after a plugin update to move the jobs to the new code**; `--check` reports `STALE COPY` until you do. A re-install replaces the copy for that version and deletes older version copies, except the one the link pointed at before.

## Install

`PW` is this skill's directory in the installed plugin, for example:

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh"                       # copy + link + both agents
"$PW/scripts/install-launchd.sh" --only <prefix>-watchdog
```

It copies the scripts into `~/.local/share/github-board/<version>/`, points the link at that copy, renders the templates into `~/Library/LaunchAgents/`, creates the log and state directories, then runs `launchctl bootout` and `launchctl bootstrap` for each label.

If a plist with the same label already runs another copy's scripts (an older bare skill), it refuses with exit 3 and names that copy. Pass `--takeover` to hand the jobs to the plugin. An unreadable plist blocks the same way.

## Uninstall

```bash
for l in <prefix>-sync <prefix>-watchdog; do
  launchctl bootout gui/$(id -u)/$l; rm -f ~/Library/LaunchAgents/$l.plist
done
rm -r ~/.local/share/github-board      # the link and every copy
```

## Check

```bash
"$PW/scripts/install-launchd.sh" --check    # exit 1 if the link, the copy or a plist is missing, wrong,
                                            # out of date (STALE COPY) or not loaded
launchctl print gui/$(id -u)/<prefix>-sync
ls -l ~/.local/state/weekly-focus/            # last-success, last-error, alert-* stamps
tail ~/Library/Logs/weekly-focus/{sync,watchdog}.log
```

| What | Where |
|---|---|
| Config | `~/.config/github-board/config.json` (`plan_week`) |
| Cache | `~/.cache/github-board/` (board ids; safe to delete) |
| Copy | `~/.local/share/github-board/<version>/` (what the jobs run) |
| Link | `~/.local/share/github-board/current` → the copy |
| Logs | `~/Library/Logs/weekly-focus/{sync,watchdog}.log` and `.err.log` |
| State | `~/.local/state/weekly-focus/` (`last-success` mtime is the heartbeat; `last-error` holds the last failure) |
| Plists | `~/Library/LaunchAgents/<prefix>-{sync,watchdog}.plist` |

Tests override `LAUNCHCTL`, `OSASCRIPT`, `PYTHON`, `GB_PYTHON`, `LA_DIR`, `STATE_DIR`, `LOG_DIR`, `SKILL_DIR`, `GITHUB_BOARD_HOME`, `GITHUB_BOARD_LINK`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `NOW`.
