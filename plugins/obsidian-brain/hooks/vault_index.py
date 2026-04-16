"""SQLite + FTS5 vault index for fast note lookup and context-driven ranking.

Provides full-text search over Obsidian vault notes, mtime-based incremental
sync, and layered ranking for context-relevant note discovery.

DB location: ~/.claude/obsidian-brain-vault.db (outside vault, alongside config).
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS notes (
    path            TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    date            TEXT,
    project         TEXT,
    title           TEXT,
    source_session  TEXT,
    source_note     TEXT,
    tags            TEXT,
    status          TEXT,
    mtime           REAL NOT NULL,
    size            INTEGER,
    body            TEXT DEFAULT '',
    importance      INTEGER DEFAULT 5
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    body,
    tags,
    content=''
);

CREATE TABLE IF NOT EXISTS access_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path       TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    context_type    TEXT NOT NULL,
    project         TEXT
);
"""

# ---------------------------------------------------------------------------
# Stopwords for keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is it this that was were be been "
    "being have has had do does did will would shall should may might can could "
    "not no nor so if then than too very are am was were with from by about "
    "into through during before after above below between out off over under "
    "again further once here there when where why how all each every both few "
    "more most other some such only own same also just because as until while "
    "up down its they them their what which who whom he she we you i my your "
    "his her our me him us".split()
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    """Return default DB path: ~/.claude/obsidian-brain-vault.db."""
    return os.path.join(os.path.expanduser("~"), ".claude", "obsidian-brain-vault.db")


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a WAL-mode connection with 5s timeout."""
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    # Split and execute each statement (can't use executescript with IF NOT EXISTS
    # for virtual tables reliably in all sqlite versions)
    cur = conn.cursor()
    for stmt in _SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    conn.commit()


def _needs_body_migration(conn: sqlite3.Connection) -> bool:
    """Return True if the notes table is missing the body column."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    return "body" not in cols


def _ensure_access_log_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes on access_log if they don't exist."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_note ON access_log (note_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_time ON access_log (timestamp)"
    )
    conn.commit()


def _needs_importance_migration(conn: sqlite3.Connection) -> bool:
    """Return True if the notes table is missing the importance column."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    return "importance" not in cols


def _add_importance_column(conn: sqlite3.Connection) -> None:
    """Add importance column to existing notes table."""
    conn.execute("ALTER TABLE notes ADD COLUMN importance INTEGER DEFAULT 5")
    conn.commit()


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_note(file_path: str) -> dict | None:
    """Parse frontmatter and body from a vault note.

    Returns dict with keys: type, date, project, title, source_session,
    source_note, tags (comma-separated), status, body.
    Returns None for files that can't be parsed.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            full_text = f.read()
    except OSError:
        return None

    lines = full_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    # Parse frontmatter (first 40 lines)
    meta: dict = {}
    tags: list[str] = []
    in_tags = False
    end_idx = None

    for idx, line in enumerate(lines[1:40], start=1):
        stripped = line.strip()
        if stripped == "---":
            end_idx = idx
            break
        if stripped.startswith("- ") and in_tags:
            tags.append(stripped[2:].strip())
            continue
        in_tags = False
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "tags":
                in_tags = True
                continue
            meta[key] = val

    if end_idx is None:
        return None

    if tags:
        meta["tags"] = ",".join(tags)

    # Body: everything after closing ---
    body_lines = lines[end_idx + 1:]
    body = "\n".join(body_lines).strip()
    meta["body"] = body

    # Extract title from first H1 heading in body
    title = meta.get("title", "")
    if not title:
        for bl in body_lines:
            stripped = bl.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break
    meta["title"] = title

    # Handle source_session_note -> source_note (strip [[wikilink]])
    source_note_raw = meta.pop("source_session_note", None)
    if source_note_raw:
        meta["source_note"] = source_note_raw.strip("[]").replace("[[", "").replace("]]", "")

    return meta


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------


