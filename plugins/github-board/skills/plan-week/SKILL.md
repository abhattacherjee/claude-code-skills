---
name: plan-week
description: "Answers what to work on next from the cross-repo Weekly Focus board and plans the week. Use when: (1) 'what do I work on next' or 'what should I work on', (2) 'what's my focus this week', (3) 'plan my next week' or 'weekly plan', (4) 'weekly focus' or /weekly-focus (the old name of this skill)."
metadata:
  version: 2.0.0
---

# Weekly Focus

Board: user project "Weekly Focus" (abhattacherjee). All logic is in the script; this file only decides what to say.

```bash
WF="${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"   # path only: zsh does not word-split $WF
```

## Every mode

1. `python3 "$WF" sync --json`, with a Bash timeout of 300000 ms (it scans every board). Report changes first, one short line each, only non-empty: started (name the unplanned ones), stopped (cards reset to Todo), `lane_changed` (lanes filled or lifted to Security), `stale_in_progress` (name each key and tell the user to move the card back on its `board`), new since Monday, `done_this_week`. If sync fails, say so, show the error, and carry on from `show --json` (it reads the board as it is). Exit 3 means sync skipped itself because the GitHub GraphQL budget is low: say so, carry on from `show --json`. Never fail silently.
2. `python3 "$WF" show --json`.

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
3. Today's lane: Mon Security, Tue/Wed Product, Thu Tooling, Fri Season (fantasy-football-advisor, in season Sep to early Jan) then releases, Sat/Sun the lightest open item.
4. Within a lane, order by `priority` (P1 before P2; null last).

If nothing is left, say so and suggest the plan mode.

## Mode: focus

Read-only. This week items grouped by Lane with status; done/total for the week (`done_this_week` from sync counts as done); list any `not_current` or `unplanned` items by name.

## Mode: plan

Draft from `show --json`:

- Carry over every unfinished This week item (in-progress ones always).
- Add Security lane Next items.
- Add at most 3 repos besides Security, only from items with `in_current` true. Products first (Product and Season before Tooling), one tooling milestone at most, sized for 10-20h.

Show a compact table, then ONE AskUserQuestion: apply / edit / cancel. On apply:

```bash
python3 "$WF" set "This week" repo#N ...     # the picks
python3 "$WF" set Next repo#N ...            # This week items dropped from the plan
python3 "$WF" show
```

## Rules

- This week takes work from the repo's current milestone only.
- Security may jump ahead; move that issue into the current milestone.
- Unplanned in-progress work is shown, never hidden or demoted.
- Frozen repos stay off unless work is in progress.

## Scheduling

launchd runs `sync` at 07:00 and 18:00; an hourly watchdog alerts if it goes stale. `scripts/install-launchd.sh --check` verifies the install. Logs: `~/Library/Logs/weekly-focus/`. See README.md.
