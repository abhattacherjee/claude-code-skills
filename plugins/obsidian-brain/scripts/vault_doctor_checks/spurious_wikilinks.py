"""vault_doctor check: detect and repair spurious wikilinks in conversation excerpts.

Bash ``[[ $VAR == pattern ]]`` conditionals in raw conversation and tool-usage
lines are parsed by Obsidian as wikilinks, creating phantom outgoing links.
This check finds unescaped ``[[`` in lines that are clearly conversation
excerpts (prefixed with ``**User:**``, ``**Assistant:**``, or ``- **``) and
escapes them to ``\\[\\[``.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import Issue, Result

NAME = "spurious-wikilinks"
DESCRIPTION = "Detect and fix unescaped [[ in conversation excerpts (bash conditionals parsed as Obsidian wikilinks)"
DEFAULT_WINDOW_DAYS = 9999  # unbounded — scan all notes

# Lines where [[ is conversation content, never an intentional wikilink.
_CONVERSATION_LINE_RE = re.compile(
    r"^(\*\*User:\*\*|\*\*Assistant:\*\*|- \*\*)"
)

# Unescaped [[ (not preceded by backslash).
_UNESCAPED_WIKILINK_RE = re.compile(r"(?<!\\)\[\[")


def scan(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    days: int,
    project: str | None = None,
) -> list[Issue]:
    """Find session notes with unescaped [[ in conversation/tool-usage lines."""
    sess_dir = Path(vault_path) / sessions_folder
    if not sess_dir.is_dir():
        return []

    issues: list[Issue] = []

    for md_file in sorted(sess_dir.glob("*.md")):
        # Optional project filter via filename pattern
        if project and f"-{project}-" not in md_file.name:
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = content.split("\n")

        # Extract project from frontmatter
        note_project = "unknown"
        in_fm = False
        for line in lines[:30]:
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                    continue
                else:
                    break
            if in_fm and line.startswith("project:"):
                note_project = line.split(":", 1)[1].strip().strip("\"'")
                break

        # Find unescaped [[ in conversation lines
        hit_lines: list[int] = []
        for i, line in enumerate(lines):
            if _CONVERSATION_LINE_RE.match(line) and _UNESCAPED_WIKILINK_RE.search(line):
                hit_lines.append(i + 1)  # 1-indexed

        if hit_lines:
            issues.append(Issue(
                check=NAME,
                note_path=str(md_file),
                project=note_project,
                current_source=f"{len(hit_lines)} line(s) with unescaped [[",
                proposed_source="escape [[ to \\[\\[",
                reason=f"Lines {', '.join(str(n) for n in hit_lines[:10])}{'...' if len(hit_lines) > 10 else ''}",
                confidence=1.0,
                extra={"hit_lines": hit_lines},
            ))

    return issues


def apply(issues: list[Issue], backup_root: str) -> list[Result]:
    """Escape [[ → \\[\\[ in conversation lines of affected notes."""
    results: list[Result] = []

    for issue in issues:
        note_path = issue.note_path
        try:
            content = Path(note_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="error",
                error=str(exc),
            ))
            continue

        lines = content.split("\n")
        changed = False

        for i, line in enumerate(lines):
            if _CONVERSATION_LINE_RE.match(line) and _UNESCAPED_WIKILINK_RE.search(line):
                lines[i] = _UNESCAPED_WIKILINK_RE.sub(r"\\[\\[", line)
                changed = True

        if not changed:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="skipped",
            ))
            continue

        # Backup original
        backup_dir = Path(backup_root) / NAME
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / Path(note_path).name
        try:
            shutil.copy2(note_path, backup_path)
        except OSError as exc:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="error",
                error=f"backup failed: {exc}",
            ))
            continue

        # Atomic write (temp + rename, owner-only permissions)
        new_content = "\n".join(lines)
        dest = Path(note_path)
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(dest.parent),
                prefix=".vd-wikilink-",
                suffix=".tmp",
            )
            try:
                os.write(fd, new_content.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, str(dest))
        except OSError as exc:
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="error",
                error=str(exc),
            ))
            continue

        results.append(Result(
            check=NAME,
            note_path=note_path,
            status="applied",
            backup_path=str(backup_path),
        ))

    return results