def _upsert_note(conn: sqlite3.Connection, rel_path: str, parsed: dict, mtime: float, size: int) -> None:
    """Insert or replace a note in the index + FTS table.

    For contentless FTS5 (content=''), deletes require passing the old
    column values via the special 'delete' command, not DELETE FROM.
    """
    row = conn.execute("SELECT rowid, title, tags, importance FROM notes WHERE path = ?", (rel_path,)).fetchone()
    existing_importance = None
    if row:
        existing_importance = row["importance"]
        # Contentless FTS5 delete: must pass old values
        # Read old body from the FTS shadow tables isn't possible with contentless,
        # so we need to read it from the note file or accept that we can't do
        # precise deletes. Instead, drop and recreate the entire FTS table entry
        # by using DELETE on the notes table first, then rebuild.
        # Simpler approach: just delete the notes row and skip FTS delete.
        # The stale FTS entry will be overwritten by the new INSERT with the same rowid.
        # Actually, contentless FTS doesn't support any form of delete without old values.
        # The cleanest approach: delete the notes row (rowid freed), insert new one
        # (gets new rowid), insert new FTS entry. The orphaned FTS entry for the old
        # rowid is harmless — it won't join with any notes row.
        conn.execute("DELETE FROM notes WHERE path = ?", (rel_path,))

    conn.execute(
        "INSERT INTO notes (path, type, date, project, title, source_session, "
        "source_note, tags, status, mtime, size, body, importance) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rel_path,
            parsed.get("type", "unknown"),
            parsed.get("date"),
            parsed.get("project"),
            parsed.get("title", ""),
            parsed.get("source_session"),
            parsed.get("source_note"),
            parsed.get("tags", ""),
            parsed.get("status"),
            mtime,
            size,
            parsed.get("body", ""),
            existing_importance if existing_importance is not None else 5,
        ),
    )

    # Get the rowid for FTS insert
    rowid = conn.execute("SELECT rowid FROM notes WHERE path = ?", (rel_path,)).fetchone()["rowid"]
    conn.execute(
        "INSERT INTO notes_fts (rowid, title, body, tags) VALUES (?, ?, ?, ?)",
        (rowid, parsed.get("title", ""), parsed.get("body", ""), parsed.get("tags", "")),
    )


def _delete_note(conn: sqlite3.Connection, rel_path: str) -> None:
    """Remove a note from the index + FTS table.

    For contentless FTS5, we can only delete the notes row. The orphaned
    FTS entry won't match any JOIN since the notes rowid is gone.
    """
    conn.execute("DELETE FROM notes WHERE path = ?", (rel_path,))


