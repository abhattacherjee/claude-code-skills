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
import subprocess
import sys
import tempfile
from pathlib import Path

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
    """Read ~/.claude/obsidian-brain-config.json, returning defaults for missing keys."""
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
    return config


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
        "project": Path(cwd).name if cwd else "unknown",
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


def generate_summary(
    user_msgs: list[str],
    assistant_msgs: list[str],
    metadata: dict,
    model: str = "haiku",
    timeout: int = 15,
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
"""

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        print(
            f"[obsidian-brain] claude -p failed (rc={result.returncode}): "
            f"{result.stderr[:200]}",
            file=sys.stderr,
        )
    except FileNotFoundError:
        print(
            "[obsidian-brain] claude CLI not found, summarization unavailable",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print("[obsidian-brain] claude -p timed out", file=sys.stderr)
    except Exception as exc:
        print(f"[obsidian-brain] claude -p error: {exc}", file=sys.stderr)

    return None


# ---------------------------------------------------------------------------
# Vault operations
# ---------------------------------------------------------------------------


def write_vault_note(
    vault_path: str, folder: str, filename: str, content: str
) -> bool:
    """Atomic write: temp file + chmod 0o644 + rename into vault folder.

    Creates the target folder if it does not exist.  Returns True on success.
    """
    dest_dir = Path(vault_path) / folder
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"[obsidian-brain] cannot create vault dir {dest_dir}: {exc}",
            file=sys.stderr,
        )
        return False

    dest = dest_dir / filename
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(dest_dir), prefix=".ob-", suffix=".md.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.chmod(tmp_path, 0o644)
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
            return Path(first) if first else None
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
                return path
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

    # Tool usage details (commands run, files edited)
    if tool_uses:
        sections.append("## Tool Usage")
        for tu in tool_uses[:80]:
            name = tu.get("name", "")
            detail = tu.get("detail", "")
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

    # Interleaved conversation for /recall to summarize
    sections.append("## Conversation (raw)")
    max_turns = RAW_NOTE_MAX_TURNS
    u_idx, a_idx = 0, 0
    turn = 0
    while turn < max_turns and (u_idx < len(user_msgs) or (assistant_msgs and a_idx < len(assistant_msgs))):
        if u_idx < len(user_msgs):
            snippet = user_msgs[u_idx][:1200].replace("\n", " ")
            # Skip system noise (task notifications, command loading, etc.)
            if not snippet.startswith("<task-notification>") and not snippet.startswith("Base directory for this skill:") and not snippet.startswith("<local-command"):
                sections.append(f"**User:** {snippet}")
                turn += 1
            u_idx += 1
        if assistant_msgs and a_idx < len(assistant_msgs):
            snippet = assistant_msgs[a_idx][:1200].replace("\n", " ")
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
