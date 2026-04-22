# Dev-Test: vault-doctor snapshot Phases B + C (PR #63)

This is the **live Claude Code smoke test** for the new `vault-doctor`
snapshot check modules. It complements the automated script
`scripts/dev-test/test-vault-doctor-snapshots-manual.sh` which covers
fixture-based end-to-end behavior with a throwaway vault.

It also doubles as the **recovery procedure** for users who want to
backfill missing snapshot frontmatter on legacy notes and have those
snapshots picked up by `/recall` summarization.

## Prerequisites

1. `feature/snapshot-phase-b-c` branch checked out locally.
2. `./scripts/dev-test/dev-test install` executed successfully.
3. A **new Claude Code session started** in this repo so the installed
   SKILL.md content is loaded.
4. Your Obsidian vault has been backed up if you care about it (the
   `vault-doctor fix` paths write atomically and create per-check
   backups under `~/.claude/obsidian-brain-doctor-backup/`, but a
   filesystem-level snapshot/Time Machine copy is good insurance).

If you haven't run the automated checks yet:

```bash
bash scripts/dev-test/test-vault-doctor-snapshots-manual.sh
```

All automated checks should pass before starting the live flow below.

---

## Phase 0 — Baseline measurements

Capture the pre-state so you can quantify what the recovery did.

```bash
VAULT="$HOME/obsidian/claude-code-vault"   # adjust if yours differs
SESS="$VAULT/claude-sessions"

# (a) Legacy-named snapshots (pre-spec, no -HHMMSS suffix)
echo "Legacy filenames (pre-spec):"
ls "$SESS"/*-snapshot.md 2>/dev/null | wc -l

# (b) Snapshots with status: auto-logged (eligible for /recall summarization)
echo "Auto-logged snapshots:"
grep -l "^status: auto-logged" "$SESS"/*-snapshot*.md 2>/dev/null | wc -l

# (c) Snapshots missing status: field entirely
echo "Snapshots with no status field:"
for f in "$SESS"/*-snapshot*.md; do
    grep -q "^status:" "$f" 2>/dev/null || echo "$f"
done | wc -l

# (d) Sessions referenced by snapshots but missing snapshots: list
echo "Sessions missing snapshots: list (will be backfilled by Phase C check 4):"
python3 -c '
import re, os, glob
sess = os.path.expanduser(os.environ["SESS"])
snap_sids = set()
for f in glob.glob(f"{sess}/*-snapshot*.md"):
    with open(f) as fh:
        head = fh.read(2000)
    m = re.search(r"^session_id:\s*(\S+)", head, re.MULTILINE)
    if m:
        snap_sids.add(m.group(1).strip("\"'"'"'"))
missing = 0
for sid in snap_sids:
    for sf in glob.glob(f"{sess}/*.md"):
        if "-snapshot" in os.path.basename(sf):
            continue
        with open(sf) as fh:
            text = fh.read(2000)
        if f"session_id: {sid}" in text and not re.search(r"^snapshots:", text, re.MULTILINE):
            missing += 1
            break
print(missing)
'
```

Record the four numbers. They are your "before" baseline.

---

## Phase 1 — Phase C dry-run (`snapshot-migration`)

- [ ] **Run dry-run:**
      ```
      /vault-doctor --check snapshot-migration
      ```

