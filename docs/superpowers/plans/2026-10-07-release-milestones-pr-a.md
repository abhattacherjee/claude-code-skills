# Release milestones, PR A (#203) Implementation Plan

> **For agentic workers:** one implementation pass (ship Phase 4 default). Follow TDD per task and commit per task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Write the release milestone where the release is already known: `apply-plan.sh` (plan-milestones) and `apply-promotions.sh` (promote-shipped).

**Architecture:** All milestone writes become `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`, so closed milestones work. apply-plan resolves titles to numbers from the full milestone list. promote-shipped carries each item's milestone from the inventory and maps the release tag it already resolves to a milestone title.

**Tech Stack:** bash 3.2-safe shell, jq, gh; pytest tests with stubbed `gh` on PATH.

**Spec:** `docs/superpowers/specs/2026-10-07-milestone-release-sync-design.md` (section "PR A"). Acceptance criteria: issue #203.

## Global Constraints

- Bash 3.2 safe: no `mapfile`, associative arrays, `${x,,}`, `|&`.
- Exactly 3 `gh auth status` call sites in `promote-shipped/scripts/*.sh` (`tests/test_read_scripts_scope_preflight.py`). Add none.
- Exactly 9 promote classes (`tests/test_structure.py`). Add none.
- Do not add a column to apply-promotions' `\037` projection that `tests/test_apply_promotions_reconcile.py` pins. Read the milestone from the candidate JSON by item id.
- A comment failure, and now a milestone failure, never undoes the board move (apply-promotions.sh:28-30 contract).
- No test touches GitHub. Every `gh` call is stubbed.
- Run every job in `.github/workflows/validate-skill.yml` locally before pushing, plus `./scripts/commit-preflight.sh`. Stage files by name.
- Commit trailer: `Co-Authored-By: <the model you are> <noreply@anthropic.com>`.

## Review Focus

1. A milestone title that exists twice, once open and once closed (GitHub allows this after a rename). Resolve by exact title, and refuse ambiguity instead of picking one.
2. A tag with no matching milestone (`v4.0.0` with only `v4.0`, or neither). Exact `vX.Y.Z` first, then `vX.Y`. No match means a warning and no write.
3. `--release-tag` forced, and `--no-release-comment` given. The forced tag is used for the milestone. With no-comment, the lookup still runs.
4. An item already in the right milestone gets no write and no preview line.
5. `wontfix` and `nopr` items keep their milestone, even when a release tag is forced.

---

### Task 1: apply-plan.sh writes by number, and accepts `closed_moves`

**Files:**
- Modify: `plugins/github-board/skills/plan-milestones/scripts/apply-plan.sh`
- Modify: `plugins/github-board/skills/plan-milestones/SKILL.md` (plan JSON example and rules, gh mechanics note at about :200-206)
- Modify: `plugins/github-board/skills/plan-milestones/references/triage-criteria.md:106` (`--milestone` takes a title: now REST by number)
- Test: new `plugins/github-board/tests/test_apply_plan.py`. Reuse the bash-stub pattern from `tests/test_list_failures.py:27-34, 85-130`.

**Interfaces:**
- Plan JSON gains `closed_moves: [{issue: int, to: str}]`. `moves[]` keeps its rationale rule (at least 10 characters).
- `EXISTING` becomes a JSON array of `{title, number, state}`, from `milestones?state=all --paginate` merged with `jq -s add`.

- [ ] **Step 1: Write the failing tests.** Stub gh: `api repos/*/milestones*` returns `[{"title":"v0.5","number":5,"state":"closed"},{"title":"v0.6","number":6,"state":"open"}]`; `api -X PATCH repos/*/issues/*` logs and exits 0; `issue comment` logs. Tests:
  - `test_move_into_closed_milestone_uses_rest_by_number`: plan `moves:[{issue:11,to:"v0.5",rationale:"shipped inside v0.5.0"}]`, run with `--apply`, assert the log has `api -X PATCH repos/O/R/issues/11 -F milestone=5`, and no `issue edit`.
  - `test_closed_moves_need_no_rationale_and_post_no_comment`: plan `closed_moves:[{issue:181,to:"v0.6"}]`, `--apply`, assert the PATCH with `milestone=6` and no `issue comment` in the log.
  - `test_closed_moves_unknown_target_is_refused`: `to:"v9.9"`, exit non-zero, no PATCH.
  - `test_dry_run_lists_closed_moves`: no `--apply`, the output names #181 and v0.6, and the log has no PATCH.
  - `test_failed_write_prints_error_and_exits_1`: the stub fails the PATCH with `HTTP 422: Validation Failed` on stderr. Assert exit 1, and that the output contains `422`.
  - `test_ambiguous_title_is_refused`: two milestones titled `v0.5` (one open, one closed). Exit non-zero, naming the title.
