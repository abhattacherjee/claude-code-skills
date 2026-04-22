# Dev-Test: Snapshot Summary Integration (PR #43, Phase A + D)

This is the **live Claude Code smoke test** for the snapshot-summary
integration. It complements the automated script
`scripts/dev-test/test-snapshots-manual.sh` which covers the parts that can be
validated without an actual `/compact` or `/recall` firing.

## Prerequisites

1. `feature/snapshot-summary-integration` branch checked out locally.
2. `./scripts/dev-test/dev-test install` executed successfully — the
   plugin cache now contains the branch's hooks and skills.
3. A **new Claude Code session started** in this repo so the installed
   SKILL.md content is loaded.
4. Your Obsidian vault is configured and has at least one recent session
   note for this project.

If you haven't run the automated checks yet:

```bash
bash scripts/dev-test/test-snapshots-manual.sh
```

All automated checks should pass before starting the live flow below.

---

## Live smoke checklist

Walk through the following in a **fresh CC session**. Check each box
only after visually confirming the described behavior. Record any
deviation in the notes section at the bottom.

### Phase 1 — Baseline sanity

- [ ] **/recall works with no regression.** Run `/recall` in this repo
      and confirm the session history table renders and open items load
      as before. No snapshot-related crashes or empty sections where
      there used to be content.

### Phase 2 — Snapshot write on `/compact`

- [ ] **First /compact writes a timestamped snapshot.** Chat for 2-3
      turns (enough to make the transcript non-trivial), then run
      `/compact`. Inspect the vault:
      ```bash
      ls -lt "<vault>/claude-sessions/$(date +%Y-%m-%d)"*snapshot* | head -3
      ```
      Confirm a new file exists matching `*-snapshot-HHMMSS.md` where
      HHMMSS is the current wall-clock time.

- [ ] **Frontmatter is correct.** Open the new snapshot note. Verify:
      - `type: claude-snapshot`
      - `session_id:` matches the session you're in (non-empty)
      - `trigger: compact`
      - `status: auto-logged` (not yet summarized)
      - `source_session_note: "[[<date>-<project>-<hash>]]"` (the
        parent session note's stem, in wikilink form)
      - `tags:` contains `claude/snapshot`

- [ ] **Second /compact does not overwrite.** Continue chatting for
      another 2-3 turns, then run `/compact` again. Confirm a **second**
      `-snapshot-HHMMSS.md` file now exists with a distinct HHMMSS
      suffix and the first file is untouched.

### Phase 3 — SessionEnd back-reference

- [ ] **Close the session (Ctrl-D).** The SessionEnd hook fires.

- [ ] **Session note includes a `snapshots:` list.** Find the
      just-written session note for this session:
      ```bash
      grep -l "session_id: <your-session-id>" "<vault>/claude-sessions"/*.md
      ```
      Open it and confirm the frontmatter contains:
      ```yaml
      snapshots:
        - "[[<date>-<project>-<sid>-snapshot-HHMMSS>]]"
        - "[[<date>-<project>-<sid>-snapshot-HHMMSS>]]"
      ```
      One entry per `/compact` you triggered.

- [ ] **Threshold bypass works.** If you had a very short session (below
      `min_turns` / `min_duration_minutes`), the session note should
      still exist because snapshots were present. Open
      `~/.claude/obsidian-brain.log` — there should be no "skipped —
      below threshold" line for this session.

### Phase 4 — `/recall` folds snapshots in

- [ ] **Start a fresh CC session and run `/recall`.**

- [ ] **Unsummarized snapshots get upgraded.** The recall output should
      include a line like `Upgraded N session note(s) with AI summaries`
      where N includes at least the two snapshot notes you just created.

- [ ] **Session history table shows nested snapshot rows.** The parent
      session row appears at the top, and **underneath it** you should
      see indented rows prefixed with `↳ HH:MM:SS` (one per snapshot).

- [ ] **LOAD_MANIFEST mentions snapshots.** The "Loaded into this
      conversation:" block should include `snapshot_count: 2` (or
      however many `/compact`s you did) and a brief summary bullet per
      snapshot.

