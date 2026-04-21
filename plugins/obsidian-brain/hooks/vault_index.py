"""SQLite + FTS5 vault index for fast note lookup and context-driven ranking.

Provides full-text search over Obsidian vault notes, mtime-based incremental
sync, and layered ranking for context-relevant note discovery.

DB location: ~/.claude/obsidian-brain-vault.db (outside vault, alongside config).
"""

from __future__ import annotations

import json
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
    importance      INTEGER DEFAULT 5,
    tfidf_vector    TEXT
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

CREATE TABLE IF NOT EXISTS themes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    centroid        TEXT,
    note_count      INTEGER NOT NULL DEFAULT 0,
    activation      REAL NOT NULL DEFAULT 0.0,
    created_date    TEXT NOT NULL,
    updated_date    TEXT NOT NULL,
    project         TEXT
);

CREATE TABLE IF NOT EXISTS theme_members (
    theme_id        INTEGER NOT NULL,
    note_path       TEXT NOT NULL,
    similarity      REAL NOT NULL,
    surprise        REAL NOT NULL DEFAULT 0.0,
    added_date      TEXT NOT NULL,
    PRIMARY KEY (theme_id, note_path)
);

CREATE TABLE IF NOT EXISTS term_df (
    term            TEXT PRIMARY KEY,
    df              INTEGER NOT NULL
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
# Path helpers
# ---------------------------------------------------------------------------


def _is_under(child: Path, parent: Path) -> bool:
    """True iff `child` lives inside `parent` (proper containment, not prefix match).

    Prevents sibling-prefix folders (e.g. 'claude-sessions-archive') from
    being treated as nested inside 'claude-sessions'.
    """
    return child.is_relative_to(parent)


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


def _needs_tfidf_vector_migration(conn: sqlite3.Connection) -> bool:
    """Return True if the notes table is missing the tfidf_vector column."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    return "tfidf_vector" not in cols


def _add_tfidf_vector_column(conn: sqlite3.Connection) -> None:
    """Add tfidf_vector column to existing notes table."""
    conn.execute("ALTER TABLE notes ADD COLUMN tfidf_vector TEXT")
    conn.commit()


def _ensure_theme_indexes(conn: sqlite3.Connection) -> None:
    """Create secondary indexes for themes + theme_members if missing."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_theme_members_note "
        "ON theme_members (note_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_themes_project "
        "ON themes (project)"
    )
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


def _prior_tokens_for(conn: sqlite3.Connection, note_path: str) -> set[str]:
    """Return the full token set of the note's currently-stored content.

    Re-tokenises title+tags+body (the same inputs _upsert_note uses for the
    new document) so the set is symmetric with ``new_terms`` during a
    reindex. Reading the stored ``tfidf_vector`` would be wrong here — it
    is truncated to top-K=50, and any common-but-low-IDF term outside that
    cutoff would be incremented on every reindex without ever being
    decremented, drifting ``term_df.df`` upward. Returns an empty set if
    the note does not exist.
    """
    row = conn.execute(
        "SELECT title, body, tags FROM notes WHERE path = ?", (note_path,)
    ).fetchone()
    if not row:
        return set()
    full_text = " ".join([row["title"] or "", row["tags"] or "", row["body"] or ""])
    return set(_tokenize_for_tfidf(full_text))