- [ ] **Step 2: Run them; they fail** (no `closed_moves`; the script uses `gh issue edit`).
- [ ] **Step 3: Implement.** Keep `{title,number,state}` in `EXISTING`. Resolve each target to exactly one number. `create_milestones` entries get their number from the POST response. Validate `closed_moves` in the unknown-target check and the dry-run print, without a rationale. Write every move through REST with the number. Collect failures with gh's stderr and exit 1 if any. Post the rationale comment only for `moves[]`.
- [ ] **Step 4: Run the tests; they pass.** Also run `tests/test_list_failures.py`.
- [ ] **Step 5: Mutation check.** In a scratch copy, revert each guard alone (number lookup, ambiguity refusal, exit-1-on-failure, no-comment for closed_moves) and name the test that goes red. Report the table.
- [ ] **Step 6: Commit.** `plan-milestones: assign milestones by number through REST; closed_moves (#203)`

### Task 2: promote-shipped fixes the release milestone of each shipped item

**Files:**
- Modify: `plugins/github-board/skills/promote-shipped/scripts/inventory-board.sh` (Issue and PullRequest fragments at about :194-220, projection at about :260-304: add `milestone{number title state}`)
- Modify: `plugins/github-board/skills/promote-shipped/scripts/find-promotable.sh` (pass `milestone` through in the COARSE object at about :160-199, and in each candidate)
- Modify: `plugins/github-board/skills/promote-shipped/scripts/apply-promotions.sh` (milestone cache next to `releases_file`, lookup next to `find_release_for_commit` at about :162-230, dry-run block at about :385-391, apply path, summary at about :509-516)
- Modify: `plugins/github-board/skills/promote-shipped/SKILL.md` (Phase 4 preview lines, Phase 5 writes, flags)
- Test: new `plugins/github-board/tests/test_apply_promotions_milestone.py`. Reuse the `_STUB`, `_candidate` and `_run` pattern from `tests/test_apply_promotions_release_lookup.py:36-71, 128-160`.

**Interfaces:**
- Each candidate gains `milestone: {number, title, state} | null`.
- New function `milestone_for_tag <repo> <tag>`: prints `<number>\t<title>` or nothing. It tries an exact `vX.Y.Z` title, then `vX.Y`, with the leading `v` optional on both sides. The milestone list (`repos/R/milestones?state=all&per_page=100 --paginate`) is cached in `CACHE_DIR` as `milestones_<slug>`. A failed list warns once and is not cached.

- [ ] **Step 1: Write the failing tests.** Stub releases so commit `aaa` is in `v4.0.0`, and stub milestones `[{"title":"v4.0","number":15,"state":"closed"},{"title":"v4.1","number":13,"state":"open"}]`.
  - `test_dry_run_lists_mismatch`: a `merged` candidate whose milestone is `v4.1` and whose PR merge commit is `aaa`. The `--dry-run` output has `would set milestone: v4.1 -> v4.0 (v4.0.0)`, and the log has no PATCH.
  - `test_apply_fixes_into_closed_milestone_by_number`: `--apply` logs `api -X PATCH repos/O/R/issues/N -F milestone=15`.
  - `test_matching_milestone_no_write`: the candidate is already in `v4.0`. No preview line, no PATCH.
  - `test_null_milestone_gets_fixed`: the candidate milestone is null, so the preview shows `none -> v4.0`.
  - `test_exact_patch_title_wins`: milestones `v3.18` and `v3.18.1`, tag `v3.18.1`. The target is `v3.18.1`.
  - `test_no_matching_milestone_warns_and_skips`: tag `v9.0.0` with no milestone. A warning, no PATCH, exit 0.
  - `test_wontfix_and_nopr_untouched`: both classes with `--release-tag v4.0.0`. No milestone lines, no PATCH.
  - `test_forced_tag_used_for_milestone` and `test_no_release_comment_still_fixes_milestone`.
  - `test_milestone_write_failure_is_reported_not_fatal`: the PATCH fails. The board move still happens, the summary counts 1 milestone failure, and the exit code follows the existing comment-failure rule.
  - Inventory: one test that `inventory-board.sh`'s query contains `milestone` in both fragments and the projection carries it (stub the GraphQL response).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** to the spec's PR A promote-shipped section and the interfaces above.
- [ ] **Step 4: Run all github-board tests**: `python3 -m pytest plugins/github-board/tests -q`, plus the reconcile, scope-preflight and structure tests by name.
- [ ] **Step 5: Mutation check** of each guard, one at a time: class filter, exact-before-minor title match, equal-milestone skip, number lookup, non-fatal failure. Report the table.
- [ ] **Step 6: Commit.** `promote-shipped: set each shipped item's release milestone (#203)`

### Task 3: Versions, CHANGELOGs, docs

**Files:** `plugins/github-board/.claude-plugin/plugin.json` (1.0.2 -> 1.1.0), `plugins/github-board/CHANGELOG.md`, `plugins/github-board/skills/promote-shipped/CHANGELOG.md` (2.1.0) and any skill version fields the repo's tests pin (check `tests/test_structure.py` and the plugin's other CHANGELOG/version rules first), root `CHANGELOG.md` `[Unreleased]`. Then run `python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .` and `./scripts/check-docs.sh`.

- [ ] **Step 1:** Bump the versions and write the entries. Count every number you state from the diff.
- [ ] **Step 2:** Regenerate the catalogue; check-docs is clean.
- [ ] **Step 3:** Run every CI job locally, then preflight.
- [ ] **Step 4: Commit.** `github-board 1.1.0: release milestones in apply-plan and promote-shipped (#203)`
