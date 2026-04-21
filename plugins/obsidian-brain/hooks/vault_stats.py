"""Vault statistics module — compute aggregate stats from the vault index DB.

Single entry point: compute_stats(db_path, project) -> JSON string.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter

import vault_index


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _importance_bucket(importance: int) -> str:
    """Map importance score to distribution bucket."""
    if importance <= 3:
        return "trivial"
    if importance <= 6:
        return "standard"
    if importance <= 8:
        return "significant"
    return "critical"


def _enrich_top_accessed(
    conn: sqlite3.Connection,
    db_path: str,
    rows: list,
) -> list[dict]:
    """Build enriched top-accessed list from ranked query rows.

    Each row must have (note_path, cnt) columns.  Returns a list of dicts
    with path, basename, accesses, activation, and importance.
    """
    paths = [r[0] for r in rows]
    counts = {r[0]: r[1] for r in rows}
    activations = vault_index.batch_activations(db_path, paths)

    importance_map: dict[str, int] = {}
    if paths:
        placeholders = ",".join("?" for _ in paths)
        for r in conn.execute(
            f"SELECT path, COALESCE(importance, 5) FROM notes "
            f"WHERE path IN ({placeholders})",
            paths,
        ).fetchall():
            importance_map[r[0]] = r[1]

    return [
        {
            "path": p,
            "basename": os.path.basename(p),
            "accesses": counts[p],
            "activation": round(activations.get(p, 0.0), 4),
            "importance": importance_map.get(p, 5),
        }
        for p in paths
    ]


def _handle_error(label: str, exc: Exception) -> str:
    """Log error to stderr and return JSON error payload."""
    print(f"[vault-stats] {label}: {exc}", file=sys.stderr)
    return json.dumps({"error": f"{label}: {exc}"})


_KNOWN_TRIGGERS = {"compact", "clear", "auto"}


def _snapshot_stats(conn: sqlite3.Connection) -> dict:
    """Compute snapshot trigger breakdown + integrity counters.

    Returns zero-state when no snapshots exist.  Orphan detection reads
    session frontmatter directly because session_id isn't indexed as a
    column; broken-backlink detection uses the already-indexed source_note.
    Unknown trigger values are counted under 'auto' rather than growing
    the by_trigger dict with unexpected keys.
    """
    snap_rows = conn.execute(
        "SELECT path, source_note, status FROM notes WHERE type = 'claude-snapshot'"
    ).fetchall()
    total = len(snap_rows)
    if total == 0:
        return {
            "total_snapshots": 0,
            "by_trigger": {"compact": 0, "clear": 0, "auto": 0},
            "sessions_with_snapshots": 0,
            "max_snapshots_per_session": 0,
            "orphaned_snapshots": 0,
            "broken_backlinks": 0,
            "read_errors": 0,
            "summarized_fraction": 1.0,
        }

    # Build session_id set from session note frontmatters.
    # Unreadable sessions can cause false-positive orphan flags on their
    # children, so log them loudly rather than dropping silently.
    session_ids: set[str] = set()
    for (sp,) in conn.execute(
        "SELECT path FROM notes WHERE type = 'claude-session'"
    ).fetchall():
        try:
            with open(sp, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2048)
        except OSError as exc:
            print(f"[vault-stats] skipping unreadable session note {sp!r}: {exc}",
                  file=sys.stderr)
            continue
        m = re.search(r"^session_id:\s*(.+)$", head, re.MULTILINE)
        if m:
            session_ids.add(m.group(1).strip().strip('"').strip("'"))

    per_session: Counter = Counter()
    orphaned = 0
    broken_backlinks = 0
    by_trigger: dict[str, int] = {"compact": 0, "clear": 0, "auto": 0}
    summarized = 0

    read_errors = 0
    for path, source_note, status in snap_rows:
        # Status comes from the indexed notes row, so it is usable even when
        # the on-disk file is unreadable at stats-compute time. Count it up
        # front so summarized_fraction stays truthful for operators whose
        # vaults contain transient file-permission blips. Copilot PR #43
        # round 2 finding.
        if status == "summarized":
            summarized += 1

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2048)
        except OSError as exc:
            # An unreadable snapshot is an integrity failure, not a phantom row.
            # Log it and count so `sum(by_trigger) + read_errors == total` holds.
            print(f"[vault-stats] skipping unreadable snapshot {path!r}: {exc}",
                  file=sys.stderr)
            read_errors += 1
            continue
        tm = re.search(r"^trigger:\s*(\w+)", head, re.MULTILINE)
        # Missing `trigger:` and unknown values both fold into 'auto' —
        # previously defaulted to 'compact' which inflated that bucket with
        # legacy/malformed snapshots (Copilot PR #43 finding).
        trigger = tm.group(1) if tm else "auto"
        if trigger not in _KNOWN_TRIGGERS:
            trigger = "auto"
        by_trigger[trigger] += 1

        sid_m = re.search(r"^session_id:\s*(.+)$", head, re.MULTILINE)
        sid = sid_m.group(1).strip().strip('"').strip("'") if sid_m else ""
        if sid:
            per_session[sid] += 1
            if sid not in session_ids:
                orphaned += 1

        if source_note:
            row = conn.execute(
                "SELECT 1 FROM notes WHERE type = 'claude-session' AND path LIKE ? LIMIT 1",
                (f"%/{source_note}.md",),
            ).fetchone()
            if not row:
                broken_backlinks += 1

    return {
        "total_snapshots": total,
        "by_trigger": by_trigger,
        "sessions_with_snapshots": len(per_session),
        "max_snapshots_per_session": max(per_session.values()) if per_session else 0,
        "orphaned_snapshots": orphaned,
        "broken_backlinks": broken_backlinks,
        "read_errors": read_errors,
        "summarized_fraction": round(summarized / total, 3) if total else 1.0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_stats(db_path: str, project: str) -> str:
    """Compute vault-wide and project-scoped statistics.

    Returns a JSON string with two top-level keys: vault_wide and project.
    On error, returns {"error": "..."}.
    """
    if not os.path.exists(db_path):
        return json.dumps({"error": f"DB not found: {db_path}"})

    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except (sqlite3.Error, OSError) as exc:
        if conn is not None:
            conn.close()
        return _handle_error("DB open error", exc)

    try:
        return _compute_stats_inner(conn, db_path, project)
    except (sqlite3.Error, OSError) as exc:
        return _handle_error("DB error", exc)
    finally:
        conn.close()


def _compute_stats_inner(conn: sqlite3.Connection, db_path: str, project: str) -> str:
    """Core stats computation using an open connection."""
    now = time.time()
    thirty_days_ago = now - 30 * 86400
    seven_days_ago = now - 7 * 86400

    # --- vault_wide ---

    total_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    try:
        db_size_bytes = os.path.getsize(db_path)
    except OSError:
        db_size_bytes = 0
    access_log_entries = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]

    # Oldest access
    row = conn.execute("SELECT MIN(timestamp) FROM access_log").fetchone()
    oldest_ts = row[0] if row else None
    if oldest_ts is not None:
        oldest_access = datetime.datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d")
    else:
        oldest_access = None

    # Signal coverage
    has_activation_set = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT note_path FROM access_log"
        ).fetchall()
    }
    # Filter to only notes that actually exist in the notes table
    all_note_paths = {
        r[0] for r in conn.execute("SELECT path FROM notes").fetchall()
    }
    has_activation_set &= all_note_paths

    has_importance_set = {
        r[0]
        for r in conn.execute(
            "SELECT path FROM notes WHERE COALESCE(importance, 5) != 5"
        ).fetchall()
    }

    has_both = len(has_activation_set & has_importance_set)
    has_activation = len(has_activation_set)
    has_importance = len(has_importance_set)
    has_neither = total_notes - has_activation - has_importance + has_both

    signal_coverage = {
        "has_activation": has_activation,
        "has_importance": has_importance,
        "has_both": has_both,
        "has_neither": has_neither,
    }

    # Access by context (last 30 days)
    access_by_context: dict[str, int] = {}
    for r in conn.execute(
        "SELECT context_type, COUNT(*) FROM access_log "
        "WHERE timestamp >= ? GROUP BY context_type",
        (thirty_days_ago,),
    ).fetchall():
        access_by_context[r[0]] = r[1]

    # Top accessed (top 10 by access count, restricted to notes that still exist)
    top_rows = conn.execute(
        "SELECT a.note_path, COUNT(*) as cnt FROM access_log a "
        "INNER JOIN notes n ON n.path = a.note_path "
        "GROUP BY a.note_path ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    top_accessed = _enrich_top_accessed(conn, db_path, top_rows)

    # Importance distribution
    dist = {"trivial": 0, "standard": 0, "significant": 0, "critical": 0}
    for r in conn.execute("SELECT COALESCE(importance, 5) FROM notes").fetchall():
        bucket = _importance_bucket(r[0])
        dist[bucket] += 1

    vault_wide = {
        "total_notes": total_notes,
        "db_size_bytes": db_size_bytes,
        "access_log_entries": access_log_entries,
        "oldest_access": oldest_access,
        "signal_coverage": signal_coverage,
        "access_by_context": access_by_context,
        "top_accessed": top_accessed,
        "importance_distribution": dist,
        "snapshots": _snapshot_stats(conn),
    }

    # --- project ---

    proj_total = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE project = ?", (project,)
    ).fetchone()[0]

    proj_access_events = conn.execute(
        "SELECT COUNT(*) FROM access_log WHERE project = ?", (project,)
    ).fetchone()[0]

    avg_accesses = round(proj_access_events / proj_total, 2) if proj_total > 0 else 0.0

    proj_activated = 0
    if proj_total > 0:
        proj_note_paths = [
            r[0]
            for r in conn.execute(
                "SELECT path FROM notes WHERE project = ?", (project,)
            ).fetchall()
        ]
        proj_activated = len(has_activation_set & set(proj_note_paths))

    proj_importance = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE project = ? AND COALESCE(importance, 5) != 5",
        (project,),
    ).fetchone()[0]

    # Recent activity (last 7 days, project-scoped)
    recent_activity: dict[str, int] = {}
    for r in conn.execute(
        "SELECT context_type, COUNT(*) FROM access_log "
        "WHERE timestamp >= ? AND project = ? GROUP BY context_type",
        (seven_days_ago, project),
    ).fetchall():
        recent_activity[r[0]] = r[1]

    # Top 5 project notes by access count (restricted to notes that still exist)
    proj_top_rows = conn.execute(
        "SELECT a.note_path, COUNT(*) as cnt FROM access_log a "
        "INNER JOIN notes n ON n.path = a.note_path "
        "WHERE a.project = ? AND n.project = ? "
        "GROUP BY a.note_path ORDER BY cnt DESC LIMIT 5",
        (project, project),
    ).fetchall()
    proj_top_accessed = _enrich_top_accessed(conn, db_path, proj_top_rows)

    project_data = {
        "name": project,
        "total_notes": proj_total,
        "access_events": proj_access_events,
        "avg_accesses": avg_accesses,
        "notes_with_activation": proj_activated,
        "notes_with_importance": proj_importance,
        "recent_activity": recent_activity,
        "top_accessed": proj_top_accessed,
    }

    return json.dumps({"vault_wide": vault_wide, "project": project_data})


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_path> <project>", file=sys.stderr)
        sys.exit(1)
    result = compute_stats(sys.argv[1], sys.argv[2])
    print(result)
    parsed = json.loads(result)
    if "error" in parsed:
        sys.exit(1)
