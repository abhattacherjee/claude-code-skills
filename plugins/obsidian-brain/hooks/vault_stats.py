"""Vault statistics module — compute aggregate stats from the vault index DB.

Single entry point: compute_stats(db_path, project) -> JSON string.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
import time

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
