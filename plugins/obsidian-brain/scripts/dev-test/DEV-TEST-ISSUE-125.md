# DEV-TEST: Issue #125 — SessionEnd fixes (F2 + F3)

**Companion to:** `scripts/dev-test/test-issue-125-manual.py`
**Run by:** Sibling Claude Code session (NOT the one developing the fix)
**Prereq:** `/dev-test install` has synced the feature branch

Manual walkthrough required from a sibling Claude Code session **after**
`/dev-test install` of `feature/issue-125-sessionend-reaper` into the
plugin cache. Covers the parts that `test-issue-125-manual.py` (Tier-1
fixture harness, 897 passed) cannot reach: real SessionStart hook firing
against a real vault with real JSONL files.

Closes: **#125** (SessionEnd reaper + F2 errno surfacing)
Related: **#100** (Phase 1 — SessionEnd outcome logging, already shipped)

---

## Prerequisites

1. Branch `feature/issue-125-sessionend-reaper` checked out, or PR already
   merged to `develop` and pulled.
2. `/dev-test install` executed — installed plugin cache now contains the
   reaper logic in `obsidian_session_hint.py` and the F2 errno surfacing in
   `obsidian_session_log.py`.
3. **A new Claude Code session started** in this repo so the installed hooks
   are active (hooks are read from cache at session start, not mid-session).
4. Your real Obsidian vault is configured at
   `~/.claude/obsidian-brain-config.json`.

Before starting the live phases, confirm the Tier-1 fixture harness passes:

```bash
python3 scripts/dev-test/test-issue-125-manual.py
```

All 23 assertions should pass. Only proceed once the script shows `0 failed`.

---

## Live smoke checklist

Walk through each phase in a **fresh CC session** (open a sibling terminal,
`cd` to this repo, launch `claude`). Check each box only after visually
confirming the described behavior. Record deviations in the Notes section.

---

## Phase 0 — Install

- [ ] **0a.** From inside this repo on `feature/issue-125-sessionend-reaper`,
  run the install skill:

  ```
  /dev-test install
  ```

  Expected: plugin cache updated; the **current** session's hooks are
  unchanged (by design — open a NEW CC session to exercise the new hooks).

- [ ] **0b.** Verify the installed `obsidian_session_hint.py` contains the
  reaper entry point:

  ```bash
  grep -c "reaper" ~/.claude/plugins/cache/*/obsidian-brain/*/hooks/obsidian_session_hint.py
  ```

  Expected: a non-zero count (at least 1 match).

- [ ] **0c.** Verify `obsidian_session_log.py` in the cache has F2 errno
  surfacing:

  ```bash
  grep -c "errno\|OSError\|PermissionError" \
      ~/.claude/plugins/cache/*/obsidian-brain/*/hooks/obsidian_session_log.py
  ```

  Expected: a non-zero count.

---

## Phase 1 — SIGKILL recovery (F3 core path)

**Goal:** verify the SessionStart reaper reconstructs a vault note when
SessionEnd never fired because the CC process was killed.

- [ ] **1a.** Open a **fresh CC session** in `obsidian-brain` (sibling
  terminal). Send at least 5 user messages over ≥ 3 minutes so the session
  clears both the `min_messages` and `min_duration_seconds` thresholds.

- [ ] **1b.** Note the session's JSONL path (run from a second terminal
  while the session is still alive):

  ```bash
  ls -t ~/.claude/projects/*obsidian-brain*/*.jsonl | head -1
  ```

  Record the basename (minus `.jsonl`) as `$KILLED_SID`.

- [ ] **1c.** From the second terminal, find the CC process PID and kill it:

  ```bash
  pgrep -f "claude" | head -5   # identify the CC pid
  kill -9 <pid>
  ```

  The CC session window should exit abruptly. The vault should contain **no**
  note for `$KILLED_SID` at this point (SessionEnd hook never ran).

  Confirm:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  ls "$VAULT/claude-sessions/" | grep "$KILLED_SID" | wc -l
  ```

  Expected: `0`.

- [ ] **1d.** Open **another fresh CC session** in `obsidian-brain`.
  Within 5 seconds of SessionStart, the reaper should trigger.

- [ ] **1e.** Verify the reaper log line:

  ```bash
  grep "REAPED_OK" ~/.claude/obsidian-brain-hook.log | grep "$KILLED_SID" | tail -3
  ```

  Expected: at least one line of the form
  `Reaper sid=<KILLED_SID> event=REAPED_OK`.

- [ ] **1f.** Verify the reconstructed vault note exists:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  ls "$VAULT/claude-sessions/" | grep "$KILLED_SID"
  ```

  Expected: one `.md` file whose name contains `$KILLED_SID`.

