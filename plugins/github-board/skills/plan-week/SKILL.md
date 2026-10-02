---
name: plan-week
description: "Answers what to work on next from the cross-repo Weekly Focus board, plans the week, and sets the board up. Use when: (1) 'what do I work on next' or 'what should I work on', (2) 'what's my focus this week', (3) 'plan my next week' or 'weekly plan', (4) 'weekly focus' or /weekly-focus (the old name of this skill), (5) 'set up plan-week' or 'plan-week init', or a command exits 4 (no config yet)."
metadata:
  version: 2.0.0
---

# Plan Week

Board: the config owner's user project titled `plan_week.board_title`. All logic is in the script; this file only decides what to say.

Each Bash call starts a fresh shell, so no variable survives from one command to the next. Run every command exactly as written here, with the full `"${CLAUDE_SKILL_DIR}/scripts/..."` path; never put a path or file name in a shell variable for a later command.

Exit 4 from any command means plan-week is not set up yet (no config file, or a config without a `plan_week` section, e.g. one written by `create-board init`): offer **Mode: init**, run it, then carry on with what the user asked. Exit 2 that names a config key means the config is invalid: show the message and stop. Exit 1 that says the board has no Lane (or Focus) option: tell the user to add that option on the board, or to remove the lane from the config.

## Every mode except init

1. `python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" sync --json`, with a Bash timeout of 300000 ms (it scans every board). Report changes first, one short line each, only non-empty: started (name the unplanned ones), stopped (cards reset to Todo), `lane_changed` (lanes filled or lifted to a label lane), `stale_in_progress` (name each key and tell the user to move the card back on its `board`), new since Monday, `done_this_week`, and each `config_warnings` entry (a frozen repo or always issue that matches no open issue: suggest fixing the config). If sync fails, say so, show the error, and carry on from `show --json` (it reads the board as it is). Exit 3 means sync skipped itself because the GitHub GraphQL budget is low: say so, carry on from `show --json`. Never fail silently.
2. `python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" show --json`. It carries the config's `schedule`, `capacity`, `lanes` and `default_lane`. Use those; never a remembered weekday table.

## Mode: next (default)

Recommend ONE item and up to 2 alternates, each with its `url` and a one-line reason. Only `This week` items.

**Read the right field.** `focus` holds the board lane (`This week` / `Next`); `status` holds Todo / In Progress / Done. Filter on `focus == "This week"`. Filtering on `status` finds no This-week items and yields a wrong "nothing planned" answer.

