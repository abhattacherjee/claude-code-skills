"""vault_doctor check: detect and repair stale source_session backlinks.

Detection strategy:
  For each insight-type note with a `source_session` frontmatter field,
  read the note's file mtime as the "capture time." For each JSONL file
  under ~/.claude/projects/*<project>/*.jsonl, determine its activity
  window (first entry timestamp → file mtime). The correct source session
  is the JSONL whose window contains the note's capture time. Flag as
  stale whenever the note's current source_session does not match.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import Issue, Result

NAME = "source-sessions"
DESCRIPTION = "Detect and repair stale source_session backlinks"
DEFAULT_WINDOW_DAYS = 7

# Auxiliary insight-type folders we always scan in addition to the
# user-configured insights folder. These are conventional names; if a user
# customizes them, they can add a follow-up feature request.
_EXTRA_INSIGHT_FOLDERS = [
    "claude-decisions",
    "claude-error-fixes",
    "claude-retros",
]

# Regex helpers for minimal frontmatter parsing (stdlib only — no yaml dep)
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Character class used to sanitize a project name into a filesystem-safe
# path component. Anything outside [A-Za-z0-9_-] is replaced with '_'.
_SAFE_PROJECT_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _safe_project_slug(project: str) -> str:
    """Sanitize a project name for use as a filesystem path component.

    Replaces any character that isn't alphanumeric, underscore, or hyphen
    with an underscore. Empty or dot-only results become 'unknown' so the
    resulting path can never escape the parent directory via '..' tricks.
    This is used when joining an untrusted frontmatter `project` value onto
    a backup directory root in apply().
    """
    if not project:
        return "unknown"
    # Strip dots FIRST, before the regex replacement. A dot-only input like
    # "..." would otherwise become "___" after sub() and the subsequent
    # strip(".") would be a no-op, leaving an ugly placeholder instead of
    # collapsing to "unknown". Stripping dots first also defeats any
    # leading/trailing '..' path-traversal pattern regardless of how the
    # character class evolves.
    stripped = project.strip(".")
    if not stripped:
        return "unknown"
    slug = _SAFE_PROJECT_RE.sub("_", stripped)
    return slug or "unknown"


def _parse_frontmatter(text: str) -> dict:
    """Parse a flat key: value YAML frontmatter block. Nested blocks ignored."""
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if not line or line.startswith(" ") or line.startswith("-"):
            continue  # skip list items and nested keys
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _parse_iso_ts(ts: str) -> float | None:
    """Parse ISO 8601 timestamp to a POSIX float, or None on failure."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def _jsonl_window(jsonl_path: str) -> tuple[float, float] | None:
    """Return (first_entry_ts, mtime) for a JSONL session file, or None.

    Returns None when the file is unreadable or every line fails to parse.
    Falls back to `mtime - 3600` ONLY when lines parsed successfully but no
    entry had a 'timestamp' field — this is a known JSONL schema variant.
    A fully corrupt file returns None so `_find_matching_session` skips it
    rather than fabricating a window that could produce false-positive
    stale flags.
    """
    try:
        mtime = os.path.getmtime(jsonl_path)
    except OSError:
        return None
    first_ts: float | None = None
    parsed_any = False
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parsed_any = True
                ts = _parse_iso_ts(entry.get("timestamp", ""))
                if ts is not None:
                    first_ts = ts
                    break
    except OSError:
        return None
    if first_ts is None:
        if not parsed_any:
            print(
                f"[vault_doctor] JSONL has no parseable lines: {jsonl_path}",
                file=sys.stderr,
            )
            return None
        first_ts = mtime - 3600
    return (first_ts, mtime)


