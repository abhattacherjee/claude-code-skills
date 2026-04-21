"""vault_doctor check: snapshot integrity (orphans, broken backlinks,
stale/missing session snapshot lists, status/summary mismatch).

Module registry interface: NAME, DESCRIPTION, DEFAULT_WINDOW_DAYS, scan,
apply. Produces Issue objects with distinct ``check`` names so the
dispatcher can report per-check counts.

Five integrity checks emitted by ``scan()``:

  1. snapshot-orphan                    — no parent session note (warn/unresolved)
  2. snapshot-broken-backlink           — source_session_note wikilink wrong (fix)
  3. session-snapshot-list-stale        — session lists snapshot not on disk (fix)
  4. session-snapshot-list-missing      — snapshots exist but no list on session (fix)
  5. snapshot-summary-status-mismatch   — status disagrees with body summary (fix)
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from pathlib import Path

from . import Issue, Result

NAME = "snapshot-integrity"
DESCRIPTION = "Snapshot orphans, broken backlinks, stale lists, status/summary mismatches"
DEFAULT_WINDOW_DAYS = 3650  # all-history; additive + idempotent

_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_WIKI_RE = re.compile(r'\[\[([^\]]+)\]\]')


def _read_text(path: str) -> str | None:
    """Read UTF-8 text, normalising BOM and CRLF so regex anchors match."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Strip UTF-8 BOM if present
    if text.startswith("\ufeff"):
        text = text[1:]
    # Normalise CRLF to LF so ^---\n anchors still work
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")
    return text


def _parse_fm(text: str) -> dict:
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    out: dict = {"snapshots": []}
    in_list = None
    for line in m.group(1).splitlines():
        s = line.rstrip("\r")
        if s.startswith("  - ") and in_list:
            val = s[4:].strip().strip('"').strip("'")
            out.setdefault(in_list, []).append(val)
            continue
        in_list = None
        if not s or s.startswith(" "):
            continue
        if ":" not in s:
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        val = val.strip()
        if not val:
            in_list = key
            out[key] = []
        else:
            out[key] = val.strip('"').strip("'")
    return out


def _project_matches(meta_project: str, filter_project: str | None) -> bool:
    if not filter_project:
        return True
    return meta_project.lower() == filter_project.lower()


def _replace_in_frontmatter(text: str, pattern: str, replacement: str,
                            count: int = 1) -> tuple[str, int]:
    """Run ``re.subn`` against ONLY the frontmatter block.

    Returns ``(new_text, n)`` where ``n`` is the number of substitutions.
    If the text lacks frontmatter, returns ``(text, 0)``.
    """
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return text, 0
    new_fm, n = re.subn(pattern, replacement, parts[1], count=count)
    if n == 0:
        return text, 0
    new_text = parts[0] + "---\n" + new_fm + "---\n" + parts[2]
    return new_text, n