def _upsert_note(conn: sqlite3.Connection, rel_path: str, parsed: dict, mtime: float, size: int) -> None:
    """Insert or replace a note + FTS row + maintain term_df + tfidf_vector.

    For contentless FTS5 (content=''), removal requires the special
    'delete' command with the old column values — regular DELETE FROM is
    rejected. We fetch the prior title/body/tags + rowid here so that on
    update we can issue the delete before inserting the new FTS row,
    keeping the FTS index from accumulating orphan entries across rewrites.
    """
    row = conn.execute(
        "SELECT rowid, title, body, tags, importance FROM notes WHERE path = ?",
        (rel_path,),
    ).fetchone()
    existing_importance = row["importance"] if row else None
    is_new = row is None

    # --- TF-IDF maintenance (before the DELETE so _prior_tokens_for can read
    # the old body). ---
    old_terms = _prior_tokens_for(conn, rel_path)

    full_text = " ".join([
        parsed.get("title", "") or "",
        parsed.get("tags", "") or "",
        parsed.get("body", "") or "",
    ])
    tokens = _tokenize_for_tfidf(full_text)
    new_terms = set(tokens)

    # Apply df diff BEFORE computing this note's TF-IDF so its own term
    # contribution is included in the IDF denominator.
    _update_term_df(conn, old_terms=old_terms, new_terms=new_terms)

    total_docs = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    if is_new:
        total_docs += 1  # this note is about to be inserted
    term_df = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
    tfidf_vec = _compute_tfidf_vector(tokens, term_df, total_docs, top_k=50)
    tfidf_json = json.dumps(tfidf_vec, separators=(",", ":")) if tfidf_vec else None

    if not is_new:
        # Remove the old FTS row before the notes DELETE so the notes_fts
        # index doesn't accumulate orphan entries on every rewrite.
        # Contentless FTS5 only accepts the special 'delete' command with
        # the prior column values (SQLite docs: Inserting new rows into
        # an external-content table with content='').
        conn.execute(
            "INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) "
            "VALUES('delete', ?, ?, ?, ?)",
            (row["rowid"], row["title"] or "", row["body"] or "", row["tags"] or ""),
        )
        conn.execute("DELETE FROM notes WHERE path = ?", (rel_path,))

    conn.execute(
        "INSERT INTO notes (path, type, date, project, title, source_session, "
        "source_note, tags, status, mtime, size, body, importance, tfidf_vector) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            tfidf_json,
        ),
    )

    # Get the rowid for FTS insert
    rowid = conn.execute(
        "SELECT rowid FROM notes WHERE path = ?", (rel_path,)
    ).fetchone()["rowid"]
    conn.execute(
        "INSERT INTO notes_fts (rowid, title, body, tags) VALUES (?, ?, ?, ?)",
        (
            rowid,
            parsed.get("title", ""),
            parsed.get("body", ""),
            parsed.get("tags", ""),
        ),
    )