- [ ] **1g.** Verify the reconstructed note's frontmatter:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  NOTE=$(ls "$VAULT/claude-sessions/" | grep "$KILLED_SID" | head -1)
  head -30 "$VAULT/claude-sessions/$NOTE"
  ```

  Expected:
  - `reconstructed: true` present in frontmatter
  - `tags:` list includes `claude/reconstructed`
  - Body starts with the "Reconstructed by SessionStart reaper" banner

**Pass criteria:** all of 1e, 1f, 1g.

---

## Phase 2 — Cold-boot performance (steady-state < 100 ms)

**Goal:** verify the reaper does not add perceptible latency to SessionStart
when no orphan sessions exist.

- [ ] **2a.** Ensure no orphan JSONLs exist past the reaper watermark.
  If Phase 1 just completed, the watermark should already be advanced past
  `$KILLED_SID`. Optionally run one more clean CC session (start + exit
  normally) to advance the watermark further.

- [ ] **2b.** Open a **fresh CC session** in `obsidian-brain`.

- [ ] **2c.** Inspect `~/.claude/obsidian-brain-hook.log` for the SUMMARY line
  written by this session's SessionStart:

  ```bash
  grep "SUMMARY" ~/.claude/obsidian-brain-hook.log | tail -3
  ```

  Expected: a line of the form
  `Reaper ... event=SUMMARY wall_ms=<N> scanned=<N> reaped=0`.

- [ ] **2d.** Confirm the wall_ms value:

  ```bash
  grep "SUMMARY" ~/.claude/obsidian-brain-hook.log | tail -1 | grep -oE "wall_ms=[0-9]+"
  ```

  Expected: `wall_ms=<N>` where N < 100.

**Pass criteria:** `wall_ms < 100` in the SUMMARY line with `reaped=0`.

---

## Phase 3 — Restrictive permissions (graceful degradation)

**Goal:** verify F3 skips gracefully when the vault is not writable, logs
`SKIPPED_PERMISSION_BLOCKED` exactly once, and does not advance the
watermark (so the orphan is retried on the next session).

- [ ] **3a.** Open a fresh CC session to establish a clean baseline.

- [ ] **3b.** Save the current watermark:

  ```bash
  WM_PATH=~/.claude/obsidian-brain/reaper-watermark-obsidian-brain
  cp "$WM_PATH" /tmp/wm.bak
  cat /tmp/wm.bak   # note the current timestamp
  ```

- [ ] **3c.** Create an above-threshold orphan: open a CC session, send ≥ 3
  messages over ≥ 2 minutes, then SIGKILL it (same as Phase 1 steps 1a–1c).

- [ ] **3d.** Make the vault directory read-only:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  chmod 500 "$VAULT"
  ```

- [ ] **3e.** Open a fresh CC session. The reaper should attempt to write but
  fail gracefully.

- [ ] **3f.** Verify `SKIPPED_PERMISSION_BLOCKED` appears exactly once in the
  new session's log output:

  ```bash
  # Grab the new session's SID
  NEW_SID=$(ls -t ~/.claude/projects/*obsidian-brain*/*.jsonl | head -1 | xargs basename | sed 's/\.jsonl//')
  grep "SKIPPED_PERMISSION_BLOCKED" ~/.claude/obsidian-brain-hook.log | tail -5
  ```

  Expected: exactly one `SKIPPED_PERMISSION_BLOCKED` line (not one per
  orphan — the reaper logs a single permission-blocked summary).

- [ ] **3g.** Verify the watermark did NOT advance:

  ```bash
  diff <(cat ~/.claude/obsidian-brain/reaper-watermark-obsidian-brain) /tmp/wm.bak
  ```

  Expected: no diff output (watermark unchanged — orphan will be retried).