def _sync(conn: sqlite3.Connection, vault_path: str, folders: list[str]) -> dict:
    """Incremental sync: add new/changed files, remove deleted ones.

    Returns {"inserted": N, "skipped": M, "deleted": D, "by_type": {...}}.
    """
    vault = Path(vault_path)
    stats = {"inserted": 0, "skipped": 0, "deleted": 0, "by_type": {}}

    # Collect all .md files in target folders (keyed by absolute path)
    disk_files: dict[str, Path] = {}  # abs_path_str -> Path object
    for folder in folders:
        folder_path = vault / folder
        if not folder_path.is_dir():
            continue
        for md_file in folder_path.rglob("*.md"):
            disk_files[str(md_file)] = md_file

    # Get indexed files
    indexed = {
        row["path"]: row["mtime"]
        for row in conn.execute("SELECT path, mtime FROM notes").fetchall()
    }

    # Delete removed files (only if they belong to a scanned folder)
    scanned_roots = [str(vault / f) for f in folders]
    for abs_path_str in list(indexed.keys()):
        if abs_path_str not in disk_files:
            if any(abs_path_str.startswith(root) for root in scanned_roots):
                _delete_note(conn, abs_path_str)
                stats["deleted"] += 1

    # Insert/update files
    for abs_path_str, abs_path in disk_files.items():
        try:
            st = abs_path.stat()
        except OSError:
            continue  # File deleted/moved between rglob and stat
        file_mtime = st.st_mtime
        file_size = st.st_size

        # Skip if mtime unchanged (0.001 tolerance)
        if abs_path_str in indexed and abs(file_mtime - indexed[abs_path_str]) < 0.001:
            stats["skipped"] += 1
            continue

        parsed = _parse_note(str(abs_path))
        if parsed is None:
            stats["skipped"] += 1
            continue

        _upsert_note(conn, abs_path_str, parsed, file_mtime, file_size)
        note_type = parsed.get("type", "unknown")
        stats["by_type"][note_type] = stats["by_type"].get(note_type, 0) + 1
        stats["inserted"] += 1

    conn.commit()
    return stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_index(vault_path: str, folders: list[str], db_path: str | None = None) -> str:
    """Create or update the vault index. Returns the DB path.

    Handles corrupt DB by deleting and recreating.
    """
    if db_path is None:
        db_path = _default_db_path()

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    try:
        conn = _connect(db_path)
        try:
            _init_schema(conn)
            _ensure_access_log_indexes(conn)
            if _needs_importance_migration(conn):
                _add_importance_column(conn)
            if _needs_body_migration(conn):
                print(f"[vault-index] Missing body column; rebuilding {db_path}",
                      file=sys.stderr)
                conn.close()
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(db_path + suffix)
                    except OSError as exc:
                        if suffix == "":
                            print(f"[vault-index] Failed to remove {db_path}: {exc}",
                                  file=sys.stderr)
                conn = _connect(db_path)
                _init_schema(conn)
                _ensure_access_log_indexes(conn)
                if _needs_importance_migration(conn):
                    _add_importance_column(conn)
                if _needs_body_migration(conn):
                    raise sqlite3.DatabaseError("body column missing after rebuild")
            _sync(conn, vault_path, folders)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        # Corrupt DB — delete and recreate
        print(f"[vault-index] Corrupt or incompatible DB ({exc}); rebuilding {db_path}",
              file=sys.stderr)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass
        conn = _connect(db_path)
        try:
            _init_schema(conn)
            _ensure_access_log_indexes(conn)
            if _needs_importance_migration(conn):
                _add_importance_column(conn)
            _sync(conn, vault_path, folders)
        finally:
            conn.close()

    # Set permissions
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass

    return db_path


