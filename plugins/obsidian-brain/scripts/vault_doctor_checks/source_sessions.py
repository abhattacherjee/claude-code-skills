"""vault_doctor check: detect and repair stale source_session backlinks.

Detection strategy:
  For each insight-type note with a `source_session` frontmatter field,
  determine capture-time via an immutable-signal preference chain
  (`created_at` ISO-8601 → `date` YYYY-MM-DD midday UTC → filename prefix
  YYYY-MM-DD-... midday UTC → mtime as low-confidence last resort).
  For each JSONL file under ~/.claude/projects/*<project>/*.jsonl,
  determine its activity window (first entry timestamp → file mtime).
  The correct source session is the JSONL whose window contains the
  note's capture-time. Flag as stale whenever the note's current
  source_session does not match.
"""

from __future__ import annotations

import dataclasses
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


def _parse_frontmatter(text: str, source: str | None = None) -> dict:
    """Parse a flat key: value YAML frontmatter block. Nested blocks ignored.

    Flat-only by design — multiline scalars, folded YAML (``key:\\n  value``),
    block sequences nested under a key, and other non-flat YAML constructs are
    silently skipped. When a key without a same-line value is followed by an
    indented continuation line that looks like folded YAML, a stderr warning
    is emitted once per ``(file, key)`` within this parse (review SF5) so
    operators can spot high-confidence signals being silently degraded to
    mtime fallbacks. Note: dedup is per-call — the same folded key in two
    different files (or two re-parses of the same file) will each warn.

    Args:
        text: full file contents (frontmatter must start at byte 0).
        source: optional path/identifier surfaced in the SF5 warning so the
            offending file is locatable in operator logs.
    """
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    lines = m.group(1).splitlines()
    folded_warned: set[str] = set()
    for i, line in enumerate(lines):
        if not line or line.startswith(" ") or line.startswith("-"):
            continue  # skip list items and nested keys
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not value:
            # Key with no same-line value. If the next line is indented,
            # it's folded/multiline YAML — log once per (file, key) so the
            # silent degradation is visible. Skip the key as before.
            nxt = lines[i + 1] if (i + 1) < len(lines) else ""
            if nxt and (nxt.startswith(" ") or nxt.startswith("\t")):
                tag = f"{source or '?'}::{key}"
                if tag not in folded_warned:
                    folded_warned.add(tag)
                    print(
                        f"[vault_doctor] folded-YAML key skipped "
                        f"(parser is flat-only): {key} "
                        f"(file: {source or 'unknown'})",
                        file=sys.stderr,
                    )
                continue
        out[key] = value
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


def _parse_date_ts(date_str: str, hour: int = 0) -> float | None:
    """Parse a YYYY-MM-DD date string to a POSIX timestamp at `hour`:00 UTC.

    `hour=12` (midday) is used for the diagnostic reason text (the
    capture_time printed in Issue.reason) and for created_at-style
    point-in-window matching as a degraded fallback. It is NOT used by the
    primary day-overlap matcher — that path calls _parse_date_ts(date, hour=0)
    directly to compute day_start, and derives day_end as day_start + 86400.

    `hour=0` (midnight) is used for calendar-day-overlap checks against a
    JSONL window in Phase 1b and in _find_matching_session_by_day_overlap.
    """
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=hour, tzinfo=timezone.utc
        )
        return d.timestamp()
    except ValueError:
        return None


def _parse_date_midpoint(date_str: str) -> float | None:
    """Return the POSIX timestamp at 12:00 UTC of a YYYY-MM-DD date_str.

    Used by _capture_time to convert day-precision signals (frontmatter
    `date`, filename prefix) into a single capture-time anchor for the
    diagnostic reason field. The day-overlap matcher uses _parse_date_ts
    directly with hour=0; this helper is for point-anchor consumers.
    """
    return _parse_date_ts(date_str, hour=12)


