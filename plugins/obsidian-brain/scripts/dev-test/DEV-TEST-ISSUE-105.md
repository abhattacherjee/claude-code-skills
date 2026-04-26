# DEV-TEST: Issue #105 — cwd-gone session-id resolution

**Companion to:** `scripts/dev-test/test-issue-105-manual.sh`
**Run by:** Sibling Claude Code session (NOT the one developing the fix)
**Prereq:** `/dev-test install` has synced the feature branch

This checklist exercises the parts that the fixture script can't: real CC
harness behavior under a real `gh pr merge --delete-branch` worktree-deletion.
The Python self-heal happens inside the SKILL's helper subprocess; live-CC
verifies that retro/compress/decide/error-log all pick up the real SID
instead of stamping `source_session: unknown`.

---

## Phase 1: Setup (baseline — confirm normal flow works)

- [ ] **1a.** Open a fresh CC session in a sibling terminal (do NOT reuse the
  development session — that would dirty the cwd-gone test).

- [ ] **1b.** Create a throwaway worktree:

  ```bash
  cd ~/dev/claude_workspace/obsidian-brain
  git worktree add /tmp/ob-105-test -b feature/test-105-cwd-gone-throwaway
  cd /tmp/ob-105-test
  ```

- [ ] **1c.** Open a Claude Code session **inside** `/tmp/ob-105-test/` and
  let SessionStart fire.

- [ ] **1d.** Run `/compress` with any short topic (e.g. "smoke test").
  Verify the resulting insight note in
  `~/obsidian/claude-code-vault/claude-insights/` has a real
  `source_session:` UUID and a non-empty `source_session_note:` basename.
  This is the **baseline** — confirms normal flow before the wedge.

  Expected: `source_session: <real-uuid>` and
  `source_session_note: 2026-MM-DD-obsidian-brain--issue-test-...md`.

---

## Phase 2: Wedge the cwd

- [ ] **2a.** From inside the same `/tmp/ob-105-test` CC session, push the
  branch and create a PR (no real review required — this is throwaway):

  ```bash
  # NOTE: --allow-empty does not work — commit-preflight.sh:58 refuses
  # commits with no staged files. Stage a tiny throwaway file instead:
  echo "throwaway" > THROWAWAY.md
  git add THROWAWAY.md
  ./scripts/commit-preflight.sh --auto   # auto path = docs-only, skips tests
  git commit -m "test: throwaway for #105 dev-test"
  git push -u origin feature/test-105-cwd-gone-throwaway
  gh pr create --base develop --title "DO NOT MERGE — #105 dev-test throwaway" \
      --body "Throwaway PR for #105 dev-test. Will be closed."
  ```

- [ ] **2b.** Trigger the worktree-deletion failure mode:

  ```bash
  gh pr close --delete-branch <PR_NUMBER>
  ```

  > **Note:** On macOS gh ≥ 2.x, `gh pr close --delete-branch` automatically
  > runs the equivalent of `git worktree remove` when the deleted branch is
  > checked out in a worktree, AND switches the worktree to the default
  > branch. So the explicit `git worktree remove` step below is usually
  > unnecessary. Only run it if `git worktree list` still shows the
  > throwaway worktree:
  >
  > ```bash
  > git worktree remove --force /tmp/ob-105-test  # only if still listed
  > ```

  (Or, if your workflow uses `gh pr merge --delete-branch`, do that — the
  worktree-deletion outcome is identical.)

- [ ] **2c.** Confirm the cwd is now wedged. In the same CC session:

  ```
  Bash: pwd
  ```

  Expected: exit non-zero with "shell-init: error retrieving current directory"
  or similar. **The CC harness's tracked cwd points at the deleted directory.**

---

## Phase 3: Trigger the fix path

