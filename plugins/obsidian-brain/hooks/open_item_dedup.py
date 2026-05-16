"""Open item deduplication for Obsidian Brain.

Provides duplicate detection, creation-time prevention, and check-off
cascading for open items across session notes. All matching uses hybrid
distinctive-token + fuzzy-overlap matching. Python stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from obsidian_utils import get_workspace_roots

# --- Module-level compiled regexes (computed once at import) ---

_RE_FILE_PATH = re.compile(r'[\w./-]+\.(py|md|json|ts|js|tsx|jsx)')
_RE_PR_REF = re.compile(r'#\d+|PR\s+\d+|issue\s+\d+', re.IGNORECASE)
_RE_BRANCH = re.compile(r'(?:feature|release|hotfix)/[\w.-]+')
_RE_VERSION = re.compile(r'v?\d+\.\d+\.\d+')
_RE_MARKDOWN = re.compile(r'`([^`]*)`|\*\*([^*]*)\*\*|_([^_]*)_|\[([^\]]*)\]\([^)]*\)')

_CHECKBOX_PREFIX_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s+")

_STOPWORDS = frozenset({
    'the', 'a', 'an', 'to', 'for', 'in', 'on', 'of', 'and', 'or',
    'but', 'is', 'are', 'was', 'were', 'be', 'not', 'this', 'that',
    'with', 'from', 'by', 'at', 'it', 'as', 'if', 'so', 'do', 'no',
})

# ---------------------------------------------------------------------------
# Confidence tier rules (spec § Confidence tiers, lines 324-332)
# ---------------------------------------------------------------------------

CONFIDENCE_TIER_RULES = {
    "HIGH": {
        "literal_ref_patterns": [
            r"\b[0-9a-f]{7,40}\b",
            r"#\d+",
            r"\bv\d+\.\d+(?:\.\d+)?\b",
        ],
    },
    "MED": {
        "inferred_ref_patterns": [
            r"\bStory\s+\d+(?:\.\d+)*\b",
            r"\bshipped\b",
            r"\bcovered by\b",
            r"#\d+",
        ],
    },
    "LOW": {
        "fts_only_markers": ["FTS mention", "occurrence", "mentions:", "FTS:"],
    },
}


def _outer_subagent_timeout() -> int:
    """Return the outer subprocess.run timeout that wraps check_items_cli.py.

    Must be ≥ inner SUBAGENT_TIMEOUT_SEC * max-expected-chunks so the outer
    caller never races the inner cli. The inner CLI dispatches sequentially
    over N chunks of <=CLASSIFIER_CHUNK_SIZE groups each, so a payload of 4
    chunks at 300s/chunk needs ~1200s of outer headroom.

    Reads CHECK_ITEMS_SUBAGENT_TIMEOUT_SEC; the env var sets the INNER
    per-chunk timeout. Outer is then `inner * 6` so users only need to tune
    one knob (and 6 covers up to ~150 classifier-eligible groups under the
    default CLASSIFIER_CHUNK_SIZE=25 — well above realistic vault sizes).
    """
    inner = int(os.environ.get("CHECK_ITEMS_SUBAGENT_TIMEOUT_SEC", "300"))
    return inner * 6


def assign_tier(evidence_citation, item_text):
    """Deterministically assign HIGH | MED | LOW from evidence citation shape.

    HIGH requires a literal ref (sha, #N, vX.Y) appearing in BOTH the citation
    and the item text. MED matches an inferred-ref shape in the citation only.
    LOW is the default.

    Spec § Confidence tiers (lines 324-332).
    """
    if not evidence_citation or not item_text:
        return "LOW"
    citation = str(evidence_citation)
    text = str(item_text)

    for pattern in CONFIDENCE_TIER_RULES["HIGH"]["literal_ref_patterns"]:
        cit_match = re.search(pattern, citation)
        if not cit_match:
            continue
        ref = cit_match.group(0)
        if ref in text:
            return "HIGH"

    for pattern in CONFIDENCE_TIER_RULES["MED"]["inferred_ref_patterns"]:
        if re.search(pattern, citation):
            return "MED"

    return "LOW"

_COMPLETION_PHRASES = frozenset({
    'merged', 'shipped', 'fixed', 'released', 'closed', 'removed',
    'implemented', 'deleted', 'done', 'completed',
})


def _strip_markdown(text: str) -> str:
    """Remove backticks, bold, italic, and links. Keep inner text."""
    return _RE_MARKDOWN.sub(lambda m: m.group(1) or m.group(2) or m.group(3) or m.group(4) or '', text)


def _extract_distinctive_tokens(text: str) -> list[str]:
    """Extract file paths, PR refs, branch names, version numbers."""
    tokens = []
    tokens.extend(m.group() for m in _RE_FILE_PATH.finditer(text))
    tokens.extend(m.group() for m in _RE_PR_REF.finditer(text))
    tokens.extend(m.group() for m in _RE_BRANCH.finditer(text))
    tokens.extend(m.group() for m in _RE_VERSION.finditer(text))
    return tokens


def _tokenize(text: str) -> set[str]:
    """Lowercase, split, drop stopwords, keep tokens >= 3 chars."""
    words = re.findall(r'[a-z0-9][-a-z0-9/.#]*[a-z0-9]|[a-z0-9]', text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _safe_mtime(path: str) -> float:
    """Return os.path.getmtime(path), falling back to 0.0 on OSError.

    0.0 (epoch) is the safe-conservative fallback: age = now - 0 is always
    > 90 days, so L2 classifies the item as STALE rather than silently
    treating a stat-failure as ACTIVE. A one-line warning is emitted to
    stderr so the failure is visible in hook logs.
    """
    try:
        return os.path.getmtime(path)
    except OSError as exc:
        print(
            f"[obsidian-brain] mtime unavailable for {path!r}: {exc}; defaulting to 0 (STALE)",
            file=sys.stderr,
        )
        return 0.0


def collect_open_items(
    vault_path: str,
    sessions_folder: str,
    project: str,
    max_sessions: int = 10,
    exclude_path: str | None = None,
) -> list[tuple[str, int, str]]:
    """Collect unchecked open items from recent session notes for a project.

    Filters to `type: claude-session` notes; notes without a `type:` field
    are treated as sessions (legacy). Snapshot notes (`claude-snapshot`) are
    excluded — their "Key context" bullets often look like action items and
    would produce false-positive proposals.

    Returns [(file_path, line_number, item_text)] from the most recent
    max_sessions session notes matching the project. Single-pass per file,
    early termination, no stat() calls.
    """
    sessions_dir = os.path.join(vault_path, sessions_folder)
    if not os.path.isdir(sessions_dir):
        return []

    # listdir + reverse sort = newest first (filenames are YYYY-MM-DD-*)
    all_files = sorted(os.listdir(sessions_dir), reverse=True)

    results: list[tuple[str, int, str]] = []
    matched = 0

    for fname in all_files:
        if not fname.endswith('.md'):
            continue

        fpath = os.path.join(sessions_dir, fname)
        if exclude_path and os.path.abspath(fpath) == os.path.abspath(exclude_path):
            continue

        # Single-pass: read file once, check project in frontmatter,
        # then extract open items from ## Open Questions / Next Steps
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except OSError as exc:
            print(f"[obsidian-brain] skipping unreadable note {fname}: {exc}", file=sys.stderr)
            continue
        except UnicodeDecodeError as exc:
            print(f"[obsidian-brain] encoding error in {fname}: {exc}", file=sys.stderr)
            continue

        # Check frontmatter for project match and type (first 20 lines).
        # Strip quotes to handle both `project: foo` and `project: "foo"`.
        # Notes without a `type:` field are treated as claude-session (legacy).
        project_match = False
        is_session = True  # default for notes with no type field (legacy)
        type_field_seen = False
        for line in lines[:20]:
            stripped = line.strip()
            if stripped.startswith('project:'):
                val = stripped.split(':', 1)[1].strip().strip('"').strip("'")
                if val == project:
                    project_match = True
            elif stripped.startswith('type:'):
                type_field_seen = True
                tval = stripped.split(':', 1)[1].strip().strip('"').strip("'")
                is_session = (tval == 'claude-session')
        if not project_match or (type_field_seen and not is_session):
            continue

        matched += 1

        # Find ## Open Questions / Next Steps and collect - [ ] items
        in_section = False
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped == '## Open Questions / Next Steps':
                in_section = True
                continue
            if in_section:
                if stripped.startswith('## '):
                    break  # next section
                if stripped.startswith('- [ ] '):
                    item_text = stripped[6:]  # after "- [ ] "
                    results.append((fpath, line_num, item_text))

        if matched >= max_sessions:
            break

    return results


def find_duplicates(
    candidate_text: str,
    existing_items: list[tuple[str, int, str]],
    threshold: int = 5,
) -> list[tuple[str, int, str, str]]:
    """Find items in existing_items that are duplicates of candidate_text.

    Returns [(file_path, line_number, item_text, confidence)] where
    confidence is "high" (distinctive token match) or "fuzzy" (token overlap).

    Tier 0: exact text equality after markdown strip + lowercase always yields
    "high" confidence, regardless of distinctive-token presence. This guarantees
    character-identical items (including short or stop-word-heavy ones) always
    cascade correctly.
    Tier 1 short-circuits: if a distinctive token matches, skip Tier 2.
    """
    cleaned = _strip_markdown(candidate_text)
    candidate_distinctive = _extract_distinctive_tokens(cleaned)
    candidate_tokens = _tokenize(cleaned)
    candidate_normalized = cleaned.strip().lower()

    matches: list[tuple[str, int, str, str]] = []

    for fpath, line_num, item_text in existing_items:
        item_lower = item_text.lower()

        # Tier 0: exact text equality after markdown strip + lowercase (always high)
        if _strip_markdown(item_text).strip().lower() == candidate_normalized:
            matches.append((fpath, line_num, item_text, "high"))
            continue

        # Tier 1: distinctive token match (high confidence, short-circuit)
        tier1_hit = False
        for dt in candidate_distinctive:
            if dt.lower() in item_lower:
                matches.append((fpath, line_num, item_text, "high"))
                tier1_hit = True
                break
        if tier1_hit:
            continue

        # Tier 2: fuzzy token overlap (lower confidence)
        # Use set intersection, not substring — avoids "fix" matching "prefix"
        if candidate_tokens:
            item_tokens = _tokenize(_strip_markdown(item_text))
            overlap = len(candidate_tokens & item_tokens)
            if overlap >= threshold:
                matches.append((fpath, line_num, item_text, "fuzzy"))

    return matches


def cascade_checkoff(
    checked_item_text: str,
    existing_items: list[tuple[str, int, str]],
    source_file: str | None = None,
    source_line: int | None = None,
) -> list[tuple[str, int, str, str]]:
    """Find duplicates of a checked-off item for cascading.

    Excludes the source item by (file, line) to avoid self-matching.
    Returns [(file_path, line_number, item_text, confidence)].
    """
    dupes = find_duplicates(checked_item_text, existing_items)
    if source_file is not None and source_line is not None:
        src_abs = os.path.abspath(source_file)
        dupes = [
            (f, l, t, c) for f, l, t, c in dupes
            if not (os.path.abspath(f) == src_abs and l == source_line)
        ]
    return dupes


def dedup_note_open_items(
    vault_path: str,
    sessions_folder: str,
    project: str,
    note_path: str,
) -> list[str]:
    """Remove duplicate open items from a written note. Atomic rewrite.

    Reads note_path, finds - [ ] items in ## Open Questions / Next Steps,
    checks each against existing items in other session notes. Removes
    duplicates and rewrites the file atomically.

    Returns list of removed item texts (empty if no duplicates).
    """
    try:
        with open(note_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError as exc:
        print(f"[obsidian-brain] dedup: cannot read {note_path}: {exc}", file=sys.stderr)
        return []

    existing = collect_open_items(
        vault_path, sessions_folder, project,
        max_sessions=10, exclude_path=note_path,
    )
    if not existing:
        return []

    # Find open items section and mark duplicates for removal
    in_section = False
    lines_to_remove: set[int] = set()
    removed_texts: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == '## Open Questions / Next Steps':
            in_section = True
            continue
        if in_section:
            if stripped.startswith('## '):
                break
            if stripped.startswith('- [ ] '):
                item_text = stripped[6:]
                dupes = find_duplicates(item_text, existing)
                # Only auto-remove high-confidence matches; fuzzy could be false positives
                high_dupes = [d for d in dupes if d[3] == "high"]
                if high_dupes:
                    lines_to_remove.add(i)
                    removed_texts.append(item_text)

    if not lines_to_remove:
        return []

    # Remove duplicate lines
    new_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]

    # Atomic rewrite: temp file + rename
    note_dir = os.path.dirname(note_path)
    fd, tmp_path = tempfile.mkstemp(
        prefix='.ob-dedup-', suffix='.md.tmp', dir=note_dir,
    )
    try:
        # Preserve original file permissions
        try:
            orig_mode = os.stat(note_path).st_mode
        except OSError:
            orig_mode = 0o644
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        os.chmod(tmp_path, orig_mode)
        os.replace(tmp_path, note_path)
    except OSError as exc:
        print(f"[obsidian-brain] dedup: atomic write failed for {note_path}: {exc}", file=sys.stderr)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return []

    return removed_texts


def batch_cascade_checkoff(
    vault_path: str,
    sessions_folder: str,
    project: str,
    checked_texts: list[str],
) -> str:
    """Cascade check-off for multiple items. Edits files directly.

    Collects open items once, finds duplicates for each checked text,
    auto-checks high-confidence matches, reports fuzzy-only suggestions.
    Returns a compact summary string.
    """
    existing = collect_open_items(vault_path, sessions_folder, project)
    if not existing:
        return "No open items found for cascading."

    # Collect all cascade targets, deduped by (file, line)
    high_targets: dict[tuple[str, int], str] = {}  # (file, line) -> item_text
    fuzzy_raw: list[tuple[tuple[str, int], str, str]] = []  # (key, item_text, basename)

    for checked_text in checked_texts:
        dupes = cascade_checkoff(checked_text, existing)
        for fpath, line_num, item_text, confidence in dupes:
            key = (fpath, line_num)
            if confidence == "high":
                high_targets[key] = item_text
            else:
                fuzzy_raw.append((key, item_text, os.path.basename(fpath)))

    # Filter fuzzy suggestions: exclude any that were promoted to high
    fuzzy_suggestions = [
        (text, basename) for key, text, basename in fuzzy_raw
        if key not in high_targets
    ]

    if not high_targets and not fuzzy_suggestions:
        return "No duplicates found for cascading."

    # Edit files for high-confidence targets
    # Group by file to minimize file rewrites
    files_to_edit: dict[str, list[int]] = {}
    for (fpath, line_num), _ in high_targets.items():
        files_to_edit.setdefault(fpath, []).append(line_num)

    edited_count = 0
    edited_files: set[str] = set()

    for fpath, line_nums in files_to_edit.items():
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except OSError as exc:
            print(f"[obsidian-brain] cascade: cannot read {os.path.basename(fpath)}: {exc}", file=sys.stderr)
            continue

        file_edit_count = 0
        for ln in line_nums:
            idx = ln - 1  # 0-indexed
            if 0 <= idx < len(lines) and lines[idx].lstrip().startswith('- [ ] '):
                lines[idx] = lines[idx].replace('- [ ] ', '- [x] ', 1)
                file_edit_count += 1
            else:
                print(
                    f"[obsidian-brain] cascade: line {ln} in {os.path.basename(fpath)} "
                    f"no longer contains expected checkbox (file may have changed)",
                    file=sys.stderr,
                )

        if file_edit_count > 0:
            note_dir = os.path.dirname(fpath)
            fd, tmp_path = tempfile.mkstemp(
                prefix='.ob-cascade-', suffix='.md.tmp', dir=note_dir,
            )
            try:
                # Preserve original file permissions
                try:
                    orig_mode = os.stat(fpath).st_mode
                except OSError:
                    orig_mode = 0o644
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                os.chmod(tmp_path, orig_mode)
                os.replace(tmp_path, fpath)
                edited_files.add(os.path.basename(fpath))
                edited_count += file_edit_count  # count only after successful write
            except OSError as exc:
                print(f"[obsidian-brain] cascade: write failed for {os.path.basename(fpath)}: {exc}", file=sys.stderr)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # Build summary
    parts: list[str] = []
    if edited_count:
        parts.append(
            f"Cascaded {edited_count} high-confidence duplicate(s) "
            f"in {len(edited_files)} file(s)."
        )
    if fuzzy_suggestions:
        parts.append("Fuzzy suggestions (edit manually if same item):")
        seen: set[str] = set()
        for item_text, basename in fuzzy_suggestions:
            key = f"{item_text}|{basename}"
            if key not in seen:
                seen.add(key)
                parts.append(f'  - "{item_text}" in {basename}')

    return "\n".join(parts) if parts else "No duplicates found for cascading."


def cascade_group_members(
    groups: list,
    source_skips: "set[tuple[str, int]] | None" = None,
) -> str:
    """Flip checkbox on every member of each group, atomically per file.

    Each group dict must contain a ``members`` list of dicts with at least
    ``file`` (full path) and ``line`` keys. Members whose ``(file, line)`` is
    in ``source_skips`` are NOT flipped (caller already primary-flipped them).

    Lines that no longer contain a ``- [ ] `` checkbox at apply-time are
    skipped with a stderr warning (file may have changed since grouping).

    Returns a compact summary string: ``"Cascaded N member-line(s) across M
    file(s)."`` or ``"No member lines to cascade."`` for empty input.
    """
    if source_skips is None:
        source_skips = set()

    # Collect all (full_path, line_number) targets, deduplicated
    targets: dict[tuple[str, int], None] = {}  # ordered dict as ordered set
    for group in groups or []:
        for m in group.get("members", []) or []:
            fpath = m.get("file", "")
            line_num = m.get("line")
            if not fpath or line_num is None:
                continue
            key = (fpath, line_num)
            if key in source_skips:
                continue
            targets[key] = None

    if not targets:
        return "No member lines to cascade."

    # Group by file to minimise rewrites
    files_to_lines: dict[str, list[int]] = {}
    for fpath, line_num in targets:
        files_to_lines.setdefault(fpath, []).append(line_num)

    total_flipped = 0
    files_edited: set[str] = set()

    for fpath, line_nums in files_to_lines.items():
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            print(
                f"[obsidian-brain] cascade_group_members: cannot read "
                f"{os.path.basename(fpath)}: {exc}",
                file=sys.stderr,
            )
            continue

        file_flipped = 0
        for ln in line_nums:
            idx = ln - 1  # 0-indexed
            if 0 <= idx < len(lines) and lines[idx].lstrip().startswith("- [ ] "):
                lines[idx] = lines[idx].replace("- [ ] ", "- [x] ", 1)
                file_flipped += 1
            else:
                print(
                    f"[obsidian-brain] cascade_group_members: line {ln} in "
                    f"{os.path.basename(fpath)} no longer contains expected "
                    f"checkbox (file may have changed); skipping.",
                    file=sys.stderr,
                )

        if file_flipped == 0:
            continue

        note_dir = os.path.dirname(fpath)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".ob-cascade-", suffix=".md.tmp", dir=note_dir,
        )
        try:
            try:
                orig_mode = os.stat(fpath).st_mode
            except OSError:
                orig_mode = 0o644
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            os.chmod(tmp_path, orig_mode)
            os.replace(tmp_path, fpath)
            files_edited.add(os.path.basename(fpath))
            total_flipped += file_flipped
        except OSError as exc:
            print(
                f"[obsidian-brain] cascade_group_members: write failed for "
                f"{os.path.basename(fpath)}: {exc}",
                file=sys.stderr,
            )
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if total_flipped == 0:
        return "No member lines to cascade."
    return (
        f"Cascaded {total_flipped} member-line(s) across {len(files_edited)} file(s)."
    )


# ---------------------------------------------------------------------------
# Deep analysis pipeline
# ---------------------------------------------------------------------------

_RE_WIKILINK = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

# Module-level cache for deep_analysis_pipeline evidence gathering.
# Key shape: see _cache_key() — 6-tuple (basenames, projects_json, vault_path,
#   sessions_folder, insights_folder, db_path). TTL = 15 minutes.
# Prevents redundant git/gh subprocess calls when /check-items and /standup
# deep mode run back-to-back in the same interpreter process.
# Spec § Open questions / Cache coupling (line 699); Testing test 12 (line 658).
#
# Cache entry format: (timestamp: float, status: str, output_json: str)
# output_json is stored so cache hits can re-write the requested output_path
# (the cache key does not include output_path, so a hit must replay the write).
_PIPELINE_EVIDENCE_CACHE: dict[tuple, tuple[float, str, str]] = {}
_PIPELINE_CACHE_TTL_SEC = 900  # 15 minutes


def _evidence_cache_get(key: tuple, now: float) -> tuple[str, str] | None:
    """Return (status, output_json) if entry exists and is within TTL, else None."""
    entry = _PIPELINE_EVIDENCE_CACHE.get(key)
    if entry is None:
        return None
    ts, status, output_json = entry
    if now - ts > _PIPELINE_CACHE_TTL_SEC:
        del _PIPELINE_EVIDENCE_CACHE[key]
        return None
    return (status, output_json)


def _evidence_cache_put(key: tuple, result: tuple[str, str], now: float) -> None:
    """Store (status, output_json) tuple in the module-level cache."""
    status, output_json = result
    _PIPELINE_EVIDENCE_CACHE[key] = (now, status, output_json)


def _cache_key(basenames, projects_json, vault_path, sessions_folder,
               insights_folder, db_path):
    """Stable hashable key for _PIPELINE_EVIDENCE_CACHE.

    Includes every input that materially affects deep_analysis_pipeline output:
    basenames (sorted to normalize order), projects_json, vault_path,
    sessions_folder, insights_folder, db_path. A change in any field forces
    a fresh subprocess burst.
    """
    basenames_key = tuple(sorted(basenames)) if basenames else ()
    return (basenames_key, projects_json, vault_path, sessions_folder,
            insights_folder, db_path or "")


# Note types excluded from orphan detection (they are aggregation notes)
_ORPHAN_EXCLUDE_TYPES = frozenset({
    'claude-standup', 'claude-emerge', 'claude-retro',
})


def _resolve_project_paths() -> dict[str, str]:
    """Return dict mapping project name -> repo path for local git repos.

    Scans workspace roots from config (or historical defaults) for directories
    containing .git.  Roots are supplied by get_workspace_roots() which reads
    ``workspace_roots`` from obsidian-brain-config.json when present.
    """
    result: dict[str, str] = {}
    scan_dirs = get_workspace_roots()
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        try:
            for entry in os.listdir(scan_dir):
                full = os.path.join(scan_dir, entry)
                if os.path.isdir(full) and os.path.isdir(os.path.join(full, ".git")):
                    result[entry] = full
        except OSError:
            continue
    return result


def deep_analysis_pipeline(
    basenames: list[str],
    projects_json: str,
    output_path: str,
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
    db_path: str | None = None,
) -> str:
    """Single-pass deep analysis: similarity, open items, evidence gathering.

    Returns 'OK:<total_items>:<groups>:<projects_with_evidence>'.
    Writes structured JSON to output_path (atomic: tempfile + rename).

    15-minute module-level cache keyed on (projects_json, vault_path,
    sessions_folder): when /check-items and /standup deep both invoke
    this in the same process back-to-back, the second call skips all
    git/gh subprocess calls and returns the cached result string.
    Cache helpers _evidence_cache_get/_evidence_cache_put expose the
    cache for targeted unit tests without mocking the full pipeline.
    Spec § Open questions / Cache coupling (line 699);
    Testing test 12 (line 658). Refs #87.
    """
    _ck = _cache_key(basenames, projects_json, vault_path, sessions_folder,
                     insights_folder, db_path)
    _now = time.time()
    _cached = _evidence_cache_get(_ck, _now)
    if _cached is not None:
        # Warm-cache hit: skip all subprocess calls; re-write output_path so the
        # caller always finds a valid file regardless of which path was used on
        # the previous (cold-cache) call (cache key excludes output_path).
        _cached_status, _cached_json = _cached
        try:
            out_dir = os.path.dirname(output_path) or "."
            os.makedirs(out_dir, mode=0o700, exist_ok=True)
            _fd, _tmp = tempfile.mkstemp(prefix=".ob-pipeline-hit-", suffix=".json", dir=out_dir)
            with os.fdopen(_fd, 'w', encoding='utf-8') as _f:
                _f.write(_cached_json)
            os.chmod(_tmp, 0o600)
            os.replace(_tmp, output_path)
        except OSError as _exc:
            print(f"[obsidian-brain] pipeline cache: write failed: {_exc}", file=sys.stderr)
        return _cached_status

    import vault_index

    # 1. Warm vault index
    folders = [sessions_folder, insights_folder]
    try:
        actual_db = vault_index.ensure_index(vault_path, folders, db_path=db_path)
    except Exception as exc:
        return f"ERROR:vault index failed: {exc}"

    # 2. Similarity pass — extract keywords per note, find unlinked similar pairs
    # Build wikilink graph for the window notes
    basename_stems = {os.path.splitext(b)[0] for b in basenames}
    # Map stem -> full path for notes in the window
    stem_to_path: dict[str, str] = {}
    for b in basenames:
        stem = os.path.splitext(b)[0]
        for folder in [sessions_folder, insights_folder]:
            candidate = os.path.join(vault_path, folder, b)
            if os.path.isfile(candidate):
                stem_to_path[stem] = candidate
                break

    # Parse wikilinks from each note
    outgoing_links: dict[str, set[str]] = {}  # stem -> set of linked stems
    note_keywords: dict[str, list[str]] = {}
    for stem, fpath in stem_to_path.items():
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError:
            continue
        links = set(_RE_WIKILINK.findall(content))
        outgoing_links[stem] = links
        note_keywords[stem] = vault_index.extract_keywords(content)

    # Build bidirectional linked set
    linked_pairs: set[frozenset[str]] = set()
    for stem, links in outgoing_links.items():
        for target in links:
            if target in basename_stems:
                linked_pairs.add(frozenset([stem, target]))

    # Find similar unlinked pairs via keyword overlap
    link_suggestions: list[dict] = []
    merge_suggestions: list[dict] = []
    stems_list = sorted(stem_to_path.keys())

    for i, stem_a in enumerate(stems_list):
        kw_a = set(note_keywords.get(stem_a, []))
        if not kw_a:
            continue
        for stem_b in stems_list[i + 1:]:
            kw_b = set(note_keywords.get(stem_b, []))
            if not kw_b:
                continue
            shared = kw_a & kw_b
            if len(shared) < 3:
                continue
            pair = frozenset([stem_a, stem_b])
            if pair in linked_pairs:
                continue  # already linked
            overlap_ratio = len(shared) / min(len(kw_a), len(kw_b))
            entry = {
                "note_a": stem_a,
                "note_b": stem_b,
                "shared_keywords": sorted(shared),
            }
            if overlap_ratio >= 0.7 and len(merge_suggestions) < 5:
                merge_suggestions.append(entry)
            elif len(link_suggestions) < 5:
                link_suggestions.append(entry)

    # 3. Collect open items per project
    try:
        projects: list[str] = json.loads(projects_json) if projects_json else []
    except json.JSONDecodeError as exc:
        return f"ERROR:invalid projects JSON: {exc}"
    all_raw_items: list[tuple[str, int, str]] = []
    all_groups: list[dict] = []

    for project in projects:
        items = collect_open_items(
            vault_path, sessions_folder, project, max_sessions=50,
        )
        all_raw_items.extend(items)

        # Group duplicates: for each item, check against all others
        seen_grouped: set[int] = set()
        for idx, (fpath, line_num, item_text) in enumerate(items):
            if idx in seen_grouped:
                continue
            others = [(f, l, t) for j, (f, l, t) in enumerate(items) if j != idx]
            dupes = find_duplicates(item_text, others)
            if dupes:
                group_members = [{
                    "file": os.path.basename(fpath),
                    "line": line_num,
                    "text": item_text,
                    "mtime": _safe_mtime(fpath),
                }]
                for df, dl, dt, dc in dupes:
                    # Mark dupe indices as seen
                    for j, (f2, l2, t2) in enumerate(items):
                        if os.path.abspath(f2) == os.path.abspath(df) and l2 == dl:
                            seen_grouped.add(j)
                    group_members.append({
                        "file": os.path.basename(df),
                        "line": dl,
                        "text": dt,
                        "confidence": dc,
                        "mtime": _safe_mtime(df),
                    })
                all_groups.append({
                    "project": project,
                    "representative": item_text,
                    "members": group_members,
                })
                seen_grouped.add(idx)

    # 4. Gather evidence per project
    project_paths = _resolve_project_paths()
    evidence: dict[str, dict] = {}
    projects_with_evidence = 0

    for project in projects:
        repo_path = project_paths.get(project)
        if not repo_path:
            continue

        proj_evidence: dict[str, object] = {}

        # git log (last 40 commits)
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "-40"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                proj_evidence["commits"] = proc.stdout.strip().split("\n")[:40]
            else:
                print(f"[obsidian-brain] git log failed for {project}: {proc.stderr.strip()[:200]}", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[obsidian-brain] git log error for {project}: {exc}", file=sys.stderr)

        # gh release list
        try:
            proc = subprocess.run(
                ["gh", "release", "list", "--limit", "5"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                proj_evidence["releases"] = proc.stdout.strip().split("\n")[:5]
            else:
                print(f"[obsidian-brain] gh release list failed for {project}: {proc.stderr.strip()[:200]}", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[obsidian-brain] gh release error for {project}: {exc}", file=sys.stderr)

        # gh pr list --state merged
        try:
            proc = subprocess.run(
                ["gh", "pr", "list", "--state", "merged", "--limit", "20",
                 "--json", "number,title,mergedAt,url"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                try:
                    proj_evidence["merged_prs"] = json.loads(proc.stdout)
                except json.JSONDecodeError as exc:
                    print(f"[obsidian-brain] gh pr list JSON error for {project}: {exc}", file=sys.stderr)
                    proj_evidence["merged_prs"] = []
            else:
                print(f"[obsidian-brain] gh pr list failed for {project}: {proc.stderr.strip()[:200]}", file=sys.stderr)
                proj_evidence["merged_prs"] = []
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            print(f"[obsidian-brain] gh pr list error for {project}: {exc}", file=sys.stderr)
            proj_evidence["merged_prs"] = []

        # gh issue list --state closed
        try:
            proc = subprocess.run(
                ["gh", "issue", "list", "--state", "closed", "--limit", "20",
                 "--json", "number,title,closedAt,body,url"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                try:
                    proj_evidence["closed_issues"] = json.loads(proc.stdout)
                except json.JSONDecodeError as exc:
                    print(f"[obsidian-brain] gh issue list JSON error for {project}: {exc}", file=sys.stderr)
                    proj_evidence["closed_issues"] = []
            else:
                print(f"[obsidian-brain] gh issue list failed for {project}: {proc.stderr.strip()[:200]}", file=sys.stderr)
                proj_evidence["closed_issues"] = []
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            print(f"[obsidian-brain] gh issue list error for {project}: {exc}", file=sys.stderr)
            proj_evidence["closed_issues"] = []

        # CHANGELOG.md excerpt
        changelog_path = os.path.join(repo_path, "CHANGELOG.md")
        if os.path.isfile(changelog_path):
            try:
                with open(changelog_path, 'r', encoding='utf-8', errors='replace') as f:
                    proj_evidence["changelog_excerpt"] = f.read(2000)
            except OSError:
                pass

        # FTS5 search for each open item scoped to THIS project
        proj_items = [g["representative"] for g in all_groups if g["project"] == project]
        fts_mentions: dict[str, int] = {}
        for item_text in proj_items[:10]:  # cap to avoid excessive queries
            kws = vault_index.extract_keywords(item_text, limit=3)
            if kws:
                # Pass keywords as space-separated (not "OR"-joined — search_vault
                # handles tokenization internally; literal "OR" would be a search term)
                hits = vault_index.search_vault(
                    actual_db, " ".join(kws), project=project, limit=5,
                )
                fts_mentions[item_text[:60]] = len(hits)
        if fts_mentions:
            proj_evidence["fts_mentions"] = fts_mentions

        if proj_evidence:
            evidence[project] = proj_evidence
            projects_with_evidence += 1

    # 5. Build output JSON
    output_data = {
        "link_suggestions": link_suggestions,
        "merge_suggestions": merge_suggestions,
        "items": {
            "total_raw": len(all_raw_items),
            "groups": all_groups,
            "group_count": len(all_groups),
        },
        "evidence": evidence,
    }

    # Atomic write: tempfile + rename (ensure dir exists first)
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".ob-pipeline-", suffix=".json", dir=out_dir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, output_path)
    except OSError as exc:
        print(f"[obsidian-brain] pipeline: write failed: {exc}", file=sys.stderr)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return f"ERROR:{exc}"

    total = len(all_raw_items)
    groups = len(all_groups)
    _result = f"OK:{total}:{groups}:{projects_with_evidence}"
    # Cache from in-memory output_data rather than re-reading the file on disk.
    # Re-reading could yield an empty string on a race or disk error, which
    # would make later cache hits silently rewrite output_path with empty JSON.
    try:
        _output_json_str = json.dumps(output_data, indent=2)
    except (TypeError, ValueError) as exc:
        print(f"[obsidian-brain] cache skip: couldn't serialise output_data ({exc})",
              file=sys.stderr)
        return _result
    _evidence_cache_put(_ck, (_result, _output_json_str), _now)
    return _result


def build_deep_presentation(
    pipeline_path: str,
    classifications_path: str,
    basenames_json: str,
    vault_path: str,
    sessions_folder: str,
    insights_folder: str,
) -> str:
    """Build formatted markdown from pipeline JSON + classifications.

    Runs orphan detection (O(N) wikilink scan of window notes, skipping
    standup/emerge types) and builds sections for open item consolidation,
    suggested links, orphaned notes, potential merges, and action prompts.
    """
    # Load pipeline data
    try:
        with open(pipeline_path, 'r', encoding='utf-8') as f:
            pipeline = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return f"Error reading pipeline data: {exc}"

    # Load classifications (may be empty dict)
    try:
        with open(classifications_path, 'r', encoding='utf-8') as f:
            classifications = json.load(f)
    except (OSError, json.JSONDecodeError):
        classifications = {}

    try:
        basenames: list[str] = json.loads(basenames_json) if basenames_json else []
    except json.JSONDecodeError as exc:
        return f"Error parsing basenames JSON: {exc}"

    # --- Orphan detection ---
    # Build set of all stems referenced via wikilinks across window notes
    linked_stems: set[str] = set()
    note_types: dict[str, str] = {}  # stem -> type

    for b in basenames:
        stem = os.path.splitext(b)[0]
        for folder in [sessions_folder, insights_folder]:
            fpath = os.path.join(vault_path, folder, b)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError:
                continue

            # Extract type from frontmatter (first 20 lines)
            for line in content.split('\n')[:20]:
                stripped = line.strip()
                if stripped.startswith('type:'):
                    note_types[stem] = stripped.split(':', 1)[1].strip().strip('"').strip("'")
                    break

            # Collect all wikilink targets
            for target in _RE_WIKILINK.findall(content):
                linked_stems.add(target)
            break  # found in this folder

    # Find orphans: notes in window not linked by any other note, excluding aggregation types
    all_stems = {os.path.splitext(b)[0] for b in basenames}
    orphans: list[str] = []
    for stem in sorted(all_stems):
        note_type = note_types.get(stem, "")
        if note_type in _ORPHAN_EXCLUDE_TYPES:
            continue
        if stem not in linked_stems:
            orphans.append(stem)

    # --- Build markdown ---
    sections: list[str] = []

    # Open Item Consolidation
    items_data = pipeline.get("items", {})
    groups = items_data.get("groups", [])
    total_raw = items_data.get("total_raw", 0)

    # Use classifications if available (list of dicts with classification/evidence)
    classified_items: list[dict] = []
    if isinstance(classifications, list):
        classified_items = classifications

    if classified_items:
        # Group classified items by classification
        by_class: dict[str, list[dict]] = {}
        for item in classified_items:
            cls = item.get("classification", "UNKNOWN").upper()
            by_class.setdefault(cls, []).append(item)

        class_counts = {k: len(v) for k, v in by_class.items()}
        count_parts = ", ".join(f"**{v}** {k.lower()}" for k, v in sorted(class_counts.items()))
        sections.append(f"## Open Item Consolidation\n\n"
                        f"**{total_raw}** raw items classified: {count_parts}.\n")

        # Render each classification group in priority order
        class_order = ["COMPLETED", "REDUNDANT", "STALE", "ACTIVE"]
        for cls in class_order:
            items_in_class = by_class.get(cls, [])
            if not items_in_class:
                continue
            sections.append(f"### {cls.title()} ({len(items_in_class)})\n")
            for item in items_in_class:
                canonical = item.get("canonical", "?")
                evidence = item.get("evidence", "")
                project = item.get("project", "")
                instances = item.get("instances", [])
                proj_label = f" ({project})" if project else ""
                sections.append(f"- **{canonical}**{proj_label}")
                if evidence:
                    sections.append(f"  - Evidence: {evidence}")
                if instances:
                    locs = [f"`{inst.get('file', '?')}:{inst.get('line', '?')}`" for inst in instances[:3]]
                    sections.append(f"  - Found in: {', '.join(locs)}")
            sections.append("")

        # Show any remaining unclassified groups
        remaining = {k: v for k, v in by_class.items() if k not in class_order}
        for cls, items_in_class in sorted(remaining.items()):
            sections.append(f"### {cls.title()} ({len(items_in_class)})\n")
            for item in items_in_class:
                canonical = item.get("canonical", "?")
                evidence = item.get("evidence", "")
                sections.append(f"- **{canonical}**")
                if evidence:
                    sections.append(f"  - Evidence: {evidence}")
            sections.append("")
    else:
        # Fallback: show raw pipeline groups without classification labels
        sections.append(f"## Open Item Consolidation\n\n"
                        f"**{total_raw}** raw items, **{len(groups)}** duplicate groups detected.\n")
        if groups:
            for g in groups:
                rep = g.get("representative", "?")
                project = g.get("project", "?")
                members = g.get("members", [])
                sections.append(f"- **{rep}** ({project}) — {len(members)} occurrences")
        sections.append("")

    # Suggested Links
    link_suggestions = pipeline.get("link_suggestions", [])
    if link_suggestions:
        sections.append("## Suggested Links\n")
        for ls in link_suggestions:
            kws = ", ".join(ls.get("shared_keywords", [])[:5])
            sections.append(f"- [[{ls['note_a']}]] ↔ [[{ls['note_b']}]] (shared: {kws})")
        sections.append("")

    # Orphaned Notes
    if orphans:
        sections.append(f"## Orphaned Notes ({len(orphans)})\n")
        sections.append("These notes are not linked from any other note in the window:\n")
        for orphan in orphans:
            sections.append(f"- [[{orphan}]]")
        sections.append("")

    # Potential Insight Merges
    merge_suggestions = pipeline.get("merge_suggestions", [])
    if merge_suggestions:
        sections.append("## Potential Insight Merges\n")
        for ms in merge_suggestions:
            kws = ", ".join(ms.get("shared_keywords", [])[:5])
            sections.append(f"- [[{ms['note_a']}]] + [[{ms['note_b']}]] (shared: {kws})")
        sections.append("")

    # Actions prompt
    sections.append("## Actions\n")
    sections.append("Review the suggestions above and apply as needed:")
    actions: list[str] = []
    if groups:
        actions.append("- [ ] Consolidate duplicate open items")
    if link_suggestions:
        actions.append("- [ ] Add suggested wikilinks")
    if orphans:
        actions.append("- [ ] Review orphaned notes for linking opportunities")
    if merge_suggestions:
        actions.append("- [ ] Consider merging similar insight notes")
    if not actions:
        actions.append("- No actions needed — vault is well-connected!")
    sections.extend(actions)

    return "\n".join(sections)


def cross_project_dedup(groups_by_project):
    """
    Vault-scope dedup that respects project boundaries.

    Input shape: {project_name: [coarse_group_dict, ...]}
    Output shape: flat list of group dicts, project boundary preserved.

    Distinctive tokens like '#534' are keyed by (project, token) so the same
    token in two repos does NOT collide. Within-project grouping is already
    handled by find_duplicates(); this function is a pass-through with the
    project-scoped collision-avoidance guarantee for vault-wide scans.

    Spec § Pipeline architecture Stage 2a, lines 67-72.
    """
    if not groups_by_project:
        return []
    flat = []
    seen_keys = set()
    for project, groups in groups_by_project.items():
        for g in groups:
            key = (project, g.get("group_id") or id(g))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out = dict(g)
            out.setdefault("project", project)
            flat.append(out)
    return flat


def merge_groups_semantically(coarse_groups):
    """
    Stage 2b orchestrator: invoke the semantic-merge sub-agent via
    check_items_cli.run_semantic_merge, validate the response, enforce
    same-project rule, and apply the merge map by folding absorbed group
    members into the canonical group.

    Accepts either a list of groups OR a dict {project: [groups]}.
    Returns the same shape it received.

    On 2 consecutive sub-agent failures, returns coarse_groups unchanged.
    (Token-only fallback marker added in Task 13.)

    Spec §§ Pipeline architecture Stage 2b (lines 73-86) and Merge-pass rules.
    """
    global _LAST_SEMANTIC_MERGE_MODE
    _LAST_SEMANTIC_MERGE_MODE = "ok"

    return_dict_shape = isinstance(coarse_groups, dict)
    if return_dict_shape:
        flat_groups = [g for v in coarse_groups.values() for g in v]
    else:
        flat_groups = list(coarse_groups or [])

    if not flat_groups:
        return coarse_groups

    workdir = _check_items_workdir()
    _unique = f"{os.getpid()}-{time.time_ns()}"
    in_path = workdir / f"semantic-merge-{_unique}.in.json"
    out_path = workdir / f"semantic-merge-{_unique}.out.json"
    payload = {"groups": [
        {
            "group_id": g.get("group_id"),
            "project": g.get("project"),
            "representative": g.get("representative", ""),
            "member_texts": [m.get("text", "") for m in g.get("members", [])],
        }
        for g in flat_groups
    ]}
    payload_str = json.dumps(payload)
    _STDIN_CAP_BYTES = 1_000_000
    if len(payload_str.encode("utf-8")) >= _STDIN_CAP_BYTES:
        print(
            f"[check-items] payload {len(payload_str)} bytes >= {_STDIN_CAP_BYTES} cap; "
            f"skipping semantic-merge sub-agent, using token-only.",
            file=sys.stderr,
        )
        _LAST_SEMANTIC_MERGE_MODE = "token-only (payload too large)"
        for p in (in_path, out_path):
            try:
                p.unlink()
            except OSError:
                pass
        if return_dict_shape:
            return coarse_groups
        return flat_groups

    in_path.write_text(payload_str, encoding="utf-8")
    os.chmod(str(in_path), 0o600)

    cli_path = os.path.join(os.path.dirname(__file__), "check_items_cli.py")
    attempt = 0
    merge_map = None
    while attempt < 2:
        attempt += 1
        try:
            cp = subprocess.run(
                ["python3", cli_path, "semantic_merge", str(out_path)],
                input=in_path.read_text(),
                capture_output=True,
                text=True,
                timeout=_outer_subagent_timeout(),
            )
            if cp.returncode != 0 or not out_path.exists():
                continue
            merge_map = json.loads(out_path.read_text())
            if not isinstance(merge_map, dict) or "merges" not in merge_map:
                merge_map = None
                continue
            break
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            print(f"[check-items] semantic-merge attempt {attempt} failed: {exc}",
                  file=sys.stderr)
            continue

    for p in (in_path, out_path):
        try:
            p.unlink()
        except OSError:
            pass

    if merge_map is None:
        _LAST_SEMANTIC_MERGE_MODE = "token-only (semantic pass failed)"
        if return_dict_shape:
            return coarse_groups
        return flat_groups

    groups_by_id = {g.get("group_id"): dict(g) for g in flat_groups}

    for merge in merge_map.get("merges", []):
        canonical_id = merge.get("canonical_group_id")
        absorbed_ids = merge.get("absorbed_group_ids", [])
        canonical = groups_by_id.get(canonical_id)
        if canonical is None:
            continue
        canonical_project = canonical.get("project")
        for aid in absorbed_ids:
            absorbed = groups_by_id.get(aid)
            if absorbed is None:
                continue
            if absorbed.get("project") != canonical_project:
                print(f"[check-items] dropping cross-project merge "
                      f"{aid} -> {canonical_id}", file=sys.stderr)
                continue
            canonical.setdefault("members", []).extend(absorbed.get("members", []))
            canonical.setdefault("absorbed_reasoning", []).append({
                "absorbed": aid,
                "reasoning": merge.get("reasoning", ""),
            })
            groups_by_id.pop(aid, None)
        groups_by_id[canonical_id] = canonical

    surviving = list(groups_by_id.values())

    if return_dict_shape:
        out = {}
        for g in surviving:
            out.setdefault(g.get("project"), []).append(g)
        return out
    return surviving


def _check_items_workdir():
    """Return the 0o700 workdir under ~/.claude/obsidian-brain."""
    p = Path.home() / ".claude" / "obsidian-brain"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Semantic merge mode tracker (Task 13)
# ---------------------------------------------------------------------------

_LAST_SEMANTIC_MERGE_MODE = "ok"


def get_last_semantic_merge_mode():
    """Returns 'ok' on last successful merge, or
    'token-only (semantic pass failed)' on fallback."""
    return _LAST_SEMANTIC_MERGE_MODE


# ---------------------------------------------------------------------------
# Stage 4: classify_groups_with_agent orchestrator (Task 16)
# ---------------------------------------------------------------------------

_VALID_CLASSIFICATIONS = {"DONE", "NEEDS-ACTION", "STALE", "ACTIVE"}
_REQUIRED_CLASSIFIER_FIELDS = {
    "group_id", "classification", "confidence",
    "canonical_text", "evidence_citation", "action_required",
}


def _validate_classifier_response(parsed):
    """Return True iff parsed is a list of dicts containing all required fields
    with classification in the valid set."""
    if not isinstance(parsed, list):
        return False
    for item in parsed:
        if not isinstance(item, dict):
            return False
        if not _REQUIRED_CLASSIFIER_FIELDS.issubset(item.keys()):
            return False
        if item.get("classification") not in _VALID_CLASSIFICATIONS:
            return False
    return True


def classify_groups_with_agent(merged_groups, evidence):
    """
    Stage 4 orchestrator: invoke the classifier sub-agent via
    check_items_cli.run_classifier with one retry on schema-validation
    failure. Returns the parsed list on success.

    On 2 consecutive failures, returns [] and sets
    `_LAST_CLASSIFIER_MODE = 'heuristic-fallback'`.

    Spec §§ Pipeline architecture Stage 4 + Expected output.
    """
    global _LAST_CLASSIFIER_MODE
    _LAST_CLASSIFIER_MODE = "ok"

    if not merged_groups:
        return []

    workdir = _check_items_workdir()
    _unique = f"{os.getpid()}-{time.time_ns()}"
    in_path = workdir / f"classify-{_unique}.in.json"
    out_path = workdir / f"classify-{_unique}.out.json"

    payload = {
        "groups": [
            {
                "group_id": g.get("group_id"),
                "project": g.get("project"),
                "representative": g.get("representative", ""),
                "instances": [
                    {
                        "file": m.get("file"),
                        "line": m.get("line"),
                        "text": m.get("text", ""),
                        # Missing mtime → 0 → epoch (1970), which L2 bins as STALE (fail-safe).
                        "mtime": m.get("mtime", 0),
                    }
                    for m in g.get("members", [])
                ],
            }
            for g in merged_groups
        ],
        "evidence": evidence or {},
    }
    payload_str = json.dumps(payload)
    _STDIN_CAP_BYTES = 1_000_000
    if len(payload_str.encode("utf-8")) >= _STDIN_CAP_BYTES:
        print(
            f"[check-items] classifier payload {len(payload_str)} bytes >= "
            f"{_STDIN_CAP_BYTES} cap; falling back to heuristic.",
            file=sys.stderr,
        )
        _LAST_CLASSIFIER_MODE = "heuristic-fallback"
        for p in (in_path, out_path):
            try:
                p.unlink()
            except OSError:
                pass
        return []

    in_path.write_text(payload_str, encoding="utf-8")
    os.chmod(str(in_path), 0o600)

    cli_path = os.path.join(os.path.dirname(__file__), "check_items_cli.py")
    parsed = None
    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            cp = subprocess.run(
                ["python3", cli_path, "classifier", str(out_path)],
                input=in_path.read_text(),
                capture_output=True,
                text=True,
                timeout=_outer_subagent_timeout(),
            )
            if cp.returncode != 0 or not out_path.exists():
                continue
            candidate = json.loads(out_path.read_text())
            # I4: warn early (pre-validation) so the diagnostic is always
            # reachable, even though _validate_classifier_response will still
            # reject the whole response if any non-dict is present.
            if isinstance(candidate, list):
                _non_dict = sum(1 for r in candidate if not isinstance(r, dict))
                if _non_dict:
                    print(
                        f"[check-items] WARN: classifier emitted {_non_dict} non-dict"
                        f" records — dropped",
                        file=sys.stderr,
                    )
            if not _validate_classifier_response(candidate):
                continue
            parsed = candidate
            break
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            print(f"[check-items] classifier attempt {attempt} failed: {exc}",
                  file=sys.stderr)
            continue

    for p in (in_path, out_path):
        try:
            p.unlink()
        except OSError:
            pass

    if parsed is None:
        _LAST_CLASSIFIER_MODE = "heuristic-fallback"
        return []

    # Outer telemetry: summary of this classification run.
    # cache_hit is intentionally NOT emitted here — the orchestration layer
    # is SKILL.md prose: Step 3 heredoc owns partition()'s `known` list,
    # Step 6 heredoc owns this function's invocation, and they share state
    # only via partition.json on disk. Threading len(known) through
    # classify_groups_with_agent's signature is invasive; dropping it
    # entirely (emitting '-' from the CLI side) is cleaner than a placeholder.
    #
    # All three counts derive from `parsed` (the output). Non-dict records are
    # detected and warned before _validate_classifier_response() runs (above);
    # because the validator rejects any list containing a non-dict, `parsed`
    # here is guaranteed to contain only dicts — the redundant post-validation
    # drop guard is not needed.
    _prefiltered_count = sum(
        1 for r in parsed if isinstance(r, dict) and r.get("prefiltered")
    )
    _subagent_count = sum(
        1 for r in parsed if isinstance(r, dict) and not r.get("prefiltered")
    )
    _total_classified = _prefiltered_count + _subagent_count
    print(
        f"[check-items] classifier-result: total_classified={_total_classified} "
        f"prefiltered={_prefiltered_count} subagent={_subagent_count}",
        file=sys.stderr,
    )
    return parsed


_LAST_CLASSIFIER_MODE = "ok"


def get_last_classifier_mode():
    """Returns 'ok' on success or 'heuristic-fallback' if Task 17's
    heuristic must be invoked."""
    return _LAST_CLASSIFIER_MODE


# ---------------------------------------------------------------------------
# Stage 4: classify_groups_heuristic (Task 17 — long-term fallback)
# ---------------------------------------------------------------------------

_DISTINCTIVE_TOKEN_RE = re.compile(
    r"(#\d+|\b[0-9a-f]{7,40}\b|\bv\d+\.\d+(?:\.\d+)?\b)"
)
_COMPLETION_PHRASE_RE = re.compile(
    r"\b(done|merged|shipped|closed|fixed|complete[d]?|resolved|release[d]?)\b",
    re.IGNORECASE,
)
_HEURISTIC_PROXIMITY_CHARS = 120


def classify_groups_heuristic(merged_groups, evidence):
    """
    Tightened heuristic classifier (long-term fallback).

    Spec § Interim coexistence Patch 2 + memory feedback_check_items_filter_tightening:
    DONE requires BOTH a distinctive token AND a completion phrase within
    +/- 120 chars in the same member text. Otherwise -> ACTIVE.

    NEEDS-ACTION and STALE are not assigned by the heuristic (they need
    cross-source evidence the sub-agent provides).
    """
    out = []
    for g in merged_groups or []:
        classification = "ACTIVE"
        confidence = "LOW"
        evidence_citation = None
        canonical_text = g.get("representative", "")

        for m in g.get("members", []) or []:
            text = m.get("text", "") or ""
            tok_match = _DISTINCTIVE_TOKEN_RE.search(text)
            phr_match = _COMPLETION_PHRASE_RE.search(text)
            if tok_match and phr_match:
                distance = abs(tok_match.start() - phr_match.start())
                if distance <= _HEURISTIC_PROXIMITY_CHARS:
                    classification = "DONE"
                    confidence = "HIGH" if distance <= 60 else "MED"
                    evidence_citation = (
                        f"heuristic: token '{tok_match.group(0)}' "
                        f"near completion phrase '{phr_match.group(0)}'"
                    )
                    break

        out.append({
            "group_id": g.get("group_id"),
            "classification": classification,
            "confidence": confidence,
            "canonical_text": canonical_text,
            "evidence_citation": evidence_citation,
            "action_required": None,
        })
    return out


# ---------------------------------------------------------------------------
# Stage 5: partition_for_review (Task 18)
# ---------------------------------------------------------------------------

def partition_for_review(classifications, show_all=False):
    """
    Partition classifier output into UX-relevant buckets for Stage 5.

    Returns:
        {
            "review": [...DONE + NEEDS-ACTION (+ STALE if show_all)...],
            "dashboard_only": [...ACTIVE (always) + STALE (default-mode)...]
        }

    ACTIVE entries have evidence_citation forced to None before dashboard
    write, per spec § Classification semantics line 322.
    """
    review = []
    dashboard_only = []
    for item in classifications or []:
        kind = item.get("classification")
        if kind in ("DONE", "NEEDS-ACTION"):
            review.append(item)
        elif kind == "STALE":
            if show_all:
                review.append(item)
            else:
                dashboard_only.append(item)
        elif kind == "ACTIVE":
            scrubbed = dict(item)
            scrubbed["evidence_citation"] = None
            dashboard_only.append(scrubbed)
    return {"review": review, "dashboard_only": dashboard_only}


def verify_before_edit(file_path: str, line_number: int, expected_text: str) -> bool:
    """
    Re-read target line and compare against expected text BEFORE flipping
    a checkbox via Edit tool.

    Strips the checkbox prefix (`- [ ]`, `- [x]`, `- [X]`) and surrounding
    whitespace from the file side before comparing to `expected_text`. The
    classifier produces bare canonical text without the prefix; this function
    normalizes the file line to match. Returns False on missing file,
    out-of-range line, or read error.

    Memory feedback_open_item_checkoff_verify_before_edit: verification
    is mandatory before Edit-tool dispatch.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        print(
            f"[check-items] verify_before_edit: cannot read {file_path}: {exc}",
            file=sys.stderr,
        )
        return False
    if not 1 <= line_number <= len(lines):
        print(
            f"[check-items] verify_before_edit: line {line_number} out of range for"
            f" {file_path} ({len(lines)} lines)",
            file=sys.stderr,
        )
        return False
    actual_line = lines[line_number - 1]
    actual = _CHECKBOX_PREFIX_RE.sub("", actual_line).strip()
    expected = (expected_text or "").strip()
    return actual == expected
