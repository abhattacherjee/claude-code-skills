#!/usr/bin/env python3
"""
Truncate a real Claude Code session JSONL into a head/tail fixture under a
byte budget, validating that hooks/obsidian_utils parsers still round-trip.

Usage:
    capture-jsonl-fixture.py --source PATH --out PATH
                             [--max-bytes 102400]
                             [--head-records 30]
                             [--tail-records 30]
                             [--rename-cwd PATH]

Exit codes:
    0 = success
    1 = capture aborted (unreadable source, no parseable lines, can't fit
        budget, or round-trip validation failed)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make hooks/obsidian_utils importable when run from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "hooks"))
sys.path.insert(0, str(_REPO_ROOT))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--max-bytes", type=int, default=102_400)
    p.add_argument("--head-records", type=int, default=30)
    p.add_argument("--tail-records", type=int, default=30)
    p.add_argument("--rename-cwd", type=str, default=None)
    return p.parse_args(argv)


def _read_parseable_records(source: Path) -> tuple[list[dict], int]:
    """Return (records, original_byte_count). Drops lines that fail json.loads."""
    if not source.exists():
        raise FileNotFoundError(f"--source not found: {source}")
    raw = source.read_bytes()
    records: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Partial-flush trailing fragments are expected for killed sessions.
            continue
    return records, len(raw)


def _maybe_rewrite_cwd(records: list[dict], new_cwd: str | None) -> list[dict]:
    if not new_cwd:
        return records
    out = []
    for rec in records:
        if "cwd" in rec:
            rec = {**rec, "cwd": new_cwd}
        out.append(rec)
    return out


def _build_truncated(records: list[dict], head: int, tail: int, original_count: int, original_bytes: int) -> list[dict]:
    marker = {
        "type": "truncated",
        "original_records": original_count,
        "original_bytes": original_bytes,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # Clamp tail start so head and tail slices don't overlap (can happen when
    # the byte-budget fallthrough drops us into truncation with head+tail >
    # len(records) — e.g., 40-record source with default head=30/tail=30).
    tail_start = max(head, len(records) - tail)
    return records[:head] + [marker] + records[tail_start:]


def _serialize(records: list[dict]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")


def _validate_round_trip(out: Path) -> None:
    """Import production parsers and ensure they still parse the truncated file."""
    from obsidian_utils import extract_session_metadata, read_transcript  # type: ignore
    msgs = read_transcript(str(out))
    extract_session_metadata(msgs, "/fake/cwd")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        records, original_bytes = _read_parseable_records(args.source)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: cannot read --source {args.source}: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("ERROR: source has no valid JSON records — partial-flush only?", file=sys.stderr)
        return 1

    records = _maybe_rewrite_cwd(records, args.rename_cwd)
    original_count = len(records)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Passthrough only if the file is small in BOTH record count AND serialized
    # bytes. A few-but-very-large records source (e.g., transcripts dominated
    # by attachments) can have count <= head+tail while still exceeding
    # --max-bytes — fall through to truncation in that case.
    if original_count <= args.head_records + args.tail_records:
        passthrough_bytes = _serialize(records)
        if len(passthrough_bytes) <= args.max_bytes:
            args.out.write_bytes(passthrough_bytes)
            print(f"source already small: {original_count} records, {original_bytes} bytes")
            try:
                _validate_round_trip(args.out)
            except Exception as exc:
                args.out.unlink(missing_ok=True)
                print(f"ERROR: validation failed for unchanged passthrough: {exc.__class__.__name__}: {exc}", file=sys.stderr)
                return 1
            return 0
        # Else fall through to truncation loop below.

    head = args.head_records
    tail = args.tail_records
    smallest = None
    for attempt in range(5):
        out_records = _build_truncated(records, head, tail, original_count, original_bytes)
        payload = _serialize(out_records)
        smallest = len(payload) if smallest is None else min(smallest, len(payload))
        if len(payload) <= args.max_bytes:
            args.out.write_bytes(payload)
            try:
                _validate_round_trip(args.out)
            except Exception as exc:
                args.out.unlink(missing_ok=True)
                print(f"ERROR: validation failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
                return 1
            print(
                f"captured {len(out_records)} records, {len(payload)} bytes "
                f"(from {original_count} records / {original_bytes} bytes)"
            )
            return 0
        head = max(1, head // 2)
        tail = max(1, tail // 2)

    print(
        f"ERROR: cannot truncate to {args.max_bytes} bytes; smallest attempt was "
        f"{smallest} bytes — relax --max-bytes or --head-records",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