def _jsonl_dir_for_project(project: str) -> Path | None:
    """Find ~/.claude/projects/*<project>/ directory for this project name.

    Wraps os.path.getmtime in a try/except so a transient filesystem race
    (a matched directory being deleted between glob and stat) cannot crash
    the scan. Directories that disappear mid-scan are treated as missing.
    """
    home = os.environ.get("HOME", os.path.expanduser("~"))
    # glob.escape() neutralizes '*', '?', and '[' inside the project name so a
    # project called e.g. "foo[bar]" cannot cause the glob to match unintended
    # directories under ~/.claude/projects/. The leading '*' before the
    # (escaped) project remains a real wildcard — that's how we match the
    # path-encoded prefix Claude Code adds to the directory name.
    safe_project = glob.escape(project)
    pattern = os.path.join(home, ".claude", "projects", f"*{safe_project}")
    matches = glob.glob(pattern)
    if not matches:
        return None

    def _safe_mtime(p: str) -> float:
        try:
            return os.path.getmtime(p)
        except OSError:
            return -1.0  # treat as effectively-missing

    scored = [(m, _safe_mtime(m)) for m in matches]
    viable = [(m, t) for m, t in scored if t >= 0]
    if not viable:
        return None
    # Pick the most recently modified directory if multiple match (path
    # encoding variants). Deterministic tiebreak: sort by (mtime, path) so
    # same-mtime dirs pick the same winner across runs instead of depending
    # on glob order. Matches the (mtime, path) pattern used for JSONL
    # selection elsewhere in the fast path.
    return Path(max(viable, key=lambda pair: (pair[1], pair[0]))[0])


def _list_session_notes(sessions_dir: Path, project: str) -> dict[str, dict]:
    """Map session_id → {path, basename, date} for a project's session notes."""
    out: dict[str, dict] = {}
    if not sessions_dir.is_dir():
        return out
    for entry in sessions_dir.iterdir():
        if not entry.name.endswith(".md"):
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        if not fm and text.startswith("---"):
            print(
                f"[vault_doctor] malformed frontmatter, skipped: {entry}",
                file=sys.stderr,
            )
            continue
        if fm.get("project") != project:
            continue
        sid = fm.get("session_id", "")
        if not sid:
            continue
        out[sid] = {
            "path": entry,
            "basename": entry.name[:-3],
            "date": fm.get("date", ""),
        }
    return out


def _find_matching_session(
    capture_time: float,
    jsonl_dir: Path | None,
    session_note_index: dict[str, dict],
) -> dict | None:
    """Return the session note dict (+ 'sid' key) whose JSONL window contains capture_time.

    Iteration is deterministic (sorted by filename). When multiple windows
    contain capture_time (boundary tie between a previous session's end and
    a new session's start), the session with the LATEST first_ts wins — the
    most recently started session is the one actively capturing insights.
    """
    if not jsonl_dir or not jsonl_dir.is_dir():
        return None
    candidates: list[tuple[float, str]] = []
    for jsonl in sorted(jsonl_dir.glob("*.jsonl")):
        sid = jsonl.stem
        if sid not in session_note_index:
            continue
        window = _jsonl_window(str(jsonl))
        if window is None:
            continue
        first_ts, last_ts = window
        if first_ts <= capture_time <= last_ts:
            candidates.append((first_ts, sid))
    if not candidates:
        return None
    # Latest-start wins on boundary ties
    _, best_sid = max(candidates)
    return {**session_note_index[best_sid], "sid": best_sid}