def _delete_note(conn: sqlite3.Connection, rel_path: str) -> None:
    """Remove a note + FTS row + term_df contribution + theme memberships.

    Also reverses the note's contribution to any theme centroid it was a
    member of, so that `themes.note_count` and the running-average
    centroid stay consistent with the surviving `theme_members` rows.
    If the note was the theme's last member, the theme is dropped.

    For contentless FTS5, we issue the special 'delete' command with the
    prior column values before DROPping the notes row, so the FTS index
    doesn't accumulate orphan entries across the vault's lifetime.
    """
    old_terms = _prior_tokens_for(conn, rel_path)

    # Fetch the note's tfidf_vector AND FTS payload BEFORE deletion —
    # needed for both centroid unfolding and the FTS special delete.
    note_vec: dict[str, float] = {}
    vec_row = conn.execute(
        "SELECT rowid, title, body, tags, tfidf_vector FROM notes WHERE path = ?",
        (rel_path,),
    ).fetchone()
    if vec_row and vec_row["tfidf_vector"]:
        try:
            note_vec = json.loads(vec_row["tfidf_vector"]) or {}
        except json.JSONDecodeError:
            note_vec = {}

    # Update each theme the note was a member of. Walk the memberships
    # before deleting them so we know which themes to touch.
    memberships = conn.execute(
        "SELECT theme_id FROM theme_members WHERE note_path = ?", (rel_path,)
    ).fetchall()
    today = date.today().isoformat()
    for m in memberships:
        theme_id = m["theme_id"]
        theme_row = conn.execute(
            "SELECT centroid, note_count FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        if not theme_row:
            continue
        count = theme_row["note_count"] or 0
        if count <= 1:
            # Last member — drop the theme entirely rather than leave it
            # with count=0 and a stale centroid. Cascade-delete any stray
            # theme_members rows pointing at this theme_id as defense-in-
            # depth (count=1 should mean only one member, but any earlier
            # invariant violation shouldn't leave zombie rows behind).
            conn.execute(
                "DELETE FROM theme_members WHERE theme_id = ?", (theme_id,)
            )
            conn.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
            continue
        try:
            centroid = json.loads(theme_row["centroid"]) if theme_row["centroid"] else {}
        except json.JSONDecodeError:
            centroid = {}
        new_count = count - 1
        new_centroid: dict[str, float] = {}
        all_terms = set(centroid) | set(note_vec)
        for term in all_terms:
            c_val = centroid.get(term, 0.0)
            v_val = note_vec.get(term, 0.0)
            # Reverse the running-average fold:
            # old_centroid = (centroid*count - note_vec) / (count - 1)
            new_val = (c_val * count - v_val) / new_count
            # Prune near-zero terms to keep the centroid sparse.
            if abs(new_val) > 1e-9:
                new_centroid[term] = new_val
        conn.execute(
            "UPDATE themes "
            "SET centroid = ?, note_count = ?, updated_date = ? "
            "WHERE id = ?",
            (json.dumps(new_centroid, separators=(",", ":")),
             new_count, today, theme_id),
        )

    # Remove the FTS row before the notes DELETE. Contentless FTS5 rejects
    # DELETE FROM; the special 'delete' command with the prior column
    # values is the only supported removal path.
    if vec_row is not None:
        conn.execute(
            "INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) "
            "VALUES('delete', ?, ?, ?, ?)",
            (
                vec_row["rowid"],
                vec_row["title"] or "",
                vec_row["body"] or "",
                vec_row["tags"] or "",
            ),
        )
    conn.execute("DELETE FROM notes WHERE path = ?", (rel_path,))
    conn.execute("DELETE FROM theme_members WHERE note_path = ?", (rel_path,))
    if old_terms:
        _update_term_df(conn, old_terms=old_terms, new_terms=set())


def _sync(conn: sqlite3.Connection, vault_path: str, folders: list[str]) -> dict:
    """Incremental sync: add new/changed files, remove deleted ones.

    Returns {"inserted": N, "skipped": M, "deleted": D, "by_type": {...}}.

    Wraps the entire pass in BEGIN IMMEDIATE + commit/rollback so a mid-
    loop failure doesn't leave a half-applied transaction attached to
    the connection (which would poison subsequent callers).
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

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Delete removed files (only if they belong to a scanned folder).
        # Use Path.is_relative_to() rather than str.startswith() so that
        # sibling folders with a shared prefix (e.g. 'claude-sessions-archive'
        # vs 'claude-sessions') are not treated as nested.
        scanned_roots = [vault / f for f in folders]
        for abs_path_str in list(indexed.keys()):
            if abs_path_str not in disk_files:
                indexed_path = Path(abs_path_str)
                if any(
                    _is_under(indexed_path, root) for root in scanned_roots
                ):
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
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
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
            if _needs_tfidf_vector_migration(conn):
                _add_tfidf_vector_column(conn)
            _ensure_theme_indexes(conn)
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
                if _needs_tfidf_vector_migration(conn):
                    _add_tfidf_vector_column(conn)
                _ensure_theme_indexes(conn)
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
            if _needs_tfidf_vector_migration(conn):
                _add_tfidf_vector_column(conn)
            _ensure_theme_indexes(conn)
            _sync(conn, vault_path, folders)
        finally:
            conn.close()

    # Set permissions
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass

    return db_path


# Per-process cache keyed by snapshot path → resolved parent path (or None).
# Not invalidated on re-index — snapshot frontmatter changes take effect next
# process lifetime. Cleared when the process exits; intentionally not persisted.
_PARENT_CACHE: dict[str, str | None] = {}


def _parent_session_for_snapshot(note_path: str, db_path: str) -> str | None:
    """Return the absolute path of the parent session note for a snapshot,
    or None if the input isn't a snapshot or the parent can't be resolved.

    Strategy:
      1. Check per-process cache.
      2. Query notes table for the row; if type != 'claude-snapshot', return None.
      3. Read the snapshot file's frontmatter source_session_note wikilink;
         resolve to <sessions_folder>/<stem>.md. If the file exists, cache
         and return it. If not, cache None and return None.

    Swallows all exceptions — logging is observability, not a blocker.

    Cache entries are NOT invalidated when a snapshot is re-indexed; a
    corrected ``source_session_note`` won't take effect until the next process
    restart. This is a deliberate tradeoff — rename-after-first-access is rare
    and invalidation complexity outweighs the benefit.
    """
    if note_path in _PARENT_CACHE:
        return _PARENT_CACHE[note_path]
    resolved: str | None = None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            row = conn.execute(
                "SELECT type FROM notes WHERE path = ?", (note_path,),
            ).fetchone()
            if not row:
                # Not indexed yet — don't cache; retry on next call.
                return None
            if row[0] != "claude-snapshot":
                _PARENT_CACHE[note_path] = None
                return None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # Transient DB errors (locked, busy, corrupt-for-one-tx) — don't poison
        # the cache; next call retries.
        print(f"[vault-index] parent-resolve DB error for {note_path!r}: {exc}",
              file=sys.stderr)
        return None

    try:
        # Extract source_session_note from the snapshot's frontmatter.
        with open(note_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(2048)
    except OSError as exc:
        # File gone / unreadable — permanent miss for this process lifetime.
        print(f"[vault-index] parent-resolve read error for {note_path!r}: {exc}",
              file=sys.stderr)
        _PARENT_CACHE[note_path] = None
        return None

    # Accept double-quoted, single-quoted, AND unquoted wikilink values —
    # YAML frontmatter allows all three and hand-edits may use any. Copilot
    # PR #43 finding: stricter `"?...` regex silently failed on single-quoted
    # values and poisoned the cache with None.
    m = re.search(r"^source_session_note:\s*['\"]?\[\[([^\]'\"]+)\]\]['\"]?",
                  head, re.MULTILINE)
    if not m:
        _PARENT_CACHE[note_path] = None
        return None
    parent_stem = m.group(1)
    parent_path = os.path.join(os.path.dirname(note_path), f"{parent_stem}.md")
    if os.path.isfile(parent_path):
        resolved = parent_path

    _PARENT_CACHE[note_path] = resolved
    return resolved


def log_access(db_path: str, note_path: str, context_type: str, project: str | None = None) -> None:
    """Insert an access-log row for note_path, cascading to parent session
    if note_path is a snapshot.

    The cascade runs in the same connection under a single executemany, so
    either both rows land or neither does. Broken snapshot backlinks are
    tolerated — the parent is simply skipped, the snapshot is still logged.
    """
    paths = [note_path]
    parent = _parent_session_for_snapshot(note_path, db_path)
    if parent:
        paths.append(parent)

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            now = time.time()
            conn.executemany(
                "INSERT INTO access_log (note_path, timestamp, context_type, project) "
                "VALUES (?, ?, ?, ?)",
                [(p, now, context_type, project) for p in paths],
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[vault-index] log_access failed for {note_path!r}: {exc}", file=sys.stderr)


def _batch_log_access(
    conn: sqlite3.Connection,
    note_paths: list[str],
    context_type: str,
    project: str | None | list[str | None] = None,
) -> None:
    """Insert N access-log rows on an existing connection in one round-trip.

    ``project`` may be a single value applied to every row, or a list of the
    same length as ``note_paths`` to preserve per-row project attribution.
    Reuses the caller's connection (no new connect/close) and commits once
    via executemany. Swallows exceptions but logs to stderr — access logging
    is observability, not a blocker.
    """
    if not note_paths:
        return
    try:
        if isinstance(project, list):
            if len(project) != len(note_paths):
                raise ValueError(
                    f"_batch_log_access: project list length "
                    f"{len(project)} != note_paths length {len(note_paths)}"
                )
            projects = project
        else:
            projects = [project] * len(note_paths)
        now = time.time()
        conn.executemany(
            "INSERT INTO access_log (note_path, timestamp, context_type, project) "
            "VALUES (?, ?, ?, ?)",
            [
                (p, now, context_type, proj)
                for p, proj in zip(note_paths, projects)
            ],
        )
        conn.commit()
    except Exception as exc:
        print(f"[vault-index] _batch_log_access failed for "
              f"{len(note_paths)} paths: {exc}", file=sys.stderr)


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


def rebuild_index(
    vault_path: str,
    folders: list[str],
    db_path: str | None = None,
    full: bool = False,
) -> dict:
    """Rebuild the vault index.

    Default (``full=False``): non-destructive incremental sync. Preserves
    Friston-architecture state (``access_log`` activation history, ``themes``,
    ``theme_members`` surprise scores + centroids) and reconciles the index
    with current vault contents via ``_sync`` (which is mtime-incremental —
    unchanged notes are not re-tokenised). Rows whose paths are outside the
    current scanned folders are removed (pytest fixture pollution cleanup).
    After the sync, orphaned ``access_log`` / ``theme_members`` rows whose
    note paths are no longer on disk are pruned and ``themes.note_count`` is
    recomputed from the surviving memberships; themes that lose all members
    are dropped. This mode is right for clearing pollution or bulk vault
    edits, but it is **not** a guaranteed full rebuild of derivable index
    data for unchanged notes — if an FTS row or ``term_df`` counter has
    drifted for a note that hasn't changed on disk, only ``full=True`` will
    fix it.

    Opt-in ``full=True``: legacy destructive behavior. Deletes the entire DB
    file (plus WAL/SHM) and rebuilds from an empty schema. Every Friston
    field is lost. Required only when the schema is corrupt or incompatible,
    or when the derivable tables need a clean-slate rebuild.

    Returns ``{"inserted": N, "skipped": M, "by_type": {...}}`` plus, in
    non-destructive mode, ``"preserved": {...}`` and ``"pruned_orphans":
    {...}`` reporting the Friston-table delta.
    """
    if db_path is None:
        db_path = _default_db_path()

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # A fresh DB has nothing to preserve — fall through to full rebuild even
    # when full=False, so callers always get a working index.
    if not os.path.isfile(db_path):
        full = True

    if full:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except FileNotFoundError:
                pass
            # Any other OSError (PermissionError, IsADirectoryError, EBUSY,
            # read-only filesystem, etc.) must surface — a silently-failed
            # remove would leave stale state for _init_schema to run against.

        conn = _connect(db_path)
        try:
            _init_schema(conn)
            _ensure_access_log_indexes(conn)
            _ensure_theme_indexes(conn)
            stats = _sync(conn, vault_path, folders)
        finally:
            conn.close()
    else:
        conn = _connect(db_path)
        try:
            _init_schema(conn)
            _ensure_access_log_indexes(conn)
            if _needs_importance_migration(conn):
                _add_importance_column(conn)
            if _needs_tfidf_vector_migration(conn):
                _add_tfidf_vector_column(conn)
            _ensure_theme_indexes(conn)

            # Pre-body-column DBs require a full rebuild; _sync would crash
            # on the missing column. Fall through to full=True path.
            if _needs_body_migration(conn):
                print(
                    f"[vault-index] Preserve-mode rebuild saw legacy schema "
                    f"(missing body column); falling through to full rebuild",
                    file=sys.stderr,
                )
                conn.close()
                return rebuild_index(vault_path, folders, db_path=db_path, full=True)

            before_access = conn.execute(
                "SELECT COUNT(*) FROM access_log"
            ).fetchone()[0]
            before_themes = conn.execute(
                "SELECT COUNT(*) FROM themes"
            ).fetchone()[0]
            before_members = conn.execute(
                "SELECT COUNT(*) FROM theme_members"
            ).fetchone()[0]

            # Step 1: Targeted cleanup — drop rows whose paths are OUTSIDE
            # all scanned roots (pytest fixture pollution, stale-mounted
            # vaults, etc.). _sync itself skips these because they're not
            # under any folder it's responsible for. Done in a short
            # explicit transaction so its rollback is self-contained.
            vault_p = Path(vault_path)
            scanned_roots = [vault_p / f for f in folders]
            foreign = [
                row[0]
                for row in conn.execute("SELECT path FROM notes").fetchall()
                if not any(
                    _is_under(Path(row[0]), root) for root in scanned_roots
                )
            ]
            try:
                conn.execute("BEGIN IMMEDIATE")
                for abs_path in foreign:
                    _delete_note(conn, abs_path)
                conn.commit()
            except BaseException:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise

            # Step 2: Incremental re-sync from disk. _sync wraps its own
            # pass in BEGIN IMMEDIATE with commit/rollback, so a mid-loop
            # failure leaves access_log (which we haven't touched) and
            # the preserved rows from Step 1 intact.
            stats = _sync(conn, vault_path, folders)

            # Step 3: Orphan prune for access_log / theme_members. Path-
            # format invariant: note_path columns and notes.path must all
            # store absolute paths. A caller that wrote relative paths
            # would, without this guard, have every such row classified
            # as orphan and silently purged. Sample the about-to-be-
            # deleted rows across BOTH tables — a drift in theme_members
            # alone (while access_log stays clean) would still cause
            # irreversible Friston data loss through the theme_members
            # DELETE below. Use os.path.isabs() rather than startswith("/")
            # so the check stays platform-correct.
            access_sample = conn.execute(
                "SELECT note_path FROM access_log "
                "WHERE note_path NOT IN (SELECT path FROM notes) "
                "LIMIT 5"
            ).fetchall()
            member_sample = conn.execute(
                "SELECT note_path FROM theme_members "
                "WHERE note_path NOT IN (SELECT path FROM notes) "
                "LIMIT 5"
            ).fetchall()
            sample = access_sample + member_sample
            suspicious = [
                row[0] for row in sample if not os.path.isabs(row[0])
            ]
            try:
                conn.execute("BEGIN IMMEDIATE")
                if suspicious:
                    print(
                        f"[vault-index] rebuild_index: path-format drift — "
                        f"{len(suspicious)} of {len(sample)} sampled "
                        f"access_log rows use non-absolute paths "
                        f"({suspicious!r}); skipping orphan prune to "
                        f"avoid mass data loss",
                        file=sys.stderr,
                    )
                else:
                    conn.execute(
                        "DELETE FROM access_log "
                        "WHERE note_path NOT IN (SELECT path FROM notes)"
                    )
                    conn.execute(
                        "DELETE FROM theme_members "
                        "WHERE note_path NOT IN (SELECT path FROM notes)"
                    )
                # Theme invariant repair: after any theme_members rows have
                # been removed (either by _delete_note during _sync or the
                # orphan-prune above), recompute themes.note_count from the
                # surviving membership set and drop themes that now have
                # zero members. Keeps assign_to_theme / _delete_note's
                # running-average centroid math self-consistent.
                conn.execute(
                    "UPDATE themes SET note_count = ("
                    "  SELECT COUNT(*) FROM theme_members "
                    "  WHERE theme_members.theme_id = themes.id"
                    ")"
                )
                conn.execute("DELETE FROM themes WHERE note_count = 0")
                conn.commit()
            except BaseException:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise

            # Report preserved/pruned counts from the actual after-state
            # rather than deleted rowcount. _sync and _delete_note also
            # remove theme_members rows (and may drop last-member themes)
            # when a parent note is deleted, so a simple rowcount would
            # undercount by missing those.
            after_access = conn.execute(
                "SELECT COUNT(*) FROM access_log"
            ).fetchone()[0]
            after_themes = conn.execute(
                "SELECT COUNT(*) FROM themes"
            ).fetchone()[0]
            after_members = conn.execute(
                "SELECT COUNT(*) FROM theme_members"
            ).fetchone()[0]
            stats["preserved"] = {
                "access_log": after_access,
                "themes": after_themes,
                "theme_members": after_members,
            }
            stats["pruned_orphans"] = {
                "access_log": before_access - after_access,
                "themes": before_themes - after_themes,
                "theme_members": before_members - after_members,
            }
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
    except sqlite3.Error as exc:
        # Previously this branch silently returned False — the caller
        # (upgrade_note_with_summary) would then skip theme assignment with
        # no trace in stderr, leaving operators guessing. Always leave a
        # breadcrumb so theme-pipeline declines are diagnosable.
        print(f"[vault-index] index_note could not open {db_path}: {exc}",
              file=sys.stderr)
        return False

    try:
        try:
            # BEGIN IMMEDIATE so _upsert_note's read-modify-write
            # (_prior_tokens_for → _update_term_df → SELECT COUNT → INSERT)
            # is serialized against other writers (concurrent hooks,
            # _sync runs). Matches assign_to_theme's locking discipline.
            conn.execute("BEGIN IMMEDIATE")
            _upsert_note(conn, note_path, parsed, st.st_mtime, st.st_size)
            conn.commit()
            return True
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            print(f"[vault-index] index_note failed for {note_path}: {exc}",
                  file=sys.stderr)
            return False
    finally:
        conn.close()


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
        # Log access for returned results (single connection, one commit).
        # Per-row project preserves each note's project attribution for
        # per-project analytics, even when the search itself was unscoped.
        _batch_log_access(
            conn,
            [r["path"] for r in results],
            "search",
            project=[r.get("project") for r in results],
        )
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
# TF-IDF primitives (stdlib-first, numpy optional)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize_for_tfidf(text: str) -> list[str]:
    """Tokenize text for TF-IDF: lowercase alphanumerics, drop stopwords + single chars.

    Order is preserved (token occurrences count — duplicates are kept) so the
    caller can compute TF by counting. Returns [] for empty or all-stopword input.

    Single-character tokens (both letters like "a" and digits like "3" or "9"
    from expressions such as "Python-3.9") are dropped. Single digits appear
    in few documents initially, which inflates their IDF and lets them
    outrank real semantic terms in the sparse top-k — so letter and digit
    noise are both removed uniformly.
    """
    if not text:
        return []
    lowered = text.lower()
    return [
        t for t in _TOKEN_RE.findall(lowered)
        if len(t) > 1 and t not in _STOPWORDS
    ]


def _compute_tfidf_vector(
    tokens: list[str],
    term_df: dict[str, int],
    total_docs: int,
    top_k: int = 50,
) -> dict[str, float]:
    """Compute a sparse TF×IDF vector keeping the top_k heaviest terms.

    tokens:       output of _tokenize_for_tfidf() for the document
    term_df:      {term: document_frequency} for the corpus
    total_docs:   total indexed documents (including this one if it is new;
                  callers using incremental updates should increment total_docs
                  BEFORE calling this function for a newly-inserted note)
    top_k:        maximum number of terms to retain in the sparse vector

    Returns {} when tokens is empty. Uses smoothed IDF
    (1 + ln((N + 1) / (df + 1))) so new / rare terms never produce 0 or NaN.
    """
    if not tokens:
        return {}

    tf: dict[str, int] = defaultdict(int)
    for t in tokens:
        tf[t] += 1

    weights: dict[str, float] = {}
    n_plus_one = total_docs + 1
    for term, count in tf.items():
        df = term_df.get(term, 0)
        idf = 1.0 + math.log(n_plus_one / (df + 1))
        weights[term] = count * idf

    top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return dict(top)


def _cosine_similarity(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity between two sparse dict vectors. Returns 0.0 on empty input.

    Iterates the smaller dict to compute the dot product, which keeps the
    inner loop bounded even when one vector is much larger than the other.
    """
    if not v1 or not v2:
        return 0.0

    if len(v1) > len(v2):
        v1, v2 = v2, v1

    dot = 0.0
    for term, w in v1.items():
        other = v2.get(term)
        if other is not None:
            dot += w * other

    if dot == 0.0:
        return 0.0

    norm1 = math.sqrt(sum(w * w for w in v1.values()))
    norm2 = math.sqrt(sum(w * w for w in v2.values()))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def _update_term_df(
    conn: sqlite3.Connection,
    old_terms: set[str],
    new_terms: set[str],
) -> None:
    """Adjust document-frequency counts for a note whose terms changed.

    Compares the two sets and applies a +1 / -1 per term via executemany.
    Terms whose df falls to zero are deleted so the IDF denominator stays
    clean. The caller is responsible for committing the transaction — this
    helper writes through ``conn`` but does not commit, so it can be
    batched atomically with a note upsert or delete.
    """
    removed = old_terms - new_terms
    added = new_terms - old_terms
    if not removed and not added:
        return

    cur = conn.cursor()

    if added:
        cur.executemany(
            "INSERT INTO term_df (term, df) VALUES (?, 1) "
            "ON CONFLICT(term) DO UPDATE SET df = df + 1",
            [(t,) for t in added],
        )

    if removed:
        cur.executemany(
            "UPDATE term_df SET df = df - 1 WHERE term = ?",
            [(t,) for t in removed],
        )
        cur.execute("DELETE FROM term_df WHERE df <= 0")


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

        # Log access for returned results (single connection, one commit)
        _batch_log_access(
            conn,
            [r["path"] for r in results[:limit]],
            "related",
            project=project,
        )
        return results[:limit]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Theme assignment (incremental)
# ---------------------------------------------------------------------------


_THEME_SIMILARITY_THRESHOLD = 0.3


def assign_to_theme(
    db_path: str,
    note_path: str,
    project: str | None = None,
    similarity_threshold: float = _THEME_SIMILARITY_THRESHOLD,
) -> dict | None:
    """Incrementally assign a summarized note to its nearest theme (if any).

    Reads the note's tfidf_vector and compares against every project-scoped
    theme centroid plus any cross-project themes (project IS NULL). If the
    best similarity exceeds ``similarity_threshold``, adds a theme_members
    row and updates the theme's centroid via running average.

    Returns {"theme_id": int, "similarity": float} on assignment, or None
    if no theme was close enough (or the note has no vector).
    """
    if not os.path.isfile(db_path):
        return None

    try:
        conn = _connect(db_path)
    except sqlite3.Error as exc:
        print(f"[vault-index] assign_to_theme could not connect: {exc}",
              file=sys.stderr)
        return None

    try:
        # Take the write lock BEFORE reading candidates so the
        # read-modify-write cycle is atomic against concurrent writers.
        # Other callers block for up to the connection's timeout (5s in
        # _connect()) before sqlite3 raises OperationalError.
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT tfidf_vector FROM notes WHERE path = ?", (note_path,)
            ).fetchone()
            if not row or not row["tfidf_vector"]:
                conn.commit()
                return None
            try:
                note_vec = json.loads(row["tfidf_vector"])
            except json.JSONDecodeError:
                conn.commit()
                return None
            if not note_vec:
                conn.commit()
                return None

            # When project is None (global/unscoped recall), "project = ?"
            # binds to NULL and matches no rows because `NULL = NULL` is
            # false in SQL — only project-scoped themes with project IS
            # NULL would match. Branch the query so unscoped callers see
            # every theme, and scoped callers see their own + cross-project.
            if project is None:
                candidates = conn.execute(
                    "SELECT id, centroid, note_count FROM themes"
                ).fetchall()
            else:
                candidates = conn.execute(
                    "SELECT id, centroid, note_count FROM themes "
                    "WHERE project = ? OR project IS NULL",
                    (project,),
                ).fetchall()

            best: tuple[float, int, dict, int] | None = None
            for cand in candidates:
                if not cand["centroid"]:
                    continue
                try:
                    centroid = json.loads(cand["centroid"])
                except json.JSONDecodeError:
                    continue
                sim = _cosine_similarity(note_vec, centroid)
                if best is None or sim > best[0]:
                    best = (sim, cand["id"], centroid, cand["note_count"])

            if best is None or best[0] < similarity_threshold:
                conn.commit()
                return None

            sim, theme_id, centroid, count = best
            today = date.today().isoformat()

            # Detect reassignment: if the note is already a member, the
            # centroid already reflects its contribution — updating count
            # and re-averaging would double-count it and drift the centroid.
            already_member = conn.execute(
                "SELECT 1 FROM theme_members "
                "WHERE theme_id = ? AND note_path = ?",
                (theme_id, note_path),
            ).fetchone() is not None

            if not already_member:
                new_centroid: dict[str, float] = {}
                all_terms = set(centroid) | set(note_vec)
                for term in all_terms:
                    c_val = centroid.get(term, 0.0)
                    v_val = note_vec.get(term, 0.0)
                    new_centroid[term] = (c_val * count + v_val) / (count + 1)

                conn.execute(
                    "UPDATE themes "
                    "SET centroid = ?, note_count = ?, updated_date = ? "
                    "WHERE id = ?",
                    (json.dumps(new_centroid, separators=(",", ":")),
                     count + 1, today, theme_id),
                )
            else:
                # Reassignment: bump updated_date but leave count/centroid
                # alone. The member's similarity is refreshed below.
                conn.execute(
                    "UPDATE themes SET updated_date = ? WHERE id = ?",
                    (today, theme_id),
                )

            # Preserve surprise + added_date on reassignment — only
            # similarity is refreshed from the latest cosine computation.
            conn.execute(
                "INSERT INTO theme_members "
                "(theme_id, note_path, similarity, surprise, added_date) "
                "VALUES (?, ?, ?, 0.0, ?) "
                "ON CONFLICT(theme_id, note_path) DO UPDATE SET "
                "similarity = excluded.similarity",
                (theme_id, note_path, sim, today),
            )
            conn.commit()
            return {"theme_id": theme_id, "similarity": sim}
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


