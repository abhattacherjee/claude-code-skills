---
name: create-board
description: "Replicates a GitHub ProjectV2 board (Kanban view, Status columns, Milestone swimlanes, custom fields) onto a target repository by copying a known-good template, then verifies the copy and reports the one workflow that must be enabled by hand. Also audits existing boards for drift, read-only. Use when: (1) the user runs `/github-board:create-board <owner/repo>` or /create-gh-board (the old name of this skill), (2) the user asks to create, clone, copy, or replicate a project board across repos, (3) a new repo needs the standard board layout (Status: Todo/Up Next/In Progress/Development Complete/Done) wired up, (4) the user asks which existing boards have drifted or are missing auto-add. The template board comes from the github-board config (`create-board init`)."
disable-model-invocation: true
metadata:
  version: 3.0.0
---

# create-board

## Problem

Setting up a ProjectV2 by hand is tedious and drifts between repos: Status
options, the board's column and swimlane grouping, and the auto-add workflow all
end up slightly different. This skill copies a known-good template onto any repo,
proves the copy landed, and names the single step the API cannot do.

## Measured capability model

Everything here was measured on **2026-09-16, gh 2.96.0**, against real boards.
Do not restate these claims from memory — `references/graphql-snippets.md`
holds the evidence and a re-check script.

| Board property | Reproducible how |
|---|---|
| Fields, Status options (name/colour/description) | `gh project copy`, or `updateProjectV2Field` |
| View name, layout, filter | `gh project copy`, or `createProjectV2View` / `updateProjectV2View` |
| **Board columns** (`verticalGroupByFields`) | **Copy only** — read-only in the API |
| **Swimlanes** (`groupByFields`) | **Copy only** — read-only in the API |
| Repo link | `linkProjectV2ToRepository` |
| The six default workflows | Automatic — every new project has them |
| **`Auto-add to project`** | **Manual, in the UI. No mutation can create or enable a workflow.** |

Three consequences that drive the whole design:

1. **A copy is the only way to get swimlanes.** `ProjectV2ViewConfigurationInput`
   accepts only `visibleFieldIds`. A view built with `createProjectV2View` lands
   ungrouped and cannot be grouped afterwards.

2. **`gh project copy` carries no workflows at all.** The six that show up on a
   copy are GitHub defaults — a bare `gh project create` has exactly the same
   six. They are project-scoped and carry **no repo filter**, so there is nothing
   to rewrite on them after a copy. Only `Auto-add to project` is repo-scoped,
   and it is simply absent.

3. **Never rewrite Status options without their `id`.** `updateProjectV2Field`
   replaces the option list; omitting each option's existing `id` recreates them,
   clears the field on every item, and silently disables every workflow that
   referenced them. Measured: one id-less call disabled 5 of 6 workflows; the
   same call with ids disabled none. There is no API to re-enable them.

## Quick Check

```bash
"${CLAUDE_SKILL_DIR}/scripts/init-config.sh" --show                              # the configured template
"${CLAUDE_SKILL_DIR}/scripts/inspect-template.sh" --owner <template-owner> --number <n>   # snapshot it
"${CLAUDE_SKILL_DIR}/scripts/audit-board.sh" --owner <login> --all               # drift sweep, read-only
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" full                              # task list for creation
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" audit                             # task list for the audit
```

## When to Use

| Trigger | Workflow |
|---|---|
| `/github-board:create-board owner/repo` | `full` — copy, link, backfill, verify |
| "replicate our board on X repo" | `full`, target = X |
| "which boards have drifted?" / "is auto-add on everywhere?" | `audit` |
| A template other than the configured one | `full` with `--template <num> --template-owner <login>` |
| Several repos at once | Run `full` once per repo; each is independent |

## Inputs

| Arg | Required | Default | Notes |
|---|---|---|---|
| `<repo>` | yes | — | Target repo as `owner/name`. The new project links to it. |
| `--template <num>` | no | `create_board.template_number` from the config | Source ProjectV2 number. |
| `--template-owner <login>` | no | `create_board.template_owner` from the config | Source project owner. |
| `--target-owner <login>` | no | inferred from `<repo>` | Use a different login to put the board under an org. |
| `--title <string>` | no | `<RepoName> Project Board` | New project title. |
| `--dry-run` | no | off | Inspect template and show the plan; create nothing. |

## The template

The template is the board `create_board` in the github-board config names. The layout this skill expects of it:

