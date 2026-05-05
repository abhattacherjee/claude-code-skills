"""Subprocess + in-process tests for scripts/dev-test/replay-sessionend.py (#124).

Test isolation strategy (3 layers):
1. HOME redirection — every test sets HOME=tmp_path; the replay CLI's hook log,
   config, and projects/ all resolve under tmp_path via os.path.expanduser.
2. _REAL_VAULT_GUARD env sentinel — replay CLI refuses to run if the resolved
   vault path is under ~/obsidian/. Catches the case where HOME redirection
   silently fails.
3. --dry-run — patches write_vault_note to record (path, len) tuples instead
   of writing. Used in --mode reaper tests where reaper would otherwise
   produce notes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPLAY_SCRIPT = _REPO_ROOT / "scripts" / "dev-test" / "replay-sessionend.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "dropped-sessions"

# Import the script as a module (filename has hyphens).
_spec = importlib.util.spec_from_file_location("replay_sessionend", _REPLAY_SCRIPT)
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)  # type: ignore[union-attr]


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect $HOME to tmp_path with synthetic obsidian-brain config + vault."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("_REAL_VAULT_GUARD", "1")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config = {
        "vault_path": str(tmp_path / "vault"),
        "sessions_folder": "sessions",
        "insights_folder": "insights",
        "dashboards_folder": "dashboards",
        "min_messages": 3,
        "min_duration_minutes": 2,
        "summary_model": "haiku",
        "auto_log_enabled": True,
        "snapshot_on_compact": True,
        "snapshot_on_clear": True,
    }
    (claude_dir / "obsidian-brain-config.json").write_text(json.dumps(config))
    (tmp_path / "vault" / "sessions").mkdir(parents=True)
    (tmp_path / "vault" / "insights").mkdir(parents=True)
    return tmp_path


def _run_cli(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(_REPLAY_SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=str(_REPO_ROOT),
    )


# -------------------- TestReplayCliArgparse --------------------

class TestReplayCliArgparse:
    def test_missing_jsonl(self):
        result = _run_cli("--cwd", "/fake")
        assert result.returncode == 2
        assert "--jsonl" in result.stderr

    def test_invalid_mode(self):
        result = _run_cli(
            "--jsonl", str(_FIXTURES / "d63cc484-3min-14msg.jsonl"),
            "--cwd", "/fake",
            "--mode", "bogus",
        )
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower() or "bogus" in result.stderr

    def test_help_renders(self):
        result = _run_cli("--help")
        assert result.returncode == 0
        assert "--jsonl" in result.stdout
        assert "--mode" in result.stdout

    def test_dry_run_does_not_touch_disk(self, isolated_home):
        result = _run_cli(
            "--jsonl", str(_FIXTURES / "d63cc484-3min-14msg.jsonl"),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--dry-run",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        # vault_writes is a list (possibly empty); no real session note files.
        assert isinstance(out["vault_writes"], list)
        sessions_dir = isolated_home / "vault" / "sessions"
        assert not list(sessions_dir.glob("*.md"))

    def test_jsonl_path_does_not_exist(self, isolated_home, tmp_path):
        """Guard at _run_sessionend line ~174: --jsonl provided but file missing."""
        result = _run_cli(
            "--jsonl", str(tmp_path / "nonexistent.jsonl"),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()


# -------------------- TestReplayCliCaptureAlgorithm --------------------

class TestReplayCliCaptureAlgorithm:
    """Exercise the truncation halving loop and NO_LOG_LINE_EMITTED sentinel."""

    def test_halving_loop_actually_executes(self, tmp_path):
        """Construct a fixture that requires at least one halving iteration."""
        # Import capture script as module.
        capture_path = _REPO_ROOT / "scripts" / "dev-test" / "capture-jsonl-fixture.py"
        spec = importlib.util.spec_from_file_location("capture_jsonl_fixture", capture_path)
        capture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(capture)  # type: ignore[union-attr]

        # 100 records × 4 KB body bypasses small-source passthrough (head+tail=60).
        # max_bytes=10240 forces several halvings: head/tail starts at 30 → 15 →
        # 7 → 3 → 1; iter 4 (1+marker+1 ≈ 9 KB) fits under 10 KB.
        src = tmp_path / "big.jsonl"
        out = tmp_path / "small.jsonl"
        records = []
        for i in range(100):
            records.append(json.dumps({
                "type": "user" if i % 2 == 0 else "assistant",
                "uuid": f"00000000-0000-0000-0000-{i:012d}",
                "timestamp": f"2026-05-01T00:{i % 60:02d}:00.000Z",
                "cwd": "/fake/cwd",
                "message": {"role": "user", "content": "x" * 4096},
            }))
        src.write_text("\n".join(records) + "\n")
        rc = capture.main(["--source", str(src), "--out", str(out), "--max-bytes", "10240"])
        assert rc == 0, "halving loop should converge"
        assert out.stat().st_size <= 10240
        # Verify halving actually happened: output has fewer than 30+30+1 records.
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) < 61, f"expected halved output (<61 records), got {len(lines)}"

    def test_no_log_line_emitted_sentinel(self, isolated_home):
        """If _run() returns without writing to the hook log, CLI emits the sentinel.

        Reproduce by passing a transcript_path that's parsed-but-empty: the cwd
        gets a slug, fixture is staged, _run() reads stdin, but if auto_log is
        OFF the hook's universal-emit guarantee from #123 should still emit
        a SKIPPED_AUTO_LOG_OFF line. This test is the negative — we use a config
        with auto_log OFF and assert outcome is SKIPPED_AUTO_LOG_OFF (not the
        NO_LOG_LINE_EMITTED sentinel) which proves the universal-emit invariant
        from #123 holds. If #123 ever regresses, this test will flip to
        NO_LOG_LINE_EMITTED and surface the regression loudly.
        """
        # Rewrite config with auto_log_enabled=False
        config_path = isolated_home / ".claude" / "obsidian-brain-config.json"
        cfg = json.loads(config_path.read_text())
        cfg["auto_log_enabled"] = False
        config_path.write_text(json.dumps(cfg))

        result = _run_cli(
            "--jsonl", str(_FIXTURES / "d63cc484-3min-14msg.jsonl"),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        # #123 universal-emit means we get a real outcome, NOT the sentinel.
        assert out["outcome"] == "SKIPPED_AUTO_LOG_OFF", (
            f"expected SKIPPED_AUTO_LOG_OFF (proves #123 universal-emit holds), "
            f"got {out['outcome']!r}. If this is NO_LOG_LINE_EMITTED, #123 regressed."
        )

    def test_dry_run_intercepts_write_vault_note_call(self, isolated_home, tmp_path):
        """Behavioral test for --dry-run: synthesize a fixture that passes thresholds,
        assert vault_writes is non-empty AND no .md file lands on disk.

        Closes the AC3 coverage gap: all 5 H1/H2 fixtures hit
        SKIPPED_BELOW_THRESHOLD before reaching write_vault_note, so the
        dry-run patch (whose 4-arg signature was silently broken until
        Copilot R2) was previously unprotected against regressions.
        """
        # Build a JSONL with 5 user messages spanning 5 minutes (passes
        # min_messages: 3 + min_duration_minutes: 2 thresholds).
        fixture = tmp_path / "synthetic-write-path.jsonl"
        records = []
        for i in range(5):
            records.append(json.dumps({
                "type": "user",
                "uuid": f"00000000-0000-0000-0000-{i:012d}",
                "timestamp": f"2026-05-01T00:{i * 2:02d}:00.000Z",
                "cwd": "/Users/abhishek/dev/claude_workspace/obsidian-brain",
                "message": {"role": "user", "content": f"user message {i} " * 50},
            }))
            records.append(json.dumps({
                "type": "assistant",
                "uuid": f"11111111-1111-1111-1111-{i:012d}",
                "timestamp": f"2026-05-01T00:{i * 2:02d}:30.000Z",
                "cwd": "/Users/abhishek/dev/claude_workspace/obsidian-brain",
                "message": {"role": "assistant", "content": f"reply {i} " * 50},
            }))
        fixture.write_text("\n".join(records) + "\n")

        result = _run_cli(
            "--jsonl", str(fixture),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--dry-run",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        # The fixture should pass thresholds and reach write_vault_note.
        # Regression guard (R2 fix): _record_call must return None, not True.
        # Returning True falsely triggers WRITE_FAILED under Optional[str] contract
        # (caller checks `if write_err is not None:`).
        assert out["outcome"] == "OK_RAW_NOTE_ONLY", (
            f"expected OK_RAW_NOTE_ONLY from dry-run with healthy fixture, "
            f"got outcome={out['outcome']!r}. "
            f"If WRITE_FAILED: _record_call in replay-sessionend.py returned True "
            f"instead of None (truthy triggers write-error path). "
            f"hook_log_line={out.get('hook_log_line')!r}"
        )
        # Dry-run should record the call with correct (path, len) tuple.
        assert len(out["vault_writes"]) >= 1, (
            f"expected dry-run to record at least one write_vault_note call; "
            f"if 0, the patch isn't intercepting (regression in dual-namespace patching)"
        )
        # Path should look like vault/sessions/<filename>.md
        recorded_path, recorded_len = out["vault_writes"][0]
        assert "/sessions/" in recorded_path and recorded_path.endswith(".md"), (
            f"recorded path malformed: {recorded_path!r} — _record_call signature regression?"
        )
        assert recorded_len > 100, (
            f"recorded content length {recorded_len} too small — likely captured "
            f"len(folder_string) instead of len(content) (the bug Copilot R2 caught)"
        )
        # And no real .md file written to disk.
        sessions_dir = isolated_home / "vault" / "sessions"
        assert not list(sessions_dir.glob("*.md")), (
            f"--dry-run should not touch disk; found: {list(sessions_dir.glob('*.md'))}"
        )


# -------------------- TestReplayCliSessionEnd --------------------

class TestReplayCliSessionEnd:
    """
    Current-state regression guard for the 3 H1/H2 sessionend-mode fixtures.

    All 3 truncated fixtures produce SKIPPED_BELOW_THRESHOLD because head/tail
    truncation drops most user-type records (preserves metadata, not density).
    The post-F1 xfail-strict design from the original spec was dropped:
    F1's "final-flush re-read" can't recover messages from a fixture that's
    already a frozen snapshot. The current-state tests serve as the regression
    guard; #125 will revisit if its F1 fix changes how fixtures behave.
    """

    @pytest.mark.parametrize("fixture,expected_msgs", [
        ("d63cc484-3min-14msg.jsonl", "1"),
        ("6fa4f267-2min-5msg.jsonl", "0"),
        ("d2cc7e46-long-617min.jsonl", "1"),
    ])
    def test_sessionend_fixture_skipped_below_threshold(
        self, isolated_home, fixture, expected_msgs
    ):
        result = _run_cli(
            "--jsonl", str(_FIXTURES / fixture),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["outcome"] == "SKIPPED_BELOW_THRESHOLD", (
            f"expected SKIPPED_BELOW_THRESHOLD, got {out['outcome']!r}. "
            f"hook_log_line: {out.get('hook_log_line')!r}"
        )
        assert out["msgs"] == expected_msgs


# -------------------- TestReplayCliReaper --------------------

# The 5 truncated fixtures all produce SKIPPED_BELOW_THRESHOLD because head+tail
# truncation drops message density below min_messages=3.  d2cc7e46-long-617min-full
# is a density-preserving subset of the same source (lines 0..66 + last, tool_result
# bodies scrubbed, attachment blobs stubbed) that retains 3 real user-text messages
# and the full 1841-minute duration — so the reaper reaches the write path (REAPED_OK).
# That case provides the only coverage of the reaper success path in this suite.
REAPER_FIXTURES = [
    # REAPED_OK: above-threshold subset of d2cc7e46 source (3 user msgs, 1841 min)
    ("d2cc7e46-long-617min-full.jsonl", "REAPED_OK"),
    # SKIPPED_BELOW_THRESHOLD: truncated fixtures, all below min_messages threshold
    ("d2cc7e46-long-617min.jsonl", "SKIPPED_BELOW_THRESHOLD"),
    ("d63cc484-3min-14msg.jsonl", "SKIPPED_BELOW_THRESHOLD"),
    ("6fa4f267-2min-5msg.jsonl", "SKIPPED_BELOW_THRESHOLD"),
]


class TestReplayCliReaper:
    """
    F3 (#125): --mode reaper plumbing smoke tests.
    Verifies exit 0, JSON output, and correct outcome field per fixture.
    """

    @pytest.mark.parametrize("fixture_name,expected_event", REAPER_FIXTURES)
    def test_replay_cli_reaper_mode(self, isolated_home, fixture_name, expected_event):
        """Drive replay-sessionend.py in reaper mode against each fixture."""
        fixture = _FIXTURES / fixture_name
        assert fixture.exists()

        result = _run_cli(
            "--jsonl", str(fixture),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--mode", "reaper",
            "--dry-run",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out_lines = [ln for ln in result.stdout.strip().splitlines() if ln.startswith("{")]
        assert out_lines, f"no JSON line in stdout: {result.stdout!r}"
        outcome = json.loads(out_lines[-1])
        # The reaper mode emits its own outcome shape — check that the expected
        # event appears either as the outcome key or anywhere in the dict string.
        assert expected_event in str(outcome), (
            f"expected {expected_event!r} in reaper output; got: {outcome!r}"
        )


# -------------------- TestFixtureIntegrity --------------------

class TestFixtureIntegrity:
    def test_all_committed_fixtures_parse_with_read_transcript(self):
        """Every committed fixture must round-trip through production parsers."""
        hooks_dir = _REPO_ROOT / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from obsidian_utils import extract_session_metadata, read_transcript  # type: ignore

        fixtures = sorted(_FIXTURES.glob("*.jsonl"))
        assert len(fixtures) == 6, f"expected 6 fixtures, found {len(fixtures)}: {fixtures}"
        for fixture in fixtures:
            msgs = read_transcript(str(fixture))
            meta = extract_session_metadata(msgs, "/fake/cwd")
            assert isinstance(msgs, list), f"{fixture.name}: read_transcript returned non-list"
            assert "session_start" in meta or "duration_minutes" in meta, \
                f"{fixture.name}: metadata missing session_start/duration_minutes"
            assert fixture.stat().st_size <= 102_400, \
                f"{fixture.name} is {fixture.stat().st_size} bytes (>100 KB cap)"


# -------------------- TestReaperSessionsFolderDefault (N10) --------------------


class TestReaperSessionsFolderDefault:
    """N10 (R5): _run_reaper() sessions_folder default must be 'claude-sessions',
    matching obsidian_utils._DEFAULTS['sessions_folder'], not the old wrong 'sessions'.
    """

    def test_reaper_sessions_folder_default_is_claude_sessions(self, isolated_home):
        """Config without sessions_folder key: reaper must use 'claude-sessions' as default.

        Verify by writing the REAPED_OK fixture into the isolated HOME so the reaper
        can find it, then running in --dry-run mode and asserting the recorded path
        contains 'claude-sessions', not 'sessions'.
        """
        # The isolated_home fixture writes sessions_folder="sessions" (the old wrong default).
        # Remove it from the config so the script's fallback default kicks in.
        config_path = isolated_home / ".claude" / "obsidian-brain-config.json"
        cfg = json.loads(config_path.read_text())
        del cfg["sessions_folder"]
        config_path.write_text(json.dumps(cfg))

        # Create the claude-sessions dir so the reaper can write (it's expected by the
        # production flow; --dry-run patches write_vault_note but the dir must exist for
        # _permission_canary to succeed).
        (isolated_home / "vault" / "claude-sessions").mkdir(parents=True, exist_ok=True)

        fixture = _FIXTURES / "d2cc7e46-long-617min-full.jsonl"

        result = _run_cli(
            "--jsonl", str(fixture),
            "--cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "--mode", "reaper",
            "--dry-run",
            "--json",
            env_extra={"HOME": str(isolated_home), "_REAL_VAULT_GUARD": "1"},
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out_lines = [ln for ln in result.stdout.strip().splitlines() if ln.startswith("{")]
        assert out_lines, f"no JSON line in stdout: {result.stdout!r}"
        outcome = json.loads(out_lines[-1])

        # The REAPED_OK fixture should produce a vault_writes entry with the right folder.
        vault_writes = outcome.get("vault_writes", [])
        assert vault_writes, (
            f"Expected at least one vault_writes entry from REAPED_OK fixture; "
            f"outcome: {outcome!r}. N10: if sessions_folder default is wrong, the "
            f"dedupe lookup targets the wrong folder and may still write."
        )
        recorded_path = vault_writes[0][0]
        assert "/claude-sessions/" in recorded_path, (
            f"Expected recorded path to contain '/claude-sessions/' (correct default); "
            f"got {recorded_path!r}. N10 regression: default was 'sessions' not 'claude-sessions'."
        )
