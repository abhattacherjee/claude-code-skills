# Dev-Test: Source-Session Basename Stability (Issue #101 / PR #109)

This is the **live Claude Code smoke test** for the source-session basename
stability work (closes #101 + #86 + #110). It complements the automated
script `scripts/dev-test/test-issue-101-manual.sh` which covers everything
that can be validated via hook simulation against a throwaway fixture vault.

The phases below are the bits that **only a real CC session can hit** —
SessionStart hook narrative, real on-disk vault, /recall round-trip,
mid-session resume.

## Prerequisites

1. `feature/issue-101-source-session-basename-stability` checked out, or
   PR #109 already merged to develop and pulled.
2. `/dev-test install` executed — installed plugin cache now contains
   `_first_seen_date`, `_resolve_session_note_by_hash`,
   `_peek_frontmatter_{type,project_path}`, `_safe_getcwd`, and
   `is_resumed_session(cwd=...)`.
3. **A new Claude Code session started** in this repo so the installed
   SKILL.md content is loaded (skill content is read at session start).
4. Your real Obsidian vault is configured.

Before doing the live flow, run:

```bash
bash scripts/dev-test/test-issue-101-manual.sh
```

All automated checks should pass. Only proceed to the live phases below
once the script reports `0 failed`.

---

## Live smoke checklist

Walk through the following in a **fresh CC session**. Check each box only
after visually confirming the described behavior. Notes section at the
bottom for any deviations.

### Phase 1 — Baseline: marker file is lazily written on first invocation

> **Design note (per spec §Fix A):** the marker is **pure-lazy**. No SessionStart
> hook calls `_first_seen_date()` directly. The marker file is created on the
> first invocation of the helper — typically at SessionEnd when the vault note
> basename is composed, or earlier if a helper that uses `get_session_context()`
> falls through to its compose fallback (e.g. via /recall, /vault-search,
> /compress when the session note doesn't already exist in vault).
>
> Mid-session, **it is normal for the marker file to be absent** until something
> triggers the helper. This is by design — the spec calls out that pre-PR
> sessions also "get markers lazily on first helper call after upgrade."

- [ ] **Capture this session's ID.** In the new CC session, run:
      ```bash
      ls -t ~/.claude/projects/*obsidian-brain*/*.jsonl | head -1
      ```
      Note the basename minus `.jsonl` — that's `$SID`.

- [ ] **Force the lazy write, then verify the marker.** Trigger any helper
      that exercises the resolver — `/recall`, `/vault-search anything`, or
      a direct Bash call — then check:
      ```bash
      python3 -c '
      import sys, glob, os
      sys.path.insert(0, glob.glob(os.path.expanduser("~/.claude/plugins/cache/claude-code-skills/obsidian-brain/2.4.1/hooks"))[0])
      import obsidian_utils; obsidian_utils._first_seen_date("'"$SID"'")'

      ls -la ~/.claude/obsidian-brain/sessions/$SID.json
      cat ~/.claude/obsidian-brain/sessions/$SID.json
      ```
      File should exist with mode `-rw-------` (0o600), and JSON should
      contain `first_seen_date` (today, ISO) and `first_seen_iso` (UTC ISO).

      *If still missing after a forced helper call:* the install didn't pick
      up the new code, or `_first_seen_date` itself failed. Check
      `~/.claude/obsidian-brain-hook.log` and `diff -q hooks/obsidian_utils.py
      ~/.claude/plugins/cache/claude-code-skills/obsidian-brain/2.4.1/hooks/obsidian_utils.py`.

### Phase 2 — Marker is idempotent under live use

- [ ] **Trigger any /recall, /vault-search, or /compress.** Then re-check
      the marker:
      ```bash
      stat -f '%Sm' ~/.claude/obsidian-brain/sessions/$SID.json   # macOS
      # or: stat -c '%y' ~/.claude/obsidian-brain/sessions/$SID.json   # linux
      ```
      Modification time should match the FIRST write — subsequent calls
      to `_first_seen_date($SID)` must read the marker, not rewrite it.

- [ ] **Marker JSON contents stable.**
      ```bash
      cat ~/.claude/obsidian-brain/sessions/$SID.json
      ```
      `first_seen_date` and `first_seen_iso` should be unchanged from
      Phase 1. If they advanced, the helper is rewriting on every call.

### Phase 3 — SessionEnd basename matches marker date

- [ ] **End the session cleanly.** Either type `Ctrl-D` or `/quit`. SessionEnd
      hook fires, writes a vault note, attempts AI summarization.

- [ ] **Vault note basename starts with marker date.** From a regular shell:
      ```bash
      VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
      MARKER_DATE=$(jq -r .first_seen_date ~/.claude/obsidian-brain/sessions/$SID.json)
      ls -t "$VAULT/claude-sessions/" | grep "$SID" | head -3
      ```
      The most recent file matching `*-$SID*.md` should start with
      `$MARKER_DATE-`. If today and marker date differ (cross-midnight run),
      the file MUST use marker date — that's the whole point of #101.

- [ ] **No drift between filename and frontmatter.** Open the new note
      in any editor:
      ```bash
      head -10 "$VAULT/claude-sessions/$MARKER_DATE-"*"-$SID"*.md
      ```
      Frontmatter `session_id` should equal `$SID` and `project_path`
      should equal this repo's path.

### Phase 4 — Resume same SID → is_resumed_session=True

- [ ] **Restart in this repo with the same session ID.**
      ```bash
      claude --resume $SID
      ```

- [ ] **SessionStart hint reflects resume.** Look at the SessionStart
      additionalContext output (in the conversation header or hook log).
      It should mention "Last session for obsidian-brain" — proving
      `is_resumed_session` returned True via the resolver, not by date
      heuristic.

      *Verify the underlying check in a Bash cell:*
      ```bash
      python3 -c '
      import sys, glob, os
      sys.path.insert(0, max(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks"))))
      import obsidian_utils
      v = "/Users/abhishek/path/to/your/vault"  # edit
      print(obsidian_utils.is_resumed_session(v, "claude-sessions", "'$SID'", cwd=os.getcwd()))
      ' # → True
      ```

### Phase 5 — Cross-project hash collision is rejected

- [ ] **Find a hash collision (or fabricate one).** Look for any other
      project in the same vault whose session note shares the first 4
      hex chars of the SHA-256 of your `$SID`:
      ```bash
      python3 -c "import hashlib; print(hashlib.sha256(b'$SID').hexdigest()[:4])"
      ```
      Use that 4-char `$H` to grep the vault:
      ```bash
      ls "$VAULT/claude-sessions/" | grep -- "-$H.md" | head
      ```
      If a SECOND project's note appears, you have a real collision pair.

      *If no natural collision exists*, fabricate one in a temp project:
      ```bash
      cp "$VAULT/claude-sessions/$(ls "$VAULT/claude-sessions/" | grep -- "-$H.md" | head -1)" \
         "$VAULT/claude-sessions/2026-04-20-fabricated-$H.md"
      ```
      Edit the copy's frontmatter to set `project_path: "/totally/different"`.

- [ ] **is_resumed_session returns False from a different cwd.**
      ```bash
      cd /tmp && python3 -c '...is_resumed_session(... cwd="/tmp")'
      ```
      Should be `False` — cwd-strict resolver rejects the cross-project
      collision (closes #110). If True, the cwd filter is broken.

      Clean up the fabricated file when done.

### Phase 6 — Snapshot+session pair (PreCompact path)

- [ ] **In a fresh CC session, chat a few turns then `/compact`.**
      PreCompact writes a snapshot note `*-{H}-snapshot-HHMMSS.md` and
      then continues the session.

- [ ] **/recall renders snapshot under its parent session.** Run `/recall`
      in this repo. The session history table should show the parent
      session row, with the snapshot rendered as a nested `↳ HH:MM:SS`
      row underneath. If the snapshot appears as its own top-level row,
      the resolver's type filter is misclassifying it as a session.

### Phase 7 — Backward-compat for legacy notes (type-missing)

- [ ] **Find a legacy session note that lacks the `type:` field.**
      ```bash
      grep -L "^type:" "$VAULT/claude-sessions/"*.md | head -5
      ```
      Pick one and note its `session_id` value:
      ```bash
      grep -m1 "^session_id:" "$VAULT/claude-sessions/<one-of-them>.md"
      ```

- [ ] **is_resumed_session still recognizes it.** Resume with that legacy
      sid (or just check from a Python REPL) — the resolver should treat
      `type=None` as a session (matching the `open_item_dedup` legacy
      convention) and return True. If it returns False, the type-missing
      back-compat is broken.

### Phase 8 — Reverse: clean restart on brand-new vault

- [ ] **Move the marker dir aside, clear vault sessions for this project.**
      ```bash
      mv ~/.claude/obsidian-brain/sessions ~/.claude/obsidian-brain/sessions.bak
      ```

- [ ] **Start a fresh CC session.** SessionStart fires.

- [ ] **Marker dir was created with mode 0o700.**
      ```bash
      stat -f '%Mp%Lp' ~/.claude/obsidian-brain/sessions   # macOS → 40700
      # or: stat -c '%a' ~/.claude/obsidian-brain/sessions   # linux → 700
      ```

- [ ] **Restore.**
      ```bash
      rm -rf ~/.claude/obsidian-brain/sessions
      mv ~/.claude/obsidian-brain/sessions.bak ~/.claude/obsidian-brain/sessions
      ```

### Phase 9 — Cleanup + confirmation

- [ ] **Run `/dev-test restore`** to put the released plugin cache back.
- [ ] **Confirm full test suite still passes against repo HEAD.**
      ```bash
      python3 -m pytest -q
      ```
      793 passed expected (32 in `test_get_session_context.py`, 1 new
      marker-mode self-heal test on top of the pre-#109 baseline).

---

## What this validates that pytest does NOT

| Phase | Coverage gap pytest can't fill |
|-------|-------------------------------|
| 1, 2  | Lazy marker is created+stable when `_first_seen_date()` is invoked from inside a *real* running CC session against the installed cache, not by direct helper call from a unit test (per spec §Fix A: pure-lazy, no dedicated hook) |
| 3     | SessionEnd hook integration — full write path under real config + transcript flow, including AI summarization fallback |
| 4     | SessionStart hint render correctness — `is_resumed_session` plumbed through the user-visible "Last session" line |
| 5     | A genuine cross-project hash collision against your live vault, not a synthetic 4-char fixture |
| 6     | PreCompact snapshot type filter — verified through /recall's actual nested-row rendering, not just resolver unit tests |
| 7     | Legacy notes from before the `type:` convention existed — only your live vault has these |
| 8     | Marker dir bootstrap on first run after install — covered by chmod-self-heal unit tests but worth a real fresh start |

---

## Notes / deviations

(Record any unexpected behavior, broken assumptions, or test-skip rationales here.)

```
- Phase X: …
```

---

## Reference

- Plan: `~/dev/claude_workspace/docs/superpowers/plans/2026-04-25-issue-101-source-session-basename-stability-plan.md`
- Spec: `~/dev/claude_workspace/docs/superpowers/specs/2026-04-25-issue-101-source-session-basename-stability-design.md`
- Closes: #101 (write-side ABC), #86 (read-side hash resolver), #110 (cross-project collision)
- Related issues NOT closed by this PR: #102 (D, render-side defense — depends on #101), #103 (E, vault-doctor --min-confidence flag)