_NEGATION_TERMS = frozenset({
    # Simple negation / failure words
    "not", "never", "failed", "broken", "wrong", "mistake",
    "avoid", "no", "cannot",
    # Contractions — bare forms only. detect_surprise() strips apostrophes
    # from note_text before tokenizing, so "don't"/"won't"/"isn\u2019t"
    # in source text collapse to "dont"/"wont"/"isnt" and match here.
    # Apostrophed variants (e.g. "don't") would never match post-
    # tokenization and are intentionally omitted.
    "dont", "cant", "wont", "isnt", "arent", "wasnt", "werent",
    "didnt", "doesnt", "couldnt", "shouldnt", "wouldnt",
    "hasnt", "havent", "hadnt",
})


def detect_surprise(
    note_text: str,
    note_vec: dict[str, float],
    theme_centroid: dict[str, float],
    window: int = 8,
    top_shared: int = 10,
) -> float:
    """Heuristic Free-Energy surprise score for a note vs. its theme centroid.

    Returns the fraction of the top_shared shared TF-IDF terms that appear
    within ``window`` tokens of a negation word in ``note_text``. Clamped
    to [0.0, 1.0]. Zero on missing overlap or empty input.
    """
    if not note_text or not note_vec or not theme_centroid:
        return 0.0

    shared = [
        (t, min(note_vec[t], theme_centroid[t]))
        for t in set(note_vec) & set(theme_centroid)
    ]
    if not shared:
        return 0.0
    shared.sort(key=lambda kv: (-kv[1], kv[0]))
    shared_terms = [t for t, _ in shared[:top_shared]]

    # Strip apostrophes (straight + smart) before tokenizing so contractions
    # like "don't" / "can't" collapse to "dont"/"cant" and match the
    # negation set. Without this, _TOKEN_RE = [a-z0-9]+ would emit
    # "don", "t" and the negation check would silently miss every
    # apostrophed negation in the source text.
    normalized = (
        note_text.lower()
        .replace("\u2019", "")  # right single quote (smart apostrophe)
        .replace("\u2018", "")  # left single quote
        .replace("'", "")       # straight apostrophe
    )
    tokens = _TOKEN_RE.findall(normalized)
    if not tokens:
        return 0.0

    negation_positions = [
        i for i, t in enumerate(tokens) if t in _NEGATION_TERMS
    ]
    if not negation_positions:
        return 0.0

    hits = 0
    for term in shared_terms:
        term_positions = [i for i, t in enumerate(tokens) if t == term]
        for p in term_positions:
            if any(abs(p - n) <= window for n in negation_positions):
                hits += 1
                break

    score = hits / len(shared_terms)
    return max(0.0, min(1.0, score))
