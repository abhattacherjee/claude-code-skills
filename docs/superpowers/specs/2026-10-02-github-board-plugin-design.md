# github-board plugin — design

Issue: #146. Milestone: v3.20. Date: 2026-10-02.

## Goal

One `/plugin install github-board@claude-code-skills` installs the seven GitHub-workflow
skills and the four agents one of them dispatches. The skills get short verb names. The
old bare skills in `~/.claude/skills/` keep working next to the plugin until they are
deleted by hand.

## Scope

In this PR:

- the plugin itself (Phase 1 of the issue's migration path)
- callers of the old names inside this repo

Not in this PR:

- callers in other repos (claude-code-config, git-flow, obsidian-brain, codex-config) —
  one small PR per repo afterwards
- handing the launchd jobs to the plugin (Phase 3) — a manual runbook step in the README
- deleting the bare copies (Phase 4) — a manual runbook step in the README

## Decision: author directly in `plugins/github-board/`

Same pattern as `plugins/adversarial-review/`: the plugin directory is the only source.

Rejected: root source folders plus `plugin-manifest.json` assembled by
`prepare-plugin.sh` (the `deep-review` pattern). That keeps two copies of seven skills,
and it depends on generator defects already filed for v3.22 (#66, #82, #106).

Rejected: one plugin per skill. The issue's argument is a single install for a pipeline.

## Layout

```
plugins/github-board/
  .claude-plugin/plugin.json        name github-board, version 1.0.0
  README.md                         skills, agents, migration runbook (Phases 3-4)
  CHANGELOG.md
  LICENSE
  skills/
    create-board/                   was create-gh-board
    triage-issues/                  was github-issue-triage
    plan-milestones/                was github-milestone-planning
    plan-week/                      was weekly-focus
    move-card/                      was github-board-move
    promote-shipped/                was github-release-board-promote
    prune-branches/                 was git-branch-cleanup
  agents/
    template-inspector.md           was gh-board-template-inspector
    board-creator.md                was gh-board-creator
    workflow-syncer.md              was gh-board-workflow-syncer
    board-verifier.md               was gh-board-verifier
  tests/                            pytest suites moved with their code, plus new ones
```

The root `.claude-plugin/marketplace.json` gets one `github-board` row. The repo-root
`github-board-move/` folder is deleted; its content moves to `skills/move-card/`.

## Sources

Each skill is copied from where its newest version lives. Checked 2026-10-02 by
`diff -rq` between each source and the installed copy.

| New name | Source | Notes |
|---|---|---|
| `create-board` | `~/.claude/skills/create-gh-board/` | Installed copy is newer than claude-code-config's: `backfill-issues.sh` (read-back and one retry after `item-add`) and `verify-board.sh` (accepts `owner/name`) were edited 2026-10-02 and never committed upstream. Take the installed copy. |
| `triage-issues` | `~/.claude/skills/github-issue-triage/` | No upstream. |
| `plan-milestones` | `~/.claude/skills/github-milestone-planning/` | No upstream. |
| `plan-week` | claude-code-config `skills/weekly-focus/` | Identical to the installed copy apart from `README.md`, which exists only upstream. |
| `move-card` | this repo's `github-board-move/` | |
| `promote-shipped` | claude-code-config `skills/github-release-board-promote/` | Identical to the installed copy. Its five pytest files move too. |
| `prune-branches` | `~/.claude/skills/git-branch-cleanup/` | No upstream. |
| four agents | claude-code-config `agents/gh-board-*.md` | Identical to `~/.claude/agents/`. |

Per-skill `plugin-manifest.json` files are dropped; `plugin.json` replaces them.
Per-skill `CHANGELOG.md` files are kept.

## Renames

For each skill:

- directory and frontmatter `name:` take the new name
- `metadata.version` gets a major bump, because the invocation name changed
- the description keeps the old trigger phrases, so the same user wording still matches
  (and adds the old name as a phrase, e.g. "weekly focus")
- every `See Also` link and every mention of a sibling skill uses the new name
- the skill's own `task-manifest.sh` subjects and any user-facing text that print the old
  name use the new one

For each agent:

- file and frontmatter `name:` take the new name
- its "NOT user-invocable — spawned by …" line names `create-board`
- `create-board`'s `SKILL.md` dispatches `github-board:template-inspector`,
  `github-board:board-creator`, `github-board:workflow-syncer` and
  `github-board:board-verifier`. Plugin agents are namespaced `<plugin>:<agent>`, and the
  docs do not say a bare name resolves.

The old `gh-board-*` agents in `~/.claude/agents/` keep their names, so the two sets
never clash while both are installed.

## Paths

Claude Code fills in `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` in a plugin
SKILL.md's text when the skill loads. They are not environment variables in the Bash
tool. So:

- every command in a SKILL.md that runs a bundled script uses
  `"${CLAUDE_SKILL_DIR}/scripts/<script>"`
- scripts keep locating their own directory from `BASH_SOURCE[0]` / `__file__`, as they
  do today
- the plugin contains no `~/.claude/skills/` or `$HOME/.claude/skills/` path. A test
  enforces this; the only allowed mentions are in the README's migration runbook and in
  CHANGELOG history.

## plan-week: shared state and launchd

While both `/weekly-focus` and `/github-board:plan-week` are installed they must read and
write the same state. The plugin keeps unchanged:

- `STATE_DIR` default `~/.local/state/weekly-focus`
- `LOG_DIR` default `~/Library/Logs/weekly-focus`
- the launchd labels and plist file names, which come from the config's
  `launchd.label_prefix` (`<prefix>-sync`, `<prefix>-watchdog`); on this machine the prefix
  is `com.abhattacherjee.weekly-focus`, matching the bare copy
- the GitHub board ("Weekly Focus") and its fields

The launchd jobs must survive plugin upgrades. The installed plugin lives under a
versioned cache path (`~/.claude/plugins/cache/<marketplace>/github-board/<version>/`),
so a plist that points there breaks on the next upgrade. Instead:

- `install-launchd.sh` writes a stable symlink `~/.local/share/github-board/current` that
  points at the plugin root it ran from, then renders the plists against
  `~/.local/share/github-board/current/skills/plan-week/scripts/`. The symlink path can be
  overridden (`GITHUB_BOARD_LINK`) for tests.
- Re-running `install-launchd.sh` from a newer plugin version re-points the symlink. The
  README says to do this after each plugin update.
- **Takeover guard.** Before writing, `install-launchd.sh` reads any existing plist for
  each label. If its `ProgramArguments` point outside the stable symlink (for example at
  `~/.claude/skills/weekly-focus/scripts/`), it refuses with exit 3 and a message naming
  the current owner, unless `--takeover` is passed. A missing plist is not an owner and
  does not block. An unreadable plist blocks too, because its owner cannot be known.
- **`--check`** fails (non-zero) when the symlink is missing, dangling, or points at a
  directory without `skills/plan-week/scripts/run-sync.sh`, in addition to its existing
  checks.

The plist templates replace `__HOME__/.claude/skills/weekly-focus/scripts/` with a
`__SCRIPTS__` placeholder that `install-launchd.sh` fills in.

This PR does not run `--takeover` on this machine. The bare `weekly-focus` keeps owning
the jobs until the Phase 3 runbook step.

## Per-user config and metadata cache

The plugin ships with no user's values in it. Today two skills hardcode the author's:

- `weekly-focus.py`: `OWNER`, `TITLE`, `FROZEN`, `ALWAYS`, `TOOLING`, `SEASON`, the four
  `Lane` options and the rule in `lane_for()`; the weekday schedule in `SKILL.md` and in
  the board README the script writes; the `com.abhattacherjee.*` launchd labels
- `create-gh-board`: `TEMPLATE_OWNER`/`TEMPLATE_NUMBER` in `audit-board.sh` and
  `--owner abhattacherjee` in `SKILL.md`

`promote-shipped` and `move-card` already discover boards and Status columns at runtime;
only their example lines name the author. `triage-issues`, `plan-milestones` and
`prune-branches` act on the current repo and need no config.

Per-user data lives outside the plugin, so plugin upgrades never touch it and launchd
(which runs outside Claude Code) can read it. Claude Code's `userConfig` and
`${CLAUDE_PLUGIN_DATA}` are not used for this: neither exists in the launchd job's
environment.

### Preferences: `${XDG_CONFIG_HOME:-~/.config}/github-board/config.json`

What a person chooses. Hand-editable; the plugin only writes it from `init`.

```json
{
  "version": 1,
  "owner": "<login>",
  "plan_week": {
    "board_title": "Weekly Focus",
    "lanes": [
      {"name": "Security", "labels_containing": ["security"]},
      {"name": "Season",   "repos": ["<repo>"]},
      {"name": "Tooling",  "repos": ["<repo>", "<repo>"]}
    ],
    "default_lane": "Product",
    "schedule": {"mon": ["Security"], "tue": ["Product"], "wed": ["Product"],
                 "thu": ["Tooling"], "fri": ["Season"], "sat": [], "sun": []},
    "frozen": ["<repo>"],
    "always": ["<repo>#<n>"],
    "capacity": {"max_repos_besides_security": 3, "hours": [10, 20]},
    "launchd": {"enabled": true, "times": ["07:00", "18:00"],
                "label_prefix": "dev.github-board.plan-week"}
  },
  "create_board": {"template_owner": "<login>", "template_number": 0}
}
```

- Lanes are matched in order; the first rule that matches wins, else `default_lane`. This
  reproduces today's `lane_for()` exactly when filled with today's values.
- `schedule` replaces the weekday table in `SKILL.md`; `null` means no fixed days (Security
  first, then priority order). `capacity` replaces the "at most 3 repos besides Security,
  sized for 10-20h" line in `SKILL.md`'s plan mode. `show --json` includes both, and the
  skill reads it from there instead of from prose.
- A missing config file makes every `plan-week` subcommand except `init` exit 4 with
  "run `plan-week init`". Nothing falls back to built-in values. `create-board` without a
  template asks for one (the existing `--template-owner`/`--template` flags still win).
- An unparseable file, an unknown `version`, or a missing required key exits 2 with the
  key named.

### Init flow

The skill asks the questions in chat (AskUserQuestion), with suggestions fetched from
GitHub first, so most answers are a confirmation. It then calls the `init` script with the
answers as JSON on stdin. The script never prompts, so it stays testable and safe to run
from launchd's environment.

`plan-week init`, up to eight questions:

| # | Question | Suggested from | Default |
|---|---|---|---|
| 1 | Which GitHub account's repos and boards should this plan? | `gh api user` (user accounts only: `weekly-focus.py` queries `user(login:)` and `author:<owner>`, so an organization owner is not supported yet) | the logged-in user |
| 2 | Which repos are active, and which stay frozen (never synced unless listed in Q7)? | the owner's non-archived repos; active = pushed in the last 90 days and has open issues; shown as an editable list | the 90-day split |
| 3 | How do you want to group work into lanes? | presets | Security / Product / Tooling; or a single lane; or custom names |
| 4 | Which active repos belong to Tooling (or to each custom lane)? Unassigned repos go to the default lane. | active repos from Q2 | none |
| 5 | Do you work lanes on fixed days? | presets | no fixed days (`schedule: null`); or Mon Security, Tue-Wed Product, Thu Tooling, Fri releases; or custom |
| 6 | How much fits in a week? | — | 3 repos besides Security, 10-20 hours |
| 7 | Any issues to always include, even from frozen repos? | — | none |
| 8 | Run the sync in the background? | asked on macOS only; elsewhere `launchd.enabled` is `false` | yes, 07:00 and 18:00, prefix `dev.github-board.plan-week` |

- The board title is asked only when the owner already has a project with the default
  title "Weekly Focus": reuse it, or pick another title.
- The Security preset matches issues labelled `security` in any repo; it is not a
  question.
- No Season lane preset: that lane is the author's own, and `--from` carries it over.
- A repo created after `init` is not frozen, so it is synced (as today).

`create-board init`, one question: which existing board should new boards copy? Suggested
from `gh project list --owner <login>` and the owner's orgs' projects. Default: none, in
which case `create-board` asks the first time it creates a board.

Before writing, the skill shows the finished file and asks once: "Write this to
`~/.config/github-board/config.json`?" The `init` script refuses to overwrite an existing
file without `--force`. Re-running `init` with a config present pre-fills every answer
from it, and the skill passes `--force` only after that confirmation.

### Discovered metadata: `${XDG_CACHE_HOME:-~/.cache}/github-board/`

What the skills look up on every run today: the Weekly Focus board's project number and
node ID, its field and option IDs, and (for `promote-shipped` and `move-card`) each
repo's linked boards and their Status options. One JSON file per lookup, each with the
time it was fetched.

- Entries are reused for 7 days.
- Any GraphQL error that names a stale ID, or a lookup that comes back empty, drops the
  entry and refetches once.
- Deleting the directory is always safe; it is only a cache.
- `--no-cache` on the affected scripts skips it, for debugging.

### Shared code

`plugins/github-board/lib/config.py` and `lib/config.sh` load and validate the config
and read and write cache entries. Scripts find `lib/` relative to their own location.

### This machine

`plan-week init --from <file>` writes the author's current values (today's constants,
lanes, schedule and template) into the config file once, with
`launchd.label_prefix` `com.abhattacherjee.weekly-focus` so the labels stay what the
bare copy uses and the side-by-side plan still holds. Nothing changes in behaviour. The
flag reads a JSON file passed to it, which is kept out of the plugin.

## Callers in this repo

Updated to the new names:

- `skill-authoring/SKILL.md` and `skill-authoring/references/task-tracking-pattern.md`
- the same two files under `plugins/skill-authoring/skills/skill-authoring/`
- `plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh`
- `README.md` (the `github-board-move` install line goes; a `github-board` plugin entry
  is added)

Left as they are: comments in `scripts/test-sync-hygiene.sh` that describe the old names
on purpose, and CHANGELOG history.

## Tests

Moved, with paths updated to the new layout:

- claude-code-config `tests/test_weekly_focus.py`, `test_weekly_focus_launchd.py`,
  `test_weekly_focus_skill_shell.py` → `plugins/github-board/tests/`
- `promote-shipped`'s five pytest files → `plugins/github-board/tests/`

New:

- **structure test:** exactly the seven skill directories and four agent files exist;
  each `name:` matches its directory or file name; every `github-board:<agent>` that a
  skill dispatches exists under `agents/`; no old skill or agent name appears in any
  skill or agent file except as a trigger phrase or a "was …" note; no `~/.claude/skills/`
  path outside the allowed files
- **launchd tests:** symlink written and re-pointed; takeover refused (exit 3) when an
  existing plist points at another copy, allowed with `--takeover`; `--check` fails on a
  missing and on a dangling symlink
- **config tests:** missing file exits 4 for every subcommand but `init`; bad JSON, unknown
  `version` and a missing key exit 2 naming the key; lane rules filled with the author's
  values give the same lane as today's `lane_for()` for every repo/label case in the
  current tests; `init` refuses to overwrite without `--force`
- **cache tests:** a fresh entry is reused; one older than 7 days is refetched; a stale-ID
  error drops the entry and refetches once; `--no-cache` never reads or writes it
- **no personal values:** no file in the plugin contains the author's login, any of the
  repo names in today's `FROZEN`/`ALWAYS`/`TOOLING`/`SEASON`, or `com.abhattacherjee`,
  outside an allow-list of example lines and CHANGELOG history
- **clean-HOME smoke test** (a script under `tests/`, run in CI and locally): with
  `HOME` set to an empty temp dir, so nothing can fall back to an installed copy, run
  `plan-milestones`'s `milestone-report.sh --help`, `plan-week`'s `weekly-focus.py
  --help`, and `create-board`'s `task-manifest.sh`. Each must exit 0.

CI: a new job in `.github/workflows/validate-skill.yml` runs `pytest
plugins/github-board/tests` and the smoke script. `scripts/validate-plugin.sh
plugins/github-board` must pass; it already checks that agent references in SKILL.md
resolve against `agents/`.

The live parts of the issue's smoke test (`plan-week sync --json` against GitHub,
`create-board` reaching its first agent dispatch) are run by hand during the review
phase, not in CI, because they need GitHub credentials.

