"""Tests for deep_analysis_pipeline() and build_deep_presentation()."""

import json
import os
from datetime import date
from unittest.mock import patch

import pytest

import open_item_dedup
import vault_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(path, frontmatter: dict, body: str = ""):
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _make_session_note(sessions_dir, name, project, open_items=None, body=""):
    """Create a session note with optional open items."""
    path = sessions_dir / name
    fm = {
        "type": "claude-session",
        "date": "2026-04-10",
        "project": project,
        "status": "summarized",
        "tags": ["claude/session", f"claude/project/{project}"],
    }
    open_section = ""
    if open_items:
        open_section = "\n## Open Questions / Next Steps\n"
        for item in open_items:
            open_section += f"- [ ] {item}\n"
    full_body = body + open_section
    return _write_note(path, fm, full_body)


def _today():
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# CONSOL_01: Semantic dedup groups similar items
# ---------------------------------------------------------------------------


class TestDeepAnalysisPipeline:
    def test_pipeline_returns_structured_json(self, tmp_vault):
        """Pipeline output contains expected top-level keys."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            open_items=["Fix the login handler"],
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["proj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        assert result.startswith("OK:")
        assert os.path.isfile(output_path)

        data = json.loads(open(output_path).read())
        assert "link_suggestions" in data
        assert "merge_suggestions" in data
        assert "items" in data
        assert "evidence" in data

    def test_semantic_dedup_groups_similar_items(self, tmp_vault):
        """CONSOL_01: Two similar open items should be grouped together."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            open_items=["Fix login handler in src/auth.py for PR #99"],
        )
        _make_session_note(
            sessions_dir, "2026-04-10-proj-bbbb.md", "proj",
            open_items=["Fix login handler in src/auth.py for PR #99"],
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["proj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        data = json.loads(open(output_path).read())
        # Should have found duplicates → group_count >= 1
        assert data["items"]["group_count"] >= 1

    def test_no_open_items_graceful(self, tmp_vault):
        """CONSOL_12: Zero open items should not crash."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nNothing to do.\n",
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["proj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        assert result.startswith("OK:")
        data = json.loads(open(output_path).read())
        assert data["items"]["total_raw"] == 0
        assert data["items"]["group_count"] == 0

    def test_already_linked_excluded(self, tmp_vault):
        """LINK_02: Notes that already link to each other should not be suggested."""
        sessions_dir = tmp_vault / "claude-sessions"
        insights_dir = tmp_vault / "claude-insights"
        # Note A links to Note B via wikilink
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nWorked on frobulator. See [[2026-04-10-proj-bbbb]]\n",
        )
        _make_session_note(
            sessions_dir, "2026-04-10-proj-bbbb.md", "proj",
            body="## Summary\nAlso worked on frobulator widget.\n",
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["proj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        data = json.loads(open(output_path).read())
        # The already-linked pair should not appear in link_suggestions
        for suggestion in data["link_suggestions"]:
            pair = {suggestion["note_a"], suggestion["note_b"]}
            assert not (
                "2026-04-10-proj-aaaa" in str(pair)
                and "2026-04-10-proj-bbbb" in str(pair)
            ), "Already-linked notes should not be suggested"


# ---------------------------------------------------------------------------
# Orphan detection tests
# ---------------------------------------------------------------------------


class TestBuildDeepPresentation:
    def test_orphan_detected(self, tmp_vault):
        """ORPHAN_01: A note not linked by any other note is flagged as orphan."""
        sessions_dir = tmp_vault / "claude-sessions"
        insights_dir = tmp_vault / "claude-insights"
        # Note A: no wikilinks pointing to it from other notes
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nDid some solo work.\n",
        )
        # Note B: also no links
        _make_session_note(
            sessions_dir, "2026-04-10-proj-bbbb.md", "proj",
            body="## Summary\nAnother session.\n",
        )

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        # Create minimal pipeline JSON
        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {"total_raw": 0, "groups": [], "group_count": 0},
                "evidence": {},
            }, f)

        # Create minimal classifications JSON
        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump({}, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        assert "Orphan" in result or "orphan" in result.lower()
        # At least one note should be flagged
        assert "2026-04-10-proj-aaaa" in result or "2026-04-10-proj-bbbb" in result

    def test_standup_notes_excluded_from_orphans(self, tmp_vault):
        """ORPHAN_03: Standup-type notes should not appear as orphans."""
        sessions_dir = tmp_vault / "claude-sessions"
        # Regular note — could be orphan
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nSolo work.\n",
        )
        # Standup note — should be excluded
        standup_path = sessions_dir / "2026-04-10-standup.md"
        _write_note(standup_path, {
            "type": "claude-standup",
            "date": "2026-04-10",
            "tags": ["claude/standup"],
        }, "## Daily Standup\nDid stuff.\n")

        # Emerge note — should also be excluded
        emerge_path = sessions_dir / "2026-04-10-emerge.md"
        _write_note(emerge_path, {
            "type": "claude-emerge",
            "date": "2026-04-10",
            "tags": ["claude/emerge"],
        }, "## Emerge\nThemes.\n")

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {"total_raw": 0, "groups": [], "group_count": 0},
                "evidence": {},
            }, f)

        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump({}, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        # Standup and emerge notes should NOT appear in orphan list
        assert "2026-04-10-standup" not in result
        assert "2026-04-10-emerge" not in result


# ---------------------------------------------------------------------------
# _resolve_project_paths tests
# ---------------------------------------------------------------------------


class TestResolveProjectPaths:
    def test_returns_git_repos(self, tmp_path, monkeypatch):
        """Directories with .git are returned."""
        scan_dir = tmp_path / "dev" / "claude_workspace"
        scan_dir.mkdir(parents=True)
        repo = scan_dir / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        non_repo = scan_dir / "plain-dir"
        non_repo.mkdir()

        monkeypatch.setattr(os.path, "expanduser", lambda x: str(tmp_path) if x == "~" else x)
        result = open_item_dedup._resolve_project_paths()
        assert "my-project" in result
        assert "plain-dir" not in result

    def test_handles_missing_dirs(self, tmp_path, monkeypatch):
        """Missing scan directories are skipped gracefully."""
        monkeypatch.setattr(os.path, "expanduser", lambda x: str(tmp_path / "nonexistent") if x == "~" else x)
        result = open_item_dedup._resolve_project_paths()
        assert result == {}


# ---------------------------------------------------------------------------
# Pipeline with evidence (mocked subprocess)
# ---------------------------------------------------------------------------


class TestPipelineEvidence:
    def test_evidence_gathered_with_repo(self, tmp_vault):
        """When a project has a repo path, evidence is gathered."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-myproj-aaaa.md", "myproj",
            open_items=["Fix the widget"],
        )

        # Create a fake repo
        fake_repo = tmp_vault / "repos" / "myproj"
        fake_repo.mkdir(parents=True)
        (fake_repo / ".git").mkdir()
        (fake_repo / "CHANGELOG.md").write_text("# Changelog\n## v1.0.0\n- Initial\n")

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        import vault_index
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(
            open_item_dedup, "_resolve_project_paths",
            return_value={"myproj": str(fake_repo)},
        ):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["myproj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        data = json.loads(open(output_path).read())
        # Even if git log fails (no actual repo), changelog should be read
        assert "myproj" in data["evidence"]
        assert "changelog_excerpt" in data["evidence"]["myproj"]


# ---------------------------------------------------------------------------
# build_deep_presentation with rich data
# ---------------------------------------------------------------------------


class TestBuildDeepPresentationRich:
    def test_all_sections_rendered(self, tmp_vault):
        """All sections are rendered when data is available."""
        sessions_dir = tmp_vault / "claude-sessions"
        insights_dir = tmp_vault / "claude-insights"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nSolo work.\n",
        )

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [
                    {"note_a": "note-a", "note_b": "note-b", "shared_keywords": ["widget", "auth"]},
                ],
                "merge_suggestions": [
                    {"note_a": "insight-a", "note_b": "insight-b", "shared_keywords": ["pattern", "factory"]},
                ],
                "items": {
                    "total_raw": 3,
                    "groups": [
                        {
                            "project": "proj",
                            "representative": "Fix login handler",
                            "members": [
                                {"file": "a.md", "line": 10, "text": "Fix login handler"},
                                {"file": "b.md", "line": 15, "text": "Fix login handler", "confidence": "high"},
                            ],
                        }
                    ],
                    "group_count": 1,
                },
                "evidence": {},
            }, f)

        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump({"some_key": "some_value"}, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        assert "## Open Item Consolidation" in result
        assert "Fix login handler" in result
        assert "## Suggested Links" in result
        assert "## Potential Insight Merges" in result
        assert "## Actions" in result

    def test_error_reading_pipeline(self, tmp_vault):
        """Graceful error when pipeline file is unreadable."""
        result = open_item_dedup.build_deep_presentation(
            pipeline_path="/nonexistent/path.json",
            classifications_path="/nonexistent/class.json",
            basenames_json="[]",
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )
        assert "Error" in result


class TestPipelineMultiProject:
    def test_multiple_projects(self, tmp_vault):
        """Pipeline handles multiple projects."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-alpha-aaaa.md", "alpha",
            open_items=["Deploy alpha service"],
        )
        _make_session_note(
            sessions_dir, "2026-04-10-beta-bbbb.md", "beta",
            open_items=["Test beta integration"],
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        import vault_index
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["alpha", "beta"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        assert result.startswith("OK:")
        data = json.loads(open(output_path).read())
        assert data["items"]["total_raw"] == 2


# ---------------------------------------------------------------------------
# Error handling tests (Fix 3, Fix 7)
# ---------------------------------------------------------------------------


class TestPipelineErrorHandling:
    def test_invalid_projects_json(self, tmp_vault):
        """Fix 7: Invalid projects JSON returns error instead of crashing."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            open_items=["Some item"],
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json="{not valid json",
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        assert result.startswith("ERROR:invalid projects JSON:")

    def test_ensure_index_failure(self, tmp_vault):
        """Fix 3: ensure_index failure returns error instead of crashing."""
        with patch.object(
            vault_index, "ensure_index", side_effect=RuntimeError("index broken")
        ):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=["note.md"],
                projects_json="[]",
                output_path=str(tmp_vault / "out.json"),
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=str(tmp_vault / "test.db"),
            )

        assert result.startswith("ERROR:vault index failed:")
        assert "index broken" in result


