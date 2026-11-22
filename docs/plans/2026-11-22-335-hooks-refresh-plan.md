# #335: refresh harden-repo hooks to 1.3.2

Goal: the four installed hooks read the tool payload's `cwd`, so a worktree `/ship` session can push a feature branch and open a PR. Source of truth: the installed plugin, `~/.claude/plugins/cache/harden-repo/repo-hardener/1.3.2/templates/`.

## Task 1: refresh the hooks with the doctor

Delegate: claude — `.claude/` is a guarded path that `cx apply` refuses.

- Run `doctor.py --repo . --fix --safe`. It writes only the four `DRIFTED-BEHIND` hooks: `prevent-direct-push.py`, `require-preflight.py`, `update-changelog-before-pr.py` and `validate-branch-name.py`.
- Out of scope: `enforce-pr-base-branch.py` (`MISSING`, not registered), `.github/workflows/ci.yml` (`MISSING`), `scripts/bump-version.sh` (`UNRECOGNIZED`) and `scripts/commit-preflight.sh` (`UNKNOWN`, customized).
- Check: each hook is byte-identical to its 1.3.2 template; `.claude/settings.json` and `.codex/hooks.json` are unchanged; the survey prints `C` for all three columns.

## Task 2: write a bound preflight token

Delegate: claude — reads the template outside the worktree, and must be checked live against the new hook.

- 1.3.2 `require-preflight.py` refuses a token without `head`, `tree` and `worktree` (line 8527, `_OLD_FORMAT_TOKEN_REASON`). This repo's `scripts/commit-preflight.sh` writes neither field. Port the template's binding into it: read `TOKEN_HEAD`, `TOKEN_TREE` (`git write-tree`) and `TOKEN_WORKTREE` before the checks, and write the token through `_preflight_write_token`, which re-reads the tree and refuses when it changed.
- Both write sites change: the skip-tests path and the full path. Keep every repo-specific check as it is.
- Check: `bash -n`, then this PR's own commit goes through the new hook.

## Failure modes

- Fail-open paths: an old-format token must still be refused (the hook does this, line 8527); `git write-tree` failing must exit 1 with no token. Test: the commit of this PR itself (new hook, new writer), and a hand-written old-format token fed to the hook, which must deny.
- Exit codes: `commit-preflight.sh` must exit 1, not 0, when the staged tree changes during the run. Test: stage a file change mid-run in a scratch copy and check exit 1 and no token.
- Date boundaries: none; the token uses epoch seconds, unchanged.
- Doc counts: the CHANGELOG and PR body name four hooks; count them from `git diff --stat`.
- Broken Markdown: the CHANGELOG entry goes inside the `[Unreleased]` block; re-read the lines around it.
- Unrelated changes: only the four hooks, `scripts/commit-preflight.sh`, `CHANGELOG.md` and this plan. No deletions.
- Inputs: the hooks come from the installed 1.3.2 plugin cache. A stale copy would show as a sha256 mismatch against the template; checked with `cmp` at commit time.
- Bypass routes: the cheapest input that would pass the preflight gate is a hand-written token with `head`/`tree`/`worktree` set. That is outside this change's threat model (the hook docstring says it is not forgery protection). Pushes: a push to `develop` from a worktree must still be denied (acceptance check 3).

## Rollout note

Hooks run from the main checkout. After merge, a worktree or branch whose `scripts/commit-preflight.sh` predates this change writes an old-format token and cannot commit until it merges `develop`. `git worktree list` showed no other worktrees on 2026-11-22.
