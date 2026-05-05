#!/usr/bin/env python3
"""Tier-1 fixture harness for #125 — F2 errno surfacing + F3 reaper.

Usage:
    python3 scripts/dev-test/test-issue-125-manual.py

Sets up a self-contained $TMPDIR/issue-125-fixture/ with sentinel-checked
vault, fake ~/.claude/projects/<slug>/ containing the dropped-session
corpus, runs the reaper, asserts the expected outcomes, then re-invokes
the reaper to verify watermark advancement.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

_GREEN = "\033[32m"
_RED = "\033[31m"
_RESET = "\033[0m"

_PASS_COUNT = 0
_FAIL_COUNT = 0


def _section(title):
    print(f"\n=== {title} ===", flush=True)


def _assert(condition, msg):
    global _PASS_COUNT, _FAIL_COUNT
    if condition:
        _PASS_COUNT += 1
        print(f"  {_GREEN}PASS{_RESET}: {msg}")
    else:
        _FAIL_COUNT += 1
        print(f"  {_RED}FAIL{_RESET}: {msg}")
        sys.exit(1)


def main():
    _section("Setup sandbox")
    sandbox = Path(tempfile.mkdtemp(prefix="issue-125-fixture-"))
    print(f"  sandbox = {sandbox}")
    sentinel = sandbox / ".issue-125-sentinel"
    sentinel.write_text("ok\n")  # Cleanup precondition

    home = sandbox / "home"
    # Use same slug as the real project so _resolve_project_jsonl_dir matches
    project_name = "obsidian-brain"
    project_slug = "-Users-abhishek-dev-claude-workspace-obsidian-brain"
    project_dir = home / ".claude" / "projects" / project_slug
    project_dir.mkdir(parents=True)
    (home / ".claude" / "obsidian-brain").mkdir(parents=True, mode=0o700)

    vault = sandbox / "vault"
    sessions = vault / "claude-sessions"
    sessions.mkdir(parents=True)

    # Write config to isolated home
    config = {
        "vault_path": str(vault),
        "sessions_folder": "claude-sessions",
        "min_messages": 3,
        "min_duration_minutes": 2,
        "reaper_enabled": True,
        "reaper_max_runtime_seconds": 30,
    }
    config_path = home / ".claude" / "obsidian-brain-config.json"
    config_path.write_text(json.dumps(config))
    os.chmod(config_path, 0o600)

    # Fixture corpus: one above-threshold (full), two below-threshold
    fixtures = REPO_ROOT / "tests" / "fixtures" / "dropped-sessions"

    # Above-threshold: d2cc7e46-long-617min-full.jsonl (3 user msgs, 1841 min)
    above_src = fixtures / "d2cc7e46-long-617min-full.jsonl"
    above_first = json.loads(above_src.read_text().splitlines()[0])
    above_sid = above_first.get("sessionId") or above_first.get("session_id")
    above_dst = project_dir / f"{above_sid}.jsonl"
    shutil.copy(above_src, above_dst)
    print(f"  above-threshold: {above_src.name} -> {above_dst.name}")

    # Below-threshold (msg count): d63cc484-3min-14msg.jsonl (1 user msg)
    below_src1 = fixtures / "d63cc484-3min-14msg.jsonl"
    below_first1 = json.loads(below_src1.read_text().splitlines()[0])
    below_sid1 = below_first1.get("sessionId") or below_first1.get("session_id")
    shutil.copy(below_src1, project_dir / f"{below_sid1}.jsonl")
    print(f"  below-threshold: {below_src1.name} -> {below_sid1}.jsonl")

    # Below-threshold (msg count): 6fa4f267-2min-5msg.jsonl (0 user msgs)
    below_src2 = fixtures / "6fa4f267-2min-5msg.jsonl"
    below_first2 = json.loads(below_src2.read_text().splitlines()[0])
    below_sid2 = below_first2.get("sessionId") or below_first2.get("session_id")
    shutil.copy(below_src2, project_dir / f"{below_sid2}.jsonl")
    print(f"  below-threshold: {below_src2.name} -> {below_sid2}.jsonl")

    # Redirect HOME for all Path.home() calls in the reaper module
    orig_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        # Force re-import to pick up new HOME in Path.home()
        for mod in list(sys.modules.keys()):
            if "obsidian_session_reaper" in mod or "obsidian_utils" in mod or "obsidian_session_log" in mod:
                del sys.modules[mod]

        sys.path.insert(0, str(REPO_ROOT / "hooks"))
        from obsidian_session_reaper import _reap_orphaned_sessions

        # ----------------------------------------------------------------
        _section("First reaper invocation (happy path)")
        out = _reap_orphaned_sessions(
            project=project_name,
            vault_path=str(vault),
            sessions_folder="claude-sessions",
            config=config,
        )
        print(f"  outcome = {out}")

        # A1: above-threshold session was reaped
        _assert(out.reaped >= 1, "at least 1 reaped (d2cc7e46-full)")

        # A2: both below-threshold sessions skipped
        _assert(out.skipped_below_threshold >= 2,
                f">=2 skipped below threshold (got {out.skipped_below_threshold})")

        # A3: no permission block
        _assert(not out.skipped_permission_blocked,
                "no permission block (vault is writable)")

        # A4: no timeout
        _assert(not out.timeout,
                "no timeout (well within budget)")

        # A5: vault note was actually created
        notes = list(sessions.glob("*.md"))
        _assert(len(notes) >= 1, f">=1 vault note written (got {len(notes)})")

        # A6: note has reconstructed: true in frontmatter
        for n in notes:
            content = n.read_text()
            _assert("reconstructed: true" in content,
                    f"{n.name}: reconstructed: true in frontmatter")

        # A7: note has claude/reconstructed tag
        for n in notes:
            content = n.read_text()
            _assert("claude/reconstructed" in content,
                    f"{n.name}: claude/reconstructed tag present")

        # A8: watermark file was written
        wm_path = home / ".claude" / "obsidian-brain" / f"reaper-watermark-{project_name}"
        _assert(wm_path.exists(), "watermark file written after first run")

        # A9: watermark value is positive (> 0)
        wm_val = int(wm_path.read_text().strip())
        _assert(wm_val > 0, f"watermark is positive epoch seconds (got {wm_val})")

        # A10: hook log was written
        log_path = home / ".claude" / "obsidian-brain-hook.log"
        _assert(log_path.exists(), "hook log written after first run")

        # A11: log contains REAPED_OK
        log_text = log_path.read_text()
        _assert("REAPED_OK" in log_text, "REAPED_OK in hook log")

        # A12: log contains SKIPPED_BELOW_THRESHOLD
        _assert("SKIPPED_BELOW_THRESHOLD" in log_text,
                "SKIPPED_BELOW_THRESHOLD in hook log")

        # A13: log contains SUMMARY
        _assert("SUMMARY" in log_text, "SUMMARY in hook log")

        # ----------------------------------------------------------------
        _section("Second reaper invocation (idempotency / watermark advancement)")
        out2 = _reap_orphaned_sessions(
            project=project_name,
            vault_path=str(vault),
            sessions_folder="claude-sessions",
            config=config,
        )
        print(f"  outcome = {out2}")

        # A14: second invocation reaps zero (watermark honored)
        _assert(out2.reaped == 0,
                "second invocation reaps 0 (watermark honored)")

        # A15: second invocation does not re-skip below-threshold entries
        # (they are also past the watermark, so reaped=0, skipped_below=0 or same)
        _assert(out2.skipped_below_threshold <= out.skipped_below_threshold,
                "second run does not inflate below-threshold skips past first run")

        # A16: note count unchanged after second run (no duplicate notes)
        notes2 = list(sessions.glob("*.md"))
        _assert(len(notes2) == len(notes),
                f"note count unchanged after second run (got {len(notes2)}, want {len(notes)})")

        # ----------------------------------------------------------------
        _section("Reaper disabled via config flag (session_hint guard)")
        # The reaper_enabled=False guard lives in obsidian_session_hint.py, not in
        # _reap_orphaned_sessions. Verify the guard is present and the code path
        # skips the reaper import entirely.
        import importlib, inspect
        hint_src = (REPO_ROOT / "hooks" / "obsidian_session_hint.py").read_text()
        _assert('config.get("reaper_enabled", True)' in hint_src,
                "reaper_enabled guard present in obsidian_session_hint.py")
        _assert("_reap_orphaned_sessions" in hint_src or "obsidian_session_reaper" in hint_src,
                "session_hint calls the reaper when enabled")

        # ----------------------------------------------------------------
        _section("Permission canary — vault read-only")
        # Make vault unwritable so the canary fails
        os.chmod(vault, 0o555)  # r-xr-xr-x  (no write)
        try:
            # Add a fresh orphan that passes thresholds so the canary fires
            fresh_sid = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
            shutil.copy(above_src, project_dir / f"{fresh_sid}.jsonl")
            # Remove watermark so this fresh file appears new
            wm_path.unlink(missing_ok=True)

            # Re-import for clean state
            for mod in list(sys.modules.keys()):
                if "obsidian_session_reaper" in mod or "obsidian_utils" in mod or "obsidian_session_log" in mod:
                    del sys.modules[mod]
            from obsidian_session_reaper import _reap_orphaned_sessions as _reap2

            out_perm = _reap2(
                project=project_name,
                vault_path=str(vault),
                sessions_folder="claude-sessions",
                config=config,
            )
            print(f"  outcome = {out_perm}")

            # A18: permission block detected
            _assert(out_perm.skipped_permission_blocked,
                    "canary: skipped_permission_blocked=True when vault not writable")

            # A19: nothing reaped when blocked
            _assert(out_perm.reaped == 0,
                    "canary: reaped == 0 when permission blocked")

        finally:
            os.chmod(vault, 0o755)  # Restore vault permissions
            # Restore watermark for subsequent tests
            (home / ".claude" / "obsidian-brain").mkdir(parents=True, exist_ok=True)

        # ----------------------------------------------------------------
        _section("F2 — write_vault_note errno surfacing")
        # write_vault_note is imported locally inside _reap_orphaned_sessions
        # via 'from obsidian_utils import write_vault_note'.  The reaper lives in
        # hooks/ and imports obsidian_utils without the 'hooks.' prefix, so we
        # must patch the bare 'obsidian_utils' module entry in sys.modules.
        hooks_dir = str(REPO_ROOT / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        import importlib
        import obsidian_utils as bare_utils_mod
        original_write = bare_utils_mod.write_vault_note

        def fake_write_enospc(*a, **kw):
            return "OSError: [Errno 28] No space left on device: /tmp/x.md.tmp"

        bare_utils_mod.write_vault_note = fake_write_enospc
        try:
            # Fresh orphan with unique SID that passes thresholds
            fresh_sid2 = "bbbbcccc-dddd-eeee-ffff-000000000000"
            shutil.copy(above_src, project_dir / f"{fresh_sid2}.jsonl")
            # Remove watermark so all files appear new (including already-processed)
            wm_path2 = home / ".claude" / "obsidian-brain" / f"reaper-watermark-{project_name}"
            wm_path2.unlink(missing_ok=True)
            # Remove existing vault notes so dedupe set is empty
            for n in sessions.glob("*.md"):
                n.unlink()

            # Re-import reaper so it sees the patched bare_utils_mod
            for mod_name in list(sys.modules.keys()):
                if "obsidian_session_reaper" in mod_name or "obsidian_session_log" in mod_name:
                    del sys.modules[mod_name]
            import obsidian_session_reaper as fresh_reaper

            out3 = fresh_reaper._reap_orphaned_sessions(
                project=project_name,
                vault_path=str(vault),
                sessions_folder="claude-sessions",
                config=config,
            )
            log_text2 = (home / ".claude" / "obsidian-brain-hook.log").read_text()

            # A20: WRITE_FAILED logged
            _assert("WRITE_FAILED" in log_text2, "WRITE_FAILED logged to hook log")

            # A21: errno 28 detail propagated to log
            _assert("Errno 28" in log_text2 or "errno 28" in log_text2.lower(),
                    "errno 28 detail in hook log")

            # A22: reaped stays 0 when write fails
            _assert(out3.reaped == 0,
                    "reaped == 0 when write_vault_note simulates ENOSPC")

        finally:
            bare_utils_mod.write_vault_note = original_write

    finally:
        # Restore HOME
        if orig_home is not None:
            os.environ["HOME"] = orig_home
        else:
            del os.environ["HOME"]

        # Cleanup sandbox
        if sentinel.exists():
            shutil.rmtree(sandbox)
            print(f"\nCleaned up {sandbox}")
        else:
            print(f"\nWARNING: sentinel missing — leaving {sandbox} for inspection")

    print(f"\n  All {_PASS_COUNT} assertions passed.")


if __name__ == "__main__":
    main()