class TestPresentationErrorHandling:
    def test_invalid_basenames_json(self, tmp_vault):
        """Fix 7: Invalid basenames JSON returns error."""
        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {"total_raw": 0, "groups": [], "group_count": 0},
                "evidence": {},
            }, f)

        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump({}, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json="{bad json",
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )
        assert "Error parsing basenames JSON" in result


# ---------------------------------------------------------------------------
# Classifications wiring tests (Fix 1)
# ---------------------------------------------------------------------------


class TestClassificationsWiring:
    def test_classifications_list_groups_by_status(self, tmp_vault):
        """Fix 1: Classifications list is used to group items by status."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nSolo work.\n",
        )

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {"total_raw": 3, "groups": [], "group_count": 0},
                "evidence": {},
            }, f)

        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump([
                {
                    "canonical": "Fix login handler",
                    "classification": "COMPLETED",
                    "evidence": "Merged in PR #42",
                    "project": "proj",
                    "instances": [{"file": "session-a.md", "line": 10}],
                },
                {
                    "canonical": "Add integration tests",
                    "classification": "ACTIVE",
                    "evidence": "",
                    "project": "proj",
                    "instances": [{"file": "session-b.md", "line": 20}],
                },
                {
                    "canonical": "Old migration task",
                    "classification": "STALE",
                    "evidence": "No activity for 30 days",
                    "project": "proj",
                    "instances": [],
                },
            ], f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        assert "### Completed (1)" in result
        assert "### Active (1)" in result
        assert "### Stale (1)" in result
        assert "Fix login handler" in result
        assert "Merged in PR #42" in result
        assert "Add integration tests" in result

    def test_empty_classifications_falls_back_to_raw_groups(self, tmp_vault):
        """Fix 1: Empty dict classifications falls back to raw pipeline groups."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nSolo work.\n",
        )

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {
                    "total_raw": 2,
                    "groups": [
                        {
                            "project": "proj",
                            "representative": "Fix login handler",
                            "members": [
                                {"file": "a.md", "line": 10, "text": "Fix login handler"},
                            ],
                        }
                    ],
                    "group_count": 1,
                },
                "evidence": {},
            }, f)

        classifications_path = str(tmp_vault / "classifications.json")
        with open(classifications_path, "w") as f:
            json.dump({}, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path=classifications_path,
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        # Should use fallback: raw group display
        assert "duplicate groups detected" in result
        assert "Fix login handler" in result

    def test_missing_classifications_file_falls_back(self, tmp_vault):
        """Fix 1: Missing classifications file falls back gracefully."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            body="## Summary\nWork.\n",
        )

        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]
        basenames_json = json.dumps(basenames)

        pipeline_path = str(tmp_vault / "pipeline.json")
        with open(pipeline_path, "w") as f:
            json.dump({
                "link_suggestions": [],
                "merge_suggestions": [],
                "items": {"total_raw": 0, "groups": [], "group_count": 0},
                "evidence": {},
            }, f)

        result = open_item_dedup.build_deep_presentation(
            pipeline_path=pipeline_path,
            classifications_path="/nonexistent/classifications.json",
            basenames_json=basenames_json,
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
        )

        # Should not crash, should use fallback
        assert "## Open Item Consolidation" in result


# ---------------------------------------------------------------------------
# Subprocess stderr logging tests (Fix 6)
# ---------------------------------------------------------------------------


class TestSubprocessStderrLogging:
    def test_git_log_failure_logged(self, tmp_vault, capsys):
        """Fix 6: git log failure stderr is logged."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            open_items=["Item"],
        )

        fake_repo = tmp_vault / "repos" / "proj"
        fake_repo.mkdir(parents=True)
        (fake_repo / ".git").mkdir()

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        # Mock subprocess.run to simulate git log failure
        import subprocess as sp
        original_run = sp.run

        def mock_run(cmd, **kwargs):
            if cmd[0] == "git" and "log" in cmd:
                return sp.CompletedProcess(cmd, returncode=128, stdout="", stderr="fatal: not a git repository")
            if cmd[0] == "gh":
                return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr="gh not found")
            return original_run(cmd, **kwargs)

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={"proj": str(fake_repo)}):
            with patch("subprocess.run", side_effect=mock_run):
                result = open_item_dedup.deep_analysis_pipeline(
                    basenames=basenames,
                    projects_json='["proj"]',
                    output_path=output_path,
                    vault_path=str(tmp_vault),
                    sessions_folder="claude-sessions",
                    insights_folder="claude-insights",
                    db_path=db_path,
                )

        captured = capsys.readouterr()
        assert "git log failed" in captured.err
        assert "gh release list failed" in captured.err


