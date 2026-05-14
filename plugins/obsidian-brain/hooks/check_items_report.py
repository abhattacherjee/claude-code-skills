"""
Dashboard report writer for /check-items.

Path: <vault>/claude-dashboards/check-items-<scope>-<YYYY-MM-DD>.md
Always written, even on --dry-run or user cancel.
Idempotent — overwritten on next run with same scope/date.

Per spec § Dashboard report format (lines 354-408).
Atomic temp+rename pattern.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def _safe_filename_component(s: str) -> str:
    """Restrict to [A-Za-z0-9_-]. Replace anything else (including dots) with '_'.

    Dots are excluded from the allowed set so that path-traversal sequences
    like '../../etc/passwd' cannot produce '..' components in the filename.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s))[:120]


def _frontmatter(scope_name, date_str, window_days, raw_count, group_count,
                 classifications, applied, cascaded,
                 semantic_merge_mode, classifier_mode):
    counts = {"done": 0, "needs_action": 0, "stale": 0, "active": 0}
    for c in classifications:
        kind = c.get("classification", "")
        key = {"DONE": "done", "NEEDS-ACTION": "needs_action",
               "STALE": "stale", "ACTIVE": "active"}.get(kind)
        if key:
            counts[key] += 1
    # scope_name and date_str are sanitized defensively so this helper is safe
    # even if called directly with raw values containing newlines or colons that
    # could inject extra YAML fields.
    safe_scope = _safe_filename_component(scope_name)
    safe_date = _safe_filename_component(date_str)
    return (
        "---\n"
        "type: claude-check-items-report\n"
        f"date: {safe_date}\n"
        f"scope: {safe_scope}\n"
        f"window: {window_days}d\n"
        f"total_raw_items: {raw_count}\n"
        f"groups: {group_count}\n"
        f"semantic_merge_mode: {semantic_merge_mode}\n"
        f"classifier_mode: {classifier_mode}\n"
        "classifications:\n"
        f"  done: {counts['done']}\n"
        f"  needs_action: {counts['needs_action']}\n"
        f"  stale: {counts['stale']}\n"
        f"  active: {counts['active']}\n"
        f"applied: {applied}\n"
        f"cascaded: {cascaded}\n"
        "tags:\n"
        "  - claude/check-items\n"
        f"  - claude/project/{safe_scope}\n"
        "---\n"
    )


def _body(scope_name, date_str, window_days, raw_count, group_count,
          classifications, applied, cascaded, merges):
    by_kind = {"DONE": [], "NEEDS-ACTION": [], "STALE": [], "ACTIVE": []}
    for c in classifications:
        by_kind.setdefault(c.get("classification", "ACTIVE"), []).append(c)

    parts = [f"# Check-Items Report — {scope_name} — {date_str}", "",
             "## Summary"]
    parts.append(
        f"Window {window_days}d. {raw_count} raw items collapsed to "
        f"{group_count} groups after dedup. "
        f"{len(by_kind['DONE'])} DONE, {len(by_kind['NEEDS-ACTION'])} NEEDS-ACTION, "
        f"{len(by_kind['STALE'])} STALE, {len(by_kind['ACTIVE'])} ACTIVE. "
        f"{applied} applied, {cascaded} cascaded."
    )
    parts.append("")

    parts.append(f"## Done ({applied} applied of {len(by_kind['DONE'])} classified)")
    for c in by_kind["DONE"]:
        parts.append(f"- [x] {c.get('canonical_text', '')}")
        parts.append(f"  - Evidence: {c.get('evidence_citation', 'n/a')}")
    parts.append("")

    parts.append(f"## Needs-Action ({len(by_kind['NEEDS-ACTION'])} surfaced, not applied)")
    for c in by_kind["NEEDS-ACTION"]:
        parts.append(f"- [ ] {c.get('canonical_text', '')}")
        parts.append(f"  - Evidence: {c.get('evidence_citation', 'n/a')}")
        if c.get("action_required"):
            parts.append(f"  - Action: `{c['action_required']}`")
    parts.append("")

    parts.append(f"## Stale ({len(by_kind['STALE'])} — hidden without --show-all)")
    for c in by_kind["STALE"]:
        parts.append(f"- {c.get('canonical_text', '')}")
    parts.append("")

    parts.append(f"## Active ({len(by_kind['ACTIVE'])} — not reviewed)")
    for c in by_kind["ACTIVE"][:50]:
        parts.append(f"- {c.get('canonical_text', '')}")
    if len(by_kind["ACTIVE"]) > 50:
        parts.append(f"- ... and {len(by_kind['ACTIVE']) - 50} more (truncated)")
    parts.append("")

    parts.append("## Merged Groups")
    if not merges:
        parts.append("_No semantic merges this run._")
    else:
        for m in merges:
            cid = m.get("canonical_group_id", "?")
            absorbed = ", ".join(m.get("absorbed_group_ids", []))
            parts.append(f"- {cid} absorbs [{absorbed}] — {m.get('reasoning', '')}")
    parts.append("")

    return "\n".join(parts)


def write_check_items_dashboard(
    *,
    vault_path,
    scope_name,
    date_str,
    window_days,
    raw_count,
    group_count,
    classifications,
    applied,
    cascaded,
    merges,
    semantic_merge_mode,
    classifier_mode,
    dry_run,
):
    """
    Write the check-items dashboard report and return the path.
    Always writes (dry_run only affects upstream pipeline behavior).
    """
    dashboards_dir = Path(vault_path) / "claude-dashboards"
    dashboards_dir.mkdir(parents=True, exist_ok=True)

    safe_scope = _safe_filename_component(scope_name)
    safe_date = _safe_filename_component(date_str)
    filename = f"check-items-{safe_scope}-{safe_date}.md"
    target = dashboards_dir / filename
    if not target.resolve().is_relative_to(dashboards_dir.resolve()):
        raise ValueError(f"refusing to write outside dashboards dir: {target}")

    # Use safe_scope (computed above for the filename) throughout the note body
    # and frontmatter so that crafted scope values cannot inject YAML fields or
    # markdown headings with newlines/colons.
    content = (_frontmatter(safe_scope, date_str, window_days, raw_count, group_count,
                            classifications, applied, cascaded,
                            semantic_merge_mode, classifier_mode)
               + _body(safe_scope, date_str, window_days, raw_count, group_count,
                       classifications, applied, cascaded, merges))

    tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(dashboards_dir),
        suffix=".tmp", encoding="utf-8"
    )
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, str(target))
    os.chmod(str(target), 0o600)
    return str(target)