def log_access(db_path: str, note_path: str, context_type: str, project: str | None = None) -> None:
    """Insert one access-log row. Logs a warning to stderr if the database is unavailable."""
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute(
                "INSERT INTO access_log (note_path, timestamp, context_type, project) "
                "VALUES (?, ?, ?, ?)",
                (note_path, time.time(), context_type, project),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[vault-index] log_access failed for {note_path!r}: {exc}", file=sys.stderr)


def batch_activations(
    db_path: str, note_paths: list[str], decay: float = 0.5
) -> dict[str, float]:
    """Compute ACT-R base-level activation for each note path.

    Returns {path: activation} with 0.0 for notes with no access history.
    Formula: ln(Σ t_i^(-decay)) where t_i = seconds since access.
    """
    if not note_paths:
        return {}

    result: dict[str, float] = {p: 0.0 for p in note_paths}

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            now = time.time()
            placeholders = ",".join("?" for _ in note_paths)
            rows = conn.execute(
                f"SELECT note_path, timestamp FROM access_log "
                f"WHERE note_path IN ({placeholders})",
                note_paths,
            ).fetchall()

            # Group timestamps by note_path
            accesses: dict[str, list[float]] = defaultdict(list)
            for row in rows:
                accesses[row[0]].append(row[1])

            for path, timestamps in accesses.items():
                summation = 0.0
                for ts in timestamps:
                    dt = max(now - ts, 0.001)  # clamp to 1ms minimum
                    summation += dt ** (-decay)
                if summation > 0.0:
                    result[path] = math.log(summation)
        finally:
            conn.close()
    except Exception as exc:
        print(f"[vault-index] batch_activations failed ({len(note_paths)} paths): {exc}",
              file=sys.stderr)
        return result

    return result


def rebuild_index(vault_path: str, folders: list[str], db_path: str | None = None) -> dict:
    """Drop and rebuild the entire index from scratch.

    Returns {"inserted": N, "skipped": M, "by_type": {...}}.
    """
    if db_path is None:
        db_path = _default_db_path()

    # Delete existing DB and WAL/SHM sidecars
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = _connect(db_path)
    try:
        _init_schema(conn)
        stats = _sync(conn, vault_path, folders)
    finally:
        conn.close()

    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass

    return stats


def index_note(db_path: str, note_path: str) -> bool:
    """Index a single note file. Returns True on success, False otherwise."""
    if not os.path.isfile(db_path):
        return False

    if not os.path.isfile(note_path):
        return False

    parsed = _parse_note(note_path)
    if parsed is None:
        return False

    st = os.stat(note_path)

    try:
        conn = _connect(db_path)
        try:
            _upsert_note(conn, note_path, parsed, st.st_mtime, st.st_size)
            conn.commit()
            return True
        except sqlite3.Error as exc:
            print(f"[vault-index] index_note failed for {note_path}: {exc}",
                  file=sys.stderr)
            return False
        finally:
            conn.close()
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Task-context detection
# ---------------------------------------------------------------------------


_cached_git_branch: str | None = None
_cached_git_branch_set: bool = False


def _get_git_branch() -> str | None:
    """Return the current git branch name, or None on failure. Cached per-process."""
    global _cached_git_branch, _cached_git_branch_set
    if _cached_git_branch_set:
        return _cached_git_branch
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            _cached_git_branch = branch
            _cached_git_branch_set = True
            return branch
    except FileNotFoundError:
        _cached_git_branch_set = True
        return None
    except Exception as exc:
        print(f"[vault-index] git branch detection failed: {exc}", file=sys.stderr)
        _cached_git_branch_set = True
        return None


def detect_task_context(caller_skill: str | None = None) -> str:
    """Detect the current task context from git branch and caller skill.

    Returns one of: 'debugging', 'standup', 'emerge', 'search', 'general'.
    Branch-based detection (fix/bug/hotfix) takes precedence over caller.
    """
    branch = _get_git_branch()
    if branch and re.match(r"^(?:refs/heads/)?(?:fix|bug|hotfix)(?:/|$)", branch.lower()):
        return "debugging"

    if caller_skill in ("standup", "emerge"):
        return caller_skill
    if caller_skill in ("vault-ask", "vault-search"):
        return "search"

    return "general"


_TYPE_SCORES_BY_CONTEXT = {
    "debugging": {
        "claude-error-fix": 1.0, "claude-session": 0.8, "claude-insight": 0.6,
        "claude-decision": 0.5, "claude-retro": 0.3, "claude-standup": 0.3,
    },
    "standup": {
        "claude-session": 1.0, "claude-decision": 0.8, "claude-insight": 0.7,
        "claude-retro": 0.6, "claude-error-fix": 0.5, "claude-standup": 0.3,
    },
    "search": {
        "claude-insight": 1.0, "claude-decision": 0.9, "claude-error-fix": 0.8,
        "claude-session": 0.5, "claude-retro": 0.4, "claude-standup": 0.3,
    },
    "emerge": {
        "claude-insight": 1.0, "claude-decision": 0.9, "claude-error-fix": 0.8,
        "claude-session": 0.5, "claude-retro": 0.4, "claude-standup": 0.3,
    },
    "general": {
        "claude-insight": 1.0, "claude-decision": 1.0, "claude-error-fix": 0.9,
        "claude-session": 0.5, "claude-retro": 0.4, "claude-standup": 0.3,
    },
}


def get_type_scores(context: str) -> dict[str, float]:
    """Return type score mapping for the given task context.

    Falls back to 'general' for unknown contexts.
    """
    return _TYPE_SCORES_BY_CONTEXT.get(context, _TYPE_SCORES_BY_CONTEXT["general"])


# ---------------------------------------------------------------------------
# FTS search
# ---------------------------------------------------------------------------


def _sanitize_fts_query_or(query: str) -> str:
    """Build an OR-mode FTS5 query for fallback."""
    query = query.replace("-", " ")
    words = re.findall(r"[a-zA-Z0-9_/]+", query)
    if not words:
        return ""
    return " OR ".join(f'"{w}"' for w in words)


def _extract_query_terms(query: str) -> list[str]:
    """Extract individual search terms from a query string."""
    query = query.replace("-", " ")
    stripped = re.sub(r'"[^"]*"', " ", query)
    terms = re.findall(r"[a-zA-Z0-9_/]+", stripped)
    phrases = re.findall(r'"([^"]*)"', query)
    for phrase in phrases:
        terms.extend(re.findall(r"[a-zA-Z0-9_/]+", phrase))
    return [t.lower() for t in terms if len(t) > 1]


def _sanitize_fts_query(query: str) -> str:
    """Sanitize user input for FTS5 MATCH using AND-mode (implicit AND).

    Replaces hyphens with spaces (FTS5 unicode61 tokenizer treats hyphens
    as token separators, so "maintain-catalog" inside quotes becomes
    "maintain" NOT "catalog"). Quoted phrases are preserved as-is.
    Remaining words are each quoted individually and space-joined so
    FTS5 applies implicit AND — all terms must appear.
    """
    query = query.replace("-", " ")
    parts: list[str] = []
    remaining = query
    while '"' in remaining:
        start = remaining.index('"')
        end = remaining.index('"', start + 1) if '"' in remaining[start + 1:] else -1
        if end == -1:
            break
        phrase = remaining[start:end + 1]
        parts.append(phrase)
        remaining = remaining[:start] + remaining[end + 1:]
    words = re.findall(r"[a-zA-Z0-9_/]+", remaining)
    parts.extend(f'"{w}"' for w in words)
    # Filter empty phrases (e.g. '""') that could confuse FTS5
    parts = [p for p in parts if p != '""']
    if not parts:
        return ""
    # Phrase order may differ from input (phrases first, then words);
    # FTS5 implicit AND is commutative so order doesn't affect results.
    return " ".join(parts)


def _compute_proximity(body_lower: str, query_terms: list[str]) -> float:
    """Compute proximity score between query terms in text.

    Single-term: 1.0. Multi-term: 1.0 / (1.0 + min_distance / 200).
    """
    # Deduplicate terms so "sentry sentry" is treated as single-term
    unique_terms = list(dict.fromkeys(t.lower() for t in query_terms))
    if len(unique_terms) <= 1:
        return 1.0

    positions: dict[str, list[int]] = {}
    for term in unique_terms:
        term_lower = term.lower()
        pos_list: list[int] = []
        start = 0
        while True:
            idx = body_lower.find(term_lower, start)
            if idx == -1:
                break
            pos_list.append(idx)
            start = idx + 1
        if pos_list:
            positions[term_lower] = pos_list

    if len(positions) < 2:
        return 0.0

    min_dist = float("inf")
    terms_with_pos = list(positions.keys())
    for i in range(len(terms_with_pos)):
        for j in range(i + 1, len(terms_with_pos)):
            for p1 in positions[terms_with_pos[i]]:
                for p2 in positions[terms_with_pos[j]]:
                    dist = abs(p1 - p2)
                    if dist < min_dist:
                        min_dist = dist

    if min_dist == float("inf"):
        return 0.0

    return 1.0 / (1.0 + min_dist / 200)


def rerank_results(
    fts_results: list[dict],
    query_terms: list[str],
    limit: int = 15,
    db_path: str | None = None,
    task_context: str | None = None,
) -> list[dict]:
    """Rerank FTS5 results using 7 signals for context-relevant ordering.

    Signals and weights:
        proximity  0.25 — how close query terms appear in the note body
        bm25       0.20 — FTS5 BM25 relevance score (normalized)
        activation 0.20 — ACT-R base-level activation from access history
        type       0.10 — note type score adapted to task context
        recency    0.10 — exponential decay based on note age
        importance 0.10 — editorial importance (frontmatter, 1-10 scale)
        density    0.05 — fraction of query terms matched in full text

    When ``db_path`` is None, the activation signal is 0 for all candidates.
    When ``task_context`` is None, the 'general' type scores are used.
    """
    if not fts_results:
        return []

    ranks = [r.get("rank", 0.0) for r in fts_results]
    # FTS5 bm25() returns negative values; most-negative = best match.
    # Map so that the best (most-negative) score normalises to 1.0.
    best_rank = min(ranks)   # most negative = best FTS5 match
    worst_rank = max(ranks)  # least negative = worst FTS5 match
    rank_range = worst_rank - best_rank if best_rank != worst_rank else 1.0

    today = date.today()
    type_scores = get_type_scores(task_context or "general")

    # --- Activation signal (batch lookup) ---
    note_paths = [r.get("path", "") for r in fts_results]
    if db_path:
        raw_activations = batch_activations(db_path, note_paths)
    else:
        raw_activations = {p: 0.0 for p in note_paths}

    # Normalize activations to [0, 1] — non-zero values (including negatives) get mapped
    nonzero_acts = [v for v in raw_activations.values() if v != 0.0]
    if nonzero_acts:
        act_min = min(nonzero_acts)
        act_max = max(nonzero_acts)
        act_range = act_max - act_min
    else:
        act_min = 0.0
        act_range = 1.0

    scored: list[tuple[float, dict]] = []
    for r in fts_results:
        body = r.get("body", "") or ""
        full_text = f"{r.get('title', '')} {r.get('tags', '')} {body}".lower()

        proximity = _compute_proximity(body.lower(), query_terms)

        bm25_norm = (worst_rank - r.get("rank", worst_rank)) / rank_range

        type_score = type_scores.get(r.get("type", ""), 0.5)

        try:
            note_date = date.fromisoformat(r.get("date", "") or "")
            days_old = max((today - note_date).days, 0)
        except (ValueError, TypeError):
            days_old = 365
        recency = 0.5 ** (days_old / 30)

        if query_terms:
            matched = sum(
                1 for t in query_terms
                if re.search(r'\b' + re.escape(t) + r'\b', full_text)
            )
            density = matched / len(query_terms)
        else:
            density = 1.0

        # Activation (normalized)
        raw_act = raw_activations.get(r.get("path", ""), 0.0)
        if raw_act == 0.0:
            activation_norm = 0.0
        elif act_range == 0.0:
            activation_norm = 1.0  # all accessed notes share same score
        else:
            # Reserve 0.0 for "no history"; accessed notes map to (0, 1]
            activation_norm = 0.01 + ((raw_act - act_min) / act_range) * 0.99

        # Importance (0-1 scale from frontmatter 1-10)
        raw_importance = r.get("importance", 5)
        if raw_importance is None:
            raw_importance = 5
        try:
            raw_importance = max(1, min(10, int(raw_importance)))
        except (TypeError, ValueError):
            raw_importance = 5
        importance_norm = raw_importance / 10.0

        final = (
            0.25 * proximity
            + 0.20 * bm25_norm
            + 0.20 * activation_norm
            + 0.10 * type_score
            + 0.10 * recency
            + 0.10 * importance_norm
            + 0.05 * density
        )

        r_copy = dict(r)
        r_copy["rerank_score"] = round(final, 4)
        scored.append((final, r_copy))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def search_vault(
    db_path: str,
    query: str,
    project: str | None = None,
    note_type: str | None = None,
    limit: int = 15,
    caller: str | None = None,
) -> list[dict]:
    """Full-text search over the vault index.

    Returns up to ``limit`` results (default 15) as a list of dicts
    containing note metadata plus the initial FTS ``rank`` and reranked
    ``rerank_score``. The note ``body`` is used internally for reranking
    but is removed before results are returned.

    Candidates are retrieved with BM25 column weighting (title=10x,
    tags=5x), then reranked with a 7-signal scorer for context relevance.
    Falls back to OR-mode if the AND query returns no results.

    The optional ``caller`` parameter (e.g. 'vault-search', 'standup')
    drives task-context detection for context-adaptive type scoring.
    """
    if not os.path.isfile(db_path):
        return []

    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []

    query_terms = _extract_query_terms(query)

    try:
        conn = _connect(db_path)
    except sqlite3.Error as exc:
        print(f"[vault-index] search_vault could not connect: {exc}",
              file=sys.stderr)
        return []

    candidate_limit = min(limit * 3, 50)

    try:
        filter_sql = ""
        filter_params: list = []
        if project:
            filter_sql += "AND n.project = ? "
            filter_params.append(project)
        if note_type:
            filter_sql += "AND n.type = ? "
            filter_params.append(note_type)

        sql = (
            "SELECT n.path, n.type, n.date, n.project, n.title, n.tags, n.status, "
            "n.source_session, n.source_note, n.size, n.body, n.importance, "
            "bm25(notes_fts, 10.0, 1.0, 5.0) AS rank "
            "FROM notes_fts f "
            "JOIN notes n ON n.rowid = f.rowid "
            "WHERE notes_fts MATCH ? "
            + filter_sql
            + "ORDER BY rank LIMIT ?"
        )
        params: list = [sanitized] + filter_params + [candidate_limit]

        rows = conn.execute(sql, params).fetchall()
        candidates = [dict(row) for row in rows]

        # OR fallback when AND returns nothing
        if not candidates:
            or_query = _sanitize_fts_query_or(query)
            if or_query:
                print(f"[vault-index] AND query returned 0 results; falling back to OR",
                      file=sys.stderr)
                or_params: list = [or_query] + filter_params + [candidate_limit]
                rows = conn.execute(sql, or_params).fetchall()
                candidates = [dict(row) for row in rows]

        task_context = detect_task_context(caller_skill=caller) if caller else None
        results = rerank_results(
            candidates, query_terms, limit,
            db_path=db_path, task_context=task_context,
        )
        # Log access for returned results
        for r in results:
            log_access(db_path, r["path"], "search", project=r.get("project"))
        # Strip body — callers don't need it
        for r in results:
            r.pop("body", None)
        return results

    except sqlite3.Error as exc:
        print(f"[vault-index] search_vault query failed: {exc}",
              file=sys.stderr)
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    """Extract keywords from text, removing stopwords and short words.

    Returns up to `limit` keywords ordered by frequency.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", text.lower())
    # Filter stopwords and words <= 2 chars
    filtered = [w for w in words if w not in _STOPWORDS and len(w) > 2]

    # Count frequency
    freq: dict[str, int] = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1

    # Sort by frequency descending, then alphabetically
    ranked = sorted(freq.keys(), key=lambda w: (-freq[w], w))
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Layered ranking query
# ---------------------------------------------------------------------------


def query_related_notes(
    db_path: str,
    project: str,
    session_ids: list[str],
    session_tags: list[str],
    session_summary: str,
    note_types: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Find notes related to current context using layered ranking.

    Layer 1: Backlinks (notes whose source_session is in session_ids)
    Layer 2: Tag overlap (claude/topic/* tags)
    Layer 3: FTS keyword search on session summary

    Returns up to `limit` results, filling slots layer by layer.
    """
    if not os.path.isfile(db_path):
        return []

    try:
        conn = _connect(db_path)
    except sqlite3.Error as exc:
        print(f"[vault-index] query_related_notes could not connect: {exc}",
              file=sys.stderr)
        return []

    try:
        results: list[dict] = []
        seen_paths: set[str] = set()

        type_filter = ""
        type_params: list = []
        if note_types:
            placeholders = ",".join("?" for _ in note_types)
            type_filter = f"AND type IN ({placeholders})"
            type_params = list(note_types)

        # Layer 1: Backlinks — notes whose source_session matches loaded sessions
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            sql = (
                f"SELECT path, type, date, project, title, tags, status, "
                f"source_session, source_note, size "
                f"FROM notes WHERE source_session IN ({placeholders}) "
                f"AND project = ? "
                f"{type_filter} "
                f"ORDER BY date DESC"
            )
            try:
                rows = conn.execute(sql, session_ids + [project] + type_params).fetchall()
                for row in rows:
                    d = dict(row)
                    d["layer"] = "backlink"
                    if d["path"] not in seen_paths:
                        results.append(d)
                        seen_paths.add(d["path"])
            except sqlite3.Error as exc:
                print(f"[vault-index] Layer 1 (backlinks) query failed: {exc}",
                      file=sys.stderr)

        # Layer 2: Tag overlap (claude/topic/* tags)
        topic_tags = [t for t in session_tags if t.startswith("claude/topic/")]
        if topic_tags and len(results) < limit:
            for tag in topic_tags:
                if len(results) >= limit:
                    break
                escaped_tag = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                sql = (
                    f"SELECT path, type, date, project, title, tags, status, "
                    f"source_session, source_note, size "
                    f"FROM notes WHERE tags LIKE ? ESCAPE '\\' AND project = ? "
                    f"{type_filter} "
                    f"ORDER BY date DESC"
                )
                try:
                    rows = conn.execute(
                        sql, [f"%{escaped_tag}%", project] + type_params
                    ).fetchall()
                    for row in rows:
                        d = dict(row)
                        d["layer"] = "tag"
                        if d["path"] not in seen_paths:
                            results.append(d)
                            seen_paths.add(d["path"])
                except sqlite3.Error as exc:
                    print(f"[vault-index] Layer 2 (tags) query failed: {exc}",
                          file=sys.stderr)

        # Layer 3: FTS keyword search
        if len(results) < limit and session_summary:
            keywords = extract_keywords(session_summary)
            if keywords:
                # Layer 3 uses OR-mode: keyword discovery benefits from
                # recall over precision (5-8 keywords rarely all co-occur).
                fts_query = _sanitize_fts_query_or(" ".join(keywords))
                if fts_query:
                    remaining = limit - len(results)
                    sql = (
                        f"SELECT n.path, n.type, n.date, n.project, n.title, n.tags, "
                        f"n.status, n.source_session, n.source_note, n.size "
                        f"FROM notes_fts f "
                        f"JOIN notes n ON n.rowid = f.rowid "
                        f"WHERE notes_fts MATCH ? AND n.project = ? "
                        f"{type_filter} "
                        f"ORDER BY f.rank LIMIT ?"
                    )
                    try:
                        rows = conn.execute(
                            sql, [fts_query, project] + type_params + [remaining]
                        ).fetchall()
                        for row in rows:
                            d = dict(row)
                            d["layer"] = "fts"
                            if d["path"] not in seen_paths:
                                results.append(d)
                                seen_paths.add(d["path"])
                    except sqlite3.Error as exc:
                        print(f"[vault-index] Layer 3 (FTS) query failed: {exc}",
                              file=sys.stderr)

        # Log access for returned results
        for r in results[:limit]:
            log_access(db_path, r["path"], "related", project)
        return results[:limit]
    finally:
        conn.close()
