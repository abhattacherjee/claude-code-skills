"""
obsidian_utils.py — Shared utilities for obsidian-brain hook scripts.

Extracted from the validated spike (spike_session_log.py) with these changes:
  - No hardcoded config; uses load_config() reading ~/.claude/obsidian-brain-config.json
  - All functions take explicit parameters (vault_path, model, etc.) — no global state
  - File extraction uses tool_use blocks instead of regex heuristics
  - Python stdlib only

Every public function catches its own errors and logs to stderr.
"""

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

    # --- Files touched: extract from tool_use blocks (Edit/Write/MultiEdit) ---
    files_seen: list[str] = []
    for entry in messages:
        msg = entry.get("message", {})
        content = msg.get("content") if isinstance(msg, dict) else None
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
                inp = block.get("input", {})
                if isinstance(inp, dict):
                    fp = inp.get("file_path", "")
                    if fp and fp not in files_seen:
                        files_seen.append(fp)
    meta["files_touched"] = files_seen[:50]

    # --- Errors: extract from tool_result blocks with is_error ---
    errors: list[str] = []
    for entry in messages:
        msg = entry.get("message", {})
        content = msg.get("content") if isinstance(msg, dict) else None
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
    meta["errors"] = errors[:20]

    return meta


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
    """
    tool_uses: list[dict] = []
    for entry in messages:
        msg = entry.get("message", {})
        content = msg.get("content") if isinstance(msg, dict) else None
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
        for f in files[:30]:
            sections.append(f"- `{f}`")
    else:
        sections.append("None detected.")
    sections.append("")

    # Tool usage details (commands run, files edited)
    if tool_uses:
        sections.append("## Tool Usage")
        for tu in tool_uses[:30]:
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
        for e in errors[:15]:
            sections.append(f"- {e}")
    else:
        sections.append("None.")
    sections.append("")

    sections.append("## Open Questions / Next Steps")
    sections.append("_Not extracted (AI summary unavailable)._\n")

    # Interleaved conversation for /recall to summarize
    sections.append("## Conversation (raw)")
    max_turns = 40
    u_idx, a_idx = 0, 0
    turn = 0
    while turn < max_turns and (u_idx < len(user_msgs) or (assistant_msgs and a_idx < len(assistant_msgs))):
        if u_idx < len(user_msgs):
            snippet = user_msgs[u_idx][:600].replace("\n", " ")
            # Skip system noise (task notifications, command loading, etc.)
            if not snippet.startswith("<task-notification>") and not snippet.startswith("Base directory for this skill:") and not snippet.startswith("<local-command"):
                sections.append(f"**User:** {snippet}")
                turn += 1
            u_idx += 1
        if assistant_msgs and a_idx < len(assistant_msgs):
            snippet = assistant_msgs[a_idx][:600].replace("\n", " ")
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
