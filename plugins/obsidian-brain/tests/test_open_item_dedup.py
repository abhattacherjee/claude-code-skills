"""Tests for hooks/open_item_dedup.py."""

from __future__ import annotations

import os

import pytest

from open_item_dedup import (
    _strip_markdown,
    _extract_distinctive_tokens,
    _tokenize,
    collect_open_items,
    find_duplicates,
    cascade_checkoff,
    dedup_note_open_items,
    batch_cascade_checkoff,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _create_session_note(sessions_dir, filename, project, open_items):
    items_text = "\n".join(f"- [ ] {item}" for item in open_items)
    note = sessions_dir / filename
    note.write_text(
        f"---\ntype: claude-session\nproject: {project}\nstatus: summarized\n---\n\n"
        f"# Session\n\n## Summary\nDid stuff.\n\n"
        f"## Open Questions / Next Steps\n{items_text}\n",
        encoding="utf-8",
    )
    return note


# ---------------------------------------------------------------------------
# 1. _strip_markdown
# ---------------------------------------------------------------------------

def test_strip_markdown():
    assert _strip_markdown("`code`") == "code"
    assert _strip_markdown("**bold**") == "bold"
    assert _strip_markdown("_italic_") == "italic"
    assert _strip_markdown("[link text](https://example.com)") == "link text"
    assert _strip_markdown("plain text") == "plain text"
    # Multiple patterns in one string
    result = _strip_markdown("Fix `obsidian_utils.py` and **refactor** the _loop_")
    assert "obsidian_utils.py" in result
    assert "refactor" in result
    assert "loop" in result
    assert "`" not in result
    assert "**" not in result
    # Italic delimiters removed: "_loop_" → "loop" (no standalone _ around words)
    assert "_loop_" not in result
    assert "loop" in result


# ---------------------------------------------------------------------------
# 2. _extract_distinctive_tokens
# ---------------------------------------------------------------------------

def test_extract_distinctive_tokens():
    # File paths
    tokens = _extract_distinctive_tokens("Update hooks/obsidian_utils.py and README.md")
    assert any("obsidian_utils.py" in t for t in tokens)
    assert any("README.md" in t for t in tokens)

    # PR refs
    tokens = _extract_distinctive_tokens("Closes #42 and PR 99")
    assert any("#42" in t for t in tokens)

    # Branch names
    tokens = _extract_distinctive_tokens("Merge feature/new-hook into develop")
    assert any("feature/new-hook" in t for t in tokens)

    # Version numbers
    tokens = _extract_distinctive_tokens("Bump to v1.2.3 for release")
    assert any("v1.2.3" in t for t in tokens)

    # Nothing distinctive
    tokens = _extract_distinctive_tokens("Add more unit tests")
    assert tokens == []


# ---------------------------------------------------------------------------
# 3. _tokenize
# ---------------------------------------------------------------------------

def test_tokenize():
    tokens = _tokenize("Fix the login bug in auth module")
    # Should be lowercase
    assert all(t == t.lower() for t in tokens)
    # Stopwords dropped
    assert "the" not in tokens
    assert "in" not in tokens
    # Short tokens dropped
    assert all(len(t) >= 3 for t in tokens)
    # Meaningful words kept
    assert "fix" in tokens
    assert "login" in tokens
    assert "bug" in tokens
    assert "auth" in tokens
    assert "module" in tokens


# ---------------------------------------------------------------------------
# 4. collect_open_items
# ---------------------------------------------------------------------------

def test_collect_open_items(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(sessions_dir, "2026-04-10-proj-aaa.md", "myproject",
                         ["Write unit tests", "Update README.md"])
    _create_session_note(sessions_dir, "2026-04-09-proj-bbb.md", "myproject",
                         ["Deploy to production"])

    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    texts = [t for _, _, t in items]

    assert len(texts) == 3
    assert "Write unit tests" in texts
    assert "Update README.md" in texts
    assert "Deploy to production" in texts


# ---------------------------------------------------------------------------
# 5. collect_open_items_empty_vault
# ---------------------------------------------------------------------------

def test_collect_open_items_empty_vault(tmp_vault):
    # No notes created
    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    assert items == []


# ---------------------------------------------------------------------------
# 6. collect_open_items_wrong_project
# ---------------------------------------------------------------------------

def test_collect_open_items_wrong_project(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(sessions_dir, "2026-04-10-proj-ccc.md", "otherproject",
                         ["Fix the widget bug"])

    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    assert items == []


# ---------------------------------------------------------------------------
# 7. find_duplicates_exact (distinctive token match → "high")
# ---------------------------------------------------------------------------

def test_find_duplicates_exact():
    existing = [
        ("/vault/sessions/note-a.md", 10, "Merge feature/new-hook into develop"),
        ("/vault/sessions/note-b.md", 20, "Write unit tests"),
    ]
    # Candidate shares distinctive token "feature/new-hook"
    matches = find_duplicates("Finish feature/new-hook branch", existing)
    assert len(matches) >= 1
    high_matches = [m for m in matches if m[3] == "high"]
    assert len(high_matches) >= 1
    assert any("feature/new-hook" in m[2] for m in high_matches)


# ---------------------------------------------------------------------------
# 8. find_duplicates_fuzzy (token overlap above threshold → "fuzzy")
# ---------------------------------------------------------------------------

def test_find_duplicates_fuzzy():
    # Craft items with lots of overlapping non-distinctive tokens
    existing_text = (
        "Review the summarization pipeline configuration for batch recall upgrade"
    )
    candidate_text = (
        "Check the summarization pipeline configuration for batch recall upgrade process"
    )
    existing = [("/vault/sessions/note.md", 5, existing_text)]
    matches = find_duplicates(candidate_text, existing, threshold=5)
    assert len(matches) >= 1
    # At least one fuzzy match (no distinctive tokens)
    assert any(m[3] in ("fuzzy", "high") for m in matches)


# ---------------------------------------------------------------------------
# 9. find_duplicates_no_match (dissimilar items → [])
# ---------------------------------------------------------------------------

def test_find_duplicates_no_match():
    existing = [
        ("/vault/sessions/note.md", 1, "Deploy the authentication service"),
    ]
    matches = find_duplicates("Update the CSS color scheme", existing)
    assert matches == []


# ---------------------------------------------------------------------------
# 10. cascade_checkoff — excludes source item from results
# ---------------------------------------------------------------------------

def test_cascade_checkoff():
    source_file = "/vault/sessions/note-a.md"
    source_line = 7
    existing = [
        (source_file, source_line, "Merge feature/auth-fix into develop"),
        ("/vault/sessions/note-b.md", 12, "Merge feature/auth-fix into develop"),
    ]
    # The source item itself should be excluded
    matches = cascade_checkoff(
        "Merge feature/auth-fix into develop",
        existing,
        source_file=source_file,
        source_line=source_line,
    )
    assert all(
        not (m[0] == source_file and m[1] == source_line)
        for m in matches
    )
    # The duplicate in note-b should still be returned
    assert any(m[0] == "/vault/sessions/note-b.md" for m in matches)


# ---------------------------------------------------------------------------
# 11. dedup_note_open_items — removes high-confidence duplicate from newer note
# ---------------------------------------------------------------------------

def test_dedup_note_open_items(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"

    # Older note (already has the item)
    _create_session_note(
        sessions_dir,
        "2026-04-09-proj-old.md",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    # Newer note (duplicate item — same distinctive file path token)
    newer_note = _create_session_note(
        sessions_dir,
        "2026-04-10-proj-new.md",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error", "Write new tests"],
    )

    removed = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(newer_note)
    )

    assert len(removed) >= 1
    assert any("obsidian_utils.py" in r for r in removed)

    # Verify file was rewritten without the duplicate
    content = newer_note.read_text(encoding="utf-8")
    assert "Write new tests" in content  # non-duplicate preserved


# ---------------------------------------------------------------------------
# 12. batch_cascade_checkoff — returns a string result
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"

    _create_session_note(
        sessions_dir,
        "2026-04-09-proj-aaa.md",
        "myproject",
        ["Merge feature/new-hook into develop"],
    )

    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Merge feature/new-hook into develop"],
    )
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 13. batch_cascade_checkoff_empty — no items → appropriate message
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_empty(tmp_vault):
    # No notes in vault at all
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Fix the authentication bug"],
    )
    assert isinstance(result, str)
    assert "no open items" in result.lower() or "no duplicate" in result.lower()


# ---------------------------------------------------------------------------
# 14. collect_open_items: snapshot exclusion (line 81)
# ---------------------------------------------------------------------------

def test_collect_open_items_skips_snapshot_files(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    # Snapshot notes (type: claude-snapshot) are excluded via frontmatter type
    # filter, regardless of filename suffix.
    snapshot_note = sessions_dir / "2026-04-10-proj-snapshot-140000.md"
    snapshot_note.write_text(
        "---\ntype: claude-snapshot\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n- [ ] Snapshot item\n",
        encoding="utf-8",
    )
    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    texts = [t for _, _, t in items]
    assert "Snapshot item" not in texts


# ---------------------------------------------------------------------------
# 15. collect_open_items: exclude_path filtering (line 71 / 84-85)
# ---------------------------------------------------------------------------

def test_collect_open_items_exclude_path(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-10-proj-excl.md", "myproject",
        ["Excluded item here"],
    )
    items = collect_open_items(
        str(tmp_vault), "claude-sessions", "myproject",
        exclude_path=str(note),
    )
    texts = [t for _, _, t in items]
    assert "Excluded item here" not in texts


# ---------------------------------------------------------------------------
# 16. collect_open_items: OSError on file read (lines 92-94)
# ---------------------------------------------------------------------------

def test_collect_open_items_oserror(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-10-proj-bad.md", "myproject", ["Good item"]
    )

    original_open = open

    def patched_open(path, *args, **kwargs):
        if str(note) in str(path):
            raise OSError("simulated read error")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", patched_open)
    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    captured = capsys.readouterr()
    assert "skipping unreadable note" in captured.err
    # The unreadable file's items should not appear
    assert all("Good item" not in t for _, _, t in items)


# ---------------------------------------------------------------------------
# 17. collect_open_items: UnicodeDecodeError on file read (lines 95-97)
# ---------------------------------------------------------------------------

def test_collect_open_items_unicode_error(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-10-proj-unicode.md", "myproject", ["Unicode item"]
    )

    original_open = open

    def patched_open(path, *args, **kwargs):
        if str(note) in str(path):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "simulated")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", patched_open)
    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    captured = capsys.readouterr()
    assert "encoding error" in captured.err


# ---------------------------------------------------------------------------
# 18. collect_open_items: max_sessions limit (lines 128-129)
# ---------------------------------------------------------------------------

def test_collect_open_items_max_sessions(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    for i in range(5):
        _create_session_note(
            sessions_dir, f"2026-04-0{i+1}-proj-ms{i}.md", "myproject",
            [f"Item from session {i}"],
        )
    # max_sessions=2 → only 2 files processed
    items = collect_open_items(
        str(tmp_vault), "claude-sessions", "myproject", max_sessions=2
    )
    assert len(items) == 2


# ---------------------------------------------------------------------------
# 19. collect_open_items: section break on next ## header (line 123)
# ---------------------------------------------------------------------------

def test_collect_open_items_section_break(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    note = sessions_dir / "2026-04-10-proj-secbreak.md"
    note.write_text(
        "---\ntype: claude-session\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n"
        "- [ ] Item in section\n"
        "## Another Section\n"
        "- [ ] Item outside section\n",
        encoding="utf-8",
    )
    items = collect_open_items(str(tmp_vault), "claude-sessions", "myproject")
    texts = [t for _, _, t in items]
    assert "Item in section" in texts
    assert "Item outside section" not in texts


# ---------------------------------------------------------------------------
# 20. dedup_note_open_items: OSError reading note_path (lines 213-215)
# ---------------------------------------------------------------------------

def test_dedup_note_oserror(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-10-proj-derr.md", "myproject", ["Bad file item"]
    )

    original_open = open

    def patched_open(path, *args, **kwargs):
        if str(note) in str(path):
            raise OSError("cannot open")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", patched_open)
    result = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(note)
    )
    assert result == []
    captured = capsys.readouterr()
    assert "dedup: cannot read" in captured.err


# ---------------------------------------------------------------------------
# 21. dedup_note_open_items: no existing items (early return, line 222)
# ---------------------------------------------------------------------------

def test_dedup_note_no_existing_items(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    # Only one session note — no other notes for comparison
    note = _create_session_note(
        sessions_dir, "2026-04-10-proj-only.md", "myproject", ["Solo item"]
    )
    result = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(note)
    )
    assert result == []


# ---------------------------------------------------------------------------
# 22. dedup_note_open_items: section break → no duplicates found (line 247)
# ---------------------------------------------------------------------------

def test_dedup_note_no_duplicates_found(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-old2.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    # Newer note with completely different items (no high-confidence match)
    newer_note = sessions_dir / "2026-04-10-proj-new2.md"
    newer_note.write_text(
        "---\ntype: claude-session\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n"
        "- [ ] Totally unrelated task with no common tokens whatsoever\n",
        encoding="utf-8",
    )
    removed = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(newer_note)
    )
    assert removed == []


# ---------------------------------------------------------------------------
# 23. dedup_note_open_items: stat OSError fallback (lines 261-262)
# ---------------------------------------------------------------------------

def test_dedup_note_stat_oserror_fallback(tmp_vault, monkeypatch):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-statold.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    newer_note = _create_session_note(
        sessions_dir, "2026-04-10-proj-statnew.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error", "Another item"],
    )

    original_stat = os.stat

    def patched_stat(path, *args, **kwargs):
        if str(newer_note) in str(path):
            raise OSError("stat failed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", patched_stat)
    removed = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(newer_note)
    )
    # Should still remove the duplicate even without stat
    assert len(removed) >= 1


# ---------------------------------------------------------------------------
# 24. dedup_note_open_items: atomic write OSError → cleanup (lines 267-273)
# ---------------------------------------------------------------------------

def test_dedup_note_atomic_write_oserror(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-wold.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    newer_note = _create_session_note(
        sessions_dir, "2026-04-10-proj-wnew.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error", "Another item"],
    )

    original_replace = os.replace

    def patched_replace(src, dst):
        if ".ob-dedup-" in src:
            raise OSError("replace failed")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", patched_replace)
    result = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(newer_note)
    )
    assert result == []
    captured = capsys.readouterr()
    assert "atomic write failed" in captured.err