- [ ] **3h.** Restore vault permissions:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  chmod 700 "$VAULT"
  ```

- [ ] **3i.** Open a fresh CC session. Verify the previously-queued orphan is
  now reaped (same success criteria as Phase 1 steps 1e–1g).

**Pass criteria:** 3f (exactly one SKIPPED line), 3g (watermark stable),
3i (orphan reaped on retry).

---

## Phase 4 — Disable flag (`reaper_enabled: false`)

**Goal:** verify setting `reaper_enabled: false` in config produces zero
reaper activity, even with orphans present.

- [ ] **4a.** Edit `~/.claude/obsidian-brain-config.json` and add or update:

  ```json
  "reaper_enabled": false
  ```

- [ ] **4b.** Create an above-threshold orphan: open a CC session, send ≥ 3
  messages over ≥ 2 minutes, then SIGKILL it.

- [ ] **4c.** Open a fresh CC session.

- [ ] **4d.** Inspect the hook log for the new session's entries. There should
  be **no** lines beginning with `Reaper`:

  ```bash
  # Get approximate timestamp of the new SessionStart
  SINCE=$(date -v-30S '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -d '30 seconds ago' '+%Y-%m-%d %H:%M:%S')
  grep "Reaper" ~/.claude/obsidian-brain-hook.log | tail -20
  ```

  Expected: no new `Reaper` lines from this session. (Lines from Phase 1–3
  sessions are fine to see; verify none are from the current session's SID.)

- [ ] **4e.** Restore the flag:

  ```bash
  # Either remove the key or set it back to true:
  python3 -c "
  import json, os
  p = os.path.expanduser('~/.claude/obsidian-brain-config.json')
  c = json.load(open(p))
  c.pop('reaper_enabled', None)
  open(p, 'w').write(json.dumps(c, indent=2))
  "
  ```

**Pass criteria:** zero `Reaper` log lines in the disabled session.

---

## Phase 5 — Watermark file inspection

**Goal:** verify the watermark file format and permissions are correct.

- [ ] **5a.** Inspect the watermark file:

  ```bash
  WM_PATH=~/.claude/obsidian-brain/reaper-watermark-obsidian-brain
  ls -la "$WM_PATH"
  cat "$WM_PATH"
  # Convert to human-readable date:
  date -r "$(cat "$WM_PATH")"
  ```

  Expected:
  - File mode `-rw-------` (0o600)
  - Contents: an integer Unix epoch seconds timestamp (e.g. `1746307200`)
  - `date -r` output should show a recent date matching the last reap run

- [ ] **5b.** Verify the watermark advances after a successful reap (Phase 1
  should have already done this). Compare values:

  ```bash
  cat ~/.claude/obsidian-brain/reaper-watermark-obsidian-brain
  # should be a larger epoch value than before Phase 1
  date -r "$(cat ~/.claude/obsidian-brain/reaper-watermark-obsidian-brain)"
  ```

  Expected: the converted date is later than the `$KILLED_SID` session's start time.

- [ ] **5c.** Verify the watermark directory has correct permissions:

  ```bash
  ls -la ~/.claude/obsidian-brain/ | grep -E "^d"
  ```

  Expected: the `obsidian-brain/` directory is mode `drwx------` (0o700).

**Pass criteria:** watermark file at 0o600, integer epoch-seconds content,
directory at 0o700.

---

## Phase 6 — F2 errno surfacing (optional, harder to live-test)

**Goal:** verify F2 surfaces the OS errno in the `WRITE_FAILED` log detail
when SessionEnd cannot write to the vault.

> This scenario is hard to trigger in a live CC session without filesystem
> disruption. The Tier-1 fixture script (`test-issue-125-manual.py`) covers
> F2 deterministically via mock injection. Live-CC verification is optional.

- [ ] **6a.** Make the vault read-only:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  chmod 500 "$VAULT"
  ```

- [ ] **6b.** Open a CC session, send ≥ 3 messages over ≥ 2 minutes, then
  exit **normally** (Ctrl-D or `/quit` — let SessionEnd run).

- [ ] **6c.** Inspect the hook log for the WRITE_FAILED outcome:

  ```bash
  grep "WRITE_FAILED" ~/.claude/obsidian-brain-hook.log | tail -3
  ```

  Expected: a line of the form `outcome=WRITE_FAILED detail=...Errno 13...`
  (Permission denied). The `detail=` field should contain the OS errno string,
  not a bare "write failed" message.

- [ ] **6d.** Restore vault permissions:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  chmod 700 "$VAULT"
  ```

**Pass criteria (if attempted):** Errno 13 (or the OS equivalent) appears in
the `WRITE_FAILED detail=` field.

---

## Phase 7 — Cleanup + confirmation

- [ ] **7a.** Run `/dev-test restore` to put the released plugin cache back.

- [ ] **7b.** Confirm the full Tier-1 test suite still passes against repo HEAD:

  ```bash
  python3 -m pytest -q
  ```

  Expected: all tests pass (0 failed). Count will be higher than 897 as
  new tests have been added since this document was authored.

- [ ] **7c.** Verify there are no stale orphan notes left from the test run:

  ```bash
  VAULT=$(jq -r .vault_path ~/.claude/obsidian-brain-config.json)
  ls "$VAULT/claude-sessions/" | grep "reconstructed" | wc -l
  ```

  This is informational — the reconstructed notes are valid vault notes and
  do not need to be removed. Record the count as a reference.

---

## What this validates that pytest does NOT

| Phase | Coverage gap pytest cannot fill |
|-------|----------------------------------|
| 1     | Full SIGKILL → reaper → vault-write round-trip with real JSONL files and real hook invocation from CC harness |
| 2     | Wall-clock latency of the reaper on the live filesystem (cold cache, real OS stat calls) |
| 3     | `chmod 500` degradation path — OS-level permission error in a real vault, not a mock |
| 4     | Config reload at SessionStart — verifies installed hooks read config correctly from disk |
| 5     | Watermark file mode and content after real atomic writes |
| 6     | F2 live errno path — SessionEnd write failure with real vault and real OS permission error |

---

## Notes / deviations

(Record any unexpected behavior, broken assumptions, or test-skip rationales here.)

```
- Phase X: …
```

---

## Reference

- Plan: `~/dev/claude_workspace/docs/superpowers/plans/2026-05-02-issue-125-sessionend-fixes-plan.md`
- Tier-1 fixture script: `scripts/dev-test/test-issue-125-manual.py`
- Closes: **#125** (F2 errno surfacing + F3 SessionStart reaper)
- Related: **#100** (Phase 1 — SessionEnd outcome telemetry, shipped as `4d53751`)
- See also: `~/.claude/obsidian-brain-hook.log` — primary diagnostic surface
  for session outcome events; inspect with:
  ```bash
  awk '/SessionEnd|Reaper/ {print}' ~/.claude/obsidian-brain-hook.log | tail -20
  ```
