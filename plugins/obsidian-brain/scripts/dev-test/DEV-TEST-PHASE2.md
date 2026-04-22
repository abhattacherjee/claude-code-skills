# Phase 2 Dev-Test Checklist

Manual verification procedure for the Friston Phase 2 implementation (TF-IDF + themes + surprise + review fixes) on branch `feature/friston-phase2-tfidf-themes` / PR #41.

Run this BEFORE `/finish` on the PR. The automated test suite (518 tests, 90% coverage) catches unit-level regressions; this procedure exercises the SKILL.md ↔ Python ↔ SQLite integration boundary that the test suite cannot reach.

---

## Step 0 — Prerequisites

- [ ] Current branch is `feature/friston-phase2-tfidf-themes` (or your rebase of it)
- [ ] Working tree clean (`git status --short` prints nothing)
- [ ] Automated tests pass: `python3 -m pytest -q` → `518 passed`
- [ ] Preflight clean: `./scripts/commit-preflight.sh --auto` → `✅ PREFLIGHT PASSED`
- [ ] Config file exists at `~/.claude/obsidian-brain-config.json` with `vault_path` set
- [ ] A vault with ≥2 summarized session notes from the same project exists (needed for theme-assignment exercise)

If the vault has <2 notes on any single project, run `/vault-import 30d` first to seed history.

---

## Step 1 — Install dev version

```bash
cd ~/dev/claude_workspace/obsidian-brain
# Claude Code: invoke the skill
/obsidian-brain:dev-test install
```

Expected:
- Backs up `~/.claude/plugins/cache/claude-code-skills/obsidian-brain/<version>/` → `<version>.bak/`
- Copies `hooks/*.py` + `skills/*/` into the cache
- Prints summary of files replaced

Verify:
```bash
ls ~/.claude/plugins/cache/claude-code-skills/obsidian-brain/*/hooks/ | grep vault_index.py
# confirm the dev version hook is in place
```

**Restart Claude Code** (close and reopen the session) so the new SKILL.md files are loaded.

---

## Step 2 — Upgrade-mode setup (DB migration + first-pass deps prompt)

Phase 2 adds 3 new tables (`themes`, `theme_members`, `term_df`) and 1 new column (`notes.tfidf_vector`). `/obsidian-setup` in upgrade mode calls `rebuild_index()` in Step 8.5 — same path as `/vault-reindex` — **and** exercises the new Step 8.7 optional-deps prompt in one invocation.

```
/obsidian-brain:obsidian-setup
```

When prompted for mode, choose **upgrade**. Expected flow:

1. Step 5: folder mkdir (idempotent)
2. Step 6: dashboard files (existing ones skipped)
3. Step 7: config write — **skipped** in upgrade mode (existing config preserved)
4. Step 8: vault access check
5. Step 8.5: `rebuild_index()` drops + recreates all tables → "Indexed N notes across M folders"
6. Step 8.7: first-time deps prompt (skip it here — Step 5 below covers all three branches)
7. Step 9: claudeception nudge (idempotent)
8. Step 10: success message

This single invocation replaces both `/vault-reindex` AND the first-time-deps case of the old Step 5. No separate `/vault-reindex` call needed.

Verify via `sqlite3`:

```bash
DB="$HOME/.claude/obsidian-brain-vault.db"
sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('themes','theme_members','term_df')"
# Expected 3 lines: themes, theme_members, term_df

sqlite3 "$DB" "PRAGMA table_info(notes)" | grep tfidf_vector
# Expected: "X|tfidf_vector|TEXT|0||0"
```

**Fallback:** if you only want to migrate the DB schema without re-running setup (e.g. config already known-good, just touching this branch), `/vault-reindex` does the schema work alone.

---

## Step 3 — Run the automated invariant checker

```bash
bash scripts/dev-test/test-phase2-manual.sh
```

Expected:
- `✅` marks across Schema, Indexes, Data population, term_df consistency, FTS cleanliness
- `⏭` (skipped) for Theme invariants if themes haven't been created yet (run /recall first — Step 6)
- No `❌` marks

If any `❌` appears, **stop here** and diagnose before proceeding.

---

## Step 4 — Run the Python numerical checker

```bash
python3 scripts/dev-test/validate_phase2.py
```

Or with detail:
```bash
python3 scripts/dev-test/validate_phase2.py --verbose
```

Expected:
- Tokenizer, TF-IDF compute, cosine similarity, detect_surprise, assign_to_theme idempotency, _delete_note centroid unfold, check_optional_deps, load_config deepcopy — all **PASS**
- Exit code 0

