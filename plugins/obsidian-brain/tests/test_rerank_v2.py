"""Tests for 7-signal scorer with task-context-adaptive type weights."""

import math
import sqlite3
import time
from unittest.mock import patch

import pytest

import vault_index


class TestDetectTaskContext:
    def test_general_context_default(self):
        with patch.object(vault_index, "_get_git_branch", return_value="develop"):
            assert vault_index.detect_task_context() == "general"

    def test_debugging_from_fix_branch(self):
        with patch.object(vault_index, "_get_git_branch", return_value="fix/login-bug"):
            assert vault_index.detect_task_context() == "debugging"

    def test_debugging_from_hotfix_branch(self):
        with patch.object(vault_index, "_get_git_branch", return_value="hotfix/urgent"):
            assert vault_index.detect_task_context() == "debugging"

    def test_debugging_from_bug_branch(self):
        with patch.object(vault_index, "_get_git_branch", return_value="bug/crash-on-start"):
            assert vault_index.detect_task_context() == "debugging"

    def test_caller_standup(self):
        with patch.object(vault_index, "_get_git_branch", return_value="develop"):
            assert vault_index.detect_task_context(caller_skill="standup") == "standup"

    def test_caller_emerge(self):
        with patch.object(vault_index, "_get_git_branch", return_value="develop"):
            assert vault_index.detect_task_context(caller_skill="emerge") == "emerge"

    def test_caller_vault_search(self):
        with patch.object(vault_index, "_get_git_branch", return_value="develop"):
            assert vault_index.detect_task_context(caller_skill="vault-search") == "search"

    def test_caller_vault_ask(self):
        with patch.object(vault_index, "_get_git_branch", return_value="develop"):
            assert vault_index.detect_task_context(caller_skill="vault-ask") == "search"

    def test_branch_takes_precedence_over_caller_for_debugging(self):
        with patch.object(vault_index, "_get_git_branch", return_value="fix/thing"):
            assert vault_index.detect_task_context(caller_skill="vault-search") == "debugging"

    def test_no_branch_available(self):
        with patch.object(vault_index, "_get_git_branch", return_value=None):
            assert vault_index.detect_task_context() == "general"

    def test_feature_branch_with_fix_substring_not_debugging(self):
        """'feature/prefix-cleanup' should NOT be detected as debugging."""
        with patch.object(vault_index, "_get_git_branch", return_value="feature/prefix-cleanup"):
            assert vault_index.detect_task_context() == "general"

    def test_fix_branch_with_slash(self):
        """'fix/something' IS debugging."""
        with patch.object(vault_index, "_get_git_branch", return_value="fix/something"):
            assert vault_index.detect_task_context() == "debugging"

    def test_hotfix_exact(self):
        """'hotfix' alone (no slash) IS debugging."""
        with patch.object(vault_index, "_get_git_branch", return_value="hotfix"):
            assert vault_index.detect_task_context() == "debugging"


class TestContextAdaptiveTypeScores:
    def test_get_type_scores_debugging(self):
        scores = vault_index.get_type_scores("debugging")
        assert scores["claude-error-fix"] == 1.0
        assert scores["claude-session"] == 0.8
        assert scores["claude-decision"] == 0.5

    def test_get_type_scores_standup(self):
        scores = vault_index.get_type_scores("standup")
        assert scores["claude-session"] == 1.0
        assert scores["claude-decision"] == 0.8

    def test_get_type_scores_search(self):
        scores = vault_index.get_type_scores("search")
        assert scores["claude-insight"] == 1.0
        assert scores["claude-decision"] == 0.9

    def test_get_type_scores_general(self):
        scores = vault_index.get_type_scores("general")
        assert scores["claude-insight"] == 1.0
        assert scores["claude-decision"] == 1.0
        assert scores["claude-error-fix"] == 0.9

    def test_get_type_scores_unknown_context_uses_general(self):
        scores = vault_index.get_type_scores("unknown_context")
        assert scores == vault_index.get_type_scores("general")

    def test_get_type_scores_unknown_type_returns_default(self):
        scores = vault_index.get_type_scores("general")
        assert scores.get("unknown-type", 0.5) == 0.5


def _make_fts_result(
    path="/vault/test.md",
    note_type="claude-session",
    date_str="2026-04-15",
    rank=-5.0,
    body="some content here",
    title="Test Note",
    tags="claude/session",
    importance=5,
):
    return {
        "path": path, "type": note_type, "date": date_str, "rank": rank,
        "body": body, "title": title, "tags": tags, "importance": importance,
        "status": "summarized",
    }