def _parse_date_start(date_str: str) -> float | None:
    """Return the POSIX timestamp at 00:00 UTC of a YYYY-MM-DD date_str.

    Currently unused in the production code path; retained as a
    symmetric public helper in case future checks need a midnight anchor.
    """
    return _parse_date_ts(date_str, hour=0)


# Filename prefix YYYY-MM-DD-...
_FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _capture_time(note_path: Path, fm: dict) -> tuple[float, float, str]:
    """Return (POSIX_ts, confidence, signal_name) using immutable signals first.

    Preference order:
      1. fm['created_at'] ISO-8601                 → conf 1.0,  signal 'created_at'
      2. fm['date'] YYYY-MM-DD (interpreted as     → conf 0.9,  signal 'date'
         midpoint of UTC day)
      3. filename prefix YYYY-MM-DD-...            → conf 0.85, signal 'filename'
      4. os.path.getmtime() (last resort)          → conf 0.5,  signal 'mtime'
      5. unreadable file                           → conf 0.0,  signal 'none'

    Confidence is surfaced in the issue payload so the report can
    distinguish high-signal matches from low-signal fallbacks.
    """
    # 1. created_at
    if (ts := _parse_iso_ts(fm.get("created_at", ""))) is not None:
        return (ts, 1.0, "created_at")
    # 2. date (day-precision)
    if (ts := _parse_date_midpoint(fm.get("date", ""))) is not None:
        return (ts, 0.9, "date")
    # 3. filename prefix
    if (m := _FILENAME_DATE_RE.match(note_path.name)):
        if (ts := _parse_date_midpoint(m.group(1))) is not None:
            return (ts, 0.85, "filename")
    # 4. mtime (last resort)
    try:
        return (os.path.getmtime(note_path), 0.5, "mtime")
    except OSError:
        return (0.0, 0.0, "none")


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
        # SF6: parseable lines but no `timestamp` field — log the synthesized
        # 1-hour window so a future schema variant can't silently produce
        # confidently-wrong matches.
        print(
            f"[vault_doctor] JSONL has no timestamp fields; "
            f"using synthetic 1h window: {jsonl_path}",
            file=sys.stderr,
        )
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
    # Fallback: Claude Code normalizes underscores to hyphens in project dirs
    if not matches and "_" in safe_project:
        alt = safe_project.replace("_", "-")
        pattern = os.path.join(home, ".claude", "projects", f"*{alt}")
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
    winner = Path(max(viable, key=lambda pair: (pair[1], pair[0]))[0])
    if len(viable) > 1:
        # SF8: silent picker on collision is invisible to operators when a
        # path-encoding variant masks a real cross-project ambiguity. Log the
        # candidates + winner so it's auditable.
        print(
            f"[vault_doctor] multiple project dirs matched {project}: "
            f"{[m for m, _ in viable]}; using {winner}",
            file=sys.stderr,
        )
    return winner


def _find_jsonl_anywhere(
    sid: str, cache: dict[str, Path | None] | None = None
) -> Path | None:
    """Locate ~/.claude/projects/*/<sid>.jsonl across all CC project dirs.

    UUIDs are globally unique, so this is safe even though it ignores the
    project-name index. Returns the first match (deterministic via sorted)
    or None.

    The project segment uses ``*`` so CC's underscore-to-hyphen slug
    normalization is irrelevant here — there's no need to normalize the
    input project name (the SID alone is sufficient to disambiguate).
    """
    if cache is not None and sid in cache:
        return cache[sid]
    home = os.environ.get("HOME", os.path.expanduser("~"))
    pattern = os.path.join(home, ".claude", "projects", "*", f"{sid}.jsonl")
    matches = sorted(glob.glob(pattern))
    result = Path(matches[0]) if matches else None
    if cache is not None:
        cache[sid] = result
    return result