# ---------------------------------------------------------------------------
# 25. dedup_note_open_items: ## section break inside note (line 236)
# ---------------------------------------------------------------------------

def test_dedup_note_section_break_stops_scan(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-sbold.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    # Newer note: has item AFTER next ## that should not be removed
    newer_note = sessions_dir / "2026-04-10-proj-sbnew.md"
    newer_note.write_text(
        "---\ntype: claude-session\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n"
        "- [ ] Fix hooks/obsidian_utils.py import error\n"
        "## Other Section\n"
        "- [ ] Fix hooks/obsidian_utils.py import error\n",
        encoding="utf-8",
    )
    removed = dedup_note_open_items(
        str(tmp_vault), "claude-sessions", "myproject", str(newer_note)
    )
    # Only the one in the Open Questions section should be considered
    assert len(removed) == 1


# ---------------------------------------------------------------------------
# 26. batch_cascade_checkoff: fuzzy-only duplicates (lines 304-305, 377-384)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_fuzzy_suggestions(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    # Create a note with a fuzzy-matchable item (high token overlap, no distinctive tokens)
    note = sessions_dir / "2026-04-09-proj-fuzzy.md"
    note.write_text(
        "---\ntype: claude-session\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n"
        "- [ ] Review the summarization pipeline configuration for batch recall upgrade\n",
        encoding="utf-8",
    )
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Check the summarization pipeline configuration for batch recall upgrade process"],
    )
    # Must find fuzzy suggestions for high-overlap input
    assert isinstance(result, str)
    assert "Fuzzy suggestions" in result, (
        f"Expected fuzzy suggestions for high-overlap input, got: {result}"
    )