# ---------------------------------------------------------------------------
# Temp file permissions tests (Fix 5)
# ---------------------------------------------------------------------------


class TestTempFilePermissions:
    def test_pipeline_output_permissions(self, tmp_vault):
        """Fix 5: Pipeline output file has 0o600 permissions."""
        sessions_dir = tmp_vault / "claude-sessions"
        _make_session_note(
            sessions_dir, "2026-04-10-proj-aaaa.md", "proj",
            open_items=["Item"],
        )

        output_path = str(tmp_vault / "pipeline_out.json")
        basenames = [f.name for f in sessions_dir.iterdir() if f.suffix == ".md"]

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        with patch.object(open_item_dedup, "_resolve_project_paths", return_value={}):
            result = open_item_dedup.deep_analysis_pipeline(
                basenames=basenames,
                projects_json='["proj"]',
                output_path=output_path,
                vault_path=str(tmp_vault),
                sessions_folder="claude-sessions",
                insights_folder="claude-insights",
                db_path=db_path,
            )

        assert result.startswith("OK:")
        mode = os.stat(output_path).st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# FTS scoping per-project (Copilot fix 1)
# ---------------------------------------------------------------------------


class TestFtsScopingPerProject:
    def test_fts_evidence_scoped_to_project(self, tmp_vault):
        """FTS evidence queries should only look at items from the current project."""
        sess = tmp_vault / "claude-sessions"
        # Two projects with different items
        _write_note(sess / f"{_today()}-proj-a-0001.md",
            {"date": _today(), "project": "proj-a", "type": "claude-session", "status": "summarized"},
            "# A\n\n## Summary\nDone.\n\n## Open Questions / Next Steps\n- [ ] Fix alpha bug")
        _write_note(sess / f"{_today()}-proj-b-0001.md",
            {"date": _today(), "project": "proj-b", "type": "claude-session", "status": "summarized"},
            "# B\n\n## Summary\nDone.\n\n## Open Questions / Next Steps\n- [ ] Fix beta bug")

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)
        output = tmp_vault / "deep.json"
        with patch.object(open_item_dedup, '_resolve_project_paths', return_value={}):
            open_item_dedup.deep_analysis_pipeline(
                [f"{_today()}-proj-a-0001", f"{_today()}-proj-b-0001"],
                '["proj-a", "proj-b"]',
                str(output),
                str(tmp_vault), "claude-sessions", "claude-insights",
                db_path=db_path)

        data = json.loads(output.read_text())
        evidence = data.get("evidence", {})
        # Each project's fts_mentions should only reference its own items
        if "proj-a" in evidence and evidence["proj-a"].get("fts_mentions"):
            for key in evidence["proj-a"]["fts_mentions"]:
                assert "beta" not in key.lower(), "proj-a FTS mentions should not contain proj-b items"