- [ ] **Session summary covers the pre- and post-compact arc.** The
      session's `## Summary` section should read as a single coherent
      arc — it should NOT be noticeably truncated to just the tail.

### Phase 5 — `/vault-search` markers

- [ ] **Run `/vault-search snapshot`** (or any keyword that matches your
      test session).

- [ ] **Session hits show `· 📸 N`.** For the session you just
      compacted, the type label in its result line should include the
      `· 📸 2` (or however many snapshots) suffix.

- [ ] **Nested snapshot rows appear under the session hit.** Below the
      snippet, indented `↳` rows list each snapshot with HH:MM:SS +
      trigger.

- [ ] **Snapshot-only hits show `→ [[parent]]`.** If any individual
      snapshot note is ranked as its own result, its metadata row ends
      with `→ [[<parent-stem>]]`.

- [ ] **Picking a snapshot result loads session-depth.** Select the
      snapshot number. CC should read the parent session body AND the
      snapshot summaries, not just the snapshot fragment.

### Phase 6 — `/vault-stats`

- [ ] **Run `/vault-stats`.**

- [ ] **A `## Snapshots` section renders** containing:
      - `Total: N (compact: X, clear: Y, auto: Z)`
      - `Sessions with snapshots: M (max K per session)`
      - `Summarization: P%`
      - `Integrity: 0 orphan(s), 0 broken backlink(s)` on a clean vault

- [ ] **No `⚠ N snapshot file(s) unreadable` line.** If this appears on
      a healthy install, something is wrong — check stderr in the log
      for paths.

### Phase 7 — `/emerge` flag

- [ ] **Run `/emerge 7d`.** The resulting pattern report should NOT
      reference any snapshot notes in its Sources section — snapshots
      are excluded by default.

- [ ] **Run `/emerge 7d --include-snapshots`.** This time the Sources
      section may include snapshot notes (whether it actually does
      depends on your corpus, but the command must not crash and the
      cache must rebuild — look for `Using cached corpus` to be ABSENT
      the first time you flip the flag).

### Phase 8 — `/vault-config` warnings

- [ ] **Run `/vault-config`.** Rows 7 (`snapshot_on_compact`) and 8
      (`snapshot_on_clear`) should appear.

- [ ] **Toggle `snapshot_on_clear` to false.** The menu should display
      an in-row `⚠ Disables pre-clear/compact checkpoint` warning, and
      a confirmation prompt should fire before the write.

- [ ] **Toggle it back to true** to leave the config clean.

### Phase 9 — Teardown

- [ ] **`./scripts/dev-test/dev-test restore`** to put the original
      plugin cache back.

- [ ] **Delete the test snapshot + session notes from the vault** if
      they are polluting your real vault (up to you — they are valid
      notes, just not ones you want in search results).

---

## Notes

_Record any observed deviations, unexpected output, or ideas for
follow-up tests below. When all boxes are ticked and notes are empty,
this section is your signal that the PR is dev-test-clean._

- …

## If something fails

1. **Check the log:** `tail -50 ~/.claude/obsidian-brain.log` — hook
   errors surface here.
2. **Re-run the automated script:** `bash scripts/dev-test/test-snapshots-manual.sh`
   — it catches code-level drift that live flows mask.
3. **File-level inspection:** the fixtures left behind by `/compact` are
   regular markdown. `cat` them and compare against the Phase 2
   frontmatter expectations.
4. **DB introspection:**
   ```bash
   sqlite3 ~/.claude/obsidian-brain-vault.db \
     "SELECT path, type, source_note, status FROM notes
      WHERE type = 'claude-snapshot' ORDER BY path DESC LIMIT 5;"
   ```
   confirms the indexed snapshot rows match the disk files.