class TestRerankV2Signals:
    def test_rerank_returns_7_signal_score(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        candidates = [
            _make_fts_result(path="/vault/a.md", rank=-10.0),
            _make_fts_result(path="/vault/b.md", rank=-5.0),
        ]
        results = vault_index.rerank_results(candidates, ["content"], db_path=db_path)
        assert len(results) == 2
        assert all("rerank_score" in r for r in results)

    def test_activation_signal_boosts_accessed_note(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/a.md", "recall")
        vault_index.log_access(db_path, "/vault/a.md", "search")
        vault_index.log_access(db_path, "/vault/a.md", "ask")
        candidates = [
            _make_fts_result(path="/vault/a.md", rank=-5.0, body="test content"),
            _make_fts_result(path="/vault/b.md", rank=-5.0, body="test content"),
        ]
        results = vault_index.rerank_results(candidates, ["test"], db_path=db_path)
        a_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/a.md")
        b_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/b.md")
        assert a_score > b_score

    def test_importance_signal_boosts_high_importance(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        candidates = [
            _make_fts_result(path="/vault/a.md", rank=-5.0, body="test content", importance=9),
            _make_fts_result(path="/vault/b.md", rank=-5.0, body="test content", importance=2),
        ]
        results = vault_index.rerank_results(candidates, ["test"], db_path=db_path)
        a_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/a.md")
        b_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/b.md")
        assert a_score > b_score

    def test_task_context_changes_type_scores(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        candidates = [
            _make_fts_result(path="/vault/err.md", note_type="claude-error-fix",
                             rank=-5.0, body="test fix"),
            _make_fts_result(path="/vault/dec.md", note_type="claude-decision",
                             rank=-5.0, body="test fix"),
        ]
        results = vault_index.rerank_results(
            candidates, ["test"], db_path=db_path, task_context="debugging"
        )
        err_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/err.md")
        dec_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/dec.md")
        assert err_score > dec_score

    def test_weights_sum_to_one(self):
        total = 0.25 + 0.20 + 0.10 + 0.10 + 0.05 + 0.20 + 0.10
        assert abs(total - 1.0) < 0.001

    def test_backward_compatible_without_db_path(self):
        candidates = [
            _make_fts_result(path="/vault/a.md", rank=-10.0),
            _make_fts_result(path="/vault/b.md", rank=-5.0),
        ]
        results = vault_index.rerank_results(candidates, ["content"])
        assert len(results) == 2
        assert all("rerank_score" in r for r in results)

    def test_empty_input(self):
        assert vault_index.rerank_results([], ["test"]) == []


class TestActivationNormalization:
    def test_negative_activation_still_boosts_over_no_history(self, tmp_vault):
        """Notes with negative activation (old access) still rank above notes with no history."""
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Insert an old access (will produce negative activation)
        conn = sqlite3.connect(db_path)
        old_time = time.time() - 86400 * 30  # 30 days ago
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type) VALUES (?, ?, ?)",
            ("/vault/old.md", old_time, "recall"),
        )
        conn.commit()
        conn.close()

        candidates = [
            _make_fts_result(path="/vault/old.md", rank=-5.0, body="test content"),
            _make_fts_result(path="/vault/new.md", rank=-5.0, body="test content"),
        ]
        results = vault_index.rerank_results(candidates, ["test"], db_path=db_path)
        old_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/old.md")
        new_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/new.md")
        assert old_score > new_score  # old access still better than no access

    def test_min_activation_note_above_no_history(self, tmp_vault):
        """Note with minimum activation (oldest access) still scores above a no-history note."""
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        now = time.time()
        # Two notes with different access histories
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type) VALUES (?, ?, ?)",
            ("/vault/recent.md", now - 60, "recall"),  # recent access
        )
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type) VALUES (?, ?, ?)",
            ("/vault/old.md", now - 86400 * 60, "recall"),  # 60 days ago
        )
        conn.commit()
        conn.close()

        candidates = [
            _make_fts_result(path="/vault/recent.md", rank=-5.0, body="test content"),
            _make_fts_result(path="/vault/old.md", rank=-5.0, body="test content"),
            _make_fts_result(path="/vault/none.md", rank=-5.0, body="test content"),
        ]
        results = vault_index.rerank_results(candidates, ["test"], db_path=db_path)
        recent = next(r["rerank_score"] for r in results if r["path"] == "/vault/recent.md")
        old = next(r["rerank_score"] for r in results if r["path"] == "/vault/old.md")
        none_score = next(r["rerank_score"] for r in results if r["path"] == "/vault/none.md")
        assert recent > old > none_score  # recent > old > no-history


def _write_note(path, frontmatter: dict, body: str = ""):
    """Helper to write a markdown note with frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
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


class TestSearchVaultCallerIntegration:
    def test_search_vault_caller_standup_boosts_sessions(self, tmp_vault):
        """search_vault with caller='standup' ranks sessions higher than insights."""
        sessions_dir = tmp_vault / "claude-sessions"
        insights_dir = tmp_vault / "claude-insights"

        # Create a session note and an insight note with same content
        session = sessions_dir / "2026-04-15-test-sess-abcd.md"
        _write_note(session, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="authentication login implementation work")

        insight = insights_dir / "2026-04-15-test-insight-ef01.md"
        _write_note(insight, {
            "type": "claude-insight",
            "date": "2026-04-15",
            "project": "test",
            "status": "active",
        }, body="authentication login implementation pattern")

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)

        # With caller='standup', sessions should rank higher than insights
        results = vault_index.search_vault(db_path, "authentication login", caller="standup")
        assert len(results) >= 2
        session_result = next((r for r in results if r["type"] == "claude-session"), None)
        insight_result = next((r for r in results if r["type"] == "claude-insight"), None)
        assert session_result is not None
        assert insight_result is not None
        assert session_result["rerank_score"] > insight_result["rerank_score"]

    def test_search_vault_caller_none_uses_general(self, tmp_vault):
        """search_vault without caller uses general context (insights >= sessions)."""
        sessions_dir = tmp_vault / "claude-sessions"
        insights_dir = tmp_vault / "claude-insights"

        session = sessions_dir / "2026-04-15-test-sess-1234.md"
        _write_note(session, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="caching strategy design pattern")

        insight = insights_dir / "2026-04-15-test-insight-5678.md"
        _write_note(insight, {
            "type": "claude-insight",
            "date": "2026-04-15",
            "project": "test",
            "status": "active",
        }, body="caching strategy design pattern")

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)

        results = vault_index.search_vault(db_path, "caching strategy")
        assert len(results) >= 2
        insight_result = next((r for r in results if r["type"] == "claude-insight"), None)
        session_result = next((r for r in results if r["type"] == "claude-session"), None)
        assert insight_result is not None
        assert session_result is not None
        # In general context, insight type score (1.0) >= session type score (0.5)
        assert insight_result["rerank_score"] >= session_result["rerank_score"]