- [ ] **Confirm report shape.** Output groups by check name and project:
      - `snapshot-legacy-filename` — count should match Phase 0 (a)
      - `snapshot-missing-status` — count should match Phase 0 (c)
      - `snapshot-missing-backlink` — count of snapshots without
        `source_session_note:` (some may be `[WARN]` / unresolved if
        the parent session can't be located)
      - `session-missing-snapshots-list` — count should match Phase 0 (d)

- [ ] **Confirm dry-run did not write anything.** Re-run Phase 0
      counts. They MUST be unchanged.

- [ ] **Spot-check one proposed rename** in the dry-run output. The
      `proposed_source` should end with `-snapshot-HHMMSS.md` where
      `HHMMSS` derives from the file's mtime. Verify with:
      ```bash
      stat -f '%Sm' -t '%H%M%S' "<one of the legacy snapshot files>"
      ```
      The HHMMSS in proposed_source should match this stat output.

---

## Phase 2 — Phase C apply (`snapshot-migration fix`)

- [ ] **Run with apply:**
      ```
      /vault-doctor fix --check snapshot-migration
      ```

- [ ] **Confirm per-project confirmation prompt fires.** The dispatcher
      asks `Apply N fix(es) for project 'X' in check 'Y'? [y/N]` —
      respond `y` for the projects you want to migrate.

- [ ] **Verify backups exist.** Each fixed file got copied under
      `~/.claude/obsidian-brain-doctor-backup/<ISO-timestamp>/<check-name>/<basename>.md`.
      Inspect one:
      ```bash
      BACKUP_ROOT=$(ls -td ~/.claude/obsidian-brain-doctor-backup/* | head -1)
      ls "$BACKUP_ROOT"
      cat "$BACKUP_ROOT/snapshot-legacy-filename"/*.md | head -20
      ```
      The backup MUST contain pre-migration content (no `-HHMMSS` in
      filename, no `source_session_note:`, no `status:`).

- [ ] **Verify renamed files exist with new names.**
      ```bash
      ls "$SESS"/*-snapshot-[0-9]*.md | wc -l
      # Should equal Phase 0 (a) count of LEGACY filenames now renamed.
      ```

- [ ] **Verify wikilinks rewritten.** Pick one renamed snapshot's old
      stem and grep the vault for it — should be zero matches outside
      the backup directory:
      ```bash
      grep -rl "\[\[2026-04-XX-myproj-aabb-snapshot\]\]" "$VAULT" \
        | grep -v obsidian-brain-doctor-backup
      # Expect: empty output (all rewritten to -snapshot-HHMMSS form)
      ```

- [ ] **Verify session backfill.** Open one of the sessions flagged
      in Phase 0 (d). It should now contain a `snapshots:` YAML list
      with bracket-wrapped wikilinks pointing at the **new** filenames.

- [ ] **Re-run dry-run for idempotency:**
      ```
      /vault-doctor --check snapshot-migration
      ```
      Output should be `Vault is clean. No issues found.` (or only
      `[WARN]` entries for snapshots whose parent session truly does
      not exist on disk — those are unresolvable by design).

---

## Phase 3 — Phase B dry-run (`snapshot-integrity`)

- [ ] **Run dry-run:**
      ```
      /vault-doctor --check snapshot-integrity
      ```

- [ ] **Expected output shape.** With Phase C done, most integrity
      issues should already be resolved. Remaining categories you may
      see:
      - `snapshot-orphan` (warn-only) — snapshot's `session_id` doesn't
        match any session note on disk. This is expected for snapshots
        from sessions you've manually deleted or that pre-date your
        sessions folder structure.
      - `snapshot-broken-backlink` (fix) — `source_session_note`
        wikilink points at the wrong stem.
      - `snapshot-summary-status-mismatch` (fix) — `status:
        summarized` set but `## Summary` body is empty (or vice versa).

- [ ] **Confirm report counts are stable across two consecutive runs.**

---

## Phase 4 — Phase B apply (`snapshot-integrity fix`)

- [ ] **Run with apply:**
      ```
      /vault-doctor fix --check snapshot-integrity
      ```

- [ ] **Confirm orphans are NOT auto-fixed.** They appear in the
      report but `apply()` records `status="unresolved"` for them.
      You must inspect them manually if you want to delete or relink.

- [ ] **Re-run dry-run for idempotency:**
      ```
      /vault-doctor --check snapshot-integrity
      ```
      Should report only `snapshot-orphan` entries (warn-only).

---

## Phase 5 — `/recall` summarization

The migration in Phases 2 + 4 has now given every legacy snapshot a
`status: auto-logged` field (or `status: summarized` if it already had
a `## Summary` body). The next `/recall` will pick up the auto-logged
ones via `find_unsummarized_notes()` and summarize them in parallel
via Haiku.

- [ ] **Run /recall:**
      ```
      /recall
      ```

- [ ] **Confirm the Step 2 status line.** Look for:
      ```
      Step 2: processing N unsummarized note(s) for <project>
      ```
      where N should equal the auto-logged count from Phase 0 (b)
      plus any newly-statused snapshots from Phase 2.

- [ ] **Confirm parallel Haiku pipeline ran.** The output should
      report `Upgraded N session note(s) with AI summaries.` and the
      session history table should now render the snapshots as nested
      `↳ HH:MM:SS` rows under their parent sessions.

- [ ] **Verify summarized status flipped on disk:**
      ```bash
      grep -l "^status: auto-logged" "$SESS"/*-snapshot*.md | wc -l
      # Should be 0 (or close to 0 — anything left is a Haiku failure
      # that will retry on the next /recall).
      ```

---

## Phase 6 — Cross-skill validation

After recovery, the snapshots are now visible to every snapshot-aware
skill.

- [ ] **`/vault-stats`** — the `## Snapshots` section should now show
      the recovered snapshots in the trigger breakdown,
      sessions-with-snapshots count, summarization fraction.

- [ ] **`/vault-search snapshot`** — session hits show `· 📸 N`
      markers for sessions that gained snapshots; snapshot hits show
      `→ [[parent-stem]]` pointer.

- [ ] **Pick one session from `/recall` history with a snapshot
      attached and load it.** The full session body plus the snapshot
      summaries should appear in the same render.

---

## Rollback (if anything went wrong)

Backups are organized per check under
`~/.claude/obsidian-brain-doctor-backup/<ISO-timestamp>/<check-name>/`.
Each file in the backup is a copy of the source note as it existed
**before** the fix. To rollback:

```bash
BACKUP_ROOT=$(ls -td ~/.claude/obsidian-brain-doctor-backup/* | head -1)

# Inspect what was backed up
ls -R "$BACKUP_ROOT"

# Restore one specific file (example for a legacy-rename rollback)
cp "$BACKUP_ROOT/snapshot-legacy-filename/2026-04-05-myproj-aabb-snapshot.md" \
   "$SESS/2026-04-05-myproj-aabb-snapshot.md"
# Then manually delete the renamed -HHMMSS file if you want a clean rollback
rm "$SESS/2026-04-05-myproj-aabb-snapshot-153022.md"
```

For the wikilink rewrites, if you need to revert them, re-run the
opposite migration manually (`sed -i` is risky; prefer running
`/vault-doctor` again after restoring the legacy filenames — the
detection will repropose the same renames and the wikilinks will end
up consistent).

---

## Notes / deviations

Record anything unexpected below for the PR review record:

- ___________________________________
- ___________________________________
