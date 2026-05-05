#!/usr/bin/env python3
"""Manual smoke test for Issue #128 — vault-reindex observability + safety.

Run AFTER: /dev-test install (in a sibling CC session, on the #128 feature branch)
Usage: python3 scripts/dev-test/test-issue-128-manual.py

Phase 1 — fixture-isolated assertions (8 improvements):
  1.1  pruned_foreign reported in stats
  1.2  skipped split into unchanged + malformed
  1.3  audit log written for prunes
  1.4  full-scan path-format drift check (no more LIMIT-5 sampling)
  1.5  pre-reindex DB backup with last-3 rotation
  1.6  --allow-fallthrough required for legacy-schema destructive path
  1.7  --dry-run rolls back all writes
  1.8  missing-DB fall-through still works (regression guard)

Phase 2 — read-only + dry-run against real vault (3 checks):
  2.1  the 4 crash-recovered notes from 2026-04-30 are still indexed
  2.2  access_log canonical (all paths absolute, all under vault root)
  2.3  dry-run on real vault is non-destructive
"""
from __future__ import annotations
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# ─── Bootstrap ────────────────────────────────────────────────────────────

REAL_HOME = os.path.expanduser("~")  # capture before any HOME override

candidates = sorted(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks"))
)
if not candidates:
    sys.exit("❌ No obsidian-brain plugin cache found. Run /dev-test install first.")
HOOK_DIR = candidates[-1]
sys.path.insert(0, HOOK_DIR)

# Sanity: confirm the #128 implementation is present in the cache.
SRC = Path(HOOK_DIR) / "vault_index.py"
SKILL = next(
    iter(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/skills/vault-reindex/SKILL.md"))),
    "",
)
required_in_src = ["pruned_foreign", "allow_fallthrough", "dry_run", "malformed", "unchanged"]
missing = [r for r in required_in_src if SRC.exists() and r not in SRC.read_text()]
if missing:
    sys.exit(
        f"❌ Plugin cache at {HOOK_DIR} is missing #128 implementations: {missing}\n"
        f"   Check out the #128 feature branch and run /dev-test install in a sibling CC session."
    )

import vault_index  # noqa: E402  (import after path mutation + sanity)
from vault_index import rebuild_index, _init_schema, _connect  # noqa: E402

PASS = 0
FAIL = 0


def pass_(msg: str) -> None:
    global PASS
    print(f"  ✅ {msg}")
    PASS += 1


def fail_(msg: str) -> None:
    global FAIL
    print(f"  ❌ {msg}")
    FAIL += 1


# ─── Fixture infrastructure ──────────────────────────────────────────────

FIXTURE = Path(tempfile.mkdtemp(prefix="ob-issue-128-"))
HOME_FIX = FIXTURE / "home"
VAULT_FIX = FIXTURE / "vault"
(HOME_FIX / ".claude" / "obsidian-brain").mkdir(parents=True)
(HOME_FIX / ".claude" / "obsidian-brain").chmod(0o700)
(VAULT_FIX / "claude-sessions").mkdir(parents=True)
(VAULT_FIX / "claude-insights").mkdir(parents=True)

# Cleanup at exit
import atexit  # noqa: E402

atexit.register(lambda: shutil.rmtree(FIXTURE, ignore_errors=True))


def write_note(rel: str, fm: dict, body: str = "body\n") -> Path:
    """Write a markdown note with YAML frontmatter under VAULT_FIX. Returns abs path."""
    p = VAULT_FIX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = "\n".join(f"{k}: {v}" for k, v in fm.items())
    p.write_text(f"---\n{fm_yaml}\n---\n\n{body}")
    return p


def fresh_db(name: str) -> Path:
    db = FIXTURE / f"{name}.db"
    if db.exists():
        db.unlink()
    conn = _connect(str(db))
    try:
        _init_schema(conn)
    finally:
        conn.close()
    return db


def insert_note_row(db: Path, abs_path: str, mtime: float, type_: str = "claude-session") -> None:
    conn = _connect(str(db))
    try:
        conn.execute(
            "INSERT INTO notes (path, type, project, date, mtime, importance, body) "
            "VALUES (?, ?, 'p', '2026-01-01', ?, 5, '')",
            (abs_path, type_, mtime),
        )
        conn.commit()
    finally:
        conn.close()


def insert_access(db: Path, note_path: str, ts: float = None, ctx: str = "search") -> None:
    conn = _connect(str(db))
    try:
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type, project) "
            "VALUES (?, ?, ?, 'p')",
            (note_path, ts or time.time(), ctx),
        )
        conn.commit()
    finally:
        conn.close()