def scan(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    days: int,
    project: str | None = None,
) -> list[Issue]:
    """Detect stale source_session backlinks modified within the last `days` days."""
    vault = Path(vault_path)
    cutoff = time.time() - days * 86400
    sessions_dir = vault / sessions_folder

    # Honor the user's configured insights folder as the primary, then scan
    # the conventional auxiliary folders (decisions, error-fixes, retros)
    # alongside it. Avoid duplicating the primary folder if a user happens
    # to configure it to one of the extras.
    scan_folders = [insights_folder] + [
        f for f in _EXTRA_INSIGHT_FOLDERS if f != insights_folder
    ]

    issues: list[Issue] = []
    session_index_cache: dict[str, dict[str, dict]] = {}
    jsonl_dir_cache: dict[str, Path | None] = {}

    for folder in scan_folders:
        folder_path = vault / folder
        if not folder_path.is_dir():
            continue
        for note in folder_path.iterdir():
            if not note.name.endswith(".md"):
                continue
            try:
                mtime = os.path.getmtime(note)
            except OSError:
                continue
            if mtime < cutoff:
                continue
            try:
                text = note.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            if "source_session" not in fm:
                continue  # non-source-session note type (e.g., standups with source_notes[])
            note_project = fm.get("project", "")
            if not note_project:
                continue
            if project and note_project != project:
                continue

            if note_project not in session_index_cache:
                session_index_cache[note_project] = _list_session_notes(sessions_dir, note_project)
                jsonl_dir_cache[note_project] = _jsonl_dir_for_project(note_project)

            idx = session_index_cache[note_project]
            jsonl_dir = jsonl_dir_cache[note_project]

            current_sid = fm.get("source_session", "")
            raw_src_note = fm.get("source_session_note", "")
            m = _WIKI_RE.search(raw_src_note)
            current_src_basename = m.group(1) if m else ""

            # Build a clean current_source display string. Avoid emitting
            # a bare "[[]]" when the frontmatter is missing or malformed —
            # fall back to the raw value, or an empty string.
            if current_src_basename:
                current_source_display = f"[[{current_src_basename}]]"
            elif raw_src_note:
                current_source_display = raw_src_note
            else:
                current_source_display = ""

            match = _find_matching_session(mtime, jsonl_dir, idx)
            if match is None:
                # No JSONL window contains this mtime. Flag as unresolved ONLY if
                # the current source doesn't resolve to any known session note — that
                # way we don't get false positives on notes whose current source is
                # correct but just doesn't have a matching JSONL window locally.
                if current_sid not in idx:
                    issues.append(
                        Issue(
                            check=NAME,
                            note_path=str(note),
                            project=note_project,
                            current_source=current_source_display,
                            proposed_source="",
                            reason="no session window contains note mtime",
                            confidence=0.0,
                            extra={"unresolved": True},
                        )
                    )
                continue

            if match["sid"] == current_sid:
                continue  # correct

            issues.append(
                Issue(
                    check=NAME,
                    note_path=str(note),
                    project=note_project,
                    current_source=current_source_display,
                    proposed_source=f"[[{match['basename']}]]",
                    reason=(
                        f"note mtime {datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds')}"
                        f" matches session {match['sid'][:8]} window, not current source {current_sid[:8]}"
                    ),
                    confidence=0.95,
                    extra={"proposed_sid": match["sid"]},
                )
            )

    return issues


def _rewrite_frontmatter(text: str, new_sid: str, new_basename: str) -> str:
    """Rewrite only source_session and source_session_note in the frontmatter block.

    Body, tags, and all other frontmatter fields are preserved byte-identically.
    If either field is missing from the block, append it.
    """
    m = _FRONT_RE.match(text)
    if not m:
        raise ValueError("no frontmatter block found")
    fm_block = m.group(1)
    body = text[m.end():]

    new_lines: list[str] = []
    saw_sid = False
    saw_src_note = False
    for line in fm_block.splitlines():
        if line.startswith("source_session:"):
            new_lines.append(f"source_session: {new_sid}")
            saw_sid = True
        elif line.startswith("source_session_note:"):
            new_lines.append(f'source_session_note: "[[{new_basename}]]"')
            saw_src_note = True
        else:
            new_lines.append(line)

    if not saw_sid:
        new_lines.append(f"source_session: {new_sid}")
    if not saw_src_note:
        new_lines.append(f'source_session_note: "[[{new_basename}]]"')

    return "---\n" + "\n".join(new_lines) + "\n---\n" + body


