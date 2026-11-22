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

- Fail-open paths: an old-format token must still be refused; `git write-tree` failing must exit 1 with no token. Test: `scripts/test-commit-preflight.sh`. It runs the real script and the real hook in a throwaway clone, so it never touches your own token. CI runs it in `validate-plugin-tests`.
- Exit codes: `commit-preflight.sh` must exit 1, not 0, when the staged tree changes during the run. Test: the same script. Its eight cases:
  1. Skip-tests run exits 0 and writes a token with tree, head, worktree, checks_run and skip_reason.
  2. The hook allows a commit that matches that token (exit 0, decision not deny, "Preflight verified").
  3. The hook denies a commit after another file is staged.
  4. The hook denies an old-format token.
  5. A check that stages a file mid-run makes preflight exit 1 and removes an older token.
  6. An unmerged index makes preflight exit 1 ("cannot read the staged tree") and removes an older token.
  7. A full run (no `--skip-tests`) on a docs file writes a token with created, expires (created + 300), staged_files, a real checks_run and no skip_reason.
  8. A held token lock makes preflight exit 1 ("locked by a commit in progress") and leaves an existing token in place.
- Date boundaries: none; the token uses epoch seconds, unchanged.
- Doc counts: the CHANGELOG and PR body name four hooks; count them from `git diff --stat`.
- Broken Markdown: the CHANGELOG entry goes inside the `[Unreleased]` block; re-read the lines around it.
- Unrelated changes: only the four hooks, `scripts/commit-preflight.sh`, `scripts/test-commit-preflight.sh`, its CI step in `.github/workflows/validate-skill.yml`, `CHANGELOG.md` and this plan. No deletions.
- Inputs: the hooks come from the installed 1.3.2 plugin cache. A stale copy would show as a sha256 mismatch against the template; checked with `cmp` at commit time.
- Bypass routes: the cheapest input that would pass the preflight gate is a hand-written token with `head`/`tree`/`worktree` set. That is outside this change's threat model (the hook docstring says it is not forgery protection). Pushes: a push to `develop` from a worktree must still be denied (acceptance check 3).

## Rollout note

Hooks run from the main checkout. After merge, a worktree or branch whose `scripts/commit-preflight.sh` predates this change writes an old-format token and cannot commit until it merges `develop`. `git worktree list` showed no other worktrees on 2026-11-22.
