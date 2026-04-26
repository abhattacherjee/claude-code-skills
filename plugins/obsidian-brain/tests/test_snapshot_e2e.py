"""End-to-end integration test for the snapshot → /recall pipeline (issue #50).

Exercises the full 5-step cycle with real hook subprocess invocations and
in-process obsidian_utils calls. CI-required.

Pipeline:
    1. obsidian_context_snapshot.py (subprocess) → snapshot note on disk
    2. obsidian_session_log.py     (subprocess) → session note with `snapshots:` back-ref
    3. find_unsummarized_notes()   (in-proc)   → [snapshot, session] in bias-sorted order
    4. upgrade_unsummarized_note() (in-proc, Haiku monkeypatched) → status: summarized
       (exercised for BOTH session and snapshot to cover the generate_summary
       vs generate_snapshot_summary dispatch in upgrade_unsummarized_note)
    5. build_context_brief()       (in-proc)   → nested `↳ HH:MM:SS` row + snapshot_count: 1
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import obsidian_utils  # conftest.py inserts hooks/ onto sys.path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SNAPSHOT = REPO_ROOT / "hooks" / "obsidian_context_snapshot.py"
HOOK_SESSION_LOG = REPO_ROOT / "hooks" / "obsidian_session_log.py"

SID = "e2e-test-session-12345"
PROJECT = "fake-cwd"
SLUG = "fake-cwd"


def _write_config(home_dir: Path, vault_path: Path) -> Path:
    """Write obsidian-brain-config.json pointing at the tmp vault."""
    cfg_dir = home_dir / ".claude"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "vault_path": str(vault_path),
        "sessions_folder": "claude-sessions",
        "insights_folder": "claude-insights",
        "auto_log_enabled": True,
        "snapshot_on_compact": True,
        "snapshot_on_clear": True,
        "min_messages": 0,
        "min_duration_minutes": 0,
        "summary_model": "haiku",
    }
    cfg_path = cfg_dir / "obsidian-brain-config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    cfg_path.chmod(0o600)
    return cfg_path


def _write_transcript(home_dir: Path, slug: str, session_id: str) -> Path:
    """Write a 3-line JSONL transcript fixture under ~/.claude/projects/<slug>/.

    Filename is `{session_id}.jsonl` so that `find_transcript_jsonl()` (which
    globs for `{session_id}.jsonl` under `~/.claude/projects/**/`) discovers
    the fixture and `upgrade_unsummarized_note()` exercises the JSONL source
    branch instead of falling through to the raw-note fallback.
    """
    proj_dir = home_dir / ".claude" / "projects" / slug
    proj_dir.mkdir(parents=True, exist_ok=True)
    transcript = proj_dir / f"{session_id}.jsonl"
    lines = [
        {"type": "user", "message": {"content": "Fix the snapshot pipeline."}},
        {"type": "assistant", "message": {"content": "Writing the test now."}},
        {"type": "user", "message": {"content": "Looks good — ship it."}},
    ]
    transcript.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    return transcript


def _write_path_shim(bin_dir: Path) -> Path:
    """Write a `claude` PATH shim emitting a canned summary on any call.

    Defense-in-depth for **hook subprocesses**: neither production hook calls
    `claude -p` (summarization is deferred to /recall), so this shim is never
    hit in the hot path — but if a hook ever regresses to shelling out, this
    keeps the subprocess leg hermetic. In-process `claude -p` calls made by
    obsidian_utils (e.g. inside `upgrade_unsummarized_note`) are intercepted
    separately by the monkeypatch on `obsidian_utils.subprocess.run` installed
    in Stage 4 — not by this shim.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'EOF'\n"
        "## Summary\n"
        "Canned E2E summary from PATH shim.\n"
        "\n"
        "## Key Decisions\n"
        "- None noted.\n"
        "\n"
        "## Changes Made\n"
        "- None noted.\n"
        "\n"
        "## Errors Encountered\n"
        "- None.\n"
        "\n"
        "## Open Questions / Next Steps\n"
        "- None.\n"
        "\n"
        "IMPORTANCE: 5\n"
        "EOF\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _hook_env(tmp_path: Path) -> dict:
    """Env dict for subprocess hook invocations.

    Sandboxes HOME (config lookups, `~/.claude/projects/` transcript search,
    default vault DB path all route into `tmp_path/home`), prepends the
    `tmp_path/bin` PATH shim, and sets PYTHONPATH so the hook can import the
    in-tree `obsidian_utils`.
    """
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = f"{REPO_ROOT / 'hooks'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_snapshot_e2e_pipeline(tmp_path, monkeypatch):
    """Fire both hooks, then walk the in-process pipeline, asserting at every boundary."""

    # --- Stage 0: fixtures ---
    vault = tmp_path / "vault"
    sessions_dir = vault / "claude-sessions"
    insights_dir = vault / "claude-insights"
    sessions_dir.mkdir(parents=True)
    insights_dir.mkdir(parents=True)

    home = tmp_path / "home"
    _write_config(home, vault)
    transcript = _write_transcript(home, SLUG, SID)
    _write_path_shim(tmp_path / "bin")

    # Redirect HOME for in-process calls so any indirect Path.home() lookup
    # (e.g. default ensure_index db path) resolves into the sandbox.
    monkeypatch.setenv("HOME", str(home))

    # --- Stage 1: fire the snapshot hook ---
    snapshot_payload = {
        "session_id": SID,
        "cwd": str(tmp_path / "fake-cwd"),
        "transcript_path": str(transcript),
        "source": "compact",
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_SNAPSHOT)],
        input=json.dumps(snapshot_payload),
        env=_hook_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        pytest.fail(f"snapshot hook exit={proc.returncode}\nstderr:\n{proc.stderr}")

    snapshot_files = sorted(sessions_dir.glob("*-snapshot-*.md"))
    assert len(snapshot_files) == 1, (
        f"expected exactly 1 snapshot file, got {len(snapshot_files)}: "
        f"{[f.name for f in snapshot_files]}\nhook stderr:\n{proc.stderr}"
    )
    snapshot_path = snapshot_files[0]

    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    assert "type: claude-snapshot" in snapshot_text
    assert f"session_id: {SID}" in snapshot_text
    assert f"project: {PROJECT}" in snapshot_text
    assert "status: auto-logged" in snapshot_text
    assert "trigger: compact" in snapshot_text
    assert "# Context Snapshot:" in snapshot_text

    # --- Stage 2: fire the session-log hook ---
    session_payload = {
        "session_id": SID,
        "cwd": str(tmp_path / "fake-cwd"),
        "transcript_path": str(transcript),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_SESSION_LOG)],
        input=json.dumps(session_payload),
        env=_hook_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        pytest.fail(f"session-log hook exit={proc.returncode}\nstderr:\n{proc.stderr}")

    session_files = [
        f for f in sessions_dir.glob("*.md")
        if "-snapshot-" not in f.name
    ]
    assert len(session_files) == 1, (
        f"expected exactly 1 session file, got {len(session_files)}: "
        f"{[f.name for f in session_files]}\nhook stderr:\n{proc.stderr}"
    )
    session_path = session_files[0]

    session_text = session_path.read_text(encoding="utf-8")
    assert "type: claude-session" in session_text
    assert f"session_id: {SID}" in session_text
    assert "status: auto-logged" in session_text

    # Back-reference check: the snapshot wikilink must live INSIDE the
    # session note's frontmatter `snapshots:` YAML list — not merely somewhere
    # in the body (which would slip past if, e.g., the wikilink leaked into a
    # rendered summary while the YAML list was silently emptied).
    fm_end = session_text.index("\n---", 3)
    frontmatter = session_text[:fm_end]
    snapshot_stem = snapshot_path.stem
    assert re.search(r"^snapshots:", frontmatter, re.MULTILINE), (
        "session note frontmatter missing `snapshots:` YAML key"
    )
    # Producer format at hooks/obsidian_session_log.py:97-98 is
    # `  - "[[<stem>]]"` (two-space indent, hyphen, quoted wikilink).
    assert f'  - "[[{snapshot_stem}]]"' in frontmatter, (
        f'expected `  - "[[{snapshot_stem}]]"` under `snapshots:` in '
        f"frontmatter:\n{frontmatter}"
    )

    # --- Stage 3: find_unsummarized_notes returns both session + snapshot ---
    result = json.loads(
        obsidian_utils.find_unsummarized_notes(
            str(vault), "claude-sessions", PROJECT
        )
    )
    assert result["auto_fixed"] == 0, (
        f"unexpected auto-fix on fresh notes: {result}"
    )
    # Order is load-bearing for /recall cohesion: snapshots must sort before
    # their parent session within the same session_id group so /recall
    # presents chronologically correct context. find_unsummarized_notes
    # enforces that via an explicit type-bias key (see obsidian_utils.py
    # `_bias_key` at lines 1682-1699 — snapshots get rank 0, sessions rank 1
    # within a session_id group), NOT via a reverse-lexicographic filename
    # trick on the outer sort.
    assert result["unsummarized"] == [str(snapshot_path), str(session_path)], (
        f"expected [snapshot, session] order, got: {result['unsummarized']}"
    )

    # --- Stage 4: upgrade_unsummarized_note (Haiku monkeypatched) ---
    CANNED_SUMMARY = (
        "## Summary\n"
        "E2E test session exercising the snapshot integration pipeline.\n"
        "\n"
        "## Key Decisions\n"
        "- None noted.\n"
        "\n"
        "## Changes Made\n"
        "- None noted.\n"
        "\n"
        "## Errors Encountered\n"
        "- None.\n"
        "\n"
        "## Open Questions / Next Steps\n"
        "- None.\n"
        "\n"
        "IMPORTANCE: 5\n"
    )
    _real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        # Intercept `claude -p ...`; delegate everything else.
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 \
                and cmd[0] == "claude" and cmd[1] == "-p":
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=CANNED_SUMMARY, stderr=""
            )
        return _real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("obsidian_utils.subprocess.run", fake_run)

    status = obsidian_utils.upgrade_unsummarized_note(
        str(session_path), str(vault), "claude-sessions", PROJECT
    )
    assert status.startswith("Upgraded "), (
        f"upgrade_unsummarized_note did not succeed: {status!r}"
    )

    session_text_after = session_path.read_text(encoding="utf-8")
    assert "status: summarized" in session_text_after, (
        f"expected status: summarized after upgrade, got:\n{session_text_after[:2000]}"
    )
    # Summary body present (find the section header and at least one char of content).
    summary_match = re.search(
        r"^## Summary\n(.+?)(?=\n^## |\Z)",
        session_text_after,
        re.MULTILINE | re.DOTALL,
    )
    assert summary_match and summary_match.group(1).strip(), (
        "expected non-empty `## Summary` section after upgrade"
    )

    # Also upgrade the SNAPSHOT note. upgrade_unsummarized_note dispatches
    # snapshots through generate_snapshot_summary (a distinct code path from
    # the generate_summary used for sessions above). Without this, the
    # snapshot-type routing branch is never exercised by the E2E test.
    snap_status = obsidian_utils.upgrade_unsummarized_note(
        str(snapshot_path), str(vault), "claude-sessions", PROJECT
    )
    assert snap_status.startswith("Upgraded "), (
        f"upgrade_unsummarized_note on snapshot did not succeed: {snap_status!r}"
    )
    snapshot_text_after = snapshot_path.read_text(encoding="utf-8")
    assert "status: summarized" in snapshot_text_after, (
        f"expected snapshot `status: summarized` after upgrade, got:\n"
        f"{snapshot_text_after[:2000]}"
    )

    # --- Stage 5: build_context_brief nested row + snapshot_count ---
    brief = obsidian_utils.build_context_brief(
        str(vault), "claude-sessions", "claude-insights", PROJECT,
        hook_status_line="[OK] test",
    )

    # Parse delimited sections.
    def _section(label: str) -> str:
        m = re.search(
            rf"<<<{label}>>>\n(.*?)(?=\n<<<[A-Z_]+>>>|\Z)",
            brief,
            re.DOTALL,
        )
        assert m, f"missing section <<<{label}>>> in brief:\n{brief[:2000]}"
        return m.group(1)

    context_brief_section = _section("OB_CONTEXT_BRIEF")
    load_manifest_section = _section("OB_LOAD_MANIFEST")
    most_recent_path = _section("OB_MOST_RECENT_SESSION_PATH").strip()

    # Extract the 6-digit HHMMSS tail from our snapshot's stem. The same
    # value is used both (a) to match the nested `↳ HH:MM:SS` row in the
    # context-brief table and (b) to match the `snapshot: [HHMMSS]` line in
    # LOAD_MANIFEST. Tying both assertions to the SAME stem-derived value
    # catches cross-session contamination that a shape-only regex would miss.
    stem_hhmmss_match = re.search(r"-snapshot-(\d{6})$", snapshot_path.stem)
    assert stem_hhmmss_match, (
        f"snapshot stem missing trailing -snapshot-HHMMSS: {snapshot_path.stem}"
    )
    hhmmss = stem_hhmmss_match.group(1)  # e.g. "075610"
    hhmmss_pretty = f"{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"  # "07:56:10"

    # Cross-midnight guard: build_context_brief() looks up snapshots via
    # fetch_snapshot_summaries(note_date), which in turn calls
    # find_snapshots_for_session() to glob `{date}-{slug}-*-snapshot*.md`.
    # If Stage 1 (snapshot hook) and Stage 2 (session-log hook) straddle a
    # calendar day boundary, the two files get different date prefixes and
    # the snapshot is legitimately excluded from the session's lookup. Keep
    # the strong assertions for the (overwhelmingly common) same-date case
    # and avoid a wall-clock flake in the ~100ms-per-year straddle window.
    snapshot_date_prefix = snapshot_path.stem.split("-snapshot-", 1)[0][:10]
    session_date_prefix = session_path.stem[:10]
    if snapshot_date_prefix == session_date_prefix:
        # Nested snapshot row: exact `↳ HH:MM:SS` match against OUR snapshot's
        # timestamp. Rendered inside a markdown table cell at
        # obsidian_utils.py:1881 (`|   | ↳ {hhmmss_pretty} | ...`), so the
        # glyph sits mid-cell after `|   | ` — no `^` line anchor.
        assert f"↳ {hhmmss_pretty}" in context_brief_section, (
            f"expected nested snapshot row `↳ {hhmmss_pretty}` in context brief:\n"
            f"{context_brief_section[:2000]}"
        )

        assert re.search(
            r"^snapshot_count:\s*1\b", load_manifest_section, re.MULTILINE
        ), (
            f"expected `snapshot_count: 1` in LOAD_MANIFEST:\n{load_manifest_section}"
        )

        # Producer at obsidian_utils.py:2091 emits
        # `snapshot: [{hhmmss}] ({trigger}) {summary}` in build_context_brief's
        # LOAD_MANIFEST composition — the full filename stem never appears on
        # the line, only the HHMMSS tail. Match on that unique substring.
        assert re.search(
            rf"^snapshot:\s*\[{hhmmss}\]",
            load_manifest_section,
            re.MULTILINE,
        ), (
            f"expected `snapshot: [{hhmmss}]` line in LOAD_MANIFEST "
            f"(stem={snapshot_path.stem}):\n{load_manifest_section}"
        )
    else:
        # Straddled midnight — degraded assertion: just verify the snapshot
        # still exists on disk (the production code path for cross-midnight
        # is tracked as follow-up #68/#70 and is out of scope for this test).
        assert snapshot_path.exists(), (
            "snapshot note missing after cross-midnight straddle: "
            f"snapshot_date={snapshot_date_prefix}, "
            f"session_date={session_date_prefix}"
        )

    assert most_recent_path == str(session_path), (
        f"expected MOST_RECENT_SESSION_PATH={session_path}, got={most_recent_path}"
    )