**Scope to the current repo first.** When the current working directory is a repo with `This week` items (the item's `repo` field), recommend only from that repo's This-week items. The user is asking what to do next *here*. Take the repo name from `git remote get-url origin`, not the directory name: a worktree directory carries a `--<branch>` suffix. Pick the obvious next item using what you know from this session and the repo, not just the board order:

- Finish what is `in_progress` in this repo before starting something new.
- Prefer the item that continues work just shipped or in flight: the next plan slice of an in-progress epic, or a follow-up of something closed today.
- Then order by `priority` (P1 before P2; null last).
- Say in the one-line reason *why* it is next, citing that context (e.g. "Plan C of #368, which is in progress").

Mention other repos in at most one line, and only for an open Security-lane P1 (`Security elsewhere: repo#N — title`). It is never the pick. Leave everything else off unless the user asks for the whole board.

**Board-wide ordering.** Use this when the cwd is not a repo, or the repo has no This-week items (say so first):

1. `in_progress` items (finish before starting). Ignore items that are not `in_progress` for this rule.
2. Security lane, any day.
3. Today's lanes: look up today's weekday (`mon` … `sun`) in `schedule` and prefer items whose `lane` is listed there. When `schedule` is null, or today's list is empty, skip this rule.
4. Within a lane, order by `priority` (P1 before P2; null last).

If nothing is left, say so and suggest the plan mode.

## Mode: focus

Read-only. This week items grouped by Lane with status; done/total for the week (`done_this_week` from sync counts as done); list any `not_current` or `unplanned` items by name.

## Mode: plan

Draft from `show --json`:

- Carry over every unfinished This week item (in-progress ones always).
- Add Security lane Next items.
- Add at most `capacity.max_repos_besides_security` repos besides Security, only from items with `in_current` true. Take lanes in the order `schedule` names them from Monday to Sunday (when `schedule` is null: `default_lane` first, then `lanes` in order), with at most one milestone per lane besides `default_lane`. Size the week to `capacity.hours` (low to high hours).

Show a compact table, then ONE AskUserQuestion: apply / edit / cancel. On apply:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" set "This week" repo#N ...   # the picks
python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" set Next repo#N ...          # This week items dropped from the plan
python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" show
```

## Mode: init

Use when the user asks to set up plan-week, or a command exited 4. Ask with AskUserQuestion, one question at a time. Fetch suggestions first so most answers are a confirmation.

0. `python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" config`. Exit 0 prints the current config: pre-fill every answer from it. Exit 4: first run. Then check `gh auth status` lists the `project` scope (sync creates the board and edits its fields). If not, tell the user to run `gh auth refresh -s read:project,project` and stop.
1. **Q1 — account.** Suggest `gh api user --jq .login`. plan-week reads one user's projects, issues and PRs, so offer user accounts only; if the user names an organization, say it is not supported yet.
2. **Q2 — active and frozen repos.** `gh repo list <owner> --no-archived --limit 300 --json name,pushedAt,issues --jq '.[] | [.name, .pushedAt, .issues.totalCount] | @tsv'`. Active = pushed in the last 90 days and has open issues; suggest the rest as `frozen`. Show the split as an editable list. Frozen repos are never synced unless listed in Q7. A repo created later is not frozen.
3. **Q3 — lanes.** Presets: Security / Product / Tooling (default); a single lane; custom names. Security is not a question: it is always the first rule, `{"name": "Security", "labels_containing": ["security"]}`. The lane that gets no repos becomes `default_lane` (Product in the default preset; the user picks one for custom names). The single-lane preset is Security plus one `default_lane` that takes everything else.
4. **Q4 — lane repos.** For Tooling (or each custom lane except Security and `default_lane`): which active repos belong to it? Suggest none. Unassigned repos go to `default_lane`.
5. **Q5 — fixed days.** Presets: no fixed days (`"schedule": null`, default); Mon Security, Tue-Wed Product, Thu Tooling, Fri releases (`{"mon": ["Security"], "tue": ["Product"], "wed": ["Product"], "thu": ["Tooling"], "fri": [], "sat": [], "sun": []}`); custom (every lane named must be one of the lanes).
6. **Q6 — capacity.** Default `{"max_repos_besides_security": 3, "hours": [10, 20]}`.
7. **Q7 — always include.** Issues as `repo#N` to include even from frozen repos. Default none.
8. **Q8 — background sync.** Ask only when `uname -s` prints `Darwin`; elsewhere write `"enabled": false`. Default `{"enabled": true, "times": ["07:00", "18:00"], "label_prefix": "dev.github-board.plan-week"}`.

Board title: ask only when `gh project list --owner <owner> --format json --jq '.projects[] | select(.closed == false) | .title'` already lists "Weekly Focus" — reuse that board, or pick another title. Otherwise use "Weekly Focus".

Build `{"owner": …, "plan_week": {"board_title", "lanes", "default_lane", "schedule", "frozen", "always", "capacity", "launchd"}}`, show it, and ask once: "Write this to `~/.config/github-board/config.json`?" On yes, pass the JSON on stdin in ONE Bash call (no temp file, no variable), replacing the placeholder line with the JSON you showed. First run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" init <<'JSON'
{"owner": "<login>", "plan_week": {...}}
JSON
```

A config exists and the user confirmed the change:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py" init --force <<'JSON'
{"owner": "<login>", "plan_week": {...}}
JSON
```

Exit 3: a different `plan_week` (or owner) is already there and `--force` was not passed. Exit 2 names the bad key: fix that answer and ask again.

When `launchd.enabled` is true, offer to run `"${CLAUDE_SKILL_DIR}/scripts/install-launchd.sh"`. Exit 3 means another copy owns the jobs, usually the bare skill this one was (`/weekly-focus`): say so and point at the plugin README's hand-over steps; never pass `--takeover` unasked.

## Rules

- This week takes work from the repo's current milestone only.
- Security may jump ahead; move that issue into the current milestone.
- Unplanned in-progress work is shown, never hidden or demoted.
- Frozen repos stay off unless work is in progress.

## Scheduling

launchd runs `sync` at `plan_week.launchd.times`; an hourly watchdog alerts if it goes stale. `"${CLAUDE_SKILL_DIR}/scripts/install-launchd.sh" --check` verifies the link, the copy the jobs run from (`STALE COPY` after a plugin update: re-run `install-launchd.sh`), the plists and that both jobs are loaded. Logs: `~/Library/Logs/weekly-focus/`. See README.md.