def reindex(db: Path, **kwargs) -> dict:
    """Wrap rebuild_index with HOME redirected to the fixture so audit logs/backups land there."""
    saved_home = os.environ.get("HOME")
    os.environ["HOME"] = str(HOME_FIX)
    try:
        return rebuild_index(
            str(VAULT_FIX),
            ["claude-sessions", "claude-insights"],
            db_path=str(db),
            **kwargs,
        )
    finally:
        if saved_home is not None:
            os.environ["HOME"] = saved_home


# ─── Phase 1 ──────────────────────────────────────────────────────────────

print("═══════════════════════════════════════════════════════════════")
print(f"Issue #128 — vault-reindex observability + safety  ({HOOK_DIR})")
print("═══════════════════════════════════════════════════════════════")
print()
print("Phase 1 — fixture-isolated assertions")
print()

# 1.1 — pruned_foreign reported in stats
print("  1.1  pruned_foreign in stats")
db = fresh_db("p11")
ok = write_note("claude-sessions/2026-01-01-good-aaaa.md", {"type": "claude-session", "session_id": "s-good", "project": "p", "date": "2026-01-01"})
insert_note_row(db, str(ok), ok.stat().st_mtime)
for i, foreign_root in enumerate(["/private/tmp/x", "/private/tmp/x", "/var/folders/y", "/Users/abhishek/old-vault", "/Users/abhishek/old-vault"]):
    insert_note_row(db, f"{foreign_root}/note-{i}.md", time.time(), "claude-session")
stats = reindex(db)
pf = stats.get("pruned_foreign", {})
if pf.get("notes") == 5:
    pass_(f"pruned_foreign.notes == 5 (got {pf.get('notes')})")
else:
    fail_(f"expected pruned_foreign.notes == 5, got {pf}")
if "by_root" in pf and "/private/tmp/" in str(pf.get("by_root", {})):
    pass_("pruned_foreign.by_root populated with recognizable roots")
else:
    fail_(f"pruned_foreign.by_root missing or empty: {pf}")

# 1.2 — split skipped into unchanged + malformed
print("  1.2  unchanged + malformed counters")
db = fresh_db("p12")
unchanged_note = write_note(
    "claude-sessions/2026-01-02-unchanged-bbbb.md",
    {"type": "claude-session", "session_id": "s-unchanged", "project": "p", "date": "2026-01-02"},
)
insert_note_row(db, str(unchanged_note), unchanged_note.stat().st_mtime)
# Malformed: no frontmatter at all
malformed_note = VAULT_FIX / "claude-sessions" / "2026-01-03-malformed-cccc.md"
malformed_note.write_text("just body, no frontmatter\n")
stats = reindex(db)
if stats.get("unchanged") == 1 and stats.get("malformed") == 1:
    pass_(f"unchanged={stats.get('unchanged')}, malformed={stats.get('malformed')}")
else:
    fail_(f"expected unchanged=1 malformed=1, got unchanged={stats.get('unchanged')} malformed={stats.get('malformed')} skipped={stats.get('skipped')}")

# 1.3 — audit log written
print("  1.3  audit log written for prunes")
db = fresh_db("p13")
real_note = write_note(
    "claude-sessions/2026-01-04-real-dddd.md",
    {"type": "claude-session", "session_id": "s-real", "project": "p", "date": "2026-01-04"},
)
insert_note_row(db, str(real_note), real_note.stat().st_mtime)
insert_access(db, str(real_note))  # canonical, will survive
insert_access(db, "/Users/abhishek/old-vault/orphan.md")  # orphan, will be pruned via Step 1+3
insert_note_row(db, "/Users/abhishek/old-vault/orphan.md", time.time())
audit_dir = HOME_FIX / ".claude" / "obsidian-brain"
before_logs = set(audit_dir.glob("reindex-prune-*.log"))
reindex(db)
after_logs = set(audit_dir.glob("reindex-prune-*.log"))
new_logs = after_logs - before_logs
if len(new_logs) == 1:
    log = new_logs.pop()
    if "old-vault/orphan.md" in log.read_text():
        pass_(f"audit log {log.name} contains pruned path")
    else:
        fail_(f"audit log written but missing expected path: {log.read_text()[:200]}")
else:
    fail_(f"expected exactly 1 new audit log, got {len(new_logs)}")

# 1.4 — full-scan path-format drift check
print("  1.4  full-scan drift check (no LIMIT-5 sampling)")
db = fresh_db("p14")
canonical_note = write_note(
    "claude-sessions/2026-01-05-canonical-eeee.md",
    {"type": "claude-session", "session_id": "s-canonical", "project": "p", "date": "2026-01-05"},
)
insert_note_row(db, str(canonical_note), canonical_note.stat().st_mtime)
# Inject 50 canonical orphan rows + 1 non-absolute drift row deeply embedded.
for i in range(50):
    insert_access(db, f"/Users/abhishek/old/orphan-{i}.md")
