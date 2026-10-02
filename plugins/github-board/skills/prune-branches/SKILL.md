---
name: prune-branches
description: "Audits and cleans stale git branches across local and remote. Use when: (1) repository has accumulated stale feature/hotfix/release branches after merges, (2) Dependabot PRs pile up with superseded older versions, (3) temp branches from git-flow-finish scripts linger as orphans, (4) git branch -d fails with 'not fully merged' on squash-merged branches, (5) periodic repo hygiene after multiple releases or hotfix cycles, (6) Dependabot PRs have been triaged into GitHub issues and the original PRs are stale, (7) 'branch cleanup' or /git-branch-cleanup (the old name of this skill)."
metadata:
  version: 2.0.0
---

# Git Branch Cleanup

## Problem

Git Flow workflows and Dependabot generate many branches. After squash-merges, hotfix finishes, and dependency update cycles, stale branches accumulate across local and remote. Manual cleanup is tedious and error-prone — squash-merged branches appear "not fully merged" to `git branch -d`, finished hotfix/release branches linger after tags are created, and temp branches from git-flow-finish scripts become orphans.

## Quick Check

```bash
# Dry-run audit (report only)
~/.claude/skills/git-branch-cleanup/scripts/cleanup-branches.sh

# Actually delete stale branches
~/.claude/skills/git-branch-cleanup/scripts/cleanup-branches.sh --delete

# Usage
~/.claude/skills/git-branch-cleanup/scripts/cleanup-branches.sh --help
```

## What It Detects

| Category | Detection Method | Deletion Strategy |
|----------|-----------------|-------------------|
| Local branches with remote `[gone]` | `git branch -vv \| grep gone` | `git branch -d`, falls back to `-D` after verifying PR merged via `gh pr list` |
| Finished hotfix/release branches | `git merge-base --is-ancestor` against main | `gh api` DELETE on remote ref |
| Orphan temp branches | Pattern `temp-*` or `feature/temp-*` with no open PR | `gh api` DELETE on remote ref |
| Superseded Dependabot PRs | Same dep_key with older PR number | Close PR with comment + delete branch |
| Issue-tracked Dependabot PRs | Cross-reference PR with GitHub issues (from triage) | Close PR with issue reference comment |
| Stale local tracking refs | N/A | `git fetch --prune` (always runs) |

## Key Gotchas

### Squash-merged branches need force-delete

When a PR is squash-merged, the original commits don't appear in the target branch. `git branch -d` rejects the delete because it can't verify the branch was merged:

```
error: the branch 'feature/xyz' is not fully merged
```

The script handles this by checking `gh pr list --state all --head <branch>` — if the PR state is `MERGED`, it uses `git branch -D` (force delete).

### Remote-only merged branches are NOT detected by the script

The script's Category 1 only finds branches that exist LOCALLY with a `[gone]` upstream (`git branch -vv | grep gone`). A feature branch that was merged and exists only on the remote — with no local tracking ref — is invisible to all five categories. The script will report "Nothing to clean up!" while merged remote branches linger.

Because the branches were squash-merged, `git merge-base --is-ancestor origin/<branch> origin/develop` also returns false (squash discards the original commits), so an ancestor check won't catch them either.

**Manual detection + cleanup** when `git branch -r` shows feature/release/hotfix branches the script ignores:

```bash
git fetch --prune origin
for b in $(git branch -r | grep -E 'feature/|release/|hotfix/' | sed 's| *origin/||'); do
  state=$(gh pr list --state all --head "$b" --json state --jq '.[0].state' 2>/dev/null)
  echo "$b -> ${state:-NO_PR}"
done
# For each branch whose PR state is MERGED:
git push origin --delete <branch>
```

Verified 2026-06-03 on obsidian-brain: script reported "Nothing to clean up" while 3 squash-merged remote feature branches (PRs #40, #83, #97) still existed; manual PR-state check + `git push origin --delete` removed them.

### Issue-tracked Dependabot PRs need cross-referencing

When `dependabot-triage` classifies a PR as Category B (major version bump), it creates a GitHub issue and labels the PR `needs-dedicated-review`. However, the PR itself stays open indefinitely. The script cross-references each open Dependabot PR with GitHub issues via `gh issue list --state all --search "PR #N"` and by package name. If tracking issues exist (open or closed), the PR is stale and can be closed with a comment linking to the issues.

**Key behavior**: GitHub auto-deletes Dependabot branches when PRs are closed — no separate branch deletion is needed for this category.

### macOS bash 3.2 compatibility

The script avoids `declare -A` (associative arrays, bash 4+) and `=~` with capture groups that behave differently across versions. Dependabot supersession detection uses temp files instead.

## When to Run

- After merging a PR (feature branch cleanup)
- After `/finalize-release` or `/review-dependabot-prs` (hotfix/release branch cleanup)
- Weekly as general hygiene
- When `git branch -r` output looks cluttered

## See Also

- `release-and-git-flow` — the git-flow-finish.sh script that creates temp branches
- `worktree` — worktree management (creates branches that should NOT be cleaned while in use)
- `dependabot-triage` agent — creates GitHub issues for Category B PRs (upstream of Category 5)
- `dependabot-pr-reviewer` agent — batches safe Dependabot PRs into hotfix releases
