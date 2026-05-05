#!/usr/bin/env python3
"""Automated post-/dev-test-install verification for Issue #123 — SessionEnd outcome telemetry.

Run AFTER: /dev-test install (in a sibling CC session, on feature/issue-100-phase1-sessionend-telemetry)
Usage: python3 scripts/dev-test/test-issue-123-manual.py

Covers Phases 2, 4, and 5 from the dev-test plan:
- Phase 2: stdin-driven smoke for 8 _Outcome enum values
- Phase 4: log integrity (rotation, no missing fields, SessionStart unaffected)
- Phase 5: fixture + config cleanup

NOT covered (require a live CC session):
- OK / OK_RAW_NOTE_ONLY end-to-end with a real vault note write — covered in Phase 3 of the plan
- WRITE_FAILED via real chmod 0500 vault — could be scripted, but lives in Phase 3 to avoid touching the real vault dir

Safety:
- Real ~/.claude/obsidian-brain-config.json is backed up to a sibling .bak file
  on first mutation and restored at exit (atexit + signal handlers).
- All test fixtures live under a mktemp dir and ~/.claude/projects/-issue-123-test/.
- The real vault DB is never touched; SKIPPED_NO_VAULT and EXCEPTION tests use
  a temp config pointing at a fake vault path.
"""
from __future__ import annotations
import atexit
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ─── Bootstrap: locate installed hook ────────────────────────────────────

REAL_HOME = Path(os.path.expanduser("~"))
HOOK_LOG = REAL_HOME / ".claude" / "obsidian-brain-hook.log"
CONFIG = REAL_HOME / ".claude" / "obsidian-brain-config.json"
PROJECTS_ROOT = REAL_HOME / ".claude" / "projects"
TEST_PROJECT = PROJECTS_ROOT / "-issue-123-test"
CONFIG_BAK = REAL_HOME / ".claude" / "obsidian-brain-config.json.issue-123-bak"
# Session-scoped config cache lives here. _get_session_id_fast() resolves a sid
# from cwd → bootstrap → JSONL glob (not from hook stdin), so multiple sequential
# subprocess calls with the same cwd hit the SAME cache file. We must clear it
# between any test that mutates the on-disk config, or the hook will read a
# stale cached config and the mutation will appear to be ignored.
SECURE_DIR = REAL_HOME / ".claude" / "obsidian-brain"

candidates = sorted(
    glob.glob(str(REAL_HOME / ".claude/plugins/cache/*/obsidian-brain/*/hooks/obsidian_session_log.py"))
)
if not candidates:
    sys.exit("❌ No installed obsidian-brain hook found. Run /dev-test install first.")
HOOK_PY = Path(candidates[-1])

# Sanity: confirm the cache has #123 implementation.
hook_src = HOOK_PY.read_text()
needed = ["_Outcome", "_append_sessionend_log", "OK_RAW_NOTE_ONLY", "SKIPPED_BELOW_THRESHOLD"]
missing = [n for n in needed if n not in hook_src]
if missing:
    sys.exit(
        f"❌ Installed hook at {HOOK_PY} is missing #123 markers: {missing}\n"
        f"   Re-run /dev-test install on the #123 feature branch."
    )

# ─── Cleanup registration (must run before any mutation) ─────────────────

def _restore_config():
    """Restore real config from backup if we created one."""
    if CONFIG_BAK.exists():
        try:
            shutil.copy2(CONFIG_BAK, CONFIG)
            CONFIG_BAK.unlink()
        except OSError as e:
            print(f"  ⚠ failed to restore config: {e}", file=sys.stderr)


def _cleanup_test_project():
    if TEST_PROJECT.exists():
        shutil.rmtree(TEST_PROJECT, ignore_errors=True)


atexit.register(_restore_config)
atexit.register(_cleanup_test_project)
# Also restore on SIGINT/SIGTERM so Ctrl-C doesn't leave a corrupted config.
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda s, f: sys.exit(130))


def _backup_config_once():
    """Idempotent: copy real config to .issue-123-bak if not already done."""
    if not CONFIG_BAK.exists() and CONFIG.exists():
        shutil.copy2(CONFIG, CONFIG_BAK)