## Error handling

- `install-launchd.sh`: exit 3 on a refused takeover, exit 1 on a failed `launchctl`
  step, exit 2 on bad arguments. Never exit 0 when it wrote nothing it was asked to.
- `--check`: non-zero on any failed check, including a missing or dangling symlink.
- Everything else keeps its current exit codes.

## Migration runbook (README)

The plugin README carries the issue's Phases 3 and 4 as copy-paste steps:

- Phase 3: run the plugin's `install-launchd.sh --takeover`, then `--check`, then one
  manual `weekly-focus.py sync --json`; update the boot-doctor service manifest's
  `restart_command`s. Rollback: run the bare copy's `install-launchd.sh`.
- Phase 4: drop `weekly-focus`, `create-gh-board` and `github-release-board-promote` from
  claude-code-config's `sync.sh` `SKILLS` array first; diff each bare copy against the
  plugin; delete the seven bare skill directories and the four `gh-board-*.md` agents;
  confirm only `github-board:` names remain.

## Acceptance

This PR closes #146. Before the PR opens, #146's acceptance criteria are narrowed to
Phase 1 plus this repo's callers, and the rest moves to follow-up issues that the PR
body links:

- one issue in this repo for the Phase 3 launchd handover and the Phase 4 removal, both
  run by hand from the README runbook
- one issue in each other repo whose callers use the old names: claude-code-config,
  git-flow, obsidian-brain, codex-config

They are separate issues because each is a different repo or a manual step on this
machine, which a claude-code-skills PR cannot carry.