def scan(vault_path: str, sessions_folder: str, insights_folder: str,
         days: int, project: str | None = None) -> list:
    """Return Issue objects for all five check kinds."""
    sess_dir = Path(vault_path) / sessions_folder
    if not sess_dir.is_dir():
        return []

    # Index all session/snapshot files once to avoid O(N^2) scans
    sessions_by_id: dict[str, dict] = {}
    snapshots: list[dict] = []
    for p in sess_dir.iterdir():
        if p.suffix != ".md":
            continue
        text = _read_text(str(p))
        if not text:
            continue
        fm = _parse_fm(text)
        if not fm:
            continue
        if not _project_matches(fm.get("project", ""), project):
            continue
        type_ = fm.get("type", "")
        if type_ == "claude-session":
            sid = fm.get("session_id", "")
            if sid:
                sessions_by_id[sid] = {
                    "path": str(p), "fm": fm, "stem": p.stem, "text": text,
                }
        elif type_ == "claude-snapshot":
            snapshots.append({"path": str(p), "fm": fm, "stem": p.stem, "text": text})

    issues: list[Issue] = []

    # 1. snapshot-orphan
    # 2. snapshot-broken-backlink
    # 5. snapshot-summary-status-mismatch
    for snap in snapshots:
        fm = snap["fm"]
        sid = fm.get("session_id", "")
        project_name = fm.get("project", "")
        parent_session = sessions_by_id.get(sid)

        if not parent_session:
            issues.append(Issue(
                check="snapshot-orphan",
                note_path=snap["path"],
                project=project_name,
                current_source=f"session_id={sid}",
                proposed_source="",
                reason="no session note on disk matches this session_id",
                confidence=0.9,
                extra={"unresolved": True},
            ))
            continue

        # Backlink check
        raw_backlink = fm.get("source_session_note", "")
        m = _WIKI_RE.search(raw_backlink)
        backlink_stem = m.group(1) if m else ""
        if backlink_stem and backlink_stem != parent_session["stem"]:
            issues.append(Issue(
                check="snapshot-broken-backlink",
                note_path=snap["path"],
                project=project_name,
                current_source=f"[[{backlink_stem}]]",
                proposed_source=f"[[{parent_session['stem']}]]",
                reason="source_session_note wikilink does not match resolved parent",
                confidence=0.95,
            ))

        # NOTE: session_id mismatch is unreachable by construction — sessions
        # are indexed BY session_id, so ``parent_session["fm"]["session_id"]``
        # is always equal to ``sid``. The check was removed to avoid dead
        # branches that confused dispatcher metrics.

        # Status vs summary
        has_real_summary = bool(re.search(r"^## Summary\s*\n\S", snap["text"], re.MULTILINE))
        status = fm.get("status", "")
        if status == "auto-logged" and has_real_summary:
            issues.append(Issue(
                check="snapshot-summary-status-mismatch",
                note_path=snap["path"],
                project=project_name,
                current_source="status=auto-logged, ## Summary present",
                proposed_source="status=summarized",
                reason="summary body exists but status was not flipped",
                confidence=0.95,
            ))
        elif status == "summarized" and not has_real_summary:
            issues.append(Issue(
                check="snapshot-summary-status-mismatch",
                note_path=snap["path"],
                project=project_name,
                current_source="status=summarized, ## Summary missing or placeholder",
                proposed_source="status=auto-logged",
                reason="status claims summarized but ## Summary body is absent",
                confidence=0.8,
            ))

    # 3. session-snapshot-list-stale, 4. session-snapshot-list-missing
    snaps_by_session: dict[str, list[str]] = {}
    for snap in snapshots:
        sid = snap["fm"].get("session_id", "")
        if sid:
            snaps_by_session.setdefault(sid, []).append(f"[[{snap['stem']}]]")

    for sid, sess in sessions_by_id.items():
        on_disk = sorted(snaps_by_session.get(sid, []))
        in_frontmatter = sess["fm"].get("snapshots") or []
        if not isinstance(in_frontmatter, list):
            # Inline YAML list parsed as string; skip stale detection (treat as missing).
            in_frontmatter = []

        # Missing list
        if on_disk and not in_frontmatter:
            issues.append(Issue(
                check="session-snapshot-list-missing",
                note_path=sess["path"],
                project=sess["fm"].get("project", ""),
                current_source="snapshots field absent",
                proposed_source="\n".join(on_disk),
                reason=f"{len(on_disk)} snapshot(s) on disk but session has no snapshots: list",
                confidence=0.98,
            ))
            continue

        # Stale entries (present in frontmatter but not on disk)
        stale = [s for s in in_frontmatter if s not in set(on_disk)]
        if stale:
            issues.append(Issue(
                check="session-snapshot-list-stale",
                note_path=sess["path"],
                project=sess["fm"].get("project", ""),
                current_source="\n".join(in_frontmatter),
                proposed_source="\n".join([s for s in in_frontmatter if s in set(on_disk)]),
                reason=f"{len(stale)} stale snapshot wikilink(s)",
                confidence=0.95,
                extra={"stale": stale},
            ))

    return issues


