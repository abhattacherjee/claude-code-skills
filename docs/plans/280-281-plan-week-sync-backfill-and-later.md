# plan-week sync: Next or Later for new cards (#281), backfill closed issues (#280)

Batch of two issues in milestone v4.3. Both change `sync()` in
`plugins/github-board/skills/plan-week/scripts/weekly-focus.py`; tests go in
`plugins/github-board/tests/test_weekly_focus.py`.

Left out on purpose: the optional `split` / `sync --resplit` command from #281. The board was
split by hand on 2026-10-29, and a resplit moves cards the user placed, which the issue's own
rule forbids sync to do.

## Task 1: new cards go to Next or Later (#281)

Delegate: codex — one script, one test file, two docs; the check is the github-board suite.

Rule: a card belongs in **Next** when its lane is `Security`, or it is in its repo's current
milestone (`in_current`) with priority P1 or P2. Every other card belongs in **Later**.

- Add `SECURITY_LANE = "Security"` and
  `focus_for(lane, labels, in_current) -> "Next" | "Later"`, using the existing `priority(labels)`.
- `in_current` for an open issue: `issue["milestone"] is not None and issue["milestone"] == current.get(repo)`
  (the same test `candidates()` and `show_items()` use). Add a small helper and use it in both
  new call sites.
- The add path in `sync()` (now `add(..., "Next")`): pass `focus_for(lane_for(repo, labels), labels, in_current)`
  and store that focus in `have[key]`.
- The `focus_filled` path (a card with an empty Focus): same rule. The lane counts as Security
  when the card's own Lane or `lane_for(...)` is `Security`.
- Sync never changes a Focus that is already set. The in-progress path (This week) is unchanged.
- `board_readme()` and `skills/plan-week/README.md`: say what Next and Later mean, and that sync
  files new cards by this rule and never moves a card that already has a Focus.
- Update the existing tests that assert a new candidate lands in `Next` (for example
  `b.adds == [("app#1", "Next")]` near line 1292 and `("i1", "F", "Next")` near line 1303) to the
  focus the rule gives, adding labels or milestones where a test meant "lands in Next".

Tests (each fails before the change):

- `test_new_security_lane_issue_lands_in_next`
- `test_new_p1_or_p2_in_current_milestone_lands_in_next` (parametrized P1, P2)
- `test_new_issue_outside_current_or_low_priority_lands_in_later` (parametrized: P1 outside current, P3, P4, no priority)
- `test_sync_keeps_an_existing_focus` (This week, Next and Later cards stay as set)
- `test_empty_focus_is_filled_by_the_same_rule` (one Next, one Later)
- `test_skill_plan_mode_still_reads_next` (SKILL.md plan mode still names Next items)

## Task 2: backfill issues closed this week (#280)

Delegate: codex — same files as Task 1 plus `SKILL.md`; the check is the github-board suite.

- `CLOSED_Q` also selects `stateReason` and `labels(first:20){nodes{name}}`.
- `closed_since(start)` returns `{repo#N: {"reason": stateReason, "labels": [...]}}` instead of a
  set. Same local-date filter (`day >= start`). Update its one caller and its test.
- Call `closed_since(start)` once in `sync()`, after the `marked_done` loop; reuse the result for
  `closed_since_monday` and the backfill.
- Backfill, for each closed key in sorted order:
  - skip unless `reason == "COMPLETED"` (leaves `NOT_PLANNED`, `DUPLICATE` and unknown alone);
  - skip when the key is in `issues` (reopened since the search ran);
  - skip when the repo is in `FROZEN`, unless the key is in `ALWAYS`;
  - not on the board: `add(..., "This week")`, then set Status `Done` (warn, as the other paths do,
    when the board has no `Done` option); record it in `have` with focus This week, status Done
    and content state CLOSED;
  - on the board with a Focus other than `This week`: set Focus to `This week`.
- Report the keys in a new `backfilled` list in `sync --json`, and a `backfilled N: ...` line in
  the text output. `done_this_week` then counts them.
- The `Board` test fixture keeps accepting a set for `closed` (reason `None`, so no backfill) and
  also takes a dict for the new tests.
- `SKILL.md` step 1: report `backfilled` (cards added or moved to This week because they were
  closed this week).

Tests (each fails before the change):

- `test_backfill_adds_missing_completed_issue_as_this_week_done`
- `test_backfill_moves_closed_card_from_next_or_later` (parametrized Next, Later)
- `test_backfill_skips_not_planned_and_duplicate`
- `test_closed_since_week_start_boundary` (closed exactly at local Monday 00:00 is in; one second earlier is out)
- `test_backfill_skips_frozen_repo_unless_always`
- `test_backfill_skips_reopened_issue`
- `test_sync_json_has_backfilled` (extend the shape test) and `test_skill_reports_backfilled`

## Failure modes

- **Fail-open paths:** a closed issue with no `stateReason` (older closures) must not be
  backfilled: test `test_backfill_skips_not_planned_and_duplicate` includes `None`. A board with no
  `Later` option is not possible (`ensure_fields` creates it), so no new fallback.
- **Exit codes:** no new exit path. Budget exit 3 still runs before any write; existing tests cover it.
- **Date boundaries:** week start at local Monday 00:00, and the UTC-day widening of the search:
  `test_closed_since_week_start_boundary`.
- **Doc counts:** no numbers in the docs change. Checked by reading the README and SKILL diffs.
- **Broken Markdown:** README and SKILL edits stay inside their lists; checked by re-reading.
- **Unrelated changes:** only the files named above; checked with `git diff --stat` and
  `--diff-filter=D`.
- **Inputs:** the board read (`board_items`), open issues (`open_issues`), closed issues
  (`closed_since`) and the config (`FROZEN`, `ALWAYS`, `LANES`). GitHub is the source of truth;
  the board cache is refreshed by `_run_with_refetch`. A stale board read (card already added)
  is handled by `add` being skipped for keys in `have`; a reopened issue by the `issues` check.
