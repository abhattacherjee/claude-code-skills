# Dropped-Session Fixture Corpus (#124)

6 JSONLs reproducing the known SessionEnd silent-drop bug from
[#100](https://github.com/abhattacherjee/obsidian-brain/issues/100). Five are
truncated head+tail snapshots captured via `scripts/dev-test/capture-jsonl-fixture.py`.
The sixth (`d2cc7e46-long-617min-full.jsonl`) is a density-preserving subset of the
same d2cc7e46 source: lines 0–66 plus the final record, with `tool_result` bodies
scrubbed and `attachment` blobs stubbed — retaining 3 real user-text messages and the
full 1841-minute duration so the reaper success path (`REAPED_OK`) is exercised.

Used by `tests/test_replay_cli.py` to drive `obsidian_session_log._run()`
deterministically. See spec `docs/superpowers/specs/2026-05-01-issue-124-sessionend-replay-cli-design.md`.

## Re-capture protocol

If a fixture's source JSONL needs re-capture (e.g., after schema change), run
the captured-by command shown for each fixture below. The truncation marker's
`captured_at` field will change but the head/tail records stay byte-identical,
so the fixture remains stable for assertion.

---

## d2cc7e46-long-617min-full.jsonl

- **Source SID:** `d2cc7e46-9778-41be-bebb-8fb22a491204`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/d2cc7e46-9778-41be-bebb-8fb22a491204.jsonl`
- **Original size:** 2,393,897 bytes / 1,136 records
- **Generated:** 2026-05-03 (87,272 bytes / 68 records)
- **Generation method:** Lines 0–66 of source + final record; `tool_result` bodies scrubbed to `[truncated-for-fixture]`; `attachment` blobs stubbed to `{type, timestamp, uuid, sessionId, _scrubbed: true}`.
- **Purpose:** Above-threshold subset — 3 real user-text messages, duration 1841 min — exercises the reaper `REAPED_OK` success path in `TestReplayCliReaper`.
- **Reaper expectation:** `REAPED_OK`
- **Original cwd:** `/Users/abhishek/dev/claude_workspace/obsidian-brain`

---

## d2cc7e46-long-617min.jsonl

- **Source SID:** `d2cc7e46-9778-41be-bebb-8fb22a491204`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/d2cc7e46-9778-41be-bebb-8fb22a491204.jsonl`
- **Original size:** 2,393,897 bytes / 1,136 records
- **Captured:** 2026-05-01 (22,663 bytes / 15 records)
- **Capture command:**
  ```bash
  python3 scripts/dev-test/capture-jsonl-fixture.py \
      --source ~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/d2cc7e46-9778-41be-bebb-8fb22a491204.jsonl \
      --out tests/fixtures/dropped-sessions/d2cc7e46-long-617min.jsonl
  ```
- **Hypothesis:** H1 (long-session SIGKILL — `_run()` never reached SessionEnd for the 617-minute session)
- **Original cwd:** `/Users/abhishek/dev/claude_workspace/obsidian-brain`

## d63cc484-3min-14msg.jsonl

- **Source SID:** `d63cc484-5ceb-483a-a0a7-b3ec9020ac50`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/d63cc484-5ceb-483a-a0a7-b3ec9020ac50.jsonl`
- **Original size:** 181,986 bytes / 98 records
- **Captured:** 2026-05-01 (35,935 bytes / 15 records)
- **Capture command:**
  ```bash
  python3 scripts/dev-test/capture-jsonl-fixture.py \
      --source ~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/d63cc484-5ceb-483a-a0a7-b3ec9020ac50.jsonl \
      --out tests/fixtures/dropped-sessions/d63cc484-3min-14msg.jsonl
  ```
- **Hypothesis:** H2 (partial-flush — final messages not yet in JSONL when SessionEnd ran; below-threshold miscount)
- **Original cwd:** `/Users/abhishek/dev/claude_workspace/obsidian-brain`

## 6fa4f267-2min-5msg.jsonl

- **Source SID:** `6fa4f267-4e34-470f-935a-00eabcb06683`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/6fa4f267-4e34-470f-935a-00eabcb06683.jsonl`
- **Original size:** 185,719 bytes / 43 records
- **Captured:** 2026-05-01 (44,492 bytes / 11 records)
- **Capture command** (smaller head/tail because source has few but very large records):
  ```bash
  python3 scripts/dev-test/capture-jsonl-fixture.py \
      --source ~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain/6fa4f267-4e34-470f-935a-00eabcb06683.jsonl \
      --out tests/fixtures/dropped-sessions/6fa4f267-2min-5msg.jsonl \
      --head-records 10 --tail-records 10
  ```
- **Hypothesis:** H2 (partial-flush)
- **Original cwd:** `/Users/abhishek/dev/claude_workspace/obsidian-brain`

## 87b15f72-worktree-deleted.jsonl

- **Source SID:** `87b15f72-51c3-40d6-af48-d86d848c01d1`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain--issue-45-compress-rank-gap-peers/87b15f72-51c3-40d6-af48-d86d848c01d1.jsonl`
- **Original size:** 2,846,720 bytes / 1,590 records
- **Captured:** 2026-05-01 (41,114 bytes / 15 records)
- **Original cwd at runtime (worktree now deleted):** `/Users/abhishek/dev/claude_workspace/obsidian-brain--issue-45-compress-rank-gap-peers`
- **Rewritten cwd in fixture:** `/Users/abhishek/dev/claude_workspace/obsidian-brain` (via `--rename-cwd`)
- **Capture command:**
  ```bash
  python3 scripts/dev-test/capture-jsonl-fixture.py \
      --source ~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain--issue-45-compress-rank-gap-peers/87b15f72-51c3-40d6-af48-d86d848c01d1.jsonl \
      --out tests/fixtures/dropped-sessions/87b15f72-worktree-deleted.jsonl \
      --rename-cwd /Users/abhishek/dev/claude_workspace/obsidian-brain
  ```
- **Hypothesis:** H1 (worktree teardown — `git worktree remove` killed the CC process before SessionEnd; see memory `feedback_default_to_feature_branch_not_worktree.md`)

## 7c71d4da-worktree-deleted.jsonl

- **Source SID:** `7c71d4da-36c4-43e3-a50b-54475f5e2f8d`
- **Source path:** `~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain--issue-50-e2e-snapshot-recall-test/7c71d4da-36c4-43e3-a50b-54475f5e2f8d.jsonl`
- **Original size:** 2,959,489 bytes / 1,915 records
- **Captured:** 2026-05-01 (41,069 bytes / 15 records)
- **Original cwd at runtime (worktree now deleted):** `/Users/abhishek/dev/claude_workspace/obsidian-brain--issue-50-e2e-snapshot-recall-test`
- **Rewritten cwd in fixture:** `/Users/abhishek/dev/claude_workspace/obsidian-brain` (via `--rename-cwd`)
- **Capture command:**
  ```bash
  python3 scripts/dev-test/capture-jsonl-fixture.py \
      --source ~/.claude/projects/-Users-abhishek-dev-claude-workspace-obsidian-brain--issue-50-e2e-snapshot-recall-test/7c71d4da-36c4-43e3-a50b-54475f5e2f8d.jsonl \
      --out tests/fixtures/dropped-sessions/7c71d4da-worktree-deleted.jsonl \
      --rename-cwd /Users/abhishek/dev/claude_workspace/obsidian-brain
  ```
- **Hypothesis:** H1 (worktree teardown)
