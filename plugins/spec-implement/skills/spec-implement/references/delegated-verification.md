# Delegated-Work Ground-Truth Verification

When you dispatch a sub-agent — or any delegated command — to mutate state (commit,
push, write a file, revert, update an issue/board, run tests, delete a branch, merge a
PR), the agent's narration is a **claim, not evidence**. Verify every claim against
ground truth **in your own (orchestrator) context** before repeating it to the user.

> "The subagent said done" must never become "I told the user it was done, and it wasn't."

## The rule

1. **Verify in the orchestrator's context.** Never delegate the verification to the same
   agent that made the claim — it cannot be its own witness.
2. **A failed verification is reported as a failure.** Surface the discrepancy; do not
   silently retry it into a success.
3. **Never bundle a contingent side-effect** (e.g. `gh issue close`) into the same command
   as the action it depends on. Run the action, verify it landed, *then* run the dependent
   step.

## Claim → ground-truth table

| Claim class | Ground-truth command | Pass condition |
|---|---|---|
| "committed" | `git show --stat HEAD` | expected files **all** present in the stat; author/subject match |
| "pushed" | `git rev-parse HEAD @{u}` | two identical SHAs (needs the branch's upstream set — push with `-u` first, else `@{u}` errors) |
| "file written/edited" | `test -f <path> && grep -Fc "<change-unique sentinel>" <path>` | sentinel count >= 1 — the sentinel must be unique to THIS change |
| "reverted" | `git status --porcelain <path>` + `git diff HEAD -- <path>` | **both** empty (no staged/unstaged change, no diff vs HEAD) |
| "issue/board updated" | `gh issue view N --json state,milestone` / GraphQL re-query | field equals the expected value |
| "N tests pass" | re-run the authoritative runner (`pytest -q`, `pnpm test`) | the runner's **own** count — NEVER accept a narrated count |
| "branch deleted" | `git ls-remote --heads origin <branch>` | empty output |
| "PR merged" | `gh pr view N --json state,mergedAt` | `state` == `MERGED` (there is no `merged` field — use `state` + `mergedAt`) |

**Footnote (row 8 — "PR merged"):** `gh pr view N --json state,merged` ->
`Unknown JSON field: "merged"` (verified against PR #41, 2026-07-23; re-confirmed
2026-07-24). The field does not exist; use `state` + `mergedAt`.

Per-row cautions:

- **"committed" (row 1)** — a *partial* commit is the canonical failure: an agent that
  "landed 2 of 5 files" still reports "committed, tests pass". Confirm the stat lists
  **every** expected path, not merely that `HEAD` moved.
- **"branch deleted" (row 7)** — the remote check above is necessary but not sufficient.
  Also run `git worktree prune`, then confirm the branch is gone **locally**
  (`git branch --list <branch>` -> empty). A branch still checked out in a worktree resists
  deletion; run `git worktree list` to find the offending worktree and **report** any
  branch left checked out in one rather than leaving it silently.

## Background-agent liveness contract (dispatch rule — NOT a verification row)

Distinct from the 8-row table above; this is a **dispatch-prompt contract**, not a
ground-truth command, and must not be tabulated as a 9th row. A background or parallel
sub-agent that finishes without sending its result leaves you with an idle notification
and no deliverable.

- Every background-agent dispatch prompt MUST end with:
  **"SendMessage your final result to the orchestrator that dispatched you; your
  idle-completion notification is not a deliverable."**
- The orchestrator re-requests the payload on any idle-without-payload notification, and
  never treats "the agent stopped" as "the work was delivered".
