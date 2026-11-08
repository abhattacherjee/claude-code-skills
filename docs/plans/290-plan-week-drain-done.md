# plan-week sync: drain Done cards out of their Focus column (#290)

One issue in milestone v4.3. The change is in `sync()` in
`plugins/github-board/skills/plan-week/scripts/weekly-focus.py`; tests go in
`plugins/github-board/tests/test_weekly_focus.py`.

## Why

On the live Weekly Focus board (#36, 722 cards, read 2026-11-08), This week holds 405 Done cards,
254 of them closed before 2026-11-01. Next holds 67 Done cards (61 closed before 2026-11-01) and
Later holds 2. The user asked for the Next and Later ones to be drained too.

Every board view filters on Focus (`focus:"This week" AND -status:Done`, `focus:Next`,
`focus:Later`, and Done This Week = `focus:"This week" AND status:Done AND closed:>@today-1w`).
So clearing a card's Focus drops it out of every view. It stays on the board, it can be set
back by hand, and no API behaviour has to be guessed (archived items and `items` were not
checked). Ruling: **drain = clear the Focus field**.

## Task 1: drain old Done cards in sync

Delegate: codex — one script and one test file; the check is the github-board pytest suite.

- Constants next to `STALE_DAYS`: `DRAIN_DAYS = 7` and `DRAIN_MAX = 100` (cards drained per sync
  run at most; the first live run has about 315 to drain, and many mutations at once can hit
  GitHub's secondary rate limit).
- `_BOARD_ITEMS_Q`: add `closedAt` to the Issue fragment. `board_items()` stores it as
  `content["closed_at"]` (None when absent).
- New `clear_opt(pid, item_id, field)`: runs
  `gh project item-edit --project-id <pid> --id <item_id> --field-id <field["id"]> --clear`
  with `parse=False`.
- New `_now()` returning `datetime.datetime.now(datetime.timezone.utc)`, so tests can patch it.
- In `sync()`, after the backfill loop: a card is **due** when all hold:
  - its Focus is set (any value: This week, Next or Later);
  - its Status is `Done`;
  - `content.state == "CLOSED"` and the key is not in `issues` (a reopened issue is never drained);
  - `content.closed_at` parses (`_parse_ts`) and is strictly older than `_now() - DRAIN_DAYS days`.
    An unparsable or missing date is never drained.
  Sort due cards oldest `closed_at` first, then by key. Take at most `DRAIN_MAX`. Then the same
  budget check the backfill uses (`_read_budget()`, `MIN_BUDGET`), at 1 write per card: when the
  budget is low, drain only `remaining - MIN_BUDGET` cards (none when that is 0 or less), and
  warn on stderr `weekly-focus: warning: drained N of M card(s): GraphQL budget low (R left)`.
  When the budget read fails, drain as usual (the same as the backfill: an unknown budget is
  not treated as low).
  For each drained card: `clear_opt(pid, it["id"], fields["Focus"])` and set `it["focus"] = None`.
- Why no flip-flop with the backfill: the backfill only touches issues closed on or after this
  week's Monday (local date), at most 6 days 23 h ago. A drained card closed more than 7 days ago.
- Report: JSON gets `"drained": [keys]` and `"drain_left": <due cards not drained this run>`.
  Text output gets `drained N: keys` (or `-`), with ` (M left for the next run)` when M > 0,
  after the `backfilled` line.
- `board_readme()`: add one rule line: sync clears the Focus of a Done card whose issue closed
  more than 7 days ago, so it leaves every view (set the Focus again to bring it back).
- Tests: the `Board` fixture also patches `clear_opt`, recording `(item_id, field_id, None)` in
  `self.sets`. Update `test_sync_json_shape_and_human_output`'s key set.

Tests (each fails before the change):

- `test_drain_and_backfill_on_one_fixture_board`: one board with This week, Next and Later Done
  cards closed 8 to 30 days ago (drained), a This week Done card closed 3 days ago (kept), a Next
  card closed this week (backfilled to This week, not drained), a reopened card (kept), an open
  Done card (kept), a Done card with no Focus (no write), and a card with no `closed_at` (kept).
  Asserts `drained`, `backfilled` and the exact writes.
- `test_drain_boundary_is_strictly_older_than_seven_days` (exactly 7 days: kept; 7 days and 1 s: drained).
- `test_drain_caps_each_run_and_reports_what_is_left` (`DRAIN_MAX` patched to 2: the 2 oldest go,
  `drain_left` is the rest, text says `left for the next run`).
- `test_drain_is_cut_to_the_budget` (low budget: only `remaining - MIN_BUDGET` drained, warning printed).
- `test_drain_marks_and_drains_an_old_closed_todo_card` (Status Todo, closed 20 days ago: marked Done and drained in the same run).
- `test_board_items_reads_closed_at` and `test_clear_opt_runs_item_edit_clear` (gh argv).

## Task 2: docs and versions

Delegate: claude — CHANGELOG, README and version fields across the monorepo; prose, no check command.

- `skills/plan-week/SKILL.md` step 1: report `drained` (and `drain_left` when non-zero). Version 2.2.0.
- `skills/plan-week/README.md`: the Focus paragraph says sync clears the Focus of Done cards
  closed more than 7 days ago.
- `plugins/github-board/CHANGELOG.md` `[1.4.0]`, plugin.json 1.4.0, marketplace.json, root
  README and plugin README version lines, root `CHANGELOG.md` `[Unreleased]` entry.

## Failure modes

- **Fail-open paths:** a missing or bad `closedAt` must not drain (test: no `closed_at` kept). A
  failed budget read drains as usual, the same rule the backfill uses; the per-run cap still bounds it.
- **Exit codes:** no new exits. A `clear_opt` gh failure raises `GhError` like every other write
  and goes through `_run_with_refetch`; sync is idempotent, so the rerun is safe.
- **Date boundaries:** strict `<` against `_now() - 7 days`, in UTC on aware datetimes (boundary
  test). Backfill uses local Monday; the gap between them is at least a few hours (see Task 1).
- **Doc counts:** the version numbers and the JSON key list are counted from the diff.
- **Broken Markdown:** CHANGELOG entries go inside the existing blocks; re-read around each.
- **Unrelated changes:** none; `__pycache__` is not staged.
- **Inputs:** the live board via `BOARD_ITEMS_Q` is the only source; `board_items` is a
  per-process memo, not a disk cache, so there is no stale copy. Test: `test_board_items_reads_closed_at`.