def _list_all_session_notes(sessions_dir: Path) -> dict[str, dict]:
    """Map session_id → {path, basename, date, project} across ALL projects.

    Used by Phase 1b's UUID-first lookup to handle the case where a note's
    declared `project:` doesn't match its actual source session note's
    `project:` (e.g., insight written from main repo's cwd while the
    session ran in a worktree). The session_id is globally unique, so
    cross-project lookup is safe.

    Iterates entries in sorted order so the winner is deterministic across
    runs (Copilot R5). When two session notes share the same session_id
    (a known possible vault state — typically a vault-import collision or
    a rename gone wrong), warn to stderr instead of silently overwriting.
    """
    out: dict[str, dict] = {}
    if not sessions_dir.is_dir():
        return out
    for entry in sorted(sessions_dir.iterdir()):
        if not entry.name.endswith(".md"):
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text, source=str(entry))
        if not fm:
            if text.startswith("---"):
                print(
                    f"[vault_doctor] malformed frontmatter, skipped: {entry}",
                    file=sys.stderr,
                )
            continue
        sid = fm.get("session_id", "")
        if not sid:
            continue
        if fm.get("type") != "claude-session":
            continue  # skip claude-snapshot — same UUID, not the canonical session
        if sid in out:
            print(
                f"[vault_doctor] duplicate session_id {sid[:8]} across "
                f"{out[sid]['path'].name} and {entry.name} — keeping first "
                f"(sorted-order winner); rename one to disambiguate",
                file=sys.stderr,
            )
            continue
        out[sid] = {
            "path": entry,
            "basename": entry.name[:-3],
            "date": fm.get("date", ""),
            "project": fm.get("project", ""),
        }
    return out


def _list_session_notes(sessions_dir: Path, project: str) -> dict[str, dict]:
    """Map session_id → {path, basename, date} for a project's session notes.

    Iterates in sorted order for a deterministic duplicate-SID winner; warns
    on collisions (Copilot R5; mirrors _list_all_session_notes).
    """
    out: dict[str, dict] = {}
    if not sessions_dir.is_dir():
        return out
    for entry in sorted(sessions_dir.iterdir()):
        if not entry.name.endswith(".md"):
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text, source=str(entry))
        if not fm and text.startswith("---"):
            print(
                f"[vault_doctor] malformed frontmatter, skipped: {entry}",
                file=sys.stderr,
            )
            continue
        if fm.get("project", "").replace("_", "-") != project.replace("_", "-"):
            continue
        sid = fm.get("session_id", "")
        if not sid:
            continue
        if fm.get("type") != "claude-session":
            continue  # skip claude-snapshot — same UUID, not the canonical session
        if sid in out:
            print(
                f"[vault_doctor] duplicate session_id {sid[:8]} across "
                f"{out[sid]['path'].name} and {entry.name} — keeping first "
                f"(sorted-order winner); rename one to disambiguate",
                file=sys.stderr,
            )
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