def _clear_config_cache():
    """Remove all session-scoped config cache files so the hook re-reads
    obsidian-brain-config.json on its next invocation. Best-effort.

    Necessary because load_config() in obsidian_utils.py caches the parsed
    config keyed by _get_session_id_fast()'s sid (which depends on cwd, NOT
    on the hook input's session_id). Sequential test calls with the same
    TMPDIR-based cwd resolve to the same sid and therefore share a cache.
    """
    if not SECURE_DIR.exists():
        return
    for cache_file in SECURE_DIR.glob("cache-*.json"):
        try:
            cache_file.unlink()
        except OSError:
            pass


# ─── Test scaffolding ────────────────────────────────────────────────────

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


def log_size_lines() -> int:
    """Return current line count of the hook log (0 if absent)."""
    if not HOOK_LOG.exists():
        return 0
    return sum(1 for _ in HOOK_LOG.open(encoding="utf-8", errors="replace"))


def run_hook(payload: dict | str) -> tuple[int, str, str]:
    """Pipe payload (dict→json or raw str) into the installed hook. Returns (rc, stdout, stderr)."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run(
        ["python3", str(HOOK_PY)],
        input=body,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return p.returncode, p.stdout, p.stderr


def find_outcome_for_sid(sid: str) -> str | None:
    """Scan the hook log for a SessionEnd line with sid=<sid>. Return its outcome=, or None.

    Note: the hook truncates session_id to 8 chars when emitting the log line
    (see _append_sessionend_log in obsidian_utils.py), so we match against the
    8-char prefix.
    """
    if not HOOK_LOG.exists():
        return None
    target = f"sid={sid[:8]}"
    for line in HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if "SessionEnd" in line and target in line:
            for tok in line.split():
                if tok.startswith("outcome="):
                    return tok.split("=", 1)[1]
    return None


def fresh_sid(tag: str) -> str:
    """Build a unique 8-char synthetic session_id with a tag prefix."""
    return f"tst{tag}{int(time.time()*1000) % 100000:05d}"


def make_jsonl(path: Path, n_user: int = 5, dur_min: float = 5.0) -> None:
    """Write a synthetic JSONL with n_user user messages spread across dur_min minutes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time() - dur_min * 60
    lines = []
    for i in range(n_user):
        ts = start + i * (dur_min * 60 / max(n_user, 1))
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        lines.append(json.dumps({
            "type": "user",
            "message": {"content": f"user msg {i}"},
            "timestamp": iso,
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": f"reply {i}"}]},
            "timestamp": iso,
        }))
    path.write_text("\n".join(lines) + "\n")


# ─── Phase 2 — outcome smoke tests ──────────────────────────────────────

print("═══════════════════════════════════════════════════════════════")
print(f"Issue #123 — SessionEnd telemetry smoke ({HOOK_PY})")
print("═══════════════════════════════════════════════════════════════")
print()
print("Phase 2 — outcome enum coverage")
print()

TEST_PROJECT.mkdir(parents=True, exist_ok=True)
TMPDIR = Path(tempfile.mkdtemp(prefix="ob-issue-123-"))
atexit.register(lambda: shutil.rmtree(TMPDIR, ignore_errors=True))

# 2.1 — SKIPPED_INVALID_INPUT (empty stdin)
print("  2.1  SKIPPED_INVALID_INPUT — empty stdin")
sid = fresh_sid("a")
rc, _, _ = run_hook("")
# Empty stdin can't carry sid; just check that an INVALID_INPUT line was added.
last_line = HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-1] if HOOK_LOG.exists() else ""
if "outcome=SKIPPED_INVALID_INPUT" in last_line:
    pass_(f"empty stdin → SKIPPED_INVALID_INPUT (rc={rc})")
else:
    fail_(f"empty stdin: expected SKIPPED_INVALID_INPUT, got: {last_line!r}")

# 2.2 — SKIPPED_INVALID_INPUT (missing session_id)
# Note: transcript_path containment check runs BEFORE the missing-sid check,
# so we must point at a path inside ~/.claude/projects/ to actually exercise
# the missing-sid branch.
print("  2.2  SKIPPED_INVALID_INPUT — missing session_id")
rc, _, _ = run_hook({"transcript_path": str(TEST_PROJECT / "no-sid.jsonl")})
last_line = HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-1]
if "outcome=SKIPPED_INVALID_INPUT" in last_line:
    pass_(f"missing session_id → SKIPPED_INVALID_INPUT")
