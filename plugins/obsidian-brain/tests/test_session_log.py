# tests/test_session_log.py
"""Tests for _build_note() in obsidian_session_log.py."""

from obsidian_session_log import _build_note


class TestBuildNote:
    def test_build_note_structure(self):
        """Full metadata: verify frontmatter fields, tags, and title with branch."""
        metadata = {
            "project": "my-project",
            "project_path": "/tmp/my-project",
            "git_branch": "feature/cool-thing",
            "duration_minutes": 42,
        }
        result = _build_note("sess-abc123", metadata, "## Body\nSome content.")

        # Frontmatter delimiters present
        assert result.startswith("---\n")
        assert "---\n" in result[4:]  # closing ---

        # Required frontmatter fields
        assert "type: claude-session" in result
        assert "session_id: sess-abc123" in result
        assert "project: my-project" in result
        assert "duration_minutes: 42" in result
        assert "status: auto-logged" in result

        # Tags
        assert "- claude/session" in result
        assert "- claude/project/my-project" in result
        assert "- claude/auto" in result

        # Title with branch
        assert "# Session: my-project (feature/cool-thing)" in result

        # Body present
        assert "## Body" in result
        assert "Some content." in result

    def test_build_note_with_resumed(self):
        """resumed=True: verify 'resumed: true' appears in output."""
        metadata = {
            "project": "my-project",
            "project_path": "/tmp/my-project",
            "git_branch": "main",
            "duration_minutes": 10,
        }
        result = _build_note("sess-resumed", metadata, "body text", resumed=True)

        assert "resumed: true" in result

    def test_build_note_without_resumed(self):
        """resumed=False (default): verify 'resumed: true' does NOT appear."""
        metadata = {
            "project": "my-project",
            "project_path": "/tmp/my-project",
            "git_branch": "main",
            "duration_minutes": 10,
        }
        result = _build_note("sess-not-resumed", metadata, "body text")

        assert "resumed: true" not in result

    def test_build_note_no_branch(self):
        """Empty git_branch: title must be '# Session: <project>' without parentheses."""
        metadata = {
            "project": "branchless-proj",
            "project_path": "/tmp/branchless-proj",
            "git_branch": "",
            "duration_minutes": 5,
        }
        result = _build_note("sess-nobranch", metadata, "body")

        assert "# Session: branchless-proj\n" in result
        # No parentheses after project name on the title line
        title_line = [line for line in result.splitlines() if line.startswith("# Session:")][0]
        assert "(" not in title_line
        assert ")" not in title_line

    def test_build_note_minimal(self):
        """Minimal metadata (project='x', empty strings, duration=0): no crash, has --- and title."""
        metadata = {
            "project": "x",
            "project_path": "",
            "git_branch": "",
            "duration_minutes": 0,
        }
        result = _build_note("sess-min", metadata, "")

        # Must have YAML frontmatter delimiters
        assert "---" in result

        # Must have title
        assert "# Session: x" in result


def test_cleanup_session_cache_removes_file(tmp_path, monkeypatch):
    """_cleanup_session_cache removes /tmp/.obsidian-brain-cache-<sid>.json for the ended session."""
    import obsidian_utils
    from pathlib import Path

    sid = "cleanup-sid-9999"
    cache_path = tmp_path / f".obsidian-brain-cache-{sid}.json"
    cache_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(obsidian_utils, "_CACHE_PREFIX", str(tmp_path / ".obsidian-brain-cache-"))

    # Import the session_log module (it lives in hooks/ which is on sys.path via conftest)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "obsidian_session_log",
        str(Path(__file__).parent.parent / "hooks" / "obsidian_session_log.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod._cleanup_session_cache(sid)
    assert not cache_path.exists(), "cache file should have been removed"


def test_cleanup_session_cache_handles_missing_file(tmp_path, monkeypatch):
    """_cleanup_session_cache is a no-op when the cache file doesn't exist."""
    import obsidian_utils
    from pathlib import Path

    monkeypatch.setattr(obsidian_utils, "_CACHE_PREFIX", str(tmp_path / ".obsidian-brain-cache-"))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "obsidian_session_log",
        str(Path(__file__).parent.parent / "hooks" / "obsidian_session_log.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Should not raise even when the file doesn't exist
    mod._cleanup_session_cache("nonexistent-sid")


def test_cleanup_session_cache_empty_sid_noop(tmp_path, monkeypatch):
    """_cleanup_session_cache with empty sid does nothing."""
    import obsidian_utils
    from pathlib import Path

    # Create a file that would match an empty-sid pattern to make sure we DON'T touch it
    canary = tmp_path / ".obsidian-brain-cache-.json"
    canary.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(obsidian_utils, "_CACHE_PREFIX", str(tmp_path / ".obsidian-brain-cache-"))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "obsidian_session_log",
        str(Path(__file__).parent.parent / "hooks" / "obsidian_session_log.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod._cleanup_session_cache("")
    assert canary.exists(), "empty sid should not touch any files"