def apply(issues, backup_root) -> list[Result]:
    """Apply fixes: back up each file, then atomically rewrite frontmatter.

    Unresolved issues are skipped. Missing proposed_sid in extra yields
    status='error'. All writes are atomic (temp file + os.replace).
    """
    import shutil
    import tempfile

    results: list[Result] = []
    os.makedirs(backup_root, exist_ok=True)

    for issue in issues:
        if issue.extra.get("unresolved"):
            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="unresolved",
                    backup_path=None,
                    error=None,
                )
            )
            continue

        proposed_sid = issue.extra.get("proposed_sid", "")
        proposed_basename = issue.proposed_source.strip().lstrip("[").rstrip("]")
        if not proposed_sid or not proposed_basename:
            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="error",
                    error="missing proposed_sid or proposed_source",
                )
            )
            continue

        # Stage 1: backup (failure → note unchanged, no backup)
        # issue.project comes from untrusted frontmatter; sanitize it through
        # _safe_project_slug() before joining so a value like "../../../etc"
        # cannot cause the backup write to escape backup_root. The resolved
        # post-check below is defense-in-depth against any future helper bug.
        try:
            # Preserve the source folder name in the backup path to prevent
            # basename collisions across insight-type folders (e.g., an
            # insight and a retro both named 2026-04-10-foo.md would otherwise
            # clobber each other's backups). The resulting layout is
            # <backup_root>/<project>/<folder>/<basename>.
            note_path = Path(issue.note_path)
            source_folder = note_path.parent.name  # e.g., "claude-insights"
            project_backup_dir = (
                Path(backup_root) / _safe_project_slug(issue.project) / source_folder
            )
            project_backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = project_backup_dir / note_path.name
            resolved_root = Path(backup_root).resolve()
            resolved_backup = backup_path.resolve()
            if resolved_root not in resolved_backup.parents:
                raise ValueError(
                    f"backup path {backup_path} would escape backup_root {backup_root}"
                )
            shutil.copy2(issue.note_path, backup_path)
        except (OSError, ValueError) as exc:
            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="error",
                    error=f"backup failed (note unchanged): {exc}",
                )
            )
            continue

        # Capture original stat so we can preserve mtime across the rewrite.
        # scan() uses note mtime as capture_time for JSONL window matching —
        # updating mtime on apply would cause re-runs to re-flag fixed notes.
        try:
            original_stat = os.stat(issue.note_path)
        except OSError as exc:
            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="error",
                    backup_path=str(backup_path),
                    error=f"stat failed: {exc}",
                )
            )
            continue

        # Stage 2: read/patch/atomic-write (failure → note may or may not be
        # patched; backup exists so the user can recover)
        tmp = None
        try:
            with open(issue.note_path, "r", encoding="utf-8") as f:
                text = f.read()
            new_text = _rewrite_frontmatter(text, proposed_sid, proposed_basename)

            fd, tmp = tempfile.mkstemp(
                prefix=".vd-", suffix=".md.tmp", dir=os.path.dirname(issue.note_path)
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_text)
            os.replace(tmp, issue.note_path)
            tmp = None  # replaced successfully; nothing to clean up

            # Restore original atime/mtime so future scans see the same
            # capture_time the scan that flagged this note saw.
            try:
                os.utime(
                    issue.note_path,
                    (original_stat.st_atime, original_stat.st_mtime),
                )
            except OSError as exc:
                # Non-fatal: the rewrite succeeded, but mtime preservation failed.
                # Log to stderr but still mark as applied (backup exists for recovery).
                print(
                    f"[vault_doctor] warning: failed to restore mtime on "
                    f"{issue.note_path}: {exc}",
                    file=sys.stderr,
                )

            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="applied",
                    backup_path=str(backup_path),
                )
            )
        except Exception as exc:  # per-issue isolation; don't abort the loop
            results.append(
                Result(
                    check=NAME,
                    note_path=issue.note_path,
                    status="error",
                    backup_path=str(backup_path),  # user can recover from this
                    error=f"rewrite failed (backup preserved): {type(exc).__name__}: {exc}",
                )
            )
        finally:
            # Best-effort cleanup of any orphaned temp file left behind when
            # os.replace didn't consume it (e.g., exception before/during replace).
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    return results