insert_access(db, "relative/drift.md")  # non-absolute → should abort prune
import io
import contextlib

stderr = io.StringIO()
with contextlib.redirect_stderr(stderr):
    stats = reindex(db)
err = stderr.getvalue()
if "non-absolute" in err and ("count" in err.lower() or ":1" in err or " 1 " in err):
    pass_("drift check counted (not sampled) and aborted prune")
else:
    fail_(f"expected full-count drift abort, got stderr: {err[:300]}")
# Prune should have been skipped → access_log row count > 1 (canonical preserved).
conn = _connect(str(db))
n = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
conn.close()
if n > 1:
    pass_(f"prune skipped, access_log retained {n} rows")
else:
    fail_(f"prune ran despite drift: access_log={n}")

# 1.5 — pre-reindex DB backup with last-3 rotation
print("  1.5  DB backup with last-3 rotation")
db = fresh_db("p15")
canonical = write_note(
    "claude-sessions/2026-01-06-bk-ffff.md",
    {"type": "claude-session", "session_id": "s-bk", "project": "p", "date": "2026-01-06"},
)
insert_note_row(db, str(canonical), canonical.stat().st_mtime)
for i in range(4):
    reindex(db)
    time.sleep(1.05)  # ensure distinct timestamps for the .bak suffix
backups = sorted(FIXTURE.glob("p15.db.bak-*"))
if len(backups) == 3:
    pass_(f"backup rotation kept last 3 (got {len(backups)})")
else:
    fail_(f"expected 3 backups, got {len(backups)}: {[b.name for b in backups]}")
if backups and backups[-1].stat().st_size > 0:
    pass_("most recent backup is non-empty")
else:
    fail_("most recent backup empty or missing")

# 1.6 — --allow-fallthrough required for legacy-schema destructive path
print("  1.6  --allow-fallthrough guard for legacy schema")
db = fresh_db("p16")
# Simulate legacy schema by dropping the body column (or whatever marker the
# implementation uses — adjust to match _needs_body_migration's heuristic).
conn = _connect(str(db))
try:
    conn.execute("ALTER TABLE notes RENAME TO notes_legacy_test")
    conn.execute("CREATE TABLE notes (path TEXT PRIMARY KEY, type TEXT, project TEXT, date TEXT, mtime REAL, importance REAL)")
    conn.execute("INSERT INTO access_log (note_path, timestamp, context_type, project) VALUES (?, ?, 'search', 'p')",
                 ("/Users/abhishek/something.md", time.time()))
    conn.commit()
finally:
    conn.close()
saved_access = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM access_log").fetchone()[0]

try:
    reindex(db)
    fail_("expected SystemExit/abort on legacy schema without --allow-fallthrough")
except SystemExit as e:
    if "fallthrough" in str(e).lower() or "incompatible" in str(e).lower():
        pass_("aborted with informative message on legacy schema")
    else:
        fail_(f"aborted but message unclear: {e}")
except Exception as e:
    msg = str(e).lower()
    if "fallthrough" in msg or "incompatible" in msg or "schema" in msg:
        pass_("aborted with schema-related error")
    else:
        fail_(f"unexpected exception type: {type(e).__name__}: {e}")

# Verify access_log is intact (the abort prevented the destructive fall-through)
n_after = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
if n_after == saved_access:
    pass_("access_log preserved after abort")
else:
    fail_(f"access_log changed despite abort: before={saved_access} after={n_after}")

# Now run with explicit consent — should succeed and wipe.
stats = reindex(db, allow_fallthrough=True)
n_final = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
if stats.get("mode") == "full" and n_final == 0:
    pass_("--allow-fallthrough opted-in and wiped access_log as expected")
else:
    fail_(f"--allow-fallthrough did not perform destructive rebuild: stats={stats} access_log_after={n_final}")

# 1.7 — --dry-run rolls back all writes
print("  1.7  --dry-run is non-destructive")
db = fresh_db("p17")
canonical = write_note(
    "claude-sessions/2026-01-07-dry-gggg.md",
    {"type": "claude-session", "session_id": "s-dry", "project": "p", "date": "2026-01-07"},
)
insert_note_row(db, str(canonical), canonical.stat().st_mtime)
insert_note_row(db, "/private/tmp/foreign.md", time.time())  # would-be foreign prune target
insert_access(db, "/private/tmp/foreign.md")  # would-be orphan
before = {
    "notes": sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM notes").fetchone()[0],
    "access_log": sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM access_log").fetchone()[0],
}
audit_before = set((HOME_FIX / ".claude" / "obsidian-brain").glob("reindex-prune-*.log"))
backup_before = set(FIXTURE.glob("p17.db.bak-*"))
stats = reindex(db, dry_run=True)
after = {
    "notes": sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM notes").fetchone()[0],
    "access_log": sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM access_log").fetchone()[0],
}
audit_after = set((HOME_FIX / ".claude" / "obsidian-brain").glob("reindex-prune-*.log"))
backup_after = set(FIXTURE.glob("p17.db.bak-*"))
if before == after:
    pass_(f"dry-run preserved row counts: {before}")
