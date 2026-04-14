"""vault_doctor check: normalize underscore project names to hyphens in frontmatter.

Claude Code normalizes underscores to hyphens in project directory names
(e.g. ``personal_ws`` → ``personal-ws``). Notes created before this
normalization was applied to ``get_session_context()`` and
``extract_session_metadata()`` may have ``project: personal_ws`` in their
frontmatter, causing vault-doctor to treat them as a separate project.
This check detects and fixes the inconsistency.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from . import Issue, Result

NAME = "project-name-normalization"
DESCRIPTION = "Detect and fix underscored project names in frontmatter (should use hyphens to match Claude Code convention)"
DEFAULT_WINDOW_DAYS = 9999  # unbounded — scan all notes

_FM_PROJECT_RE = re.compile(r"^project:\s*(.+)$", re.MULTILINE)


def _parse_frontmatter_project(content: str) -> str | None:
    """Extract the project value from YAML frontmatter."""
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    fm_block = content[: end + 4]
    m = _FM_PROJECT_RE.search(fm_block)
    if not m:
        return None
    return m.group(1).strip().strip("\"'")


def scan(
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    days: int,
    project: str | None = None,
) -> list[Issue]:
    """Find notes with underscored project names in frontmatter."""
    issues: list[Issue] = []

    for folder in (sessions_folder, insights_folder):
        folder_path = Path(vault_path) / folder
        if not folder_path.is_dir():
            continue

        for md_file in sorted(folder_path.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            note_project = _parse_frontmatter_project(content)
            if not note_project:
                continue

            # Optional project filter (normalize both sides)
            if project and note_project.replace("_", "-") != project.replace("_", "-"):
                continue

            if "_" in note_project:
                normalized = note_project.replace("_", "-")
                issues.append(Issue(
                    check=NAME,
                    note_path=str(md_file),
                    project=note_project,
                    current_source=f"project: {note_project}",
                    proposed_source=f"project: {normalized}",
                    reason="underscore in project name; Claude Code uses hyphens",
                    confidence=1.0,
                    extra={"original": note_project, "normalized": normalized},
                ))

    return issues


def apply(issues: list[Issue], backup_root: str) -> list[Result]:
    """Replace underscored project names with hyphenated versions in frontmatter."""
    results: list[Result] = []

    for issue in issues:
        note_path = issue.note_path
        original = issue.extra.get("original", "")
        normalized = issue.extra.get("normalized", "")
        if not original or not normalized:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="error",
                error="missing original/normalized in issue extra",
            ))
            continue

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

        # Only replace in frontmatter block, not in body text
        if not content.startswith("---"):
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="skipped",
            ))
            continue

        end = content.find("\n---", 3)
        if end == -1:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="skipped",
            ))
            continue

        fm_block = content[: end + 4]
        body = content[end + 4:]

        # Replace project value (with or without quotes) and tag references
        new_fm = re.sub(
            rf"^(project:\s*)[\"']?{re.escape(original)}[\"']?\s*$",
            rf"\g<1>{normalized}",
            fm_block,
            flags=re.MULTILINE,
        )
        new_fm = new_fm.replace(f"claude/project/{original}", f"claude/project/{normalized}")

        if new_fm == fm_block:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="skipped",
            ))
            continue

        # Backup original (include source folder to avoid cross-folder collisions)
        source_folder = Path(note_path).parent.name
        backup_dir = Path(backup_root) / NAME / source_folder
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

        # Atomic write
        new_content = new_fm + body
        dest = Path(note_path)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(dest.parent),
                prefix=".vd-projnorm-",
                suffix=".tmp",
            )
            try:
                os.write(fd, new_content.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, str(dest))
            tmp = None  # consumed by os.replace
        except OSError as exc:
            results.append(Result(
                check=NAME,
                note_path=note_path,
                status="error",
                error=str(exc),
            ))
            continue
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        results.append(Result(
            check=NAME,
            note_path=note_path,
            status="applied",
            backup_path=str(backup_path),
        ))

    return results