This hits the numerical paths that don't require a populated vault.

---

## Step 5 — Exercise all three `/obsidian-setup --deps` branches

Step 2's upgrade-mode run already hit Step 8.7 once. This step uses the `--deps` flag — which jumps directly to Step 8.7 without re-running the rest of setup — to exercise **all three prompt branches** in isolation and validate idempotency.

Each invocation is independent; re-running is safe.

### 5a. If numpy/scipy are NOT installed

```
/obsidian-brain:obsidian-setup --deps
```

Expected prompt:
```
Performance dependencies
========================
numpy: not installed
scipy: not installed

Install now? (yes/skip/not-now)
```

Test each branch:
- **Type `skip`** → should write `optional_deps_declined: ["numpy", "scipy"]` + `optional_deps_prompted: true` to config. Verify:
  ```bash
  cat ~/.claude/obsidian-brain-config.json | python3 -m json.tool | grep optional_deps
  ```
- **Type `not-now`** → should write `optional_deps_prompted: false` (so it prompts again next run). Verify same config path.
- **Type `yes`** → invokes `python3 -m pip install --user numpy scipy` (or platform equivalent). Should succeed if network available. After completion, re-run `/obsidian-setup --deps` — should detect they're installed and skip the prompt entirely (idempotent).

### 5b. If numpy/scipy ARE already installed

```
/obsidian-brain:obsidian-setup --deps
```

Expected: detects installed packages, skips the prompt, prints "Performance dependencies: all present". No config write.

### 5c. Atomic config write test

Inspect the config file perms:
```bash
ls -l ~/.claude/obsidian-brain-config.json
# Expected: -rw-------  (0o600)
```

If perms are anything else, the atomic write is regressing.

### 5d. Verify deepcopy isolation (subtle bug from PR review round 3)

```bash
python3 -c "
import sys, glob, os
sys.path.insert(0, max(glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks'))))
import obsidian_utils
c1 = obsidian_utils.load_config()
c1.setdefault('optional_deps_declined', []).append('TEST_POISON')
obsidian_utils.cache_set(obsidian_utils._get_session_id_fast(), 'config', None)
c2 = obsidian_utils.load_config()
assert 'TEST_POISON' not in c2.get('optional_deps_declined', []), 'MUTABLE DEFAULT LEAKED'
print('OK — deepcopy isolation holds')
"
```

Expected: `OK — deepcopy isolation holds`

---

## Step 6 — Exercise `/recall` to trigger theme assignment

This is the main Phase 2 integration point. `/recall` should:
1. Find unsummarized notes via `find_unsummarized_notes()` (now includes the widened type filter).
2. Summarize them via `upgrade_batch()` (Phase 1 parallel-Haiku fan-out) with sub-agent fallback for failures (Phase 2).
3. On write-back, call `index_note()` → `assign_to_theme()` → write surprise via `detect_surprise()`.

```
/obsidian-brain:recall
```

Expected:
- Normal `/recall` output (context brief, session history table, etc.)
- `[INFO] Phase 2: theme assignment …` lines in stderr for each upgraded note (check the hidden messages or the Claude Code log)
- No `[ERROR] theme pipeline unexpected error` entries
- No `[WARN] theme re-index failed` entries unless a known cause (e.g. DB temporarily locked)

Verify themes were created:
```bash
sqlite3 "$DB" "SELECT id, name, note_count, project FROM themes LIMIT 10"
```

Expected: at least one theme per project with ≥2 semantically-similar summarized notes. `note_count` should be ≥1. `name` may be blank (theme naming is a Phase 3 feature).

Verify membership:
```bash
sqlite3 "$DB" "SELECT t.name, COUNT(tm.note_path) FROM themes t JOIN theme_members tm ON tm.theme_id = t.id GROUP BY t.id"
```

The COUNT per theme should match `themes.note_count`. (The `test-phase2-manual.sh` script also checks this invariant.)

---

## Step 7 — Surprise detection sanity check

Find a theme_members row where surprise > 0:
```bash
sqlite3 "$DB" "SELECT theme_id, note_path, similarity, surprise FROM theme_members WHERE surprise > 0 ORDER BY surprise DESC LIMIT 5"
```