| Aspect | Value |
|---|---|
| View | one, named `Kanban`, `BOARD_LAYOUT`, no filter |
| Columns | `Status` |
| Swimlanes | `Milestone` |
| `Status` options | Todo (GRAY) → Up Next (BLUE) → In Progress (YELLOW) → Development Complete (ORANGE) → Done (PURPLE) |
| Fields | 13 total: Title, Assignees, Status, Labels, Linked PRs, Milestone, Repository, Reviewers, Parent issue, Sub-issues progress, Created, Updated, Closed |
| Workflows | the 6 defaults. `Auto-add to project` is deliberately **not** set, because it would be scoped to the wrong repo. |

The option descriptions follow Git Flow:
`Development Complete` means merged to `develop`, `Done` means shipped to `main`.

The template is **not** marked with `markProjectV2AsTemplate` — that mutation
rejects user-owned projects (*"Only projects owned by an Organization can be
marked as a template"*). It is a template by convention; copying does not need the badge.

## Progress Tracking (MANDATORY)

Build the checklist from `"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" <workflow>` before starting.
TaskUpdate `in_progress` before each phase, `completed` after. On abort, mark
the rest `deleted`.

| # | Phase | Agent | Model |
|---|---|---|---|
| 1 | Inspect template | `github-board:template-inspector` | `haiku` |
| 2 | Copy template → new project | `github-board:board-creator` | `haiku` |
| 3 | Link project to target repo | `github-board:board-creator` (continued) | `haiku` |
| 4 | Check `Auto-add to project` | `github-board:workflow-syncer` | `sonnet` |
| 5 | Backfill existing issues | `github-board:board-creator` (continued) | `haiku` |
| 6 | Verify against template | `github-board:board-verifier` | `sonnet` |

Every agent dispatch passes `skill_dir: ${CLAUDE_SKILL_DIR}` plus the inputs the agent lists.
The agents run each script as `<skill_dir>/scripts/<name>`.

## Workflow: `full`

### Phase 0 — Validate

- Resolve the template: `--template-owner`/`--template` win; else `init-config.sh --show` → `create_board`; else run **Mode: init** first.
- `gh auth status` shows the `project` scope. If not: `gh auth refresh -s project`.
- `gh repo view <repo>` succeeds.
- `gh project view <num> --owner <login>` succeeds for the template.

Halt on any failure with the exact remediation command.

### Phase 1 — Inspect template (`github-board:template-inspector`, `haiku`)

Runs `scripts/inspect-template.sh`, writing a snapshot to a `mktemp` file
whose path the script prints on stdout: fields with option ids, view shape
including columns and swimlanes, workflow toggles. Returns the path.

### Phase 2 — Copy (`github-board:board-creator`, `haiku`)

Runs `scripts/copy-template.sh`, which wraps `gh project copy` and returns the
new project's id, number and url. This is the step that carries the columns and
swimlanes; nothing later can add them.

### Phase 3 — Link (`github-board:board-creator`, continued)

Runs `scripts/link-repo.sh --project-id <project-id> --repo <owner/name>` → `linkProjectV2ToRepository`.

### Phase 4 — Check `Auto-add to project` (`github-board:workflow-syncer`, `sonnet`)

Reports whether the workflow is present and emits the UI URL plus the exact
filter. It is always absent on a fresh copy. **Do not tell the user to rewrite
filters on the other six workflows** — they are defaults and have none.

### Phase 5 — Backfill (`github-board:board-creator`, continued)

Auto-add workflows fire on new events only; they never add existing items.
`scripts/backfill-issues.sh` adds the repo's current open issues. Idempotent.
Defaults to open issues, no PRs — use `--state all --include-prs` only if asked.

### Phase 6 — Verify (`github-board:board-verifier`, `sonnet`)

`scripts/verify-board.sh` re-introspects the new board and diffs it against the
snapshot: field count, Status options, **view shape (name, layout, filter,
columns, swimlanes)**, and the expected workflow set (template's enabled set
minus `Auto-add to project`). It reports `auto_add` separately.

| Exit | Meaning |
|---|---|
| `0` | Structural parity and auto-add already enabled |
| `1` | Structural drift — re-copy rather than hand-fix |
| `2` | Bad usage or unreadable snapshot |
| `3` | Structurally clean; auto-add still needs enabling in the UI |

Exit `3` is the normal outcome of a fresh run. Treat it as "done, one manual
step pending", not as a failure. Re-running after the user enables the workflow
gives exit `0`.

For a tracking issue:

```bash
"${CLAUDE_SKILL_DIR}/scripts/verify-board.sh" --print-remediation \
  --new-owner <owner> --new-number <n> --target-repo <repo> \
  | gh issue create --repo <owner/repo> --title "Enable board auto-add" --body-file -
```

## Workflow: `audit` (read-only)

```bash
"${CLAUDE_SKILL_DIR}/scripts/audit-board.sh" --owner <login> --number <n>     # one board
"${CLAUDE_SKILL_DIR}/scripts/audit-board.sh" --owner <login> --all            # every open board
"${CLAUDE_SKILL_DIR}/scripts/audit-board.sh" --owner <login> --all --json     # one JSON object per line
```

Compares Status options, view shape and `Auto-add to project` against the
template. **Writes nothing** — it prints drift and the remediation, and you
decide. Exit `0` clean, `1` drift found, `2` usage.

This is how boards that silently lost auto-add get found: a board created by
copy has no auto-add until someone enables it, and nothing else surfaces that.

Repair guidance the audit prints, and the reason for each:

| Drift | What to do |
|---|---|
| auto-add missing | Enable it in `/workflows`. No mutation exists. |
| view drifted | Name, layout and filter: `updateProjectV2View`. Columns or swimlanes: re-copy the template — they are read-only. |
| status drifted | `updateProjectV2Field`, **sending each option's existing `id`**. Without ids you clear item values and disable workflows. |

## Mode: init

One question: which existing board should new boards copy? Suggest from
`gh project list --owner <login> --format json --jq '.projects[] | select(.closed == false) | "\(.number)\t\(.title)"'`
for the logged-in user (`gh api user --jq .login`) and each of their orgs (`gh api user/orgs --jq '.[].login'`).
Default: none — then ask again the first time a board is created.

Show the result and ask once: "Write this to `~/.config/github-board/config.json`?" On yes, pass the JSON on stdin in ONE Bash call (each Bash call is a fresh shell, so no temp-file variable survives), replacing the placeholder line with the JSON you showed:

```bash
"${CLAUDE_SKILL_DIR}/scripts/init-config.sh" <<'JSON'
{"create_board": {"template_owner": "<login>", "template_number": <n>}}
JSON
```

Replacing a different template, after the user confirmed: the same call with `--force` after `init-config.sh`.

Add `"owner": "<login>"` to the payload only when `init-config.sh --show` exits 4 (no config yet).
Exit 3: a different template is configured; ask before passing `--force`.

## Sub-Agent Registry

| Agent | Concurrency | Purpose | Model |
|---|---|---|---|
| `github-board:template-inspector` | sequential (1) | Snapshot template structure to JSON | `haiku` |
| `github-board:board-creator` | sequential (2, 3, 5) | Copy, link, backfill | `haiku` |
| `github-board:workflow-syncer` | sequential (4) | Report auto-add absence + UI URL and filter | `sonnet` |
| `github-board:board-verifier` | sequential (6) | Diff new board vs snapshot | `sonnet` |

Phases are sequential because each needs the previous one's output. Sub-agents
still keep the orchestrator's context lean and right-size the model per task.

## Output

```
Created:    https://github.com/users/<owner>/projects/<n>
Linked to:  <owner/repo>
Fields:     13 (Status: 5 options, colours match)
View:       Kanban  BOARD_LAYOUT  columns=Status  swimlanes=Milestone  ✓ carried by copy
Workflows:  6/6 expected enabled (GitHub defaults — copy carries none)
Backfilled: 5 open issues
Verify:     structural PASS, exit 3

One manual step — no API can do this:
  Enable "Auto-add to project" at https://github.com/users/<owner>/projects/<n>/workflows
  Filter: repo:<owner>/<repo> is:issue,pr is:open
  Then re-run verify-board.sh for a clean exit 0.
```

## Gotchas

- The `project` OAuth scope is required: `gh auth refresh -s project`.
- Copying across owners (user → org) needs admin on both sides.
- A private template board needs collaborator access for cross-account use.
- `gh api graphql -F opts=<json>` cannot pass a list of input objects. Inline the
  literals into the query, or use `gh api graphql --input`.
- `gh api graphql` exits 0 on a `data: null` + `errors` envelope. Check `.errors`.
- Org and user projects have different URLs (`/orgs/…` vs `/users/…`). The
  scripts detect which; hand-written URLs often 404.

## See Also

- `references/graphql-snippets.md` — every query and mutation, plus the measured
  capability table and a re-check script
- `triage-issues` — labelling and prioritising items once they land
- `promote-shipped` — moving items to Done after a release
- `plan-milestones` — swimlanes are grouped by Milestone, so milestone
  hygiene directly shapes how this board reads
