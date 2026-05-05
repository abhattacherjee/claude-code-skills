"""Unit tests for scripts/dev-test/capture-jsonl-fixture.py (#124)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "dev-test" / "capture-jsonl-fixture.py"
_spec = importlib.util.spec_from_file_location("capture_jsonl_fixture", _SCRIPT_PATH)
capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capture)  # type: ignore[union-attr]


def _write_synthetic_jsonl(path: Path, n_records: int, body_bytes_per_record: int = 1024) -> None:
    """Generate an oversize JSONL with `n_records` user/assistant message records."""
    lines = []
    for i in range(n_records):
        lines.append(json.dumps({
            "type": "user" if i % 2 == 0 else "assistant",
            "uuid": f"00000000-0000-0000-0000-{i:012d}",
            "timestamp": f"2026-05-01T00:{i % 60:02d}:00.000Z",
            "cwd": "/Users/abhishek/dev/claude_workspace/obsidian-brain",
            "message": {"role": "user", "content": "x" * body_bytes_per_record},
        }))
    path.write_text("\n".join(lines) + "\n")


def test_truncate_oversize_jsonl_under_budget(tmp_path):
    src = tmp_path / "big.jsonl"
    out = tmp_path / "small.jsonl"
    _write_synthetic_jsonl(src, n_records=200, body_bytes_per_record=1024)
    rc = capture.main(["--source", str(src), "--out", str(out), "--max-bytes", "102400"])
    assert rc == 0
    assert out.exists()
    assert out.stat().st_size <= 102_400
    # Truncation marker present.
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert any(r.get("type") == "truncated" for r in lines)


def test_validate_round_trip_with_read_transcript(tmp_path):
    src = tmp_path / "small.jsonl"
    out = tmp_path / "out.jsonl"
    _write_synthetic_jsonl(src, n_records=20, body_bytes_per_record=64)
    rc = capture.main(["--source", str(src), "--out", str(out)])
    assert rc == 0
    # If validation failed, capture would have unlinked `out`.
    assert out.exists()


def test_invalid_source_aborts_no_output(tmp_path, capsys):
    out = tmp_path / "should-not-exist.jsonl"
    rc = capture.main(["--source", str(tmp_path / "nope.jsonl"), "--out", str(out)])
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "not found" in err.lower() or "cannot read" in err.lower()


def test_source_with_only_partial_flush_aborts(tmp_path, capsys):
    src = tmp_path / "garbage.jsonl"
    out = tmp_path / "out.jsonl"
    src.write_text("not json\n{also not\nlol\n")
    rc = capture.main(["--source", str(src), "--out", str(out)])
    assert rc == 1
    assert not out.exists()
    assert "no valid JSON records" in capsys.readouterr().err


def test_small_source_passthrough(tmp_path):
    src = tmp_path / "tiny.jsonl"
    out = tmp_path / "out.jsonl"
    _write_synthetic_jsonl(src, n_records=5, body_bytes_per_record=32)
    rc = capture.main(["--source", str(src), "--out", str(out), "--head-records", "30", "--tail-records", "30"])
    assert rc == 0
    # Small source: no truncation marker should be added.
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert all(r.get("type") != "truncated" for r in lines)


def test_rename_cwd_rewrites_every_record(tmp_path):
    src = tmp_path / "src.jsonl"
    out = tmp_path / "out.jsonl"
    _write_synthetic_jsonl(src, n_records=10, body_bytes_per_record=64)
    rc = capture.main([
        "--source", str(src), "--out", str(out),
        "--rename-cwd", "/Users/abhishek/dev/claude_workspace/obsidian-brain",
    ])
    assert rc == 0
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    cwds = [r["cwd"] for r in lines if "cwd" in r]
    assert cwds, "expected at least one record with cwd"
    assert all(c == "/Users/abhishek/dev/claude_workspace/obsidian-brain" for c in cwds)