If rows exist with `surprise > 0`: open one of those notes in Obsidian and verify its content contains negation words near shared TF-IDF terms (the heuristic's intent). This is a sanity check; false positives are acceptable.

If ALL surprise values are 0: either your vault has no contradictory content (fine), OR `detect_surprise` regressed (run `validate_phase2.py` Step 4).

---

## Step 8 — FTS5 orphan cleanup test (from PR review round 2)

This is the "contentless FTS5 'delete'" fix. Verify that modifying a note multiple times doesn't accumulate `notes_fts` rows.

```bash
# Pick a note path to modify — one of your existing session notes is fine
NOTE="$HOME/obsidian/claude-code-vault/claude-sessions/$(ls ~/obsidian/claude-code-vault/claude-sessions/*.md | head -1 | xargs basename)"

# Current FTS count
FTS_BEFORE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes_fts")
NOTES_BEFORE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes")
echo "Before: notes=$NOTES_BEFORE, fts=$FTS_BEFORE"

# Touch mtime 3 times and reindex each time
for i in 1 2 3; do
    touch -A +002 "$NOTE"  # bump mtime by 2s
    python3 -c "
import sys, glob, os
sys.path.insert(0, max(glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks'))))
import vault_index
from obsidian_utils import load_config
c = load_config()
vault_index.ensure_index(c['vault_path'], [c.get('sessions_folder', 'claude-sessions')])
"
done

FTS_AFTER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes_fts")
NOTES_AFTER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes")
echo "After: notes=$NOTES_AFTER, fts=$FTS_AFTER"

if [ "$FTS_AFTER" -eq "$NOTES_AFTER" ]; then
    echo "✅ FTS count matches notes count — orphan cleanup works"
else
    echo "❌ FTS=$FTS_AFTER != notes=$NOTES_AFTER — orphans accumulating"
fi
```

Expected: `FTS count matches notes count`.

---

## Step 9 — `/vault-search` smoke test

Confirms access_log cascade (if you want to pre-verify the Section 7 design of the snapshot spec; skip for strict Phase 2 scope).

```
/obsidian-brain:vault-search retrieval scoring
```

Expected: results returned with ranking. Check `access_log`:

```bash
sqlite3 "$DB" "SELECT COUNT(*) FROM access_log WHERE timestamp > strftime('%s', 'now', '-5 minutes')"
```

Expected: >0 (recent events from the search).

---

## Step 10 — Concurrency smoke test (BEGIN IMMEDIATE)

Two concurrent `index_note` calls should serialize cleanly, not deadlock or corrupt data.

```bash
python3 -c "
import sys, glob, os, threading
sys.path.insert(0, max(glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks'))))
import vault_index
from obsidian_utils import load_config
c = load_config()
db = os.path.expanduser('~/.claude/obsidian-brain-vault.db')

import glob as g
notes = g.glob(os.path.join(c['vault_path'], c.get('sessions_folder', 'claude-sessions'), '*.md'))[:4]
if len(notes) < 2:
    print('Need >=2 notes in sessions folder; aborting concurrency test')
    exit()

errors = []
def worker(path):
    try:
        vault_index.index_note(db, path)
    except Exception as e:
        errors.append(f'{path}: {e}')

threads = [threading.Thread(target=worker, args=(n,)) for n in notes]
for t in threads: t.start()
for t in threads: t.join()

if errors:
    print('❌ Concurrent index_note failures:')
    for e in errors: print(f'  {e}')
else:
    print(f'✅ {len(notes)} concurrent index_note calls all succeeded')
"
```

Expected: `✅ N concurrent index_note calls all succeeded`. SQLITE_BUSY warnings in stderr are acceptable (the retry should succeed within 5s timeout).

---

## Step 11 — Re-run invariant checker

After all the above exercise, re-run the automated invariants to confirm no drift:

```bash
bash scripts/dev-test/test-phase2-manual.sh && python3 scripts/dev-test/validate_phase2.py
```

Expected: both exit 0, no `❌`.

---

## Step 12 — Restore original version

```
/obsidian-brain:dev-test restore
```

Verify:
```bash
ls ~/.claude/plugins/cache/claude-code-skills/obsidian-brain/
# Should show only the original <version>/ directory, no <version>.bak/
```

**Restart Claude Code** one more time to confirm everything still works on the original version.

---

## Exit criteria

All of the following must be true before `/finish` on PR #41:

- [ ] Steps 1-11 all pass with no `❌` markers
- [ ] Step 2 `/obsidian-setup` (upgrade mode) exercised end-to-end — DB schema migrated, dashboards preserved, config untouched
- [ ] `/obsidian-setup --deps` tested in at least one branch explicitly (install-yes OR skip+re-run for idempotency)
- [ ] `/recall` produces theme rows in the DB
- [ ] FTS5 orphan test shows count parity after 3x rewrite
- [ ] Concurrency test shows no corruption
- [ ] Original version restored cleanly via `/dev-test restore`

If any fail, note the failure in the PR description and don't merge until resolved.
