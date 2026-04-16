"""
obsidian_utils.py — Shared utilities for obsidian-brain hook scripts.

Extracted from the validated spike (spike_session_log.py) with these changes:
  - No hardcoded config; uses load_config() reading ~/.claude/obsidian-brain-config.json
  - All functions take explicit parameters (vault_path, model, etc.) — no global state
  - File extraction uses tool_use blocks instead of regex heuristics
  - Python stdlib only

Every public function catches its own errors and logs to stderr.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import vault_index as _vault_index
except ImportError as exc:
    _vault_index = None  # type: ignore[assignment]
    print(f"[obsidian-brain] vault_index not available, access tracking disabled: {exc}",
          file=sys.stderr)

# --- Section-parsing regexes (used by collect_vault_corpus, build_context_brief) ---
# Each captures the body between a ## heading and the next ## heading (or EOF).

_RE_SUMMARY = re.compile(
    r"^## Summary\n(.+?)(?=\n^## |\Z)", re.MULTILINE | re.DOTALL
)
_RE_DECISIONS = re.compile(
    r"^## Key Decisions\n(.+?)(?=\n^## |\Z)", re.MULTILINE | re.DOTALL
)
_RE_ERRORS = re.compile(
    r"^## Errors Encountered\n(.+?)(?=\n^## |\Z)", re.MULTILINE | re.DOTALL
)
_RE_OPEN_ITEMS = re.compile(
    r"^## Open Questions / Next Steps\n(.+?)(?=\n^## |\Z)", re.MULTILINE | re.DOTALL
)
_RE_RAW_CONVERSATION = re.compile(
    r"^## Conversation \(raw\)\n(.+?)(?=\n^## |\Z)", re.MULTILINE | re.DOTALL
)

# --- Secure working directory ---
# All temp/cache files use ~/.claude/obsidian-brain/ (0o700) instead of /tmp.
# This prevents symlink attacks and cache poisoning on multi-user systems.

_SECURE_DIR = os.path.expanduser("~/.claude/obsidian-brain")


def _ensure_secure_dir() -> str:
    """Create and return the secure working directory with 0o700 permissions."""
    os.makedirs(_SECURE_DIR, mode=0o700, exist_ok=True)
    st = os.stat(_SECURE_DIR)
    if st.st_mode & 0o077:
        os.chmod(_SECURE_DIR, 0o700)
    return _SECURE_DIR


# --- Session-scoped cache ---
# Avoids repeated vault scans when multiple skills run in one session.

_CACHE_PREFIX = os.path.join(_SECURE_DIR, "cache-")
_BOOTSTRAP_PREFIX = os.path.join(_SECURE_DIR, "sid-")


def _bootstrap_prefix() -> str:
    """Return the bootstrap file prefix. Fixed to secure directory."""
    return _BOOTSTRAP_PREFIX


def _safe_mtime(path: str) -> float:
    """Return file mtime, or -1.0 if the path is missing/unstatable.

    Used by _get_session_id_fast() and similar helpers that need best-effort
    mtime comparison over globs — filesystem races (a JSONL rotated between
    glob and stat) must not crash the caller.
    """
    try:
        return os.path.getmtime(path)
    except OSError:
        return -1.0


def _glob_project_jsonls(safe_project: str, suffix: str = "*.jsonl") -> list[str]:
    """Glob ~/.claude/projects/*<project>/<suffix>, with underscore-to-hyphen fallback.

    Claude Code normalizes underscores to hyphens in project directory names,
    so a project at ``personal_ws/`` gets stored as ``personal-ws/``.
    """
    import glob as _glob
    pattern = os.path.expanduser(
        f"~/.claude/projects/*{safe_project}/{suffix}"
    )
    matches = _glob.glob(pattern)
    if not matches and "_" in safe_project:
        alt = safe_project.replace("_", "-")
        pattern = os.path.expanduser(f"~/.claude/projects/*{alt}/{suffix}")
        matches = _glob.glob(pattern)
    return matches


def _slow_path_newest_sid() -> str:
    """Determine the current session id by scanning JSONL files directly.

    Bootstrap-independent — does NOT read, write, or trust the bootstrap
    cache. Used by health checks that must not be fooled by stale cache
    entries. Returns 'unknown' if no JSONLs are found for the current cwd.
    """
    import glob as _glob
    project = os.path.basename(os.getcwd())
    safe_project = _glob.escape(project)
    matches = _glob_project_jsonls(safe_project)
    entries = [(_safe_mtime(p), p) for p in matches]
    viable = [(m, p) for m, p in entries if m >= 0]
    if not viable:
        return "unknown"
    _, newest = max(viable)
    return os.path.splitext(os.path.basename(newest))[0]


def _get_session_id_fast() -> str:
    """Derive session ID, using bootstrap file for speed on repeat calls.

    Validation strategy:
      1. Read bootstrap file (~0.1 ms)
      2. Verify cached JSONL still exists
      3. Determine the newest JSONL deterministically via (mtime, path)
         tuple comparison. Ties broken by path string so the result is
         reproducible on filesystems with 1-second mtime resolution.
      4. If the newest JSONL's basename equals the cached sid, trust the
         cache. If the cached JSONL shares the newest mtime (same-second
         race), also trust the cache — the SessionStart hook has already
         authoritatively written the current sid and same-mtime ties
         effectively mean "these happened simultaneously."
      5. Otherwise fall through to the slow path (full glob + deterministic
         max) which is the authoritative answer.

    Comparing basenames rather than mtime values directly is important
    because the active session's JSONL is appended throughout the session,
    so its mtime increases continuously. A naive mtime comparison would
    invalidate the bootstrap on every call after a few seconds, defeating
    the optimization.

    The slow path is strictly READ-ONLY — it never writes the bootstrap
    file. The SessionStart hook is the sole authoritative writer of the
    bootstrap. Writing from the slow path would clobber the hook's correct
    write if the slow path ran during the hook's own invocation (which
    happens whenever downstream hook code calls a function that triggers
    this, before CC has flushed the new session's JSONL to disk).
    """
    import glob as _glob
    project = os.path.basename(os.getcwd())
    bootstrap = f"{_bootstrap_prefix()}{project}"
    safe_project = _glob.escape(project)

    # Fast path: bootstrap file
    try:
        with open(bootstrap, 'r') as f:
            cached_sid = f.read().strip()
        if cached_sid:
            safe_cached = _glob.escape(cached_sid)
            cached_matches = _glob_project_jsonls(
                safe_project, f"{safe_cached}.jsonl"
            )
            if cached_matches:
                # Determine the newest JSONL deterministically: order by
                # (mtime, path). Ties broken by path string so results are
                # reproducible across filesystems that report 1-second mtime
                # resolution.
                all_matches = _glob_project_jsonls(safe_project)
                if all_matches:
                    # Determine the newest JSONL deterministically via (mtime, path).
                    # _safe_mtime returns -1.0 for files that disappear between glob
                    # and stat, so transient races never crash the caller.
                    entries = [(_safe_mtime(p), p) for p in all_matches]
                    viable = [(m, p) for m, p in entries if m >= 0]
                    if viable:
                        newest_mtime, newest_path = max(viable)
                        newest_sid = os.path.splitext(os.path.basename(newest_path))[0]
                        if newest_sid == cached_sid:
                            return cached_sid
                        # Tie-breaker: if ANY cached JSONL matches the newest
                        # mtime (across all worktree/project-dir matches), trust
                        # the cache. When multiple project-dir variants exist
                        # (e.g. worktrees), the cached sid's JSONL may appear in
                        # several of them; comparing only cached_matches[0]
                        # could miss the tie and cause an unnecessary
                        # fall-through. This handles the same-second race where
                        # the previous session's JSONL and the current
                        # session's JSONL report identical mtimes on
                        # coarse-resolution filesystems, and the SessionStart
                        # hook has already authoritatively written the current
                        # sid.
                        cached_mtimes = [_safe_mtime(p) for p in cached_matches]
                        cached_newest = max(
                            (m for m in cached_mtimes if m >= 0), default=-1.0
                        )
                        if cached_newest == newest_mtime:
                            return cached_sid
                        # Otherwise a different session is strictly newer; fall through.
                    else:
                        return cached_sid  # no viable JSONLs; trust cache
                else:
                    return cached_sid  # no other JSONLs; trust cache
    except OSError:
        pass

    # Slow path: full glob + mtime sort with deterministic tiebreaker.
    # This path is READ-ONLY — never writes the bootstrap file. The
    # SessionStart hook is the sole authoritative writer. Writing here
    # would clobber the hook's correct write if the slow path ran
    # during the hook's own invocation (which happens whenever the
    # hook's downstream code calls a function that triggers this).
    # Use _safe_mtime so a JSONL deleted or rotated between glob and
    # stat cannot crash the caller (e.g. load_config).
    matches = _glob_project_jsonls(safe_project)
    entries = [(_safe_mtime(p), p) for p in matches]
    viable = [(m, p) for m, p in entries if m >= 0]
    if not viable:
        return "unknown"
    _, newest = max(viable)
    return os.path.splitext(os.path.basename(newest))[0]


def cache_get(session_id: str, key: str):
    """Read a key from the session cache. Returns None on miss."""
    cache_path = f"{_CACHE_PREFIX}{session_id}.json"
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
        return data.get(key)
    except (OSError, json.JSONDecodeError):
        return None


def cache_set(session_id: str, key: str, value) -> None:
    """Write a key to the session cache. Atomic write."""
    _ensure_secure_dir()
    cache_path = f"{_CACHE_PREFIX}{session_id}.json"
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            print(f"[obsidian-brain] cache corrupted, resetting: {exc}", file=sys.stderr)
        data = {}

    data[key] = value

    fd, tmp = tempfile.mkstemp(prefix='.ob-cache-', suffix='.json.tmp', dir=_SECURE_DIR)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, cache_path)
    except OSError as exc:
        print(f"[obsidian-brain] cache write failed: {exc}", file=sys.stderr)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def cache_invalidate(session_id: str, *keys: str) -> None:
    """Remove specific keys from cache. No keys = clear all."""
    cache_path = f"{_CACHE_PREFIX}{session_id}.json"
    if not keys:
        try:
            os.unlink(cache_path)
        except OSError:
            pass
        return

    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    for k in keys:
        data.pop(k, None)

    _ensure_secure_dir()
    fd, tmp = tempfile.mkstemp(prefix='.ob-cache-', suffix='.json.tmp', dir=_SECURE_DIR)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, cache_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

# Shared cap for the raw-note conversation section. Used by build_raw_fallback
# as the write-time truncation limit, and returned by parse_full_transcript
# so /recall can deterministically detect truncation by comparing the parsed
# message total against it — avoiding any dependence on the raw note's
# message-filtering heuristics.
RAW_NOTE_MAX_TURNS = 120

_CONFIG_PATH = Path.home() / ".claude" / "obsidian-brain-config.json"

_DEFAULTS: dict = {
    "vault_path": "",
    "sessions_folder": "claude-sessions",
    "insights_folder": "claude-insights",
    "dashboards_folder": "claude-dashboards",
    "min_messages": 3,
    "min_duration_minutes": 2,
    "summary_model": "haiku",
    "auto_log_enabled": True,
    "snapshot_on_compact": True,
    "snapshot_on_clear": True,
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """Read ~/.claude/obsidian-brain-config.json, returning defaults for missing keys.

    Session-scoped caching: first call loads from disk and writes to cache;
    subsequent calls within the same session hit the cache.
    """
    sid = _get_session_id_fast()
    cached = cache_get(sid, "config")
    if cached is not None:
        return cached

    config = dict(_DEFAULTS)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            user_cfg = json.load(fh)
        if isinstance(user_cfg, dict):
            config.update(user_cfg)
    except FileNotFoundError:
        print(
            f"[obsidian-brain] config not found at {_CONFIG_PATH}, using defaults",
            file=sys.stderr,
        )
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"[obsidian-brain] error reading config: {exc}, using defaults",
            file=sys.stderr,
        )

    # Auto-fix config file permissions if group/world readable
    try:
        config_stat = os.stat(_CONFIG_PATH)
    except OSError:
        pass  # file doesn't exist or can't stat — nothing to fix
    else:
        if config_stat.st_mode & 0o077:
            try:
                os.chmod(_CONFIG_PATH, 0o600)
                print("[obsidian-brain] fixed config permissions to 0o600", file=sys.stderr)
            except OSError as exc:
                print(f"[obsidian-brain] WARNING: config is world-readable and chmod failed: {exc}", file=sys.stderr)

    cache_set(sid, "config", config)
    return config


def check_hook_status() -> dict:
    """Inspect the bootstrap file to report session-logging health.

    Returns:
        {"ok": bool, "message": str, "bootstrap_sid": str, "current_sid": str}

    "ok" is True if the bootstrap file exists (session logging is active).
    A SID mismatch (bootstrap points at a previous session) is normal after
    reconnects and does NOT indicate a problem — sessions are still logged.
    "ok" is False only when the bootstrap file is missing entirely or no
    session files can be found.
    """
    project = os.path.basename(os.getcwd())
    bootstrap = f"{_bootstrap_prefix()}{project}"

    # Read bootstrap BEFORE deriving current_sid so we see its real state.
    try:
        with open(bootstrap, "r") as f:
            bootstrap_sid = f.read().strip()
    except OSError:
        bootstrap_sid = None

    # Use the bootstrap-independent slow path so the check isn't circular.
    # _get_session_id_fast() can return the cached bootstrap value, which
    # would make this health check report OK even when the bootstrap is
    # stale.
    current_sid = _slow_path_newest_sid()

    if bootstrap_sid is None:
        return {
            "ok": False,
            "message": "Session logging may not be active — run /obsidian-setup to configure",
            "bootstrap_sid": "",
            "current_sid": current_sid,
        }

    if current_sid == "unknown":
        return {
            "ok": False,
            "message": "No session files found — run /obsidian-setup to verify configuration",
            "bootstrap_sid": bootstrap_sid,
            "current_sid": current_sid,
        }

    # Bootstrap exists = session logging is working. SID mismatch is
    # expected after reconnects and is not a problem — keep ok=True
    # but include diagnostic detail for debugging.
    if bootstrap_sid != current_sid:
        return {
            "ok": True,
            "message": "Session logging active (resumed session)",
            "bootstrap_sid": bootstrap_sid,
            "current_sid": current_sid,
        }

    return {
        "ok": True,
        "message": "Session logging active",
        "bootstrap_sid": bootstrap_sid,
        "current_sid": current_sid,
    }


def get_session_context(vault_path: str | None = None, sessions_folder: str | None = None) -> dict:
    """Get session ID, hash, project, and session note name. Cached.

    Returns {session_id, hash, project, session_note_name} or
    {session_id: 'unknown', hash: '', project: <cwd basename>, session_note_name: ''}.
    """
    sid = _get_session_id_fast()
    # Include args in cache key so different call signatures don't collide
    cache_key = f"session_context:{vault_path or ''}:{sessions_folder or ''}"
    cached = cache_get(sid, cache_key)
    if cached is not None:
        return cached

    project = os.path.basename(os.getcwd()).lower().replace(' ', '-').replace('_', '-')
    if sid == "unknown":
        # Don't cache "unknown" — would pollute cache shared across projects
        return {"session_id": "unknown", "hash": "", "project": project, "session_note_name": ""}

    h = hashlib.sha256(sid.encode()).hexdigest()[:4]

    session_note_name = ""
    if vault_path and sessions_folder:
        sessions_dir = os.path.join(vault_path, sessions_folder)
        if os.path.isdir(sessions_dir):
            for fname in os.listdir(sessions_dir):
                if fname.endswith(f'-{h}.md'):
                    session_note_name = fname[:-3]  # strip .md
                    break

    # If not found, construct expected name
    if not session_note_name:
        from datetime import date
        session_note_name = f"{date.today().isoformat()}-{project}-{h}"

    ctx = {"session_id": sid, "hash": h, "project": project, "session_note_name": session_note_name}
    cache_set(sid, cache_key, ctx)
    return ctx


def read_note_metadata(file_path: str) -> dict | None:
    """Parse YAML frontmatter from a vault note. Returns dict or None.

    Reads first 40 lines, extracts fields between --- markers.
    Cached per file path within the session.
    """
    sid = _get_session_id_fast()
    cache_key = f"metadata:{os.path.realpath(file_path)}"
    _CACHE_SENTINEL = {"__no_frontmatter__": True}
    cached = cache_get(sid, cache_key)
    if cached is not None:
        return None if cached == _CACHE_SENTINEL else cached

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= 40:
                    break
                lines.append(line)
    except OSError:
        return None

    if not lines or lines[0].strip() != '---':
        cache_set(sid, cache_key, _CACHE_SENTINEL)
        return None

    meta: dict = {}
    tags: list[str] = []
    in_tags = False

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == '---':
            break
        if stripped.startswith('- ') and in_tags:
            tags.append(stripped[2:].strip())
            continue
        in_tags = False
        if ':' in stripped:
            key, _, val = stripped.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == 'tags':
                in_tags = True
                continue
            meta[key] = val

    if tags:
        meta['tags'] = tags

    cache_set(sid, cache_key, meta)
    return meta


def match_items_against_evidence(
    evidence_text: str,
    open_items: list[tuple[str, int, str]],
) -> list[dict]:
    """Match open items against evidence prose for completion detection.

    Different from find_duplicates() — this matches items (short checkbox
    lines) against free-form text (summaries, changelogs, commit messages).

    Returns [{"file": f, "line": l, "text": t, "evidence": snippet, "confidence": score}]
    for items that appear to be completed based on the evidence.
    """
    try:
        _hooks_dir = os.path.dirname(os.path.abspath(__file__))
        if _hooks_dir not in sys.path:
            sys.path.insert(0, _hooks_dir)
        from open_item_dedup import (
            _strip_markdown, _extract_distinctive_tokens, _tokenize,
            _COMPLETION_PHRASES,
        )
    except ImportError as exc:
        print(f"[obsidian-brain] match_items: import failed: {exc}", file=sys.stderr)
        return []

    if not evidence_text.strip():
        return []

    evidence_lower = evidence_text.lower()
    evidence_tokens = _tokenize(evidence_text)
    candidates: list[dict] = []

    for fpath, line_num, item_text in open_items:
        cleaned = _strip_markdown(item_text)
        distinctive = _extract_distinctive_tokens(cleaned)
        tokens = _tokenize(cleaned)

        # Score: distinctive tokens get higher weight
        score = 0
        match_positions: list[int] = []

        # Check distinctive tokens
        for dt in distinctive:
            dt_lower = dt.lower()
            pos = evidence_lower.find(dt_lower)
            if pos >= 0:
                score += 3
                match_positions.append(pos)

        # Check regular tokens (3+ chars) — set intersection for word-boundary matching
        matched_token_set = tokens & evidence_tokens
        matched_tokens = len(matched_token_set)
        # Find positions for matched tokens (for evidence snippet extraction)
        for t in matched_token_set:
            pos = evidence_lower.find(t)
            if pos >= 0:
                match_positions.append(pos)

        score += matched_tokens

        # Minimum threshold: 3+ token matches, or any distinctive token match
        if score < 3:
            continue

        # Completion phrase boost: check ±100 char window around EACH match position
        has_completion_phrase = False
        if match_positions:
            for mpos in match_positions:
                if has_completion_phrase:
                    break
                window_start = max(0, mpos - 100)
                window_end = min(len(evidence_lower), mpos + 100)
                window = evidence_lower[window_start:window_end]
                for phrase in _COMPLETION_PHRASES:
                    if phrase in window:
                        has_completion_phrase = True
                        score += 2
                        break

        # Extract evidence snippet (~60 chars around best match (first position)
        best_match_pos = min(match_positions) if match_positions else -1
        snippet = ""
        if best_match_pos >= 0:
            start = max(0, best_match_pos - 30)
            end = min(len(evidence_text), best_match_pos + 30)
            snippet = evidence_text[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(evidence_text):
                snippet = snippet + "..."

        candidates.append({
            "file": fpath,
            "line": line_num,
            "text": item_text,
            "evidence": snippet,
            "confidence": score,
            "has_completion_phrase": has_completion_phrase,
        })

    # Sort by confidence descending
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------


def read_transcript(path: str) -> list[dict]:
    """Parse a JSONL transcript file into a list of entry dicts."""
    messages: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError) as exc:
        print(f"[obsidian-brain] failed to read transcript: {exc}", file=sys.stderr)
    return messages


def _extract_text(content) -> list[str]:
    """Extract text from message content (string or list of blocks)."""
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                # Skip tool_use and tool_result blocks for text extraction
            elif isinstance(part, str):
                texts.append(part)
    return [t for t in texts if t.strip()]


def extract_user_messages(entries: list[dict]) -> list[str]:
    """Extract user message texts from CC transcript JSONL entries.

    CC format: top-level ``type`` field ("user"/"assistant"),
    message nested under ``entry["message"]["content"]``.
    Also supports flat format as fallback.
    """
    texts: list[str] = []
    for entry in entries:
        # CC JSONL format
        if entry.get("type") == "user":
            msg = entry.get("message", {})
            texts.extend(_extract_text(msg.get("content", "")))
        # Flat format fallback
        elif entry.get("role") == "user":
            texts.extend(_extract_text(entry.get("content", "")))
    return texts


def extract_assistant_messages(entries: list[dict]) -> list[str]:
    """Extract assistant message texts from CC transcript JSONL entries."""
    texts: list[str] = []
    for entry in entries:
        if entry.get("type") == "assistant":
            msg = entry.get("message", {})
            texts.extend(_extract_text(msg.get("content", "")))
        elif entry.get("role") == "assistant":
            texts.extend(_extract_text(entry.get("content", "")))
    return texts


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _parse_ts(ts_str: str) -> datetime.datetime | None:
    """Best-effort timestamp parsing (ISO formats + epoch seconds/millis)."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    # Epoch seconds or milliseconds
    try:
        val = float(ts_str)
        if val > 1e12:
            val /= 1000.0
        return datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc)
    except (ValueError, OSError):
        pass
    return None


def extract_session_metadata(messages: list[dict], cwd: str) -> dict:
    """Extract session metadata from transcript entries.

    Returns dict with: project, project_path, git_branch, files_touched,
    errors, duration_minutes, commits.
    """
    meta: dict = {
        "project": Path(cwd).name.lower().replace(" ", "-").replace("_", "-") if cwd else "unknown",
        "project_path": cwd or "",
        "git_branch": "",
        "files_touched": [],
        "errors": [],
        "duration_minutes": 0,
        "commits": [],
    }

    # --- Git branch: try transcript gitBranch field first, then CLI fallback ---
    for entry in messages:
        branch = entry.get("gitBranch")
        if branch and branch != "HEAD":
            meta["git_branch"] = branch
            break
    if not meta["git_branch"]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd or None,
            )
            if result.returncode == 0:
                meta["git_branch"] = result.stdout.strip()
        except Exception:
            pass

    # --- Duration: first and last entry timestamps ---
    timestamps: list[str] = []
    for entry in messages:
        ts = entry.get("timestamp") or entry.get("ts") or entry.get("created_at")
        if ts:
            timestamps.append(str(ts))
    if len(timestamps) >= 2:
        try:
            first = _parse_ts(timestamps[0])
            last = _parse_ts(timestamps[-1])
            if first and last:
                delta = (last - first).total_seconds() / 60.0
                meta["duration_minutes"] = round(delta, 1)
        except Exception:
            pass

    # --- Files touched + Errors: delegate to shared helpers ---
    meta["files_touched"] = _extract_files_touched(messages)[:60]
    meta["errors"] = _extract_errors(messages)[:30]

    return meta


def _entry_content(entry: dict) -> str | list | None:
    """Return the raw transcript content value for an entry.

    Supports both the canonical CC JSONL shape (nested under
    entry['message']['content']) and the flat fallback shape
    (entry['content'] directly). Mirrors the shape handling of
    extract_user_messages / extract_assistant_messages so the
    _extract_* helpers below stay consistent across transcript formats.

    Return value is whatever the transcript stored — typically a
    list of content blocks (for tool-use / text / tool_result blocks)
    but can also be a plain string in flat-format transcripts, or
    None when no content is present. Callers must `isinstance` check
    before iterating.
    """
    msg = entry.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if content is not None:
            return content
    return entry.get("content")


def _extract_files_touched(messages: list[dict]) -> list[str]:
    """Extract unique file paths from Edit/Write/MultiEdit tool_use blocks.

    Shared between extract_session_metadata (SessionEnd write path) and
    parse_full_transcript (/recall read path) to prevent drift. Handles
    both CC and flat transcript shapes via _entry_content.
    """
    files_seen: list[str] = []
    for entry in messages:
        content = _entry_content(entry)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in (
                "Edit",
                "Write",
                "MultiEdit",
            ):
                inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                fp = inp.get("file_path", "")
                if fp and fp not in files_seen:
                    files_seen.append(fp)
    return files_seen


def _extract_errors(messages: list[dict]) -> list[str]:
    """Extract unique error snippets from tool_result blocks with is_error=true.

    Shared between extract_session_metadata (SessionEnd write path) and
    parse_full_transcript (/recall read path) to prevent drift. Handles
    both CC and flat transcript shapes via _entry_content.
    """
    errors: list[str] = []
    for entry in messages:
        content = _entry_content(entry)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result" and block.get("is_error"):
                err_content = block.get("content", "")
                if isinstance(err_content, str) and err_content.strip():
                    snippet = err_content.strip()[:200]
                    if snippet not in errors:
                        errors.append(snippet)
    return errors


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def _dedup_summary_open_items(summary_text: str, existing_items: list) -> str:
    """Remove duplicate open items from AI-generated summary text.

    Operates on the string before disk write. Uses find_duplicates()
    for matching — same logic as dedup_note_open_items() but on a string.
    """
    # Lazy import to avoid top-level dependency on hooks/ being on sys.path
    _hooks_dir = os.path.dirname(os.path.abspath(__file__))
    if _hooks_dir not in sys.path:
        sys.path.insert(0, _hooks_dir)
    from open_item_dedup import find_duplicates

    # Find the ## Open Questions / Next Steps section
    pattern = r'(## Open Questions / Next Steps\n)(.*?)(?=\n## |\Z)'
    match = re.search(pattern, summary_text, re.DOTALL)
    if not match:
        return summary_text

    section_header = match.group(1)
    section_body = match.group(2)

    # Parse individual - [ ] items
    lines = section_body.split('\n')
    kept_lines: list[str] = []
    removed = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('- [ ] '):
            item_text = stripped[6:]
            dupes = find_duplicates(item_text, existing_items)
            # Only auto-remove high-confidence matches; fuzzy could be false positives
            high_dupes = [d for d in dupes if d[3] == "high"]
            if high_dupes:
                removed = True
                continue  # drop this line
        kept_lines.append(line)

    if not removed:
        return summary_text

    new_body = '\n'.join(kept_lines)
    # If all items removed, add placeholder
    if not any(l.strip().startswith('- [ ]') for l in kept_lines):
        new_body = 'None.'
    # Ensure consistent trailing newline before next section
    if not new_body.endswith('\n'):
        new_body += '\n'

    return summary_text[:match.start()] + section_header + new_body + summary_text[match.end():]


def parse_importance(summary_text: str) -> int:
    """Extract importance score (1-10) from summary text.

    Looks for either '## Importance\\nN' or 'IMPORTANCE: N' format.
    Returns 5 (default) if not found or invalid.
    """
    # Try ## Importance section
    match = re.search(r'##\s*Importance\s*\n\s*(\d+)', summary_text)
    if match:
        score = int(match.group(1))
        return max(1, min(10, score))
    # Try IMPORTANCE: N format (sub-agent output)
    match = re.search(r'IMPORTANCE:\s*(\d+)', summary_text)
    if match:
        score = int(match.group(1))
        return max(1, min(10, score))
    return 5


def generate_summary(
    user_msgs: list[str],
    assistant_msgs: list[str],
    metadata: dict,
    model: str = "haiku",
    timeout: int = 30,
) -> str | None:
    """Call ``claude -p --model <model>`` to summarize the session.

    Samples first 10 + last 10 messages for large sessions.
    Returns None on failure.
    """
    # Sample messages for large sessions
    if len(user_msgs) > 20:
        sampled_user = (
            user_msgs[:10] + ["[... middle messages omitted ...]"] + user_msgs[-10:]
        )
    else:
        sampled_user = user_msgs

    if len(assistant_msgs) > 20:
        sampled_asst = (
            assistant_msgs[:10]
            + ["[... middle messages omitted ...]"]
            + assistant_msgs[-10:]
        )
    else:
        sampled_asst = assistant_msgs

    user_sample = "\n---\n".join(sampled_user)[:12000]
    assistant_sample = "\n---\n".join(sampled_asst)[:12000]

    prompt = f"""You are a technical summarizer. You will be given the transcript of a Claude Code coding session. Your job is to produce a structured summary. Do NOT respond conversationally. Do NOT ask questions. Just output the summary.

SESSION METADATA:
- Project: {metadata.get('project', 'unknown')}
- Branch: {metadata.get('git_branch', 'unknown')}
- Duration: {metadata.get('duration_minutes', 0)} minutes
- Files touched: {', '.join(metadata.get('files_touched', [])[:15]) or 'none detected'}

TRANSCRIPT (user and assistant messages):
{user_sample}

---

{assistant_sample}

OUTPUT EXACTLY these markdown sections with no preamble, no commentary, no questions:

## Summary
1-3 sentence overview of what was accomplished in this session.

## Key Decisions
- Bullet list of important technical decisions made. Write "None noted." if none.

## Changes Made
- Bullet list of files modified/created with brief description. Write "None noted." if none.

## Errors Encountered
- Bullet list of errors and how resolved. Write "None." if none.

## Open Questions / Next Steps
- [ ] Checkbox list of unresolved items. Write "None." if none.

## Importance
Rate this session 1-10. 1-3: trivial (config, interrupted). 4-6: standard work. 7-8: key decisions or error resolutions. 9-10: major releases or security audits. Output ONLY the number.
"""

    # Layer 1: Append existing open items to prevent AI duplication
    existing_items = []
    if metadata.get("vault_path") and metadata.get("sessions_folder"):
        try:
            _hooks_dir = os.path.dirname(os.path.abspath(__file__))
            if _hooks_dir not in sys.path:
                sys.path.insert(0, _hooks_dir)
            from open_item_dedup import collect_open_items
            existing_items = collect_open_items(
                metadata["vault_path"],
                metadata["sessions_folder"],
                metadata.get("project", "unknown"),
                max_sessions=10,
            )
        except Exception as exc:
            print(f"[obsidian-brain] open item collection failed (non-fatal): {exc}", file=sys.stderr)

    if existing_items:
        prompt += "\n\n## Existing Open Items for This Project (DO NOT DUPLICATE)\n"
        prompt += "The following items are already tracked in older session notes. Do NOT include any item\n"
        prompt += "that is semantically equivalent to these — same PR, same branch, same task, same file.\n"
        prompt += "Only add genuinely NEW open items from this session's conversation.\n\n"
        for _, _, item_text in existing_items:
            prompt += f"- {item_text}\n"

    attempts = (timeout, timeout * 2)  # escalate on first timeout
    for i, attempt_timeout in enumerate(attempts):
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=attempt_timeout,
            )
            if result.returncode == 0 and result.stdout.strip():
                summary_text = result.stdout.strip()
                # Layer 2: Post-generation dedup pass (string-based, pre-write)
                if existing_items:
                    summary_text = _dedup_summary_open_items(summary_text, existing_items)
                return summary_text
            print(
                f"[obsidian-brain] claude -p failed (rc={result.returncode}): "
                f"{result.stderr[:200]}",
                file=sys.stderr,
            )
            break  # non-timeout failure, don't retry
        except FileNotFoundError:
            print(
                "[obsidian-brain] claude CLI not found, summarization unavailable",
                file=sys.stderr,
            )
            break  # won't succeed on retry
        except subprocess.TimeoutExpired as exc:
            stderr_snippet = f" stderr: {exc.stderr[:200]}" if exc.stderr else ""
            if i < len(attempts) - 1:
                print(f"[obsidian-brain] claude -p timed out at {attempt_timeout}s, retrying with {attempts[i+1]}s{stderr_snippet}", file=sys.stderr)
                continue
            print(f"[obsidian-brain] claude -p timed out at {attempt_timeout}s, giving up{stderr_snippet}", file=sys.stderr)
        except Exception as exc:
            print(f"[obsidian-brain] claude -p error ({type(exc).__name__}): {exc}", file=sys.stderr)
            break  # unknown error, don't retry

    return None


# ---------------------------------------------------------------------------
# Secret scrubbing
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r'gh[ps]_[A-Za-z0-9_]{36,}'), '[REDACTED:github-token]'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED:aws-key]'),
    (re.compile(r'(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+'), r'\1=[REDACTED]'),
    (re.compile(r'-----BEGIN [A-Z ]+-----'), '[REDACTED:pem-header]'),
    (re.compile(r'(?i)Bearer\s+[A-Za-z0-9._\-]{20,}'), 'Bearer [REDACTED]'),
    (re.compile(r'(?i)(key|secret|token)\s*[=:]\s*[A-Za-z0-9+/=]{40,}'), r'\1=[REDACTED:base64]'),
]


def scrub_secrets(text: str) -> str:
    """Best-effort redaction of common secret patterns."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def escape_wikilinks(text: str) -> str:
    """Escape ``[[`` so Obsidian does not parse bash conditionals as wikilinks.

    Bash ``[[ $VAR == pattern ]]`` in conversation excerpts triggers
    Obsidian's wikilink parser, creating spurious outgoing links.
    """
    return text.replace("[[", r"\[\[")


# ---------------------------------------------------------------------------
# Vault operations
# ---------------------------------------------------------------------------


def write_vault_note(
    vault_path: str, folder: str, filename: str, content: str
) -> bool:
    """Atomic write: temp file + chmod 0o600 + rename into vault folder.

    Creates the target folder if it does not exist.  Returns True on success.
    """
    dest_dir = Path(vault_path) / folder
    dest = dest_dir / filename

    # Path traversal check — BEFORE any filesystem side effects
    vault_real = Path(vault_path).resolve()
    if not dest.resolve().is_relative_to(vault_real):
        print(f"[obsidian-brain] path traversal blocked: {dest}", file=sys.stderr)
        return False

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"[obsidian-brain] cannot create vault dir {dest_dir}: {exc}",
            file=sys.stderr,
        )
        return False

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(dest_dir), prefix=".ob-", suffix=".md.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.chmod(tmp_path, 0o600)
            os.rename(tmp_path, str(dest))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        print(f"[obsidian-brain] write failed for {dest}: {exc}", file=sys.stderr)
        return False

    print(f"[obsidian-brain] wrote {dest}", file=sys.stderr)
    return True


def flip_note_status(path: str, old_status: str, new_status: str) -> bool:
    """Atomically change a note's frontmatter status field.

    Reads the file, replaces 'status: <old>' with 'status: <new>' in the
    frontmatter, and writes back via temp file + rename.
    Returns True on success.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        print(f"[obsidian-brain] cannot read {path}: {exc}", file=sys.stderr)
        return False

    old_line = f"status: {old_status}"
    new_line = f"status: {new_status}"

    # Constrain replacement to the frontmatter block (between --- delimiters)
    if not content.startswith("---"):
        return False
    end_idx = content.index("\n---", 3) + 1 if "\n---" in content[3:] else -1
    if end_idx < 0:
        return False
    frontmatter = content[:end_idx]
    if old_line not in frontmatter:
        return False

    new_content = frontmatter.replace(old_line, new_line, 1) + content[end_idx:]

    dir_path = os.path.dirname(path)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".ob-flip-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            orig_mode = stat.S_IMODE(os.stat(path).st_mode)
            os.chmod(tmp_path, orig_mode)
            os.rename(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        print(f"[obsidian-brain] flip_note_status failed for {path}: {exc}", file=sys.stderr)
        return False

    return True


def find_latest_session(
    vault_path: str, sessions_folder: str, project: str
) -> dict | None:
    """Find the most recent session note for a project.

    Searches YAML frontmatter for ``project: <project>``.
    Returns ``{date, summary, next_steps}`` or None.
    """
    sessions_dir = Path(vault_path) / sessions_folder
    if not sessions_dir.exists():
        return None

    slug = slugify(project)
    # Collect candidate files sorted by name descending (newest date first)
    candidates = sorted(sessions_dir.glob("*.md"), reverse=True)

    for note_path in candidates:
        try:
            text = note_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Quick check: does frontmatter mention this project?
        # Look for project: <name> in the YAML block
        fm_end = text.find("\n---", 3)  # skip opening ---
        if fm_end == -1:
            continue
        frontmatter = text[: fm_end + 4]

        # Match project field (case-insensitive basename or slug)
        project_match = re.search(r"^project:\s*(.+)$", frontmatter, re.MULTILINE)
        if not project_match:
            continue
        fm_project = project_match.group(1).strip().strip('"').strip("'")
        if fm_project.lower() != project.lower() and slugify(fm_project) != slug:
            continue

        # Extract date from frontmatter
        date_match = re.search(r"^date:\s*(.+)$", frontmatter, re.MULTILINE)
        date_str = date_match.group(1).strip() if date_match else ""

        # Extract summary section
        summary = ""
        summary_match = re.search(
            r"## Summary\n(.+?)(?=\n## |\Z)", text, re.DOTALL
        )
        if summary_match:
            summary = summary_match.group(1).strip()

        # Extract next steps section
        next_steps = ""
        ns_match = re.search(
            r"## Open Questions / Next Steps\n(.+?)(?=\n## |\Z)", text, re.DOTALL
        )
        if ns_match:
            next_steps = ns_match.group(1).strip()

        return {"date": date_str, "summary": summary, "next_steps": next_steps}

    return None


def find_unsummarized_notes(
    vault_path: str,
    sessions_folder: str,
    project: str,
) -> str:
    """Find unsummarized session notes for a project, with defense-in-depth.

    Scans sessions folder for notes with status: auto-logged in frontmatter,
    filters by project, and checks for false positives (notes that already
    have a real ## Summary but stale status). Auto-fixes stale status inline.

    Returns JSON string: {"unsummarized": [paths], "auto_fixed": N}
    """
    sessions_dir = Path(vault_path) / sessions_folder
    if not sessions_dir.is_dir():
        return json.dumps({"unsummarized": [], "auto_fixed": 0})

    unsummarized: list[str] = []
    auto_fixed = 0

    for f in sorted(sessions_dir.iterdir(), reverse=True):
        if f.suffix != '.md':
            continue

        # Read ENTIRE file from disk — DO NOT use read_note_metadata() which
        # has a persistent cache that may be stale after status changes.
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            print(f"[obsidian-brain] cannot read {f.name}: {exc}", file=sys.stderr)
            continue

        # Parse frontmatter inline (no cache)
        if not content.startswith('---'):
            continue
        fm_end = content.find('\n---', 3)
        if fm_end == -1:
            continue
        frontmatter = content[:fm_end]

        # Must be auto-logged
        status_match = re.search(r'^status:\s*(.+)$', frontmatter, re.MULTILINE)
        if not status_match or status_match.group(1).strip() != 'auto-logged':
            continue

        # Must match project
        project_match = re.search(r'^project:\s*(.+)$', frontmatter, re.MULTILINE)
        if not project_match:
            continue
        fm_project = project_match.group(1).strip().strip('"').strip("'")
        if fm_project.lower() != project.lower() and slugify(fm_project) != slugify(project):
            continue

        # Defense-in-depth: check if already has a real summary
        has_summary = bool(re.search(r'^## Summary', content, re.MULTILINE))
        has_unavailable = 'AI summary unavailable' in content

        if has_summary and not has_unavailable:
            # Already summarized by legacy code path — fix status on disk
            try:
                fixed = re.sub(
                    r'^status: auto-logged',
                    'status: summarized',
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                # Atomic write: temp file + rename (per CLAUDE.md convention)
                fd, tmp = tempfile.mkstemp(
                    prefix='.ob-fix-', suffix='.md.tmp', dir=str(f.parent)
                )
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as fw:
                        fw.write(fixed)
                    os.replace(tmp, str(f))
                except Exception:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    continue
                # Invalidate cache for this file
                sid = _get_session_id_fast()
                cache_key = f"metadata:{os.path.realpath(str(f))}"
                cache_set(sid, cache_key, None)
                auto_fixed += 1
            except OSError:
                pass
            continue

        unsummarized.append(str(f))

    return json.dumps({"unsummarized": unsummarized, "auto_fixed": auto_fixed})


def build_context_brief(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    project: str,
    hook_status_line: str | None = None,
) -> str:
    """Build the /recall context brief entirely in Python.

    Reads session and insight files directly (no sub-agent), composes
    a structured markdown brief, and runs open-item detection.

    Args:
        vault_path: Obsidian vault root.
        sessions_folder: Folder name (relative to vault) containing sessions.
        insights_folder: Folder name (relative to vault) containing insights.
        project: Project slug to filter on.
        hook_status_line: Optional pre-formatted status line (e.g. "[OK] …" or
            "[WARN] …") to prepend to the brief so /recall can surface SessionStart
            hook health at a glance.

    Returns a structured string with labeled sections:
      CONTEXT_BRIEF: <markdown brief>
      LOAD_MANIFEST: <key-value metadata>
      MOST_RECENT_SESSION_PATH: <path>
      OPEN_ITEM_CANDIDATES: <JSON array or NO_CANDIDATES>
    """
    sessions_dir = Path(vault_path) / sessions_folder
    insights_dir = Path(vault_path) / insights_folder

    # --- 1. Scan and filter sessions ---
    def _safe_sort_key(p: Path) -> tuple:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (p.name[:10], mtime)

    session_files: list[tuple[str, str, dict]] = []  # (filename, path, metadata)
    if sessions_dir.is_dir():
        md_files = [f for f in sessions_dir.iterdir() if f.suffix == '.md']
        for f in sorted(md_files, key=_safe_sort_key, reverse=True):
            meta = read_note_metadata(str(f))
            if not meta:
                continue
            fm_project = meta.get('project', '')
            if fm_project.lower() != project.lower() and slugify(fm_project) != slugify(project):
                continue
            session_files.append((f.name, str(f), meta))

    # --- 2. Read sessions (tiered) ---
    most_recent_summary = ""
    most_recent_open_items = ""
    most_recent_title = ""
    most_recent_date = ""
    most_recent_path = ""
    second_summary = ""
    second_title = ""
    second_date = ""

    _summary_re = re.compile(r"## Summary\n(.+?)(?=\n## |\Z)", re.DOTALL)
    _next_steps_re = re.compile(r"## Open Questions / Next Steps\n(.+?)(?=\n## |\Z)", re.DOTALL)

    if len(session_files) >= 1:
        _, most_recent_path, meta = session_files[0]
        most_recent_date = meta.get('date', '')
        most_recent_title = f"Session: {meta.get('project', project)}"
        if meta.get('git_branch'):
            most_recent_title += f" ({meta['git_branch']})"
        try:
            text = Path(most_recent_path).read_text(encoding='utf-8', errors='replace')
            m = _summary_re.search(text)
            if m:
                most_recent_summary = m.group(1).strip()
                # Use first sentence of summary as title
                first_line = most_recent_summary.split('\n')[0].strip()
                if first_line:
                    most_recent_title = first_line
            m = _next_steps_re.search(text)
            if m:
                most_recent_open_items = m.group(1).strip()
        except OSError:
            most_recent_summary = "(could not read session note)"
        else:
            try:
                if _vault_index is not None:
                    _db = _vault_index._default_db_path()
                    if os.path.isfile(_db):
                        _vault_index.log_access(_db, most_recent_path, "recall", project)
            except Exception as exc:
                print(f"[obsidian-brain] access log for recall context failed: {exc}",
                      file=sys.stderr)

    if len(session_files) >= 2:
        _, second_path, meta = session_files[1]
        second_date = meta.get('date', '')
        second_title = f"Session: {meta.get('project', project)}"
        if meta.get('git_branch'):
            second_title += f" ({meta['git_branch']})"
        try:
            with open(second_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = [f.readline() for _ in range(50)]
            text = ''.join(lines)
            m = _summary_re.search(text)
            if m:
                second_summary = m.group(1).strip()
                # Use first sentence of summary as title
                first_line = second_summary.split('\n')[0].strip()
                if first_line:
                    second_title = first_line
        except OSError:
            second_summary = "(could not read session note)"
        else:
            try:
                if _vault_index is not None:
                    _db = _vault_index._default_db_path()
                    if os.path.isfile(_db):
                        _vault_index.log_access(_db, second_path, "recall", project)
            except Exception as exc:
                print(f"[obsidian-brain] access log for recall context failed: {exc}",
                      file=sys.stderr)

    # History table (last 5 sessions)
    history_rows: list[str] = []
    for i, (fname, fpath, meta) in enumerate(session_files[:5]):
        date = meta.get('date', '')
        title = meta.get('project', project)
        branch = meta.get('git_branch', '')
        # Format duration as readable time
        dur_min = meta.get('duration_minutes', 0)
        try:
            dur_min = float(dur_min)
        except (ValueError, TypeError):
            dur_min = 0.0
        if dur_min >= 60:
            duration = f"{int(dur_min // 60)}h {int(dur_min % 60)}m"
        elif dur_min > 0:
            duration = f"{int(dur_min)}m"
        else:
            duration = ""
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content_text = f.read()
            # Prefer first sentence of ## Summary as title (more descriptive)
            summary_match = re.search(r'## Summary\n+(.+)', content_text)
            if summary_match:
                title = summary_match.group(1).strip()
            else:
                # Fall back to H1 heading
                for line_text in content_text.split('\n'):
                    if line_text.startswith('# '):
                        title = line_text[2:].strip()
                        break
        except OSError:
            pass
        history_rows.append(f"| {i+1} | {date} | {duration} | {title} | {branch} |")

    # --- 3. Load insights via vault index (layered ranking) ---
    insight_entries: list[tuple[str, str]] = []  # (title, key_point)
    insight_count = 0

    # Collect session context for layered ranking
    _session_ids: list[str] = []
    _session_tags: list[str] = []
    _session_summary = ""
    for _, _, _meta in session_files[:5]:
        sid = _meta.get("session_id", "")
        if sid:
            _session_ids.append(sid)
        for tag in _meta.get("tags", []):
            if "claude/topic/" in tag and tag not in _session_tags:
                _session_tags.append(tag)

    # Build summary from loaded sessions
    if most_recent_summary:
        _session_summary = most_recent_summary

    _use_vault_index = True
    try:
        from vault_index import ensure_index, query_related_notes
    except ImportError:
        _use_vault_index = False

    if _use_vault_index:
        try:
            db_path = ensure_index(vault_path, [sessions_folder, insights_folder])
            ranked_notes = query_related_notes(
                db_path=db_path,
                project=project,
                session_ids=_session_ids,
                session_tags=_session_tags,
                session_summary=_session_summary,
                note_types=["claude-insight", "claude-decision", "claude-error-fix", "claude-retro"],
                limit=20,
            )
            insight_count = len(ranked_notes)
            for note in ranked_notes:
                title = note["title"]
                key_point = ""
                note_path = note["path"]
                try:
                    with open(note_path, "r", encoding="utf-8", errors="replace") as fh:
                        past_frontmatter = False
                        frontmatter_closed = False
                        for line_text in fh:
                            stripped = line_text.strip()
                            if stripped == "---":
                                if not past_frontmatter:
                                    past_frontmatter = True
                                    continue
                                else:
                                    frontmatter_closed = True
                                    continue
                            if not frontmatter_closed:
                                continue
                            if stripped.startswith("# "):
                                continue
                            if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                                key_point = stripped[:100]
                                break
                except OSError:
                    pass
                insight_entries.append((title, key_point))
        except (sqlite3.Error, OSError) as _vi_exc:
            print(f"[obsidian-brain] vault index failed ({type(_vi_exc).__name__}: {_vi_exc}); "
                  "falling back to file scan", file=sys.stderr)
            _use_vault_index = False

    if not _use_vault_index:
        # Fallback to original file scan if vault index unavailable
        if insights_dir.is_dir():
            insight_files = sorted(
                [f for f in insights_dir.iterdir() if f.suffix == '.md'],
                reverse=True
            )
            project_insights: list[Path] = []
            for f in insight_files:
                meta = read_note_metadata(str(f))
                if not meta:
                    continue
                fm_project = meta.get('project', '')
                if fm_project.lower() != project.lower() and slugify(fm_project) != slugify(project):
                    continue
                project_insights.append(f)

            insight_count = len(project_insights)
            for f in project_insights[:20]:
                title = f.stem
                key_point = ""
                try:
                    with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                        past_frontmatter = False
                        frontmatter_closed = False
                        for line_text in fh:
                            stripped = line_text.strip()
                            if stripped == '---':
                                if not past_frontmatter:
                                    past_frontmatter = True
                                    continue
                                else:
                                    frontmatter_closed = True
                                    continue
                            if not frontmatter_closed:
                                continue
                            if stripped.startswith('# '):
                                title = stripped[2:].strip()
                                continue
                            if stripped and not stripped.startswith('#') and not stripped.startswith('---'):
                                key_point = stripped[:100]
                                break
                except OSError:
                    pass
                insight_entries.append((title, key_point))

    # Trim insights to ~500 tokens (~375 words, ~1875 chars)
    insight_text_parts: list[str] = []
    total_chars = 0
    for title, key_point in insight_entries:
        entry = f"- **{title}**"
        if key_point:
            entry += f" — {key_point}"
        if total_chars + len(entry) > 1875:
            insight_text_parts.append(f"- **{title}**")
            total_chars += len(title) + 6
            if total_chars > 2200:
                break
            continue
        insight_text_parts.append(entry)
        total_chars += len(entry)

    insights_section = "\n".join(insight_text_parts) if insight_text_parts else "No curated insights yet for this project."

    # --- 4. Compose brief ---
    brief_parts: list[str] = []
    if hook_status_line:
        brief_parts.append(hook_status_line)
        brief_parts.append("")
    brief_parts.append(f"## Project Context: {project}")

    if most_recent_summary:
        brief_parts.append(f"\n### Last Session ({most_recent_date})")
        brief_parts.append(most_recent_summary)
        if most_recent_open_items:
            brief_parts.append(f"\n**Open Items / Next Steps:**\n{most_recent_open_items}")
    else:
        brief_parts.append(f"\nNo session history found for {project}.")

    if second_summary:
        brief_parts.append(f"\n### Previous Session ({second_date})")
        brief_parts.append(second_summary)

    brief_parts.append(f"\n### Curated Insights")
    brief_parts.append(insights_section)

    if history_rows:
        brief_parts.append("\n### Recent Session History")
        brief_parts.append("| # | Date | Duration | Title | Branch |")
        brief_parts.append("|---|------|----------|-------|--------|")
        brief_parts.extend(history_rows)

    brief = "\n".join(brief_parts)

    # --- 5. Open-item detection ---
    candidates_output = "NO_CANDIDATES"
    if most_recent_path:
        try:
            _hooks_dir = os.path.dirname(os.path.abspath(__file__))
            if _hooks_dir not in sys.path:
                sys.path.insert(0, _hooks_dir)
            from open_item_dedup import collect_open_items

            evidence_parts: list[str] = []
            try:
                content = Path(most_recent_path).read_text(encoding='utf-8', errors='replace')
                for section in ["Summary", "Key Decisions", "Changes Made", "Errors Encountered"]:
                    m = re.search(rf"## {section}\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
                    if m:
                        evidence_parts.append(m.group(1))
            except OSError:
                pass

            evidence = "\n".join(evidence_parts)
            if evidence:
                items = collect_open_items(vault_path, sessions_folder, project)
                if not items:
                    candidates_output = "NO_ITEMS"
                elif items:
                    candidates = match_items_against_evidence(evidence, items)
                    if candidates:
                        filtered = [c for c in candidates if c.get("confidence", 0) >= 3]
                        if filtered:
                            candidates_output = json.dumps(filtered)
        except Exception as exc:
            print(f"[obsidian-brain] open-item detection failed (non-fatal): {exc}", file=sys.stderr)

    # --- 6. Compose structured output ---
    manifest_lines = [
        f"full_session_title: {most_recent_title or '(none)'}",
        f"full_session_date: {most_recent_date or '(none)'}",
        f"full_session_path: {most_recent_path or '(none)'}",
        f"summary_session_title: {second_title or '(none)'}",
        f"summary_session_date: {second_date or '(none)'}",
        f"insight_count: {insight_count}",
    ]

    # Use unique delimiters that cannot appear in user-authored markdown content
    output_parts = [
        "<<<OB_CONTEXT_BRIEF>>>",
        brief,
        "",
        "<<<OB_LOAD_MANIFEST>>>",
        "\n".join(manifest_lines),
        "",
        "<<<OB_MOST_RECENT_SESSION_PATH>>>",
        most_recent_path,
        "",
        "<<<OB_OPEN_ITEM_CANDIDATES>>>",
        candidates_output,
    ]

    return "\n".join(output_parts)


# ---------------------------------------------------------------------------
# Vault corpus collection (for /emerge pattern discovery)
# ---------------------------------------------------------------------------


def _parse_section_bullets(text: str | None) -> list[str]:
    """Extract bullet items from a markdown section body.

    Returns empty list for None, empty, or 'None.' content.
    """
    if not text:
        return []
    stripped = text.strip()
    if stripped.lower() in ("none.", "none", "n/a", ""):
        return []
    items = []
    for line in stripped.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def collect_vault_corpus(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    days: int = 7,
) -> str:
    """Scan vault session and insight notes, date-filter, extract structured data.

    Returns JSON string with keys: date_range, note_count, notes[].
    Each note has: file, type, date, project, tags, summary, decisions,
    errors, open_items.

    Security: path containment via resolve() + is_relative_to().
    Note: scrub_secrets() is NOT called — content is already scrubbed at write time.
    """
    vault_root = Path(vault_path).resolve()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    end_date = datetime.date.today()

    # Cap limits
    _MAX_SUMMARY_CHARS = 500
    _MAX_LIST_ITEMS = 10

    notes_out: list[dict] = []

    # Scan both folders
    folders = [
        (sessions_folder, "claude-session"),
        (insights_folder, "claude-insight"),
    ]

    for folder_name, default_type in folders:
        folder = vault_root / folder_name
        if not folder.is_dir():
            continue

        for md_file in folder.iterdir():
            if md_file.suffix != ".md":
                continue

            # Path containment: reject symlinks pointing outside vault
            resolved = md_file.resolve()
            if not resolved.is_relative_to(vault_root):
                continue

            meta = read_note_metadata(str(md_file))
            if not meta:
                continue

            # Date filtering — skip notes without parseable date
            date_str = meta.get("date", "")
            if not date_str:
                continue
            try:
                note_date = datetime.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue
            if note_date < cutoff:
                continue

            # Read full note content for section parsing
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Parse summary — with unsummarized fallback
            summary = ""
            m = _RE_SUMMARY.search(content)
            if m:
                raw_summary = m.group(1).strip()
                if "AI summary unavailable" in raw_summary:
                    # Fall back to raw conversation section
                    m_raw = _RE_RAW_CONVERSATION.search(content)
                    if m_raw:
                        summary = m_raw.group(1).strip()[:_MAX_SUMMARY_CHARS]
                else:
                    summary = raw_summary[:_MAX_SUMMARY_CHARS]

            # Parse structured sections
            m_dec = _RE_DECISIONS.search(content)
            decisions = _parse_section_bullets(m_dec.group(1) if m_dec else None)[
                :_MAX_LIST_ITEMS
            ]

            m_err = _RE_ERRORS.search(content)
            errors = _parse_section_bullets(m_err.group(1) if m_err else None)[
                :_MAX_LIST_ITEMS
            ]

            m_open = _RE_OPEN_ITEMS.search(content)
            open_items = _parse_section_bullets(m_open.group(1) if m_open else None)[
                :_MAX_LIST_ITEMS
            ]

            tags = meta.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            tags = tags[:_MAX_LIST_ITEMS]

            note_type = meta.get("type", default_type)

            notes_out.append(
                {
                    "file": md_file.name,
                    "type": note_type,
                    "date": date_str,
                    "project": meta.get("project", ""),
                    "tags": tags,
                    "summary": summary,
                    "decisions": decisions,
                    "errors": errors,
                    "open_items": open_items,
                }
            )

    result = {
        "date_range": f"{cutoff.isoformat()} to {end_date.isoformat()}",
        "note_count": len(notes_out),
        "notes": notes_out,
    }
    return json.dumps(result, indent=2)


def upgrade_and_collect_corpus(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    days: int,
    output_path: str,
) -> str:
    """Upgrade unsummarized notes then collect corpus in a single pass.

    1. Scan sessions folder for notes with ``status: auto-logged`` within
       the date window and attempt ``upgrade_unsummarized_note()`` on each.
    2. Call ``collect_vault_corpus()`` to build the full corpus (including
       freshly upgraded notes).
    3. Atomically write corpus JSON to *output_path*.
    4. Return status line: ``OK:<total>:<upgraded>:<failed>`` or
       ``EMPTY:0:0:0``.
    """
    vault_root = Path(vault_path).resolve()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)

    upgraded = 0
    failed = 0

    # --- Phase 1: upgrade unsummarized notes ---
    sessions_dir = vault_root / sessions_folder
    if sessions_dir.is_dir():
        for md_file in sessions_dir.iterdir():
            if md_file.suffix != ".md":
                continue

            # Path containment
            resolved = md_file.resolve()
            if not resolved.is_relative_to(vault_root):
                continue

            meta = read_note_metadata(str(md_file))
            if not meta:
                continue

            # Date filter
            date_str = meta.get("date", "")
            if not date_str:
                continue
            try:
                note_date = datetime.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue
            if note_date < cutoff:
                continue

            # Only upgrade auto-logged notes
            if meta.get("status") != "auto-logged":
                continue

            try:
                result = upgrade_unsummarized_note(
                    note_path=str(md_file),
                    vault_path=vault_path,
                    sessions_folder=sessions_folder,
                    project=meta.get("project", ""),
                )
                if result and not result.startswith("Failed"):
                    upgraded += 1
                    # Bust metadata cache for this note
                    session_id = meta.get("session_id", "")
                    if session_id:
                        cache_invalidate(session_id)
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                print(f"[obsidian-brain] upgrade failed for {md_file.name}: {exc}", file=sys.stderr)

    # --- Phase 2: collect corpus (now includes freshly upgraded notes) ---
    corpus_json = collect_vault_corpus(
        vault_path, sessions_folder, insights_folder, days
    )
    corpus = json.loads(corpus_json)

    total = corpus.get("note_count", 0)
    if total == 0:
        return "EMPTY:0:0:0"

    # Add stats to corpus
    corpus["stats"] = {
        "total_notes": total,
        "upgraded": upgraded,
        "upgrade_failures": failed,
        "window_days": days,
    }

    # --- Phase 3: atomic write to output_path ---
    out = Path(output_path)
    os.makedirs(str(out.parent), exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        dir=str(out.parent), suffix=".tmp", prefix=".corpus-"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(corpus, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(out))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return f"OK:{total}:{upgraded}:{failed}"


# ---------------------------------------------------------------------------
# Filename / slug helpers
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 40) -> str:
    """Turn arbitrary text into a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "session"


def make_filename(
    date_str: str, slug: str, session_id: str, suffix: str = ""
) -> str:
    """Build note filename: ``YYYY-MM-DD-<slug>-<hash>[suffix].md``

    Uses a 4-char SHA256 hash of the session_id.
    """
    h = hashlib.sha256(session_id.encode()).hexdigest()[:4]
    return f"{date_str}-{slug}-{h}{suffix}.md"


def should_skip_session(
    user_messages: list[str],
    duration: float,
    min_messages: int = 3,
    min_duration: float = 2.0,
) -> bool:
    """Return True if the session is below logging thresholds.

    Skips if user message count < min_messages.
    Skips if duration is known (> 0) and below min_duration.
    """
    if len(user_messages) < min_messages:
        return True
    if duration > 0 and duration < min_duration:
        return True
    return False


def extract_tool_uses(messages: list[dict]) -> list[dict]:
    """Extract tool usage details from transcript for the raw fallback note.

    Returns a list of dicts: [{"name": "Edit", "detail": "file.py:10-20"}, ...]

    Handles both the canonical CC JSONL shape (entry['message']['content'])
    and the flat fallback shape (entry['content']) via _entry_content.
    """
    tool_uses: list[dict] = []
    for entry in messages:
        content = _entry_content(entry)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {}) if isinstance(block.get("input"), dict) else {}
            detail = ""
            if name in ("Edit", "Write", "MultiEdit"):
                fp = inp.get("file_path", "")
                detail = f"`{fp}`" if fp else ""
            elif name == "Bash":
                cmd = inp.get("command", "")[:120]
                detail = f"`{cmd}`" if cmd else ""
            elif name == "Read":
                fp = inp.get("file_path", "")
                detail = f"`{fp}`" if fp else ""
            elif name in ("Grep", "Glob"):
                pattern = inp.get("pattern", "")
                detail = f'pattern="{pattern}"' if pattern else ""
            elif name == "WebFetch":
                url = inp.get("url", "")[:80]
                detail = url if url else ""
            elif name == "WebSearch":
                query = inp.get("query", "")[:80]
                detail = f'"{query}"' if query else ""
            elif name == "Agent":
                desc = inp.get("description", "")[:80]
                detail = desc if desc else ""
            else:
                detail = ""

            if name:
                tool_uses.append({"name": name, "detail": detail})
    return tool_uses


def get_project_name(cwd: str) -> str:
    """Return the basename of the working directory as the project name."""
    return Path(cwd).name if cwd else "unknown"


def find_transcript_jsonl(session_id: str) -> Path | None:
    """Locate the original Claude Code transcript JSONL by session_id.

    Returns the Path if found, None otherwise. Uses find(1) so it is
    agnostic to project-path encoding (hyphens vs underscores).
    """
    if not session_id or session_id == "unknown":
        return None
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return None
    # Reject any session_id containing glob metacharacters, path separators,
    # or whitespace. `find -name` matches basenames and treats its argument
    # as a glob, so separators would never match and metacharacters would
    # match the wrong file. UUIDs never contain any of these — an occurrence
    # indicates garbage input rather than a legitimate lookup.
    if any(c in session_id for c in "*?[]/\\ \t\n\r"):
        return None
    target = f"{session_id}.jsonl"
    # Primary path: external `find` with -print -quit (fast on large trees).
    # Suppress stderr so permission-denied or other noise on unrelated
    # subtrees does not poison the exit code. Use stdout whenever it's
    # non-empty regardless of returncode — `find` commonly returns non-zero
    # after encountering a restricted directory even when it also printed a
    # legitimate match from a sibling directory.
    try:
        result = subprocess.run(
            ["find", str(projects_dir), "-name", target, "-type", "f", "-print", "-quit"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        )
        if result.stdout.strip():
            first = result.stdout.strip().split("\n")[0]
            if first:
                real_first = os.path.realpath(first)
                if not real_first.startswith(str(projects_dir.resolve()) + os.sep):
                    return None
                return Path(real_first)
            return None
    except subprocess.TimeoutExpired:
        # If `find` already timed out on this tree, a pure-Python rglob
        # will almost certainly be slower — the tree is too large. Treat
        # timeout as a hard failure so /recall falls back to the raw note
        # rather than hanging on a worse scan.
        return None
    except FileNotFoundError:
        # `find` not on PATH (sandboxed/minimal container). Fall through
        # to the pure-Python rglob fallback below.
        pass
    except OSError:
        pass

    # Fallback: pure-Python rglob. Only reached when `find` is unavailable,
    # never when it timed out. Dependency-free so /recall still works in
    # sandboxed environments that don't ship with `find`.
    try:
        for path in projects_dir.rglob(target):
            if path.is_file():
                real = os.path.realpath(str(path))
                if not real.startswith(str(projects_dir.resolve()) + os.sep):
                    continue  # skip symlinks escaping projects_dir
                return Path(real)
    except OSError:
        return None
    return None


def parse_full_transcript(jsonl_path: Path, max_bytes: int = 5_000_000) -> dict:
    """Parse a Claude Code transcript JSONL WITHOUT the raw-note caps.

    Delegates to the canonical extract_user_messages / extract_assistant_messages /
    extract_tool_uses helpers so tool-use and error detection stay in parity
    with the SessionEnd write path. Never fails silently on data loss —
    the returned `warnings` list is the caller's signal for every hiccup.

    Applies a hard byte budget. When the transcript exceeds max_bytes, it
    is sliced into head + tail halves of the budget; partial lines at the
    slice boundaries are detected (head not ending on \\n, tail not starting
    on \\n) and dropped explicitly with a warning.

    Returns a dict with keys:
        - user_msgs: list[str]
        - assistant_msgs: list[str]
        - tool_uses: list[dict]   (same shape as extract_tool_uses output)
        - files_touched: list[str]
        - errors: list[str]
        - truncated: bool          (True if byte budget kicked in)
        - warnings: list[str]      (visible issues the caller should surface)
        - raw_note_max_turns: int  (the RAW_NOTE_MAX_TURNS constant, for caller reference)
        - raw_note_would_truncate: bool  (True iff build_raw_fallback would hit its write cap)
    """
    warnings: list[str] = []
    bad_lines = 0
    unknown_block_types: set[str] = set()
    truncated = False

    def _empty_result(warning: str) -> dict:
        return {
            "user_msgs": [], "assistant_msgs": [], "tool_uses": [],
            "files_touched": [], "errors": [], "truncated": False,
            "warnings": [warning],
            # Always include the shared cap + derived signal so /recall's
            # decision logic can key off one consistent schema regardless
            # of which branch ran. Empty transcripts cannot have truncated.
            "raw_note_max_turns": RAW_NOTE_MAX_TURNS,
            "raw_note_would_truncate": False,
        }

    try:
        size = jsonl_path.stat().st_size
    except OSError as exc:
        return _empty_result(f"Could not stat transcript file: {exc}")

    if size == 0:
        return _empty_result("Transcript file is empty (0 bytes).")

    if size <= max_bytes:
        try:
            with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError as exc:
            return _empty_result(f"Could not read transcript file: {exc}")
    else:
        # Slice head + tail of the byte budget. Boundary-safe: only drop a
        # line when the slice actually cut it mid-record. If head_bytes
        # ends on a newline, its last line is complete — keep it.
        half = max_bytes // 2
        # Guarantee head and tail do not overlap: tail starts at max(half, size - half).
        tail_offset = max(half, size - half)
        # Peek at the byte immediately before tail_offset to determine
        # whether the tail slice started exactly at the beginning of a
        # record. If that preceding byte is a newline, tail_offset lies at
        # a record boundary and the first tail line is complete; otherwise
        # the record was cut mid-line and the first tail line is partial.
        # (Checking tail_text[0] == "\n" is wrong — a clean record boundary
        # means the tail text starts with the first char of a record, not
        # a newline.)
        tail_starts_cleanly = False
        try:
            with open(jsonl_path, "rb") as fh:
                head_bytes = fh.read(half)
                if tail_offset > 0:
                    fh.seek(tail_offset - 1)
                    prev_byte = fh.read(1)
                    tail_starts_cleanly = prev_byte in (b"\n", b"\r")
                else:
                    tail_starts_cleanly = True
                fh.seek(tail_offset)
                tail_bytes = fh.read()
        except OSError as exc:
            return _empty_result(f"Could not slice transcript file: {exc}")

        head_text = head_bytes.decode("utf-8", errors="replace")
        tail_text = tail_bytes.decode("utf-8", errors="replace")
        head_lines = head_text.splitlines()
        tail_lines = tail_text.splitlines()
        partial_dropped = 0
        # Drop the last head line only if head_bytes did not end on a newline
        # (meaning the record is genuinely cut mid-line).
        if head_lines and not head_text.endswith(("\n", "\r")):
            head_lines.pop()
            partial_dropped += 1
        # Drop the first tail line only if tail_offset did NOT land at a
        # clean record boundary (byte before tail_offset is not a newline).
        if tail_lines and not tail_starts_cleanly:
            tail_lines.pop(0)
            partial_dropped += 1
        lines = head_lines + tail_lines
        truncated = True
        if partial_dropped:
            warnings.append(
                f"Transcript byte budget exceeded ({size} > {max_bytes} bytes) — "
                f"middle section sliced, {partial_dropped} partial JSONL lines dropped at slice boundaries."
            )
        else:
            warnings.append(
                f"Transcript byte budget exceeded ({size} > {max_bytes} bytes) — "
                f"middle section sliced (both slice boundaries fell on record boundaries cleanly)."
            )

    # First pass: collect parsed JSONL records into an entries list. The
    # downstream extract_* helpers accept both the canonical CC shape
    # (top-level `type` plus nested `message.content`) and the flat
    # fallback shape, so no explicit normalization is needed here.
    entries: list[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if not isinstance(obj, dict):
            bad_lines += 1
            continue
        entries.append(obj)
        # Collect any unexpected content block types for user-visible warnings.
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype and btype not in (
                        "text", "tool_use", "tool_result", "thinking",
                        "image", "redacted_thinking",
                    ):
                        unknown_block_types.add(btype)

    # Delegate to canonical helpers so behavior stays in parity with the
    # SessionEnd write path.
    user_msgs = extract_user_messages(entries)
    assistant_msgs = extract_assistant_messages(entries)
    tool_uses = extract_tool_uses(entries)

    # Files touched + errors: delegate to the shared helpers used by
    # extract_session_metadata so both code paths stay in lockstep.
    # No caps applied here — caps belong to the display layer, not
    # re-parse, so the full summary can see everything the transcript
    # actually contains.
    files_seen = _extract_files_touched(entries)
    errors = _extract_errors(entries)

    # Note: we do not inject a "[... middle truncated ...]" marker into
    # user_msgs. At this point it would land at the very end of the list
    # (after the tail slice), not at the actual head/tail boundary, which
    # would be misleading. The slice is already surfaced via `truncated`
    # and the `warnings` list, which is what the caller uses for display.

    if bad_lines:
        warnings.append(f"{bad_lines} malformed JSONL line(s) skipped while re-parsing transcript.")
    if unknown_block_types:
        warnings.append(
            f"Unknown content block types encountered (data may be incomplete): {', '.join(sorted(unknown_block_types))}"
        )

    # Simulate the exact write loop in build_raw_fallback to determine
    # whether the raw fallback would have truncated. This is the only
    # fully deterministic signal: the cap applies to lines actually
    # written, and filtered system-noise user messages do not increment
    # the counter. Simple parsed_total > cap comparison can false-positive
    # when noise filtering gives headroom.
    raw_note_would_truncate = _would_raw_fallback_truncate(user_msgs, assistant_msgs)

    return {
        "user_msgs": user_msgs,
        "assistant_msgs": assistant_msgs,
        "tool_uses": tool_uses,
        "files_touched": files_seen,
        "errors": errors,
        "truncated": truncated,
        "warnings": warnings,
        # The raw-note cap constant, preserved for backward compatibility
        # with callers that still want to inspect it.
        "raw_note_max_turns": RAW_NOTE_MAX_TURNS,
        # Definitive signal: true iff build_raw_fallback would have hit
        # its write cap before consuming all user+assistant messages.
        # This is what /recall should branch on.
        "raw_note_would_truncate": raw_note_would_truncate,
    }


def _would_raw_fallback_truncate(
    user_msgs: list[str], assistant_msgs: list[str]
) -> bool:
    """Return True iff build_raw_fallback's write loop would hit its
    RAW_NOTE_MAX_TURNS cap before consuming all user+assistant messages.

    Mirrors the exact loop in build_raw_fallback so the signal is
    deterministic: filtered system-noise user messages do not count
    toward the cap, so a transcript with more total messages than the
    cap may still fit entirely when enough noise is filtered out.
    """
    max_turns = RAW_NOTE_MAX_TURNS
    u_idx, a_idx = 0, 0
    turn = 0
    while turn < max_turns and (
        u_idx < len(user_msgs)
        or (assistant_msgs and a_idx < len(assistant_msgs))
    ):
        if u_idx < len(user_msgs):
            snippet = user_msgs[u_idx][:1200].replace("\n", " ")
            # Same filter as build_raw_fallback: skip system noise.
            if not (
                snippet.startswith("<task-notification>")
                or snippet.startswith("Base directory for this skill:")
                or snippet.startswith("<local-command")
            ):
                turn += 1
            u_idx += 1
        if assistant_msgs and a_idx < len(assistant_msgs):
            a_idx += 1
            turn += 1
    # Truncated iff the loop bailed on the cap with inputs remaining.
    return u_idx < len(user_msgs) or a_idx < len(assistant_msgs)


def build_raw_fallback(
    user_msgs: list[str],
    metadata: dict,
    assistant_msgs: list[str] | None = None,
    tool_uses: list[dict] | None = None,
    config: dict | None = None,
) -> str:
    """Build a detailed note body without AI summarization -- raw data extraction.

    Includes user messages, assistant messages, tool usage, files touched,
    and errors for maximum context when /recall does deferred summarization.
    """
    sections: list[str] = []

    project = metadata.get("project", "unknown")
    duration = metadata.get("duration_minutes", 0)

    sections.append("## Summary")
    sections.append(
        f"Session in **{project}** ({duration} min). "
        "AI summary unavailable \u2014 raw extraction below.\n"
    )

    sections.append("## Key Decisions")
    sections.append("_Not extracted (AI summary unavailable)._\n")

    sections.append("## Changes Made")
    files = metadata.get("files_touched", [])
    if files:
        for f in files[:60]:
            sections.append(f"- `{f}`")
    else:
        sections.append("None detected.")
    sections.append("")

    # Tool usage details (commands run, files edited) — scrubbed for secrets
    if tool_uses:
        sections.append("## Tool Usage")
        for tu in tool_uses[:80]:
            name = tu.get("name", "")
            detail = escape_wikilinks(scrub_secrets(tu.get("detail", "")))
            if name and detail:
                sections.append(f"- **{name}**: {detail}")
            elif name:
                sections.append(f"- **{name}**")
        sections.append("")

    sections.append("## Errors Encountered")
    errors = metadata.get("errors", [])
    if errors:
        for e in errors[:30]:
            sections.append(f"- {e}")
    else:
        sections.append("None.")
    sections.append("")

    sections.append("## Open Questions / Next Steps")
    sections.append("_Not extracted (AI summary unavailable)._\n")

    # Interleaved conversation for /recall to summarize (controlled by config toggle)
    if (config or {}).get("log_raw_messages", True):
        sections.append("## Conversation (raw)")
        max_turns = RAW_NOTE_MAX_TURNS
        u_idx, a_idx = 0, 0
        turn = 0
        while turn < max_turns and (u_idx < len(user_msgs) or (assistant_msgs and a_idx < len(assistant_msgs))):
            if u_idx < len(user_msgs):
                snippet = escape_wikilinks(scrub_secrets(user_msgs[u_idx][:1200].replace("\n", " ")))
                # Skip system noise (task notifications, command loading, etc.)
                if not snippet.startswith("<task-notification>") and not snippet.startswith("Base directory for this skill:") and not snippet.startswith("<local-command"):
                    sections.append(f"**User:** {snippet}")
                    turn += 1
                u_idx += 1
            if assistant_msgs and a_idx < len(assistant_msgs):
                snippet = escape_wikilinks(scrub_secrets(assistant_msgs[a_idx][:1200].replace("\n", " ")))
                sections.append(f"**Assistant:** {snippet}")
                a_idx += 1
                turn += 1
        sections.append("")

    return "\n".join(sections)


def is_resumed_session(
    vault_path: str, sessions_folder: str, session_id: str
) -> bool:
    """Check if a note with the same session_id hash already exists in the vault."""
    sessions_dir = Path(vault_path) / sessions_folder
    if not sessions_dir.exists():
        return False
    h = hashlib.sha256(session_id.encode()).hexdigest()[:4]
    for _ in sessions_dir.glob(f"*-{h}.md"):
        return True
    return False


def upgrade_note_with_summary(
    note_path: str,
    summary_text: str,
    vault_path: str,
    sessions_folder: str,
    project: str,
    source: str = "sub-agent fallback",
    warnings: list[str] | None = None,
) -> str:
    """Apply a pre-generated summary to a raw session note.

    Handles the pipeline finish: read raw note, validate summary has
    ## Summary, rebuild note (frontmatter with status: summarized, title,
    summary sections, audit trail), run dedup, atomic write.

    Returns a one-line status string.
    """
    if warnings is None:
        warnings = []

    if not re.search(r"^## Summary\s*$", summary_text, re.MULTILINE):
        return f"Failed: malformed summary (no ## Summary section) from {source} for {os.path.basename(note_path)}"

    # Read the raw note
    try:
        with open(note_path, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except OSError as exc:
        return f"Failed: cannot read {os.path.basename(note_path)}: {exc}"

    # Build upgraded note: original frontmatter + new summary + original audit trail
    new_lines: list[str] = []

    # Copy frontmatter, flipping status
    past_first_marker = False
    frontmatter_end = 0
    for i, line in enumerate(raw_lines):
        if line.strip() == '---':
            if not past_first_marker:
                past_first_marker = True
                new_lines.append(line)
                continue
            else:
                # End of frontmatter
                new_lines.append(line)
                frontmatter_end = i + 1
                break
        if past_first_marker:
            if line.strip().startswith('status:'):
                new_lines.append(re.sub(r'^(\s*status:\s*).*', r'\1summarized', line) + '\n' if not line.endswith('\n') else re.sub(r'^(\s*status:\s*).*', r'\1summarized', line))
            else:
                new_lines.append(line)

    if frontmatter_end == 0:
        return f"Failed: malformed frontmatter in {os.path.basename(note_path)} (missing closing ---)"

    # Add title from original
    title_found = False
    for line in raw_lines[frontmatter_end:]:
        if line.strip().startswith('# '):
            new_lines.append('\n')
            new_lines.append(line)
            title_found = True
            break
    if not title_found:
        new_lines.append('\n# Untitled Session\n')

    # Add warnings if any
    if warnings:
        new_lines.append('\n## ⚠️ Transcript re-parse warnings\n')
        for w in warnings:
            new_lines.append(f'- {w}\n')

    # Add summary sections
    new_lines.append('\n')
    new_lines.append(summary_text + '\n')

    # Add source note
    new_lines.append(f'\n_(Summary source: {source})_\n')

    # Preserve original audit trail sections (skip frontmatter).
    # Only exclude ## Changes Made / ## Errors Encountered if summary_text
    # actually contains them — otherwise preserve the raw audit data.
    audit_sections = [
        '## Tool Usage', '## Conversation (raw)',
        '## Session Metadata', '## Files Touched',
    ]
    if '## Changes Made' not in summary_text:
        audit_sections.append('## Changes Made')
    if '## Errors Encountered' not in summary_text:
        audit_sections.append('## Errors Encountered')

    in_audit = False
    for line in raw_lines[frontmatter_end:]:
        stripped = line.strip()
        if any(stripped.startswith(s) for s in audit_sections):
            in_audit = True
        elif stripped.startswith('## '):
            in_audit = False
        if in_audit:
            new_lines.append(line)

    # Extract the summary body signature BEFORE writing so we can fail the
    # upgrade with a clear "malformed summary" error rather than silently
    # degrading post-write verification. The signature is the first non-blank,
    # non-heading line of the Summary section — used to prove on re-read that
    # the body actually landed, not just the status flip.
    #
    # Heading detection follows ATX-heading rules strictly: `#{1,6}` must be
    # followed by whitespace or end-of-line. A line like `#1234 issue ref` or
    # `#hashtag note` is legitimate content, not a heading, and must not be
    # skipped — otherwise it could produce a false "empty or heading-only
    # Summary body" failure when it is the first real content line.
    #
    # The level-2 break uses `##(?:\s|$)` (any whitespace after, or EOL) so
    # a tab-separated or double-space-separated next section like
    # `##\tKey Decisions` still terminates the Summary block cleanly.
    _atx_heading_re = re.compile(r'^#{1,6}(?:\s|$)')
    _h2_re = re.compile(r'^##(?:\s|$)')
    summary_signature = None
    in_summary = False
    for line in summary_text.split('\n'):
        if line.strip() == '## Summary':
            in_summary = True
            continue
        if in_summary:
            stripped = line.strip()
            if _h2_re.match(stripped):
                break  # next top-level section — Summary body was empty
            if _atx_heading_re.match(stripped):
                continue  # sub-heading inside Summary — skip but keep looking
            if stripped:
                summary_signature = stripped
                break

    if summary_signature is None:
        return f"Failed: malformed summary (empty or heading-only Summary body) from {source} for {os.path.basename(note_path)}"

    importance = parse_importance(summary_text)

    # Atomic write with fsync + post-write verification.
    # Guarantees the summary actually landed on disk before returning success.
    # `or "."` handles the case where note_path is a bare filename (no
    # directory component), which would otherwise produce `dir=""` and
    # crash tempfile.mkstemp on every platform.
    note_dir = os.path.dirname(note_path) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix='.ob-upgrade-', suffix='.md.tmp', dir=note_dir)
    except OSError as exc:
        return f"Failed: cannot create temp file in {note_dir}: {exc}"
    try:
        try:
            orig_mode = os.stat(note_path).st_mode
        except OSError:
            orig_mode = 0o600
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, orig_mode)
        os.replace(tmp_path, note_path)
        # fsync the containing directory so the rename itself is durable
        # across a crash, not just the file contents.
        try:
            dir_fd = os.open(note_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Directory fsync is best-effort on filesystems that don't
            # support it (e.g. some network mounts). The in-process
            # verification below is the real guarantee for non-crash
            # failure modes.
            pass
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            print(
                f"[obsidian-brain] failed to clean up temp file {tmp_path}: {cleanup_exc}",
                file=sys.stderr,
            )
        return f"Failed: atomic write error for {os.path.basename(note_path)}: {exc}"

    # Post-write verification: re-read the target file and confirm the
    # summary actually landed. Protects against silent write-loss from
    # concurrent writers, filesystem races, or phantom "success" returns.
    try:
        with open(note_path, 'r', encoding='utf-8') as f:
            verify_content = f.read()
    except OSError as exc:
        return f"Failed: post-write read verification failed for {os.path.basename(note_path)}: {exc}"

    # Scope the status check to the YAML frontmatter block so a note body
    # that happens to mention "status: summarized" (in a conversation
    # excerpt, a code block, or this very PR's diff) cannot false-positive
    # the check. Anchor to the start of the file (allowing an optional
    # UTF-8 BOM) so a Markdown horizontal rule `---` in the body cannot
    # be mistaken for the opening frontmatter delimiter.
    fm_match = re.match(
        r'\ufeff?---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)',
        verify_content,
        re.DOTALL,
    )
    if fm_match is None:
        return f"Failed: post-write verification — YAML frontmatter not found at start of {os.path.basename(note_path)}"
    frontmatter_block = fm_match.group(1)
    if not re.search(r'^\s*status:\s*summarized\s*$', frontmatter_block, re.MULTILINE):
        return f"Failed: post-write verification — status not flipped to summarized in {os.path.basename(note_path)}"

    # Scope the signature check to the ## Summary section specifically.
    # Checking the whole file would false-positive if the signature text
    # happens to appear in a preserved audit trail (Conversation raw,
    # Tool Usage), even though the actual Summary body was clobbered.
    # Boundary uses `##(?:\s|$)` to be consistent with ATX-heading rules —
    # tab-separated or multi-space-separated next sections still terminate
    # the Summary block extraction cleanly.
    summary_match = re.search(
        r'^## Summary\s*\n(.*?)(?=^##(?:\s|$)|\Z)',
        verify_content,
        re.MULTILINE | re.DOTALL,
    )
    if summary_match is None:
        return f"Failed: post-write verification — ## Summary section not found in {os.path.basename(note_path)}"
    summary_block = summary_match.group(1)
    # Compare at line granularity — a substring match could false-positive
    # if the signature is a substring of some other line in the Summary
    # (e.g. the signature is "Fixed the bug." and an adjacent line says
    # "Before: Fixed the bug. After: also broken."). The signature must
    # appear as its own stripped line in the Summary block on disk.
    summary_block_lines = {line.strip() for line in summary_block.split('\n')}
    if summary_signature not in summary_block_lines:
        return f"Failed: post-write verification — summary body missing from {os.path.basename(note_path)}"

    # Write importance to DB only after file write + verification succeeded,
    # so the DB stays in sync with the on-disk note state.
    try:
        if _vault_index is not None:
            _db = _vault_index._default_db_path()
            if os.path.isfile(_db):
                _conn = _vault_index._connect(_db)
                try:
                    _conn.execute(
                        "UPDATE notes SET importance = ? WHERE path = ?",
                        (importance, note_path),
                    )
                    _conn.commit()
                finally:
                    _conn.close()
    except Exception as exc:
        print(f"[obsidian-brain] importance write-back failed for "
              f"{os.path.basename(note_path)}: {exc}", file=sys.stderr)

    # Run dedup pass (non-fatal — note is already upgraded)
    removed = []
    dedup_failed = False
    try:
        _hooks_dir = os.path.dirname(os.path.abspath(__file__))
        if _hooks_dir not in sys.path:
            sys.path.insert(0, _hooks_dir)
        from open_item_dedup import dedup_note_open_items
        removed = dedup_note_open_items(vault_path, sessions_folder, project, note_path)
    except (ImportError, OSError) as exc:
        dedup_failed = True
        print(f"[obsidian-brain] dedup failed (non-fatal, note already upgraded): {exc}", file=sys.stderr)
    except Exception as exc:
        dedup_failed = True
        print(f"[obsidian-brain] dedup unexpected error: {exc}", file=sys.stderr)

    # Invalidate metadata cache for this note (status changed from auto-logged to summarized)
    sid = _get_session_id_fast()
    cache_set(sid, f"metadata:{os.path.realpath(note_path)}", None)

    # Build status
    status = f"Upgraded {os.path.basename(note_path)} (source: {source})"
    if removed:
        status += f", deduped {len(removed)} item(s)"
    if dedup_failed:
        status += ", dedup failed (see stderr)"
    if warnings:
        status += f", {len(warnings)} warning(s)"
    return status


def prepare_summary_input(note_path: str) -> str:
    """Check if raw note would truncate; if so, extract JSONL to temp file.

    Called by /recall Step 3 before spawning sub-agents. Determines
    whether the sub-agent should read the raw note directly or a
    pre-extracted JSONL temp file with sampled messages.

    Returns one of:
      RAW_OK:<note_path>
      JSONL_PREPPED:<temp_file_path>:<note_path>
      NO_CONTENT:<note_path>
    """
    # Read only frontmatter (first 20 lines) — avoids loading large raw notes into memory
    try:
        with open(note_path, 'r', encoding='utf-8') as f:
            raw_lines = [f.readline() for _ in range(20)]
    except OSError as exc:
        print(f"[obsidian-brain] cannot read {os.path.basename(note_path)}: {exc}", file=sys.stderr)
        return f"NO_CONTENT:{note_path}"

    session_id = None
    project = "unknown"
    git_branch = "unknown"
    duration_minutes = 0.0
    for line in raw_lines:
        stripped = line.strip()
        if stripped.startswith('session_id:'):
            session_id = stripped.split(':', 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith('project:'):
            project = stripped.split(':', 1)[1].strip().strip('"')
        elif stripped.startswith('git_branch:'):
            git_branch = stripped.split(':', 1)[1].strip().strip('"')
        elif stripped.startswith('duration_minutes:'):
            try:
                duration_minutes = float(stripped.split(':', 1)[1].strip())
            except ValueError:
                pass

    if not session_id:
        print(f"[obsidian-brain] no session_id in {os.path.basename(note_path)}", file=sys.stderr)
        return f"NO_CONTENT:{note_path}"

    # Find and parse JSONL transcript
    try:
        jsonl_path = find_transcript_jsonl(session_id)
        if not jsonl_path:
            return f"RAW_OK:{note_path}"

        parsed = parse_full_transcript(jsonl_path)

        # Surface transcript warnings (Issue #1: never discard these)
        for w in parsed.get("warnings", []):
            print(f"[obsidian-brain] transcript warning for {os.path.basename(note_path)}: {w}", file=sys.stderr)

        if not parsed.get("raw_note_would_truncate", False):
            return f"RAW_OK:{note_path}"

        # Raw note would truncate — extract JSONL content to temp file
        user_msgs = parsed.get("user_msgs", [])
        assistant_msgs = parsed.get("assistant_msgs", [])
        if not user_msgs and not assistant_msgs:
            return f"RAW_OK:{note_path}"

        # Sample messages using same logic as generate_summary()
        if len(user_msgs) > 20:
            sampled_user = user_msgs[:10] + ["[... middle messages omitted ...]"] + user_msgs[-10:]
        else:
            sampled_user = user_msgs
        if len(assistant_msgs) > 20:
            sampled_asst = assistant_msgs[:10] + ["[... middle messages omitted ...]"] + assistant_msgs[-10:]
        else:
            sampled_asst = assistant_msgs

        user_sample = "\n---\n".join(sampled_user)[:12000]
        assistant_sample = "\n---\n".join(sampled_asst)[:12000]

        files_touched = parsed.get("files_touched", [])[:15]
        files_str = ", ".join(files_touched) if files_touched else "none detected"

        content = f"""# Session Summary Input (extracted from JSONL transcript)

**Project:** {project}
**Branch:** {git_branch}
**Duration:** {duration_minutes} minutes
**Files touched:** {files_str}

## Conversation

### User Messages (sampled)
{user_sample}

### Assistant Messages (sampled)
{assistant_sample}
"""

        # Write to temp file (use full session_id to avoid collisions)
        temp_path = os.path.join(_ensure_secure_dir(), f"prep-{session_id}.md")
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except OSError as exc:
            print(f"[obsidian-brain] cannot write temp file {temp_path}, falling back to truncated raw note: {exc}", file=sys.stderr)
            return f"RAW_OK:{note_path}"

        return f"JSONL_PREPPED:{temp_path}:{note_path}"

    except Exception as exc:
        print(f"[obsidian-brain] unexpected error in JSONL prep for {os.path.basename(note_path)}: {exc}", file=sys.stderr)
        return f"RAW_OK:{note_path}"


def upgrade_unsummarized_note(
    note_path: str,
    vault_path: str,
    sessions_folder: str,
    project: str,
    summary_model: str = "haiku",
    summary_timeout: int | None = None,
) -> str:
    """Upgrade an unsummarized session note with an AI summary.

    Orchestrates: find JSONL → parse transcript → decide source →
    generate summary → dedup open items → atomic write.

    Returns a one-line status string for the model to relay.
    """
    # Read the raw note
    try:
        with open(note_path, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except OSError as exc:
        return f"Failed: cannot read {os.path.basename(note_path)}: {exc}"

    # Extract session_id from frontmatter
    session_id = None
    for line in raw_lines[:20]:
        stripped = line.strip()
        if stripped.startswith('session_id:'):
            session_id = stripped.split(':', 1)[1].strip().strip('"').strip("'")
            break
    if not session_id:
        return f"Failed: no session_id in frontmatter of {os.path.basename(note_path)}"

    # Find and parse the JSONL transcript
    jsonl_path = find_transcript_jsonl(session_id)
    parsed: dict = {}
    warnings: list[str] = []
    user_msgs: list[str] = []
    assistant_msgs: list[str] = []
    source = "raw note"

    if jsonl_path:
        parsed = parse_full_transcript(jsonl_path)
        user_msgs = parsed.get("user_msgs", [])
        assistant_msgs = parsed.get("assistant_msgs", [])
        warnings = parsed.get("warnings", [])

        # Decide which source to use
        raw_note_would_truncate = parsed.get("raw_note_would_truncate", False)
        truncated = parsed.get("truncated", False)

        # Data always comes from JSONL when found — label accurately
        if truncated:
            source = "JSONL transcript (head+tail, middle truncated)"
        elif raw_note_would_truncate:
            source = "JSONL transcript (raw note would have truncated)"
        else:
            source = "JSONL transcript (full, raw note also sufficient)"
    else:
        # Fall back to raw note content for summarization
        source = "raw note (JSONL not found)"
        # Extract user/assistant messages from raw note conversation section
        in_conversation = False
        for line in raw_lines:
            stripped = line.strip()
            if stripped == '## Conversation (raw)':
                in_conversation = True
                continue
            if in_conversation:
                if stripped.startswith('## '):
                    break
                if stripped.startswith('**User:**'):
                    user_msgs.append(stripped[9:].strip())
                elif stripped.startswith('**Assistant:**'):
                    assistant_msgs.append(stripped[14:].strip())

    # Fall back to raw note if JSONL yielded empty messages (corrupted/empty JSONL)
    if jsonl_path and not user_msgs and not assistant_msgs:
        source = "raw note (JSONL found but empty)"
        in_conversation = False
        for line in raw_lines:
            stripped = line.strip()
            if stripped == '## Conversation (raw)':
                in_conversation = True
                continue
            if in_conversation:
                if stripped.startswith('## '):
                    break
                if stripped.startswith('**User:**'):
                    user_msgs.append(stripped[9:].strip())
                elif stripped.startswith('**Assistant:**'):
                    assistant_msgs.append(stripped[14:].strip())

    if not user_msgs and not assistant_msgs:
        return f"Failed: no conversation content in {os.path.basename(note_path)}"

    # Build metadata for generate_summary
    metadata: dict = {"project": project, "vault_path": vault_path, "sessions_folder": sessions_folder}
    for line in raw_lines[:20]:
        stripped = line.strip()
        if stripped.startswith('git_branch:'):
            metadata["git_branch"] = stripped.split(':', 1)[1].strip().strip('"')
        elif stripped.startswith('duration_minutes:'):
            try:
                metadata["duration_minutes"] = float(stripped.split(':', 1)[1].strip())
            except ValueError:
                pass

    # Add files_touched and errors from parsed transcript if available
    if jsonl_path and parsed:
        metadata["files_touched"] = parsed.get("files_touched", [])
        metadata["errors"] = parsed.get("errors", [])

    # Generate summary
    gen_kwargs: dict = {"model": summary_model}
    if summary_timeout is not None:
        gen_kwargs["timeout"] = summary_timeout
    summary_text = generate_summary(
        user_msgs, assistant_msgs, metadata, **gen_kwargs,
    )

    if not summary_text:
        return f"Failed: AI summarization returned empty for {os.path.basename(note_path)}"

    return upgrade_note_with_summary(
        note_path, summary_text, vault_path, sessions_folder, project,
        source=source, warnings=warnings,
    )