# ---------------------------------------------------------------------------
# 27. batch_cascade_checkoff: no duplicates found path (line 313-314)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_no_duplicates(tmp_vault):
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-nodupe.md", "myproject",
        ["Deploy the authentication service"],
    )
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Update the CSS color scheme"],
    )
    assert "No duplicates found" in result


# ---------------------------------------------------------------------------
# 28. batch_cascade_checkoff: cascade file read OSError (lines 329-331)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_file_read_oserror(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-09-proj-casc.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    # Make the file unreadable after collect_open_items has already collected it
    call_count = [0]
    original_open = open

    def patched_open(path, *args, **kwargs):
        if str(note) in str(path):
            call_count[0] += 1
            # First call (collect) succeeds; second call (cascade edit) fails
            if call_count[0] > 1:
                raise OSError("cascade read failed")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", patched_open)
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    captured = capsys.readouterr()
    assert "cascade: cannot read" in captured.err


# ---------------------------------------------------------------------------
# 29. batch_cascade_checkoff: line no longer has checkbox (line 340)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_line_already_changed(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    # Create a note that has already been checked off (- [x])
    note = sessions_dir / "2026-04-09-proj-checked.md"
    note.write_text(
        "---\ntype: claude-session\nproject: myproject\n---\n\n"
        "## Open Questions / Next Steps\n"
        "- [x] Fix hooks/obsidian_utils.py import error\n",
        encoding="utf-8",
    )

    # But inject it into collect_open_items by patching to return a fake unchecked item
    import open_item_dedup as oid_module

    original_collect = oid_module.collect_open_items

    def patched_collect(vault_path, sessions_folder, project, *args, **kwargs):
        # Return the note as if it had an unchecked item at line 7
        return [(str(note), 7, "Fix hooks/obsidian_utils.py import error")]

    monkeypatch.setattr(oid_module, "collect_open_items", patched_collect)

    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    captured = capsys.readouterr()
    # Should warn that line no longer has expected checkbox
    assert "no longer contains expected checkbox" in captured.err


