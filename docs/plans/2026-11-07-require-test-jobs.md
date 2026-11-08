# Require the test jobs on develop (#291) — plan

**Goal:** a red test job in `.github/workflows/validate-skill.yml` blocks a merge to `develop`.

**Design:** add one aggregate job, `required-checks`, that `needs:` every other job in the
workflow and runs with `if: always()`. It fails when any needed job ended `failure` or
`cancelled`, and passes when each ended `success` or `skipped`. The `develop` ruleset then
requires `required-checks` next to `validate-skills` and `validate-plugins`.

Why not list each job in the ruleset: 8 jobs are matrix jobs, so their check names carry the
matrix values (`context-tests (macos-latest, 3)`). Renaming a job or a matrix value would leave
a required name that never reports, which blocks every merge. One aggregate name avoids that.
A guard script keeps the `needs:` list equal to the workflow's job list, so a new job cannot be
added without being required.

The workflow has no workflow-level `paths:` filter (`on: pull_request: branches: [main, develop]`),
so `required-checks` reports on every PR, docs-only PRs included.

## Task 1: guard script and its tests

Delegate: codex — self-contained, 2 new files under `scripts/`, one check command.

- `scripts/check-required-checks.py <workflow>`: stdlib only, Python 3.9. Reads the top-level
  job ids (two-space-indented keys under `jobs:`) and the `needs:` list of `required-checks`
  (flow list `[a, b]` or block list). Exit 0 when `needs` equals every other job id. Exit 1
  naming each missing or unknown id. Exit 1 when `required-checks` is missing, has no `needs`,
  or lacks `if: always()`. Exit 2 on a usage error or unreadable file.
- `scripts/test-check-required-checks.sh`: fixtures in a temp dir, each asserting the exit code:
  complete (0), one job missing from `needs` (1), unknown id in `needs` (1), no aggregate job (1),
  no `if: always()` (1), missing file (2), and the real workflow (0).
- Check: `bash scripts/test-check-required-checks.sh`

## Task 2: wire the workflow

Delegate: claude — edits `.github/`, which `cx apply` refuses.

- Add the `required-checks` job at the end of `validate-skill.yml`: checkout, run the guard on
  the workflow, then fail when any `needs.<job>.result` is not `success` or `skipped`.
- Run `scripts/test-check-required-checks.sh` in `validate-plugin-tests` (the `scripts/**` tests job).
- CHANGELOG entry under Unreleased.

## Task 3: ruleset (after merge)

Delegate: claude — a live GitHub setting, not code.

- After the PR merges, add `required-checks` to ruleset 17152213 (`develop-protection`) with
  `gh api -X PUT`, keeping every other rule as it is. Read it back.
- Doing it after merge means no PR opened before the merge is blocked by a check its branch
  does not have. There are no open PRs today.

## Failure modes

- **Fail-open paths:** the aggregate must not pass when a needed job failed or was cancelled.
  The workflow step is an allow-list: any result other than `success` or `skipped` fails it,
  so a new result value fails closed. Proved by a forced-failure run on the PR (a temporary
  failing commit, then reverted).
  A guard that cannot parse the file must exit non-zero, not 0: fixture tests for missing file (2)
  and missing aggregate (1).
- **Exit codes:** guard exits 0/1/2 as above; each has a fixture test.
- **Date boundaries:** none; no dates are read.
- **Doc counts:** the CHANGELOG and PR body name job counts; count them from `grep -c` on the workflow.
- **Broken Markdown:** CHANGELOG entry goes inside the Unreleased block; markdownlint runs in preflight.
- **Unrelated changes:** only the plan, 2 new scripts, the workflow and CHANGELOG change.
- **Inputs:** the guard reads the workflow file in the checkout (source of truth); missing file is a fixture.
- **Bypass routes:** (a) a new job added without adding it to `needs` — the guard fails the
  aggregate; fixture "one job missing". (b) `if: always()` dropped, so the aggregate is skipped
  when a dependency fails, and a skipped required check counts as passing — guard requires
  `if: always()`; fixture "no if". (c) Ruleset drift (someone removes the check) — out of the
  repo's reach; Task 3 reads the ruleset back.
