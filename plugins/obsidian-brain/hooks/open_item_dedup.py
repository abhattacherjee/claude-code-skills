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
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
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


# ---------------------------------------------------------------------------
# Deep analysis pipeline
# ---------------------------------------------------------------------------

_RE_WIKILINK = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

# Note types excluded from orphan detection (they are aggregation notes)
_ORPHAN_EXCLUDE_TYPES = frozenset({
    'claude-standup', 'claude-emerge', 'claude-retro',
})


def _resolve_project_paths() -> dict[str, str]:
    """Return dict mapping project name -> repo path for local git repos.

    Scans common directories for directories containing .git.
    """
    result: dict[str, str] = {}
    home = os.path.expanduser("~")
    scan_dirs = [
        os.path.join(home, "dev", "claude_workspace"),
        os.path.join(home, "projects"),
    ]
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
    """
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

        # git log (last 20 commits)
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                proj_evidence["commits"] = proc.stdout.strip().split("\n")[:20]
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
    return f"OK:{total}:{groups}:{projects_with_evidence}"


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
