"""Open item deduplication for Obsidian Brain.

Provides duplicate detection, creation-time prevention, and check-off
cascading for open items across session notes. All matching uses hybrid
distinctive-token + fuzzy-overlap matching. Python stdlib only.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

# --- Module-level compiled regexes (computed once at import) ---

_RE_FILE_PATH = re.compile(r'[\w./-]+\.(py|md|json|ts|js|tsx|jsx)')
_RE_PR_REF = re.compile(r'#\d+|PR\s+\d+|issue\s+\d+', re.IGNORECASE)
_RE_BRANCH = re.compile(r'(?:feature|release|hotfix)/[\w.-]+')
_RE_VERSION = re.compile(r'v?\d+\.\d+\.\d+')
_RE_MARKDOWN = re.compile(r'`([^`]*)`|\*\*([^*]*)\*\*|_([^_]*)_|\[([^\]]*)\]\([^)]*\)')

_STOPWORDS = frozenset({
    'the', 'a', 'an', 'to', 'for', 'in', 'on', 'of', 'and', 'or',
    'but', 'is', 'are', 'was', 'were', 'be', 'not', 'this', 'that',
    'with', 'from', 'by', 'at', 'it', 'as', 'if', 'so', 'do', 'no',
})

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


def collect_open_items(
    vault_path: str,
    sessions_folder: str,
    project: str,
    max_sessions: int = 10,
    exclude_path: str | None = None,
) -> list[tuple[str, int, str]]:
    """Collect unchecked open items from recent session notes for a project.

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
        if not fname.endswith('.md') or fname.endswith('-snapshot.md'):
            continue

        fpath = os.path.join(sessions_dir, fname)
        if exclude_path and os.path.abspath(fpath) == os.path.abspath(exclude_path):
            continue

        # Single-pass: read file once, check project in frontmatter,
        # then extract open items from ## Open Questions / Next Steps
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except OSError as exc:
            print(f"[obsidian-brain] skipping unreadable note {fname}: {exc}", file=sys.stderr)
            continue
        except UnicodeDecodeError as exc:
            print(f"[obsidian-brain] encoding error in {fname}: {exc}", file=sys.stderr)
            continue

        # Check frontmatter for project match (first 20 lines)
        # Strip quotes to handle both `project: foo` and `project: "foo"`
        project_match = False
        for line in lines[:20]:
            stripped = line.strip()
            if stripped.startswith('project:'):
                val = stripped.split(':', 1)[1].strip().strip('"').strip("'")
                if val == project:
                    project_match = True
                    break
        if not project_match:
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
    Tier 1 short-circuits: if a distinctive token matches, skip Tier 2.
    """
    cleaned = _strip_markdown(candidate_text)
    candidate_distinctive = _extract_distinctive_tokens(cleaned)
    candidate_tokens = _tokenize(cleaned)

    matches: list[tuple[str, int, str, str]] = []

    for fpath, line_num, item_text in existing_items:
        item_lower = item_text.lower()

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
            with open(fpath, 'r', encoding='utf-8') as f:
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