> **⏱ 10-minute window — IMPORTANT.** Layer 4 (`_recent_bootstrap_sid`) is
> strict-by-design and only considers bootstrap files with mtime within the
> last 600 seconds, to prevent silent cross-project mis-attribution (same
> bug class as #101). Run Phase 3 within **10 minutes of the parent
> SessionStart** that wrote `~/.claude/obsidian-brain/sid-<slug>`. If you
> exceed the window, either: (a) restart the wedged CC session to write a
> fresh bootstrap, or (b) `touch ~/.claude/obsidian-brain/sid-<slug>` just
> before running step 3a.

> **🚧 Known macOS harness blocker.** On macOS, the CC Bash tool
> pre-checks cwd existence and refuses dispatch with `Path X does not exist`
> the moment the cwd is gone — upstream of every SKILL bash step. This means
> `/retro` and `/compress` cannot reach the resolver helper subprocess from
> a wedged session at all. Verified empirically 2026-04-26 in PR #113
> dev-test (see [[2026-04-26-test-steps-for-issue-105-cwd-gone-session-i-639d]]).
> Tier 2 live-CC verification of Phase 3 is therefore BLOCKED on macOS until
> the harness pre-dispatch check is relaxed (filed as follow-up). The
> resolver fix itself is verified by `test-issue-105-manual.sh` Phase C
> (real OS-level cwd deletion + helper invocation, 4/4 passing).

- [ ] **3a.** Without leaving the wedged session, run `/retro`. Let it complete.

  Pre-fix behavior: bash prelude no-ops; Python `os.getcwd()` raises;
  helper exits non-zero; SKILL stamps `source_session: unknown`.

  Post-fix behavior: bash prelude no-ops; Python falls through layers
  1→4 and resolves the active session's SID via the recent-bootstrap
  best-effort scan; SKILL stamps the real SID.

- [ ] **3b.** Optionally run `/compress` with another short topic to confirm
  the fix applies to all four insight-saver SKILLs.

---

## Phase 4: Verify

- [ ] **4a.** Find the latest retro:

  ```bash
  ls -t ~/obsidian/claude-code-vault/claude-insights/*retro*.md | head -1
  ```

- [ ] **4b.** Verify `source_session` is a real UUID, NOT `unknown`:

  ```bash
  grep "^source_session" $(ls -t ~/obsidian/claude-code-vault/claude-insights/*retro*.md | head -1)
  ```

  Expected: `source_session: <8-4-4-4-12-hex-UUID>` (the real session ID).
  **If you see `source_session: unknown`, the fix did not take effect.**

  Common reasons for failure:
  - `/dev-test install` did not pick up the latest feature branch
    (verify with: `grep _resolve_session_id ~/.claude/plugins/cache/*/obsidian-brain/*/hooks/obsidian_utils.py`)
  - SessionStart never wrote a bootstrap for this worktree (verify:
    `ls -la ~/.claude/obsidian-brain/sid-ob-105-test*` — should exist
    with mtime within last 10 minutes)
  - More than one recent bootstrap (`ls -la ~/.claude/obsidian-brain/sid-* | grep "$(date +%H:%M)"`)
    — Layer 4 is strict and returns "unknown" rather than guess

- [ ] **4c.** Verify `source_session_note` is non-empty:

  ```bash
  grep "^source_session_note" $(ls -t ~/obsidian/claude-code-vault/claude-insights/*retro*.md | head -1)
  ```

  Expected: a non-empty `.md` filename pointing at a real session note.

- [ ] **4d.** Verify the bootstrap file used:

  ```bash
  cat ~/.claude/obsidian-brain/sid-ob-105-test  # or whatever the worktree slug was
  ```

  Expected: matches the `source_session` value from 4b.

---

## Cleanup

```bash
gh pr close --delete-branch <PR_NUMBER>  # if not already
git worktree remove --force /tmp/ob-105-test 2>/dev/null
git branch -D feature/test-105-cwd-gone-throwaway
git push origin --delete feature/test-105-cwd-gone-throwaway 2>/dev/null
```

Optional: delete the throwaway retros:

```bash
rm ~/obsidian/claude-code-vault/claude-insights/*retro*test-105*
```

---

## Pass criteria

All 4 phases checked. `source_session` resolves to a real UUID after the
worktree was deleted. Python helper exits cleanly (no traceback in stderr).