def _find_matching_session_by_day_overlap(
    date_str: str,
    jsonl_dir: Path | None,
    session_note_index: dict[str, dict],
) -> dict | None:
    """Return the session note dict whose JSONL window has the largest
    overlap with the UTC calendar day of date_str.

    Used for day-precision signals (`date`, `filename`) where a single
    capture_time anchor (e.g., noon UTC) excludes morning-only or
    evening-only sessions. Tie-break: largest overlap, then latest
    first_ts (mirrors point-match behavior).
    """
    if not jsonl_dir or not jsonl_dir.is_dir():
        return None
    day_start = _parse_date_ts(date_str, hour=0)
    if day_start is None:
        return None
    day_end = day_start + 86400
    best_sid: str | None = None
    best_overlap: float = 0
    best_first_ts: float = 0
    for jsonl in sorted(jsonl_dir.glob("*.jsonl")):
        sid = jsonl.stem
        if sid not in session_note_index:
            continue
        window = _jsonl_window(str(jsonl))
        if window is None:
            continue
        first_ts, last_ts = window
        overlap = max(0.0, min(day_end, last_ts) - max(day_start, first_ts))
        if overlap <= 0:
            continue
        # Pick largest overlap; tie-break by latest first_ts
        if (overlap > best_overlap) or (overlap == best_overlap and first_ts > best_first_ts):
            best_sid, best_overlap, best_first_ts = sid, overlap, first_ts
    if best_sid is None:
        return None
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
    global_sid_index: dict[str, dict] | None = None  # built lazily on first need
    # Per-scan memoization for _find_jsonl_anywhere — avoids O(N_notes * N_projects)
    # filesystem walks when many notes hit the worktree-suffixed project fallback.
    jsonl_anywhere_cache: dict[str, Path | None] = {}

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
            fm = _parse_frontmatter(text, source=str(note))
            if "source_session" not in fm:
                continue  # non-source-session note type (e.g., standups with source_notes[])
            note_project = fm.get("project", "")
            if not note_project:
                continue
            if project and note_project.replace("_", "-") != project.replace("_", "-"):
                continue

            # Capture-time for JSONL-window matching uses immutable signals.
            # mtime above is only the --days cutoff, not the matcher input.
            capture_time, capture_conf, capture_signal = _capture_time(note, fm)
            if capture_conf == 0.0:
                continue  # corrupt note — no usable signal

            # Normalize cache key so personal_ws and personal-ws share index
            cache_key = note_project.replace("_", "-")
            if cache_key not in session_index_cache:
                session_index_cache[cache_key] = _list_session_notes(sessions_dir, note_project)
                jsonl_dir_cache[cache_key] = _jsonl_dir_for_project(note_project)

            idx = session_index_cache[cache_key]
            jsonl_dir = jsonl_dir_cache[cache_key]

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

            # Phase 1b — UUID-first authoritative signal:
            # if current source's UUID resolves to ANY session note in the
            # vault (cross-project, since worktree-launched skills may write
            # `project:` from main-repo cwd while their source session ran
            # in a worktree), check whether the JSONL window overlaps the
            # note's calendar day. If yes, the UUID is correct; only the
            # basename in source_session_note may need updating.
            #
            # Only applies for day-precision signals (date, filename, mtime).
            # When created_at provides a precise sub-day timestamp the matcher
            # has enough resolution; let it run.
            if current_sid and capture_signal != "created_at":
                if global_sid_index is None:
                    global_sid_index = _list_all_session_notes(sessions_dir)
                if current_sid in global_sid_index:
                    sess = global_sid_index[current_sid]
                    sess_project = sess.get("project", "")
                    sess_jsonl_dir = (
                        _jsonl_dir_for_project(sess_project) if sess_project else None
                    )
                    note_date = fm.get("date", "")
                    if not note_date:
                        fn_match = _FILENAME_DATE_RE.match(note.name)
                        note_date = fn_match.group(1) if fn_match else ""
                    day_start = _parse_date_ts(note_date, hour=0) if note_date else None
                    window = None
                    if sess_jsonl_dir is not None:
                        jsonl_path = sess_jsonl_dir / f"{current_sid}.jsonl"
                        if jsonl_path.exists():
                            window = _jsonl_window(str(jsonl_path))
                    if window is None:
                        # I4 fix: when project-dir lookup misses (e.g., worktree-
                        # suffixed project name in the session note), try global
                        # JSONL search by UUID.
                        fallback_path = _find_jsonl_anywhere(
                            current_sid, cache=jsonl_anywhere_cache
                        )
                        if fallback_path is not None:
                            window = _jsonl_window(str(fallback_path))
                    if day_start is not None and window is not None:
                        day_end = day_start + 86400
                        first_ts, last_ts = window
                        if first_ts < day_end and last_ts > day_start:
                            # UUID resolves AND window overlaps note's day → UUID is correct.
                            # Now check if source_session_note basename is stale.
                            actual_basename = sess["basename"]
                            if (
                                current_src_basename
                                and current_src_basename != actual_basename
                            ):
                                # Basename mismatch (e.g., un-truncated worktree slug
                                # vs truncated actual filename). Propose basename-only
                                # repair; UUID stays the same.
                                issues.append(
                                    Issue(
                                        check=NAME,
                                        note_path=str(note),
                                        project=note_project,
                                        current_source=current_source_display,
                                        proposed_source=f"[[{actual_basename}]]",
                                        reason=(
                                            f"source_session UUID {current_sid[:8]} resolves "
                                            f"correctly but source_session_note basename is "
                                            f"stale (expected '{actual_basename}', got "
                                            f"'{current_src_basename}')"
                                        ),
                                        confidence=0.99,
                                        extra={
                                            "proposed_sid": current_sid,
                                            "basename_only": True,
                                            "capture_signal": capture_signal,
                                            "capture_confidence": capture_conf,
                                        },
                                    )
                                )
                            continue  # UUID is authoritative either way; skip matcher
                else:
                    # UUID not in session-note index — but a real JSONL may
                    # still exist (SessionEnd hook missed; see issue #98).
                    # Emit an unresolved diagnostic Issue so operators can see
                    # the coverage gap; UUID is authoritative, so don't propose
                    # a different-session rewrite.
                    jsonl_path = _find_jsonl_anywhere(
                        current_sid, cache=jsonl_anywhere_cache
                    )
                    if jsonl_path is not None:
                        issues.append(
                            Issue(
                                check=NAME,
                                note_path=str(note),
                                project=note_project,
                                current_source=current_source_display,
                                proposed_source="",
                                reason=(
                                    f"source UUID {current_sid[:8]} has a JSONL "
                                    f"but no session note in the vault "
                                    f"(see issue #98 for coverage-gap detector)"
                                ),
                                confidence=0.0,
                                extra={
                                    "unresolved": True,
                                    "missing_session_note": True,
                                    "jsonl_path": str(jsonl_path),
                                    "capture_signal": capture_signal,
                                    "capture_confidence": capture_conf,
                                },
                            )
                        )
                        continue  # UUID is authoritative; skip matcher

            # Day-precision signals: match by greatest overlap with UTC calendar day.
            # Sub-day precision (created_at): match by point-in-window.
            # Track which matcher actually ran so the reason text below
            # describes the right contract (Copilot R4: mtime with no date or
            # filename prefix falls through to point-in-window matching).
            note_date_for_match = ""
            used_day_overlap = False
            if capture_signal == "created_at":
                match = _find_matching_session(capture_time, jsonl_dir, idx)
            else:
                note_date_for_match = fm.get("date", "")
                if not note_date_for_match:
                    fn_match = _FILENAME_DATE_RE.match(note.name)
                    note_date_for_match = fn_match.group(1) if fn_match else ""
                if note_date_for_match:
                    match = _find_matching_session_by_day_overlap(
                        note_date_for_match, jsonl_dir, idx
                    )
                    used_day_overlap = True
                else:
                    match = _find_matching_session(capture_time, jsonl_dir, idx)
            if match is None:
                # No JSONL window contains the note's capture_time. Flag as unresolved
                # ONLY if the current source doesn't resolve to any known session note
                # — that way we don't get false positives on notes whose current source
                # is correct but just doesn't have a matching JSONL window locally.
                if current_sid not in idx:
                    issues.append(
                        Issue(
                            check=NAME,
                            note_path=str(note),
                            project=note_project,
                            current_source=current_source_display,
                            proposed_source="",
                            reason=(
                                f"no session window contains note capture_time"
                                f" (signal={capture_signal}, conf={capture_conf})"
                            ),
                            confidence=0.0,
                            extra={
                                "unresolved": True,
                                "capture_signal": capture_signal,
                                "capture_confidence": capture_conf,
                            },
                        )
                    )
                continue

            if match["sid"] == current_sid:
                continue  # correct

            # Cap confidence on date-only signals: day-precision matching can still
            # be ambiguous on multi-session days because multiple windows may overlap
            # the same UTC calendar day. `created_at` is the only signal precise
            # enough for high confidence.
            if capture_signal == "created_at":
                proposed_conf = 0.95
            elif capture_signal == "mtime":
                proposed_conf = 0.3  # below convergence floor; never auto-apply
            else:
                proposed_conf = 0.6
            # Build reason text matching the matcher actually used (Copilot R4):
            # day-overlap → describe calendar-day match; point-in-window →
            # describe capture_time match. mtime with no date/filename takes
            # the point-in-window branch even though signal != created_at.
            if used_day_overlap:
                reason = (
                    f"note calendar day {note_date_for_match}"
                    f" (signal={capture_signal}, conf={capture_conf})"
                    f" overlaps session {match['sid'][:8]} window most, "
                    f"not current source {current_sid[:8]}"
                )
            else:
                reason = (
                    f"note capture_time "
                    f"{datetime.fromtimestamp(capture_time, timezone.utc).isoformat(timespec='seconds')}"
                    f" (signal={capture_signal}, conf={capture_conf})"
                    f" matches session {match['sid'][:8]} window, "
                    f"not current source {current_sid[:8]}"
                )
            issues.append(
                Issue(
                    check=NAME,
                    note_path=str(note),
                    project=note_project,
                    current_source=current_source_display,
                    proposed_source=f"[[{match['basename']}]]",
                    reason=reason,
                    confidence=proposed_conf,
                    extra={
                        "proposed_sid": match["sid"],
                        "capture_signal": capture_signal,
                        "capture_confidence": capture_conf,
                    },
                )
            )

    # Convergence guard: if multiple flags in a project propose the same
    # target session, the date-window heuristic has structurally collapsed
    # across a multi-session day. Lower confidence and tag for operator review.
    #
    # Restrict the guard to day-precision signals (date/filename/mtime) —
    # `created_at` matches use point-in-window with sub-day precision, so two
    # legitimate stale notes from the same session sharing a proposal target
    # is just normal cluster behavior, not heuristic collapse (Copilot R4-2).
    from collections import Counter
    _DAY_PRECISION_SIGNALS = {"date", "filename", "mtime"}
    targets = Counter(
        (i.project, i.extra.get("proposed_sid", ""))
        for i in issues
        if (
            i.extra.get("proposed_sid")
            and not i.extra.get("basename_only")
            and i.extra.get("capture_signal") in _DAY_PRECISION_SIGNALS
        )
    )
    issues = [
        dataclasses.replace(
            i,
            confidence=min(i.confidence, 0.4),
            extra={
                **i.extra,
                "convergence_warning": True,
                "convergence_count": targets[(i.project, i.extra.get("proposed_sid", ""))],
            },
        )
        if (
            not i.extra.get("basename_only")
            and i.extra.get("proposed_sid")
            and i.extra.get("capture_signal") in _DAY_PRECISION_SIGNALS
            and targets[(i.project, i.extra.get("proposed_sid", ""))] >= 2
        )
        else i
        for i in issues
    ]

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
        # scan() uses mtime for the --days cutoff filter. If apply() let the
        # rewrite bump mtime to now, repaired notes would re-enter the scan
        # window every run (and could be re-flagged via mtime-fallback signal
        # if their immutable signals are ever lost). Preserving the original
        # mtime keeps the rewrite invisible to the cutoff filter.
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
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            # SF9: narrowed from bare `except Exception` so MemoryError,
            # RecursionError, and other non-I/O failures propagate instead
            # of being misreported as ordinary per-issue rewrite failures.
            # KeyboardInterrupt and SystemExit are BaseException, not Exception,
            # and were never caught by the original handler.
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