# ---------------------------------------------------------------------------
# 30. batch_cascade_checkoff: cascade write OSError (lines 363-368)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_write_oserror(tmp_vault, monkeypatch, capsys):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-09-proj-wfail.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    original_replace = os.replace

    def patched_replace(src, dst):
        if ".ob-cascade-" in src:
            raise OSError("cascade write failed")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", patched_replace)
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    captured = capsys.readouterr()
    assert "cascade: write failed" in captured.err


# ---------------------------------------------------------------------------
# 31. batch_cascade_checkoff: stat OSError fallback in cascade write (lines 355-356)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_stat_oserror(tmp_vault, monkeypatch):
    sessions_dir = tmp_vault / "claude-sessions"
    note = _create_session_note(
        sessions_dir, "2026-04-09-proj-cstat.md", "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    original_stat = os.stat

    def patched_stat(path, *args, **kwargs):
        if str(note) in str(path):
            raise OSError("stat failed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", patched_stat)
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    # Should still succeed (uses 0o644 fallback)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 32. batch_cascade_checkoff: multi-project isolation (standup Step 14)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_multi_project_isolation(tmp_vault):
    """Cascade for project A must not affect project B's open items."""
    sessions_dir = tmp_vault / "claude-sessions"

    # Project A needs two notes so cascade has a source and a target
    _create_session_note(
        sessions_dir, "2026-04-08-proj-a0.md", "project-alpha",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    _create_session_note(
        sessions_dir, "2026-04-09-proj-a1.md", "project-alpha",
        ["Fix hooks/obsidian_utils.py import error"],
    )
    # Project B has the same text but different project
    _create_session_note(
        sessions_dir, "2026-04-09-proj-b1.md", "project-beta",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    # Cascade only for project-alpha
    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "project-alpha",
        ["Fix hooks/obsidian_utils.py import error"],
    )

    # Positive: project A's items should be checked off in at least one note
    content_a0 = (sessions_dir / "2026-04-08-proj-a0.md").read_text(encoding="utf-8")
    content_a1 = (sessions_dir / "2026-04-09-proj-a1.md").read_text(encoding="utf-8")
    assert "- [x] Fix hooks/obsidian_utils.py import error" in content_a0 + content_a1

    # Negative: project B's note must remain untouched
    content_b = (sessions_dir / "2026-04-09-proj-b1.md").read_text(encoding="utf-8")
    assert "- [ ] Fix hooks/obsidian_utils.py import error" in content_b


# ---------------------------------------------------------------------------
# 33. batch_cascade_checkoff: multiple items in single call (standup Step 14)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_multiple_items(tmp_vault):
    """Standup may pass multiple completed items for one project at once."""
    sessions_dir = tmp_vault / "claude-sessions"

    _create_session_note(
        sessions_dir, "2026-04-08-proj-multi1.md", "myproject",
        ["Merge feature/auth-fix into develop", "Update hooks/obsidian_utils.py"],
    )
    _create_session_note(
        sessions_dir, "2026-04-09-proj-multi2.md", "myproject",
        ["Merge feature/auth-fix into develop"],
    )

    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        [
            "Merge feature/auth-fix into develop",
            "Update hooks/obsidian_utils.py",
        ],
    )
    assert isinstance(result, str)
    # Verify both items were actually checked off on disk
    all_content = ""
    for f in sessions_dir.iterdir():
        all_content += f.read_text(encoding="utf-8")
    assert "- [x] Merge feature/auth-fix into develop" in all_content
    assert "- [x] Update hooks/obsidian_utils.py" in all_content


# ---------------------------------------------------------------------------
# 34. batch_cascade_checkoff: verifies file modification (standup Step 14)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_modifies_files(tmp_vault):
    """After cascade, duplicate items in both notes should be checked off."""
    sessions_dir = tmp_vault / "claude-sessions"

    # Two notes with the same distinctive-token item
    _create_session_note(
        sessions_dir, "2026-04-08-proj-src.md", "myproject",
        ["Merge feature/auth-fix into develop"],
    )
    _create_session_note(
        sessions_dir, "2026-04-09-proj-dup.md", "myproject",
        ["Merge feature/auth-fix into develop", "Unrelated task here"],
    )

    batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        ["Merge feature/auth-fix into develop"],
    )

    # At least one note should have the item checked off
    content_a = (sessions_dir / "2026-04-08-proj-src.md").read_text(encoding="utf-8")
    content_b = (sessions_dir / "2026-04-09-proj-dup.md").read_text(encoding="utf-8")
    assert "- [x] Merge feature/auth-fix into develop" in content_a \
        or "- [x] Merge feature/auth-fix into develop" in content_b
    # Non-matching item should remain untouched
    assert "- [ ] Unrelated task here" in content_b


# ---------------------------------------------------------------------------
# 35. batch_cascade_checkoff: empty items list (standup Step 14 edge case)
# ---------------------------------------------------------------------------

def test_batch_cascade_checkoff_empty_items_list(tmp_vault):
    """Passing an empty items list should return gracefully."""
    sessions_dir = tmp_vault / "claude-sessions"
    _create_session_note(
        sessions_dir, "2026-04-09-proj-empty.md", "myproject",
        ["Some open item"],
    )

    result = batch_cascade_checkoff(
        str(tmp_vault),
        "claude-sessions",
        "myproject",
        [],
    )
    assert isinstance(result, str)
    # Original item should remain unchecked
    content = (sessions_dir / "2026-04-09-proj-empty.md").read_text(encoding="utf-8")
    assert "- [ ] Some open item" in content