else:
    fail_(f"dry-run mutated DB: before={before} after={after}")
if audit_before == audit_after and backup_before == backup_after:
    pass_("dry-run wrote no audit log and no backup")
else:
    fail_(f"dry-run produced side effects: audit_new={audit_after - audit_before} bak_new={backup_after - backup_before}")
if stats.get("pruned_foreign", {}).get("notes") == 1:
    pass_("dry-run still computed accurate pruned_foreign stats")
else:
    fail_(f"dry-run stats wrong: {stats}")

# 1.8 — missing-DB fall-through still works (regression guard)
print("  1.8  missing-DB fall-through (non-destructive, no flag needed)")
db = FIXTURE / "p18.db"
if db.exists():
    db.unlink()
canonical = write_note(
    "claude-sessions/2026-01-08-missing-hhhh.md",
    {"type": "claude-session", "session_id": "s-missing", "project": "p", "date": "2026-01-08"},
)
try:
    stats = reindex(db)
    if db.exists() and sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM notes").fetchone()[0] >= 1:
        pass_(f"missing-DB fall-through created index ({stats.get('mode')}, inserted={stats.get('inserted')})")
    else:
        fail_(f"missing-DB fall-through ran but DB still empty: {stats}")
except Exception as e:
    fail_(f"missing-DB fall-through unexpectedly errored: {e}")

# ─── Phase 2 — real-vault read-only + dry-run ────────────────────────────

print()
print("Phase 2 — real-vault checks (read-only + dry-run)")
print()

real_db_path = Path(REAL_HOME) / ".claude" / "obsidian-brain-vault.db"
real_vault = Path("/Users/abhishek/obsidian/claude-code-vault")

# 2.1 — 4 crash-recovered notes from 2026-04-30 are indexed
print("  2.1  4 crash-recovered notes are indexed")
recovered = [
    "2026-04-26-tiny-vacation-agent-f370.md",
    "2026-04-27-local-llm-90bd.md",
    "2026-04-27-obsidian-brain-2b78.md",
    "2026-04-29-knowledge-base-ui-59bb.md",
]
conn = sqlite3.connect(str(real_db_path))
try:
    found = 0
    for fn in recovered:
        full = str(real_vault / "claude-sessions" / fn)
        if conn.execute("SELECT 1 FROM notes WHERE path = ?", (full,)).fetchone():
            found += 1
finally:
    conn.close()
if found == 4:
    pass_("all 4 crash-recovered notes indexed")
else:
    fail_(f"only {found}/4 crash-recovered notes found in real index")

# 2.2 — access_log canonical
print("  2.2  access_log all canonical")
conn = sqlite3.connect(str(real_db_path))
try:
    n_total = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
    n_canonical = conn.execute(
        "SELECT COUNT(*) FROM access_log WHERE substr(note_path, 1, 1) = '/' "
        "AND note_path LIKE ?",
        (f"{real_vault}/%",),
    ).fetchone()[0]
finally:
    conn.close()
if n_total > 0 and n_total == n_canonical:
    pass_(f"all {n_total} access_log rows are absolute + under vault root")
else:
    fail_(f"access_log drift: {n_canonical}/{n_total} canonical")

# 2.3 — dry-run on real vault is non-destructive
print("  2.3  dry-run on real vault is non-destructive")
real_before = {}
conn = sqlite3.connect(str(real_db_path))
try:
    for tbl in ("notes", "access_log", "themes", "theme_members"):
        real_before[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
finally:
    conn.close()
try:
    # Use REAL HOME so this exercises the real config path
    os.environ["HOME"] = REAL_HOME
    stats = rebuild_index(
        str(real_vault),
        ["claude-sessions", "claude-insights"],
        dry_run=True,
    )
finally:
    pass
real_after = {}
conn = sqlite3.connect(str(real_db_path))
try:
    for tbl in ("notes", "access_log", "themes", "theme_members"):
        real_after[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
finally:
    conn.close()
if real_before == real_after:
    pass_(f"dry-run preserved real vault DB row counts: {real_before}")
else:
    fail_(f"dry-run touched real vault! before={real_before} after={real_after}")

# ─── Summary ──────────────────────────────────────────────────────────────

print()
print("═══════════════════════════════════════════════════════════════")
print(f"PASS={PASS}  FAIL={FAIL}")
print("═══════════════════════════════════════════════════════════════")
sys.exit(0 if FAIL == 0 else 1)
