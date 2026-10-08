# Changelog

All notable changes to the `promote-shipped` skill (named `github-release-board-promote`
before 2.0.0) are documented here.
This skill follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.1] — 2026-10-07

### Changed
- `apply-promotions.sh` maps a release tag to its milestone through the shared
  `lib/config.py milestone-for-tag` (`gb_milestone_for_tag`), which move-card and
  plan-milestones also use, instead of its own copy of the rules. The rules are
  unchanged, and every #203 test passes unedited. (#204)
- All three skip warnings now read `WARN: <reason> in <repo>; release milestone not set.`,
  still once per repo and tag. The reasons are `no milestone titled X.Y.Z or X.Y for
  <tag>`, `ambiguous: <title> #<n>, … for <tag>`, and `tag '<tag>' is not vX.Y.Z or
  vX.Y`. (#204)
- A tag that is not a version is now checked before the milestone list is read. With an
  unreadable list, such an item is counted as SKIPPED, not FAILED. (#204)

## [2.1.0] — 2026-10-07

### Added
- **Each promoted `merged` item gets its release milestone (#203).** `apply-promotions.sh`
  maps the release tag it resolves (or `--release-tag`) to a milestone: the exact
  `vX.Y.Z` title first, then `vX.Y`, with the leading `v` optional on both sides. When
  the item is in another milestone, or none, it is set after the board move with
  `gh api -X PATCH repos/O/R/issues/N -F milestone=<number> --jq .milestone.number`.
  Unlike `gh issue edit --milestone`, this can assign a closed milestone. A reply that
  names another milestone counts as a failed write; on an HTTP error the response body
  is printed. The milestone list (`state=all`, paginated) is read once per repo and run.
  No match, two matches, or a tag that is not a version prints a warning and changes
  nothing. `nopr` and `wontfix` items keep their milestone.
- Dry run: `would set milestone: <current|none> -> <target> (<tag>)`, printed only when
  the milestone would change, and `milestone: skipped — <reason>` when it is left alone.
- Summary line, shown only when at least one item is `merged`. After `--apply`:
  `Milestones: N set, N unchanged, N skipped, N failed`. After `--dry-run`:
  `Milestones: N to set, N unchanged, N skipped, N cannot check`.
- `inventory-board.sh` fetches `milestone { number title state }` for issues and PRs;
  `find-promotable.sh` passes it through in each candidate.

### Changed
- `--no-release-comment` still looks up the release, so the milestone can be set.
  `--release-tag` still skips the lookup and is used for the milestone too.
- A failed milestone write, or a milestone list that cannot be read, is reported like a
  comment failure: it is counted, and it never undoes the board move or changes the
  exit code. A failed list, or an empty reply, is not cached as an empty one. The
  `ACTION NEEDED` text says to re-run against the same candidates file with
  `--apply --no-release-comment`.
- A candidate repo with a `.` or `..` part gets no milestone write
  (`FAILED — malformed issue number or repo`).

## [2.0.0] — 2026-10-02

### Security
- **A pull request from another repository can no longer promote an issue.** Timeline
  discovery accepted any merged cross-referenced PR whose body said `fixes #N`, even
  from a different repo (where `#N` means that repo's issue), then checked its merge
  commit and looked up the release in the foreign repo. Only PRs in the issue's own
  repo are credited now (formal links too), a fully-qualified `owner/repo#N` counts
  only when it names the issue's repo, and reachability always uses the issue's repo.
  A foreign PR that claims the issue, merged or not, holds the card in the new
  **`hold-foreign-pr`** class. `apply-promotions.sh` also refuses (exit 1, no move, no
  comment) a `merged` candidate whose merged PRs are all from another repo.

### Fixed
- **Every closing form GitHub accepts now credits the PR, so the release guard applies.**
  Timeline discovery accepted only `Fixes #N` and `Fixes owner/repo#N`. A develop-merged
  PR that said `Fixes: #N` or `Closes https://github.com/owner/repo/issues/N` was not
  credited, and the closed issue was promoted as `nopr` before release. Both forms now
  count (the URL only for the issue's own repo), so the card is held as
  `hold-unreleased` until the base branch contains the merge.
- **An unmerged closing PR in the timeline holds the issue.** Discovery dropped every
  unmerged PR, so an issue closed by hand while its `Closes #N` PR was still open was
  promoted as `nopr`. Such a PR now adds to `linkedPRCount` and the card is held as
  `hold-unmerged-pr`.
- **`find-promotable.sh` no longer fails OPEN when timeline PR discovery errors.**
  The fallback query's result was `|| echo "[]"`, so an auth expiry, rate limit,
  missing scope, network error or jq failure produced an empty PR set — which the
  classifier reads as positive evidence of a no-PR closure and promotes as `nopr`,
  commenting that the issue was "an administrative or findings-only closure". Since
  `linkedPRCount == 0` is the normal Git-Flow state, this was the common path. The
  function now returns a `FAILED` sentinel, the candidate is flagged
  `discoveryFailed`, and the new **`hold-discovery-failed`** class (never promoted)
  holds it with the reason printed to stderr.
- **`apply-promotions.sh` release lookup paged incorrectly.** `gh api --paginate`
  applies `--jq` per page, so `sort_by(.published_at)` only ordered *within* a page;
  with GitHub returning releases newest-first the loop stamped issues with a too-new
  tag instead of the oldest containing release. Pages are now combined and sorted
  once. A failed listing is no longer cached as `[]` (which silently suppressed the
  comment for every later item in the repo) — it warns and reports the item's
  comment as FAILED.
- **`apply-promotions.sh` reported a zero-row run as a synced board.** A jq
  projection error emits no rows, so every counter stayed 0 and the script printed
  "Promotions: 0 ok, 0 failed" and exited 0 with a non-zero candidate count. Rows
  processed are now reconciled against the distinct-itemId count; a mismatch exits 1.
- **`apply-promotions.sh` did not guard `statusField.id`.** `project.id` and
  `doneOptionId` were validated but a missing field id reached the mutation as the
  literal `"null"`, failing every item individually.
- **`apply-promotions.sh --apply` now pre-flights the write-capable `project`
  scope**, like the read scripts do for `read:project`, instead of discovering a
  read-only token halfway through the mutation loop. `--dry-run` is exempt. The
  check reads `gh auth status --active --hostname "${GH_HOST:-github.com}"`.
  Unfiltered, `gh` reports every host it knows and every account on each, so a
  `project` scope held on a GHES host, or by a second account on github.com, would
  have satisfied the gate for the account the mutation actually uses. `--active`
  alone does not fix this: it picks the active account *within* each host and
  still prints them all. When no scopes are reported at all (fine-grained PAT, bare
  `GH_TOKEN`) it warns and proceeds rather than hard-failing a token that may well
  be write-capable, and the remediation now covers PATs, which `gh auth refresh`
  cannot change.
- **A failed release compare no longer reads as "this release does not contain the
  commit".** It fell through to the next, newer release, so one transient 5xx on
  the true container stamped the issue with a too-new tag — the wrong-tag outcome
  the pagination fix exists to prevent, via the error path. Now warns, claims
  nothing, and deliberately does NOT cache that verdict.
- **Row separators: unit separator instead of tab.** Tab is IFS whitespace, so runs
  fold and an EMPTY column vanishes — emitting a fixed column count never helped.
  A candidate with a null `repo` shifted `promoteClass` into the merge-SHA slot, so
  a shipped item took the no-merged-PR branch and was annotated "closed with zero
  linked pull requests" on an issue that shipped via a merged PR. Fixed on the
  candidates row and the releases row, with field values scrubbed of CR/LF.
- **`nopr` no longer claims the issue was "completed".** `stateReason` is nullable
  and legacy issues carry null, which the class silently reported as `COMPLETED` in
  the preview, the docs and the posted comment. Behaviour is unchanged — those
  issues still promote — but the claim is gone from all three surfaces. Requiring
  `COMPLETED` was the alternative and was rejected: it would park legacy issues in
  a hold class that can never resolve, the stuck card `wontfix` exists to prevent.
- **The dry-run preview names the target column**, not just its option id. The
  resolver's last tier is a substring match on `done|released|shipped`, on boards
  whose real columns include "Done in develop".
- **`inventory-board.sh` warns when an issue has more than 10 linked PRs**, since
  that cap can change a classification (`linkedPRCount` separates `nopr` from
  `hold-unmerged-pr`). The other two unpaginated caps are left silent on purpose.
- **Exit-code headers on the three scripts that lacked them** (`apply-promotions.sh`,
  `find-promotable.sh`, `task-manifest.sh`), each derived from that script's actual
  exits rather than copied from a sibling — `apply-promotions.sh` has an exit 3 the
  others do not, `find-promotable.sh` deliberately has no auth code, and
  `task-manifest.sh` uses 1 where its siblings use 2. `tests/test_script_exit_codes.py`
  runs every documented path and pins the headers to reality.
- **`inventory-board.sh --board-id` with no value** exited 1 silently, the same
  `shift 2` under `set -e` defect fixed earlier in `--release-tag` and `--base`. It
  was missed then and found now by writing the exit-code test. Now exits 2 with a
  message and usage.
- **The two READ scripts scope their preflight like the write script does.**
  `discover-boards.sh` and `inventory-board.sh` still called bare
  `gh auth status`, so a `read:project` held on an unrelated GHES login satisfied
  a github.com run: the preflight passed and the failure surfaced later at the
  GraphQL call, which is what the preflight exists to prevent. Same defect as the
  write-scope check, fixed when only that one call site was updated. All three now
  use `--active --hostname "${GH_HOST:-github.com}"`, and
  `test_scope_preflight_is_identical_across_scripts` fails if any `gh auth status`
  in the directory omits either flag — including one a future script adds.
  The read scripts also gain the write path's three-way verdict: unreadable scopes
  (fine-grained PAT, bare `GH_TOKEN`) warn and proceed rather than hard-failing a
  token that can very likely read, with remediation that names PATs.
- **Trailing value-taking flags** (`--release-tag`, `--base`) reported nothing and exited 1: `shift 2` with one argument
  left returns non-zero under `set -e`. Each now names itself and exits 2.
- **A comment-only failure is no longer readable as a clean run**: `apply-promotions.sh`
  prints an explicit `ACTION NEEDED: N release comment(s) failed` line. The exit
  code is deliberately unchanged — comment failures remain non-fatal by contract.
- **`-f` instead of `-F`** for `String!`/`ID!` GraphQL variables across all four
  scripts (`-F` type-infers, so an all-numeric owner/repo would be sent as an Int).
  The genuinely-`Int!` `num` keeps `-F`.
- **`inventory-board.sh` null-node checks** after the meta query and each items
  page: `gh` exits 0 on a response whose `node` is null (bad id / no access).
- **Comment failures now report their cause** — stderr's first line is kept, so a
  locked conversation is distinguishable from an expired token.
- **`references/projects-v2-graphql-snippets.md` drift**: section 2's items query
  was missing `stateReason` on the Issue and `mergeCommit { oid }` on both the
  linked-PR nodes and the PullRequest fragment — all three are load-bearing for the
  classifier. The timeline fallback query is now documented too.


### Changed
- **Renamed to `promote-shipped`** and moved into the `github-board` plugin (#146). Invoke it as `/github-board:promote-shipped`. The old name still matches as a trigger phrase.
- `SKILL.md` is the version that documents what the scripts in this release do (the `hold-discovery-failed` class, the three scope cases, the trimmed description below). The installed copy the plugin was first built from was an older snapshot of it. (#146)
- Held-item output no longer asserts "merged but not in main" for a reachability
  check that errored; an errored check reads "could not verify".
- Frontmatter `description` trimmed (811 → 566 chars) — implementation detail and
  the `Covers:` clause removed, trigger conditions and the no-boards no-op contract
  kept. The stale `/finalize-release` trigger is now `/finish` (git-flow plugin).

### Added
- `discover-boards.sh` caches the repo's board list for 7 days (`--no-cache` skips it); an empty list is never cached. `inventory-board.sh` drops the cached list when a board id no longer resolves. (#146)
- `tests/` — pytest regression coverage for the fail-open discovery path, the
  release-lookup pagination and failure handling, the row reconciliation, the
  `statusField.id` guard and the write-scope pre-flight. Every test was proven
  non-vacuous by reverting its fix.

## [1.5.0] — 2026-08-13

### Added
- **Guidance for squash-release (double-squash Git Flow) repos in Phase 3.** When
  `release/* → main` is squash-merged, the squash commit shares no ancestry with the
  PR merge commits on `develop`, so the reachability guard classifies genuinely
  shipped work as `hold-unreleased`. `--skip-main-check` is required to reach the
  `merged` class in that shape — but it cannot reach `nopr`/`wontfix`, so running it
  alone strands administrative closures. The skill now documents running BOTH passes
  and unioning the candidate sets, plus reconciling the promoted total against the
  source column's size.
- **Independent verification recipe for the bypassed guard.** With `--skip-main-check`
  the ancestry net is off, so Phase 3 now shows how to re-derive it correctly:
  `git merge-base --is-ancestor <mergeCommitOid> <released-develop-sha>` against the
  branch that actually shipped, rather than the squashed `main`.
- **Edge case** for squash-merged release branches, distinguishing it from the
  already-documented squashed-*PR* case, which the `compare` API handles fine.
- **Anti-pattern**: treating a single filter pass as the complete set.

### Notes
- Motivated by a real miss: a release promoted 33 `merged` items via
  `--skip-main-check` and left 3 `nopr` issues stranded in the source column. Neither
  pass reported a gap — each succeeded on its own subset — and it surfaced only when
  a human noticed one of the three still sitting on the board.
- No script changes; `find-promotable.sh` behaviour is unchanged. This release is
  documentation only.

## [1.4.0] — 2026-08-03

### Added
- **`promoteClass` taxonomy in `find-promotable.sh`.** Every candidate is now assigned exactly one of seven classes instead of a binary promotable/dropped verdict: `merged`, `wontfix`, `nopr` (promote) and `hold-unreleased`, `hold-unmerged-pr`, `hold-no-fallback`, `hold-other` (hold). Emitted in the JSON as `.candidates[].promoteClass`, with the held set surfaced as a new top-level `.held` array.
- **Closed issues with no merged PR are now promoted rather than parked.** `wontfix` (`stateReason=NOT_PLANNED`) and `nopr` (`COMPLETED` with zero linked PRs) both promote. Previously they were filtered out, which parked them permanently: a not-planned issue can never acquire a merged PR, so the merge rule could never fire, and the card blocked its column from draining on every subsequent release. Observed on the claude-code-skills board, where #4, #16, #63 and #52 accumulated across four releases.
- **Explanatory comment on no-merged-PR promotions.** `apply-promotions.sh` posts a fixed note naming which rule was bypassed and what justified it, with distinct wording for `wontfix` vs `nopr`. The `wontfix` note states explicitly that no release milestone was assigned, since release milestones denote what shipped.
- **Comment idempotency.** No-merged-PR comments carry a `<!-- gh-board-promote:no-merged-pr -->` marker and are skipped when already present, so re-running a release (normal after a partial failure) does not stack duplicates. Lookup failure falls through to posting — a duplicate comment is cosmetic, a missing audit trail is not.
- **Four-group dry-run preview** grouping candidates by `promoteClass` with a per-item reason, plus a `HELD BACK` section explaining each hold.
- **`stateReason` in `inventory-board.sh` output** (`.items[].issue.stateReason`), required to tell `NOT_PLANNED` from `COMPLETED`.

### Fixed
- **`apply-promotions.sh` TSV builder dropped a column for candidates with no merged PR.** The merge-SHA field used a jq generator, which yields nothing for an empty `mergedPRs` array; jq omits it from the array entirely, so `@tsv` emitted 7 columns instead of 8 and every field after it shifted left in the `read`. Replaced with `map(...)[0] // ""`, which always emits the column. Latent before this release (no-merged-PR candidates never reached the loop) but load-bearing now.

### Changed
- SKILL.md Phase 3 documents the full class table, the ordering constraint, and why `nopr` requires *zero linked PRs* rather than zero *merged* PRs.
- `--skip-main-check` tags its output `promoteClass: "merged"` and returns an empty `held`; the no-PR classes are deliberately unreachable on that path, since without the reachability check there is no evidence to classify from.

### Notes
- `hold-unreleased` is unchanged and remains the critical guard. Ordering places it *before* `wontfix`, so an issue with a merged-but-unreleased PR is never promoted early regardless of `stateReason`.

## [1.3.1] — 2026-04-26

### Fixed
- **`apply-promotions.sh` Status mutation failed for all-numeric option IDs.** `gh api graphql -F oid="98236657"` auto-coerced the all-digit string to an integer, but the GraphQL variable is declared `$oid:String!`, so the API rejected every call with `Variable $oid of type String! was provided invalid value`. Empirical hit on 2026-04-26 obsidian-brain board promotion: 0/10 succeeded. Switched the option-ID parameter from `-F` (auto-coerce) to `-f` (raw string). `ID!` parameters elsewhere (project ID, item ID, field ID, board ID) keep `-F` since the GraphQL `ID!` type accepts both strings and ints.

## [1.3.0] — 2026-04-25

### Added
- **Release-comment annotation**: after each successful Status→Done mutation, `apply-promotions.sh` posts `🚀 Released in [<tag>](url) (published <date>). Moved to Done on the project board.` to the linked issue/PR via `gh issue comment`.
- **Smallest-release auto-detection**: walks `gh api /repos/{owner}/{repo}/releases` oldest-first and picks the first release whose tag contains the PR's merge commit (via `compare/{sha}...{tag}` returning `ahead` or `identical`). Per-repo release list + per-(repo,sha) result cached for the run.
- **`--release-tag <tag>` flag**: forces a specific tag for every comment, skipping auto-detect (useful when the lookup picks the wrong release).
- **`--no-release-comment` flag**: skips commenting entirely; only the board move happens.
- **Dry-run preview**: shows the resolved release tag per item ("would comment: v1.6.2 (auto-detected)") so users can verify before applying.
- **Comment failure isolation**: a failed `gh issue comment` is reported separately and does NOT mark the promotion as failed. Board move is the primary side-effect; comment is annotation.
- **Defensive zsh-readonly fix**: renamed `local status` → `local cmp_status` inside the release-lookup function to avoid `(read-only variable: status)` errors if the function is ever sourced into zsh (the script's `#!/usr/bin/env bash` shebang already protects against this in normal use).

### Changed
- SKILL.md Phase 4/5 now document the comment behavior and override flags.

## [1.2.0] — 2026-04-25

### Changed
- **Renamed skill** from `release-board-promote` → `github-release-board-promote` for clearer scoping (it's GitHub-specific; future board automations for Jira/Linear/Trello would be separate skills).
- Updated frontmatter `name`, plugin-manifest `name`/`displayName`/`skills`/`homepage`, and all internal references.

## [1.1.0] — 2026-04-25

### Fixed
- **Critical filter bug**: v1.0.0 promoted any item with a merged linked PR, regardless of whether the PR's merge commit had reached main. In Git Flow this incorrectly promoted items still parked in "Dev Complete" because their PRs were merged to develop only — the work hadn't actually shipped yet.

### Added
- **Stage 2 reachability check** in `find-promotable.sh`: for each candidate's merged PRs, calls `gh api /repos/{owner}/{repo}/compare/{merge_sha}...main` and accepts only PRs whose merge commit is `ahead` or `identical` to main (i.e. main contains the commit).
- **`--base BRANCH` flag** for repos with non-`main` release targets.
- **`--skip-main-check` flag** for the legacy v1.0.0 behavior (rarely correct).
- **Per-repo+sha cache** within a single run so each unique merge commit is checked only once.
- **"Held back" reporting** in `--human` output — lists items that match status/closed/merged criteria but whose PRs haven't reached main yet, so you can see what's queued for the next release.
- **`mergeCommit.oid` field** added to GraphQL queries in `inventory-board.sh` for both Issue.closedByPullRequestsReferences and direct PullRequest items.

### Changed
- SKILL.md rule 3 now documents the ancestry check as the critical guard, with rationale on why develop-only PRs aren't promotable.

## [1.0.0] — 2026-04-25

### Added
- Initial skill — promotes GitHub Projects (v2) board items to Done after release/hotfix.
- `scripts/discover-boards.sh` — lists all Projects V2 boards linked to a repo via GraphQL.
- `scripts/inventory-board.sh` — pages through items + auto-detects Status field with Done-like option.
- `scripts/find-promotable.sh` — filters items: closed Issue + merged linked PR (or merged PR-typed item) + status != Done.
- `scripts/apply-promotions.sh` — applies `updateProjectV2ItemFieldValue` mutation. Supports `--dry-run`.
- `scripts/task-manifest.sh full-run` — 6-task progress checklist.
- `references/projects-v2-graphql-snippets.md` — GraphQL queries + mutation reference for debugging.
- Pre-flight: scripts bail with a clear message if `gh` lacks `read:project` / `project` scopes.
- AskUserQuestion integration when multiple boards found, plus pre-apply confirmation.
- Validated against `abhattacherjee/tiny-vacation-agent` and `abhattacherjee/obsidian-brain` boards.