# ---------------------------------------------------------------------------
# Pipeline dir creation (Copilot fix 3)
# ---------------------------------------------------------------------------


class TestPipelineDirCreation:
    def test_creates_output_dir_if_missing(self, tmp_vault):
        """Pipeline creates output directory if it doesn't exist."""
        sess = tmp_vault / "claude-sessions"
        bn = f"{_today()}-p-0001"
        _write_note(sess / f"{bn}.md",
            {"date": _today(), "project": "p", "type": "claude-session", "status": "summarized"},
            "# T\n\n## Summary\nDone.")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)

        # Output to a non-existent subdirectory
        output = tmp_vault / "nonexistent" / "subdir" / "deep.json"
        with patch.object(open_item_dedup, '_resolve_project_paths', return_value={}):
            status = open_item_dedup.deep_analysis_pipeline(
                [bn], '["p"]', str(output),
                str(tmp_vault), "claude-sessions", "claude-insights",
                db_path=db_path)
        assert status.startswith("OK:")
        assert output.exists()


# ---------------------------------------------------------------------------
# Representative key (not canonical)
# ---------------------------------------------------------------------------


class TestRepresentativeKey:
    def test_groups_use_representative_key(self, tmp_vault):
        """Pipeline groups use 'representative' key, not 'canonical'."""
        sess = tmp_vault / "claude-sessions"
        bn = f"{_today()}-p-0001"
        _write_note(sess / f"{bn}.md",
            {"date": _today(), "project": "p", "type": "claude-session", "status": "summarized"},
            "# T\n\n## Summary\nDone.\n\n## Open Questions / Next Steps\n- [ ] Fix the important bug")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)

        output = tmp_vault / "deep.json"
        with patch.object(open_item_dedup, '_resolve_project_paths', return_value={}):
            open_item_dedup.deep_analysis_pipeline(
                [bn], '["p"]', str(output),
                str(tmp_vault), "claude-sessions", "claude-insights",
                db_path=db_path)

        data = json.loads(output.read_text())
        for group in data["items"]["groups"]:
            assert "representative" in group, f"Group missing 'representative' key: {group.keys()}"
            assert "canonical" not in group, f"Group has stale 'canonical' key"