def _write_atomic(path: str, text: str, backup_root: str, check_name: str) -> str | None:
    """Write text to path atomically, backing up the original under backup_root.

    Returns the backup file path if a backup was created (i.e. the target
    file existed before the write); otherwise returns ``None``.
    """
    import shutil, tempfile
    p = Path(path)
    backup_path: Path | None = None
    if p.exists():
        bdir = Path(backup_root) / check_name
        bdir.mkdir(parents=True, exist_ok=True)
        backup_path = bdir / p.name
        shutil.copy2(p, backup_path)
    fd, tmp = tempfile.mkstemp(prefix=".ob-doctor-", suffix=".md.tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return str(backup_path) if backup_path is not None else None


def apply(issues, backup_root: str) -> list:
    results: list[Result] = []
    for issue in issues:
        if issue.extra.get("unresolved"):
            results.append(Result(
                check=issue.check, note_path=issue.note_path, status="unresolved",
                error="no auto-fix available; manual review required",
            ))
            continue
        try:
            backup: str | None = None
            if issue.check == "snapshot-broken-backlink":
                text = _read_text(issue.note_path) or ""
                new_text, n = _replace_in_frontmatter(
                    text,
                    r'(?m)^source_session_note:.*$',
                    f'source_session_note: "{issue.proposed_source}"',
                    count=1,
                )
                if new_text == text:
                    reason = (
                        "source_session_note already matches proposed value"
                        if n > 0
                        else "source_session_note line not found in frontmatter "
                             "(missing frontmatter or YAML block-scalar form)"
                    )
                    results.append(Result(
                        check=issue.check, note_path=issue.note_path, status="skipped",
                        error=reason,
                    ))
                    continue
                backup = _write_atomic(issue.note_path, new_text, backup_root, issue.check)
            elif issue.check == "snapshot-summary-status-mismatch":
                new_status = "summarized" if "status=summarized" in issue.proposed_source else "auto-logged"
                text = _read_text(issue.note_path) or ""
                new_text, n = _replace_in_frontmatter(
                    text,
                    r"(?m)^status:\s*\S+",
                    f"status: {new_status}",
                    count=1,
                )
                if new_text == text:
                    reason = (
                        "status already matches proposed value"
                        if n > 0
                        else "status: line not found in frontmatter"
                    )
                    results.append(Result(
                        check=issue.check, note_path=issue.note_path, status="skipped",
                        error=reason,
                    ))
                    continue
                backup = _write_atomic(issue.note_path, new_text, backup_root, issue.check)
            elif issue.check == "session-snapshot-list-missing":
                text = _read_text(issue.note_path) or ""
                parts = text.split("---\n", 2)
                if len(parts) < 3:
                    raise RuntimeError(
                        "could not locate frontmatter to insert snapshots block"
                    )
                fm = parts[1]
                # Defensive re-check: if snapshots: already exists in the
                # frontmatter (stale Issue replay / race with another
                # writer), treat as an idempotent no-op. Without this
                # guard, the ``^status:`` anchor would inject a DUPLICATE
                # snapshots: block above status:, which the byte-identity
                # short-circuit below cannot detect.
                if re.search(r"(?m)^snapshots:", fm):
                    results.append(Result(
                        check=issue.check, note_path=issue.note_path, status="skipped",
                        error="snapshots field already present in frontmatter (stale Issue?)",
                    ))
                    continue
                wikilinks = sorted(issue.proposed_source.splitlines())
                block = "snapshots:\n" + "\n".join(f'  - "{s}"' for s in wikilinks) + "\n"
                # Try to insert before the first ``status:`` line in the
                # frontmatter. If that anchor isn't present, append before
                # the closing fence. Body-level ``status:`` lines (code
                # blocks, ``## Status`` headings) MUST NOT be matched.
                new_fm, n = re.subn(
                    r"(?m)^status:", block + "status:", fm, count=1,
                )
                if n == 0:
                    # No status: line inside the frontmatter — append before
                    # the closing fence.
                    new_fm = fm + block
                new_text = parts[0] + "---\n" + new_fm + "---\n" + parts[2]
                if new_text == text:
                    results.append(Result(
                        check=issue.check, note_path=issue.note_path, status="skipped",
                        error="frontmatter already contains the proposed snapshots block",
                    ))
                    continue
                backup = _write_atomic(issue.note_path, new_text, backup_root, issue.check)
            elif issue.check == "session-snapshot-list-stale":
                text = _read_text(issue.note_path) or ""
                stale = issue.extra.get("stale", [])
                # Restrict stale-entry pruning to the frontmatter block.
                # A body bullet list matching ``- "[[stale-stem]]"`` (e.g.
                # user-authored References section quoting historical
                # wikilinks) MUST NOT be mutated — the PR guarantee is
                # that vault-doctor only touches frontmatter.
                parts = text.split("---\n", 2)
                if len(parts) < 3:
                    raise RuntimeError(
                        "could not locate frontmatter to prune stale entries"
                    )
                fm_lines = parts[1].splitlines(keepends=True)
                cleaned: list[str] = []
                for line in fm_lines:
                    s = line.strip()
                    # Match all three forms: double-quoted, single-quoted, and
                    # unquoted YAML scalar. ``_parse_fm`` strips quotes during
                    # scan so ``- [[stem]]`` and ``- "[[stem]]"`` both register
                    # as stale; the apply branch must drop both forms or
                    # idempotency is an illusion (scan re-flags, apply no-ops).
                    if any(
                        s == f'- "{v}"' or s == f"- '{v}'" or s == f"- {v}"
                        for v in stale
                    ):
                        continue
                    cleaned.append(line)
                new_fm = "".join(cleaned)
                new_text = parts[0] + "---\n" + new_fm + "---\n" + parts[2]
                if new_text == text:
                    results.append(Result(
                        check=issue.check, note_path=issue.note_path, status="skipped",
                        error="no stale entries found in frontmatter (already pruned?)",
                    ))
                    continue
                backup = _write_atomic(issue.note_path, new_text, backup_root, issue.check)
            else:
                results.append(Result(
                    check=issue.check, note_path=issue.note_path, status="skipped",
                ))
                continue
            results.append(Result(
                check=issue.check, note_path=issue.note_path, status="applied",
                backup_path=backup,
            ))
        except Exception as exc:  # noqa: BLE001
            results.append(Result(
                check=issue.check, note_path=issue.note_path, status="error",
                error=f"{type(exc).__name__}: {exc}",
            ))
            print(
                f"[vault_doctor] apply failed for {issue.note_path}:\n"
                f"{traceback.format_exc()}",
                file=sys.stderr,
            )
    return results