else:
    fail_(f"missing sid: expected SKIPPED_INVALID_INPUT, got: {last_line!r}")

# 2.3 — SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS
print("  2.3  SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS")
sid = fresh_sid("c")
rc, _, _ = run_hook({"session_id": sid, "transcript_path": "/tmp/foreign.jsonl", "cwd": "/tmp"})
got = find_outcome_for_sid(sid)
if got == "SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS":
    pass_(f"foreign transcript_path → {got}")
else:
    fail_(f"expected SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS, got {got!r}")

# 2.4 — SKIPPED_AUTO_LOG_OFF
# Note: the hook reads `auto_log_enabled` (see obsidian_utils.py _DEFAULTS and
# obsidian_session_log.py line 249); `auto_log_sessions` is not the canonical
# key and would be silently ignored.
print("  2.4  SKIPPED_AUTO_LOG_OFF — auto_log_enabled=false")
_backup_config_once()
cfg = json.loads(CONFIG.read_text())
cfg["auto_log_enabled"] = False
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()
sid = fresh_sid("d")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=5, dur_min=5)
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got == "SKIPPED_AUTO_LOG_OFF":
    pass_(f"auto_log=false → {got}")
else:
    fail_(f"expected SKIPPED_AUTO_LOG_OFF, got {got!r}")
# Restore auto_log
cfg["auto_log_enabled"] = True
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()

# 2.5 — SKIPPED_NO_VAULT (vault_path empty/unconfigured)
# Note: the hook only checks `if not vault_path:` (truthy), not directory
# existence — see obsidian_session_log.py line 258. So we trigger this branch
# with an empty string, which matches what an unconfigured config produces.
print("  2.5  SKIPPED_NO_VAULT — vault_path empty")
_backup_config_once()
cfg = json.loads(CONFIG.read_text())
real_vault = cfg.get("vault_path")
cfg["vault_path"] = ""
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()
sid = fresh_sid("e")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=5, dur_min=5)
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got == "SKIPPED_NO_VAULT":
    pass_(f"empty vault_path → {got}")
else:
    fail_(f"expected SKIPPED_NO_VAULT, got {got!r}")
cfg["vault_path"] = real_vault
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()

# 2.6 — SKIPPED_NO_TRANSCRIPT (file missing under ~/.claude/projects/)
print("  2.6  SKIPPED_NO_TRANSCRIPT — file missing")
sid = fresh_sid("f")
missing_path = TEST_PROJECT / f"missing-{sid}.jsonl"
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(missing_path), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got == "SKIPPED_NO_TRANSCRIPT":
    pass_(f"missing JSONL → {got}")
else:
    fail_(f"expected SKIPPED_NO_TRANSCRIPT, got {got!r}")

# 2.7 — SKIPPED_BELOW_THRESHOLD (small JSONL)
print("  2.7  SKIPPED_BELOW_THRESHOLD — <3 user messages")
sid = fresh_sid("g")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=2, dur_min=10)  # 2 user msgs, default min is 3
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got == "SKIPPED_BELOW_THRESHOLD":
    pass_(f"<3 user msgs → {got}")
else:
    fail_(f"expected SKIPPED_BELOW_THRESHOLD, got {got!r}")

# 2.8 — EXCEPTION (corrupt config — present-but-invalid JSON)
print("  2.8  EXCEPTION — corrupt config")
_backup_config_once()
CONFIG.write_text("{this is not json")
_clear_config_cache()
sid = fresh_sid("h")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=5, dur_min=5)
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
# Implementation may classify corrupt config as EXCEPTION OR SKIPPED_NO_VAULT
# (load_config catches JSON errors and returns defaults whose vault_path="").
if got in ("EXCEPTION", "SKIPPED_NO_VAULT"):
    pass_(f"corrupt config → {got}")
else:
    fail_(f"expected EXCEPTION or SKIPPED_NO_VAULT, got {got!r}")
# Restore from backup
shutil.copy2(CONFIG_BAK, CONFIG)
_clear_config_cache()