class TestEncodingCorruption:
    """Vault notes with non-UTF8 bytes must not crash the pipeline."""

    def test_pipeline_handles_binary_content_in_notes(self, tmp_vault):
        """Notes with encoding corruption are read with errors='replace', not skipped."""
        sess = tmp_vault / "claude-sessions"
        bn = f"{_today()}-corrupt-0001"
        note_path = sess / f"{bn}.md"
        # Write a note with valid frontmatter but binary garbage in body
        content = (
            "---\ndate: " + _today() + "\nproject: p\ntype: claude-session\nstatus: summarized\n---\n\n"
            "# Corrupt\n\n## Summary\nDone.\n\n## Open Questions / Next Steps\n- [ ] Fix the bug\n\n"
        )
        note_path.write_bytes(content.encode("utf-8") + b"\xff\xfe\x00\x80binary garbage")

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)
        output = tmp_vault / "deep.json"
        with patch.object(open_item_dedup, '_resolve_project_paths', return_value={}):
            status = open_item_dedup.deep_analysis_pipeline(
                [bn], '["p"]', str(output),
                str(tmp_vault), "claude-sessions", "claude-insights",
                db_path=db_path)
        assert status.startswith("OK:")
        data = json.loads(output.read_text())
        # Should have collected the open item despite encoding corruption
        assert data["items"]["total_raw"] >= 1

    def test_collect_open_items_handles_binary_notes(self, tmp_vault):
        """collect_open_items reads notes with errors='replace'."""
        sess = tmp_vault / "claude-sessions"
        note_path = sess / f"{_today()}-bin-0001.md"
        content = (
            "---\ndate: " + _today() + "\nproject: p\ntype: claude-session\nstatus: summarized\n---\n\n"
            "# Bin\n\n## Open Questions / Next Steps\n- [ ] Handle encoding\n"
        )
        note_path.write_bytes(content.encode("utf-8") + b"\xff\xfe\x00binary")

        items = open_item_dedup.collect_open_items(
            str(tmp_vault), "claude-sessions", "p")
        # Should find the item without crashing
        assert len(items) >= 1
        assert any("Handle encoding" in t for _, _, t in items)


class TestBatchCascadeEncoding:
    """batch_cascade_checkoff must handle encoding-corrupted vault notes."""

    def test_cascade_handles_binary_notes(self, tmp_vault):
        """Cascade reads notes with errors='replace', doesn't crash on binary."""
        sess = tmp_vault / "claude-sessions"
        note_path = sess / f"{_today()}-cascade-bin-0001.md"
        content = (
            "---\ndate: " + _today() + "\nproject: p\ntype: claude-session\nstatus: summarized\n---\n\n"
            "# T\n\n## Open Questions / Next Steps\n- [ ] Fix encoding bug\n"
        )
        note_path.write_bytes(content.encode("utf-8") + b"\xff\xfe\x00")

        result = open_item_dedup.batch_cascade_checkoff(
            str(tmp_vault), "claude-sessions", "p", ["Fix encoding bug"])
        # Should not crash — either finds the item or reports no duplicates
        assert isinstance(result, str)