# 2.9 — OK / OK_RAW_NOTE_ONLY (real success path with synthetic JSONL)
print("  2.9  OK / OK_RAW_NOTE_ONLY — real success path against TEST vault")
_backup_config_once()
test_vault = TMPDIR / "test-vault"
(test_vault / "claude-sessions").mkdir(parents=True)
(test_vault / "claude-insights").mkdir(parents=True)
cfg = json.loads(CONFIG.read_text())
real_vault = cfg.get("vault_path")
cfg["vault_path"] = str(test_vault)
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()
sid = fresh_sid("i")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=10, dur_min=20)
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got and got.startswith("OK"):
    notes_written = list((test_vault / "claude-sessions").glob("*.md"))
    if notes_written:
        pass_(f"success path → {got} + {len(notes_written)} note(s) written to test vault")
    else:
        fail_(f"outcome={got} but no note in test vault — write may have failed silently")
else:
    fail_(f"expected OK*, got {got!r}")
cfg["vault_path"] = real_vault
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()

# 2.10 — WRITE_FAILED (test vault chmod 0500)
print("  2.10 WRITE_FAILED — test vault read-only")
_backup_config_once()
ro_vault = TMPDIR / "ro-vault"
(ro_vault / "claude-sessions").mkdir(parents=True)
(ro_vault / "claude-insights").mkdir(parents=True)
cfg = json.loads(CONFIG.read_text())
cfg["vault_path"] = str(ro_vault)
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()
os.chmod(ro_vault / "claude-sessions", 0o500)
sid = fresh_sid("j")
jsonl = TEST_PROJECT / f"{sid}.jsonl"
make_jsonl(jsonl, n_user=10, dur_min=20)
rc, _, _ = run_hook({"session_id": sid, "transcript_path": str(jsonl), "cwd": str(TMPDIR)})
got = find_outcome_for_sid(sid)
if got == "WRITE_FAILED":
    pass_(f"read-only vault → {got}")
else:
    fail_(f"expected WRITE_FAILED, got {got!r}")
os.chmod(ro_vault / "claude-sessions", 0o700)  # so cleanup can rm it
cfg["vault_path"] = real_vault
CONFIG.write_text(json.dumps(cfg, indent=2))
_clear_config_cache()

# ─── Phase 4 — log integrity ─────────────────────────────────────────────

print()
print("Phase 4 — log integrity")
print()

# 4.1 — every SessionEnd line has outcome=, sid=, project=
print("  4.1  every SessionEnd line has outcome= sid= project=")
missing_field = []
for ln, line in enumerate(HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
    if "SessionEnd" not in line:
        continue
    for required in ("outcome=", "sid=", "project="):
        if required not in line:
            missing_field.append((ln, required, line[:200]))
            break
if not missing_field:
    pass_("all SessionEnd lines have required fields")
else:
    fail_(f"{len(missing_field)} SessionEnd line(s) missing required field; first: {missing_field[0]}")

# 4.2 — SessionStart entries unaffected
print("  4.2  SessionStart entries still emitting")
ss_count = sum(1 for line in HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
               if "SessionStart" in line)
if ss_count > 0:
    pass_(f"{ss_count} SessionStart line(s) present (regression guard)")
else:
    fail_("no SessionStart lines in hook log — telemetry may have broken existing logger")

# 4.3 — rotation cap (100 KB) preserved structure
print("  4.3  log size within rotation cap")
log_bytes = HOOK_LOG.stat().st_size
if log_bytes <= 100 * 1024 + 4096:  # 100 KB + a small grace for the latest line
    pass_(f"log is {log_bytes} bytes (under 100 KB rotation cap)")
else:
    rotated = HOOK_LOG.with_suffix(".log.1")
    if rotated.exists():
        pass_(f"log is {log_bytes} bytes but rotated .log.1 exists")
    else:
        fail_(f"log is {log_bytes} bytes and no .log.1 — rotation broken")

# ─── Summary ─────────────────────────────────────────────────────────────

print()
print("═══════════════════════════════════════════════════════════════")
print(f"PASS={PASS}  FAIL={FAIL}")
print("═══════════════════════════════════════════════════════════════")
print()
print("Cleanup will run via atexit:")
print(f"  - restore real config from {CONFIG_BAK.name}")
print(f"  - rm -rf {TEST_PROJECT}")
print(f"  - rm -rf {TMPDIR}")
print()
print("Live-CC steps NOT covered (run separately, see Phase 3 in the dev-test plan):")
print("  - real OK in a fresh CC session that produces a vault note")
print("  - WRITE_FAILED on the REAL vault dir (chmod 0500 ~/obsidian/.../claude-sessions/)")
print()
sys.exit(0 if FAIL == 0 else 1)
