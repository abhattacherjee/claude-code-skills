"""Schema + incremental assignment tests for the Phase 2 theme engine."""

import json
import sqlite3

import pytest

import vault_index


@pytest.fixture
def db_path(tmp_vault):
    p = str(tmp_vault / "test.db")
    vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=p)
    return p


class TestPhase2Schema:
    def test_themes_table_exists(self, db_path):
        conn = sqlite3.connect(db_path)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "themes" in tables
        assert "theme_members" in tables
        assert "term_df" in tables

    def test_themes_columns(self, db_path):
        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(themes)").fetchall()}
        conn.close()
        assert cols == {
            "id", "name", "summary", "centroid", "note_count",
            "activation", "created_date", "updated_date", "project",
        }

    def test_theme_members_columns(self, db_path):
        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(theme_members)"
        ).fetchall()}
        conn.close()
        assert cols == {
            "theme_id", "note_path", "similarity", "surprise", "added_date",
        }

    def test_notes_has_tfidf_vector_column(self, db_path):
        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
        conn.close()
        assert "tfidf_vector" in cols

    def test_tfidf_vector_migration_on_existing_db(self, tmp_vault):
        """A DB created without the new column must gain it via ensure_index()."""
        db_path = str(tmp_vault / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE notes ("
            "path TEXT PRIMARY KEY, type TEXT NOT NULL, date TEXT, "
            "project TEXT, title TEXT, source_session TEXT, "
            "source_note TEXT, tags TEXT, status TEXT, mtime REAL NOT NULL, "
            "size INTEGER, body TEXT DEFAULT '', importance INTEGER DEFAULT 5)"
        )
        conn.commit()
        conn.close()

        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
        conn.close()
        assert "tfidf_vector" in cols

    def test_term_df_columns(self, db_path):
        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(term_df)").fetchall()}
        conn.close()
        assert cols == {"term", "df"}


def _indexed_note(tmp_vault, slug, title, body, project="proj"):
    """Write a note and return its path (caller re-indexes)."""
    path = tmp_vault / "claude-sessions" / f"2026-04-16-{project}-{slug}.md"
    path.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-16\n"
        f"project: {project}\n"
        f"title: {title}\n"
        "tags:\n  - claude/session\n"
        "status: summarized\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return str(path)


class TestAssignToTheme:
    def test_first_note_leaves_no_theme(self, tmp_vault):
        """With no existing themes, assignment is a no-op returning None."""
        path = _indexed_note(tmp_vault, "a", "retrieval scoring",
                             "retrieval scoring activation")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        result = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result is None

        conn = sqlite3.connect(db_path)
        themes = conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM theme_members").fetchone()[0]
        conn.close()
        assert themes == 0
        assert members == 0

    def test_similar_note_joins_existing_theme(self, tmp_vault):
        path_a = _indexed_note(tmp_vault, "a", "retrieval scoring",
                               "retrieval scoring activation importance")
        path_b = _indexed_note(tmp_vault, "b", "activation importance",
                               "retrieval scoring activation importance")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec_a = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_a,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", json.dumps(vec_a), 1,
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, path_a, "2026-04-16"),
        )
        conn.commit()
        conn.close()

        result = vault_index.assign_to_theme(db_path, path_b, project="proj")
        assert result is not None
        assert result["theme_id"] == theme_id
        assert result["similarity"] > 0.3

        conn = sqlite3.connect(db_path)
        members = conn.execute(
            "SELECT note_path FROM theme_members WHERE theme_id = ?", (theme_id,)
        ).fetchall()
        note_count = conn.execute(
            "SELECT note_count FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()[0]
        conn.close()
        assert {m[0] for m in members} == {path_a, path_b}
        assert note_count == 2

    def test_low_similarity_stays_unassigned(self, tmp_vault):
        path_theme = _indexed_note(tmp_vault, "theme", "retrieval scoring",
                                   "retrieval scoring activation")
        path_stranger = _indexed_note(tmp_vault, "stranger", "garlic pasta",
                                      "garlic pasta recipe italian dinner")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_theme,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", json.dumps(vec), 1,
             "2026-04-16", "2026-04-16", "proj"),
        )
        conn.commit()
        conn.close()

        result = vault_index.assign_to_theme(db_path, path_stranger, project="proj")
        assert result is None

    def test_centroid_update_is_running_average(self, tmp_vault):
        """After a second note joins, centroid term weight is the mean of the two vectors."""
        path_a = _indexed_note(tmp_vault, "a", "retrieval", "retrieval retrieval")
        path_b = _indexed_note(tmp_vault, "b", "retrieval scoring",
                               "retrieval scoring")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec_a = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_a,)
        ).fetchone()[0])
        vec_b = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_b,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", json.dumps(vec_a), 1,
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, path_a, "2026-04-16"),
        )
        conn.commit()
        conn.close()

        vault_index.assign_to_theme(db_path, path_b, project="proj")

        conn = sqlite3.connect(db_path)
        centroid = json.loads(conn.execute(
            "SELECT centroid FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()[0])
        conn.close()

        for term, a_val in vec_a.items():
            b_val = vec_b.get(term, 0.0)
            expected = (a_val + b_val) / 2
            assert centroid.get(term) == pytest.approx(expected, rel=1e-6)

    def test_reassignment_preserves_surprise_and_added_date(self, tmp_vault):
        """Assigning a note twice must not reset surprise or added_date."""
        path = _indexed_note(tmp_vault, "reassign", "retrieval scoring",
                             "retrieval scoring activation importance")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", json.dumps(vec), 0,
             "2026-04-16", "2026-04-16", "proj"),
        )
        conn.commit()
        conn.close()

        # First assignment: joins the theme, surprise defaults to 0.0.
        result1 = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result1 is not None

        # Simulate Batch F writing a surprise score and a custom added_date.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE theme_members SET surprise = 0.7, added_date = '2026-04-10' "
            "WHERE note_path = ?", (path,),
        )
        conn.commit()
        conn.close()

        # Second assignment: similarity may update, surprise + added_date must NOT reset.
        result2 = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result2 is not None

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT similarity, surprise, added_date FROM theme_members "
            "WHERE note_path = ?", (path,),
        ).fetchone()
        conn.close()
        assert row is not None
        # similarity should reflect the fresh cosine
        assert row[0] == pytest.approx(result2["similarity"], rel=1e-6)
        assert row[1] == pytest.approx(0.7, rel=1e-6), (
            f"surprise reset to {row[1]!r} — INSERT OR REPLACE bug regressed"
        )
        assert row[2] == "2026-04-10", (
            f"added_date overwritten to {row[2]!r} — should be preserved"
        )

    def test_reassignment_does_not_double_count_or_drift_centroid(self, tmp_vault):
        """Reassigning an already-member note must leave note_count and
        centroid unchanged.

        Regression: assign_to_theme always did +1 on note_count and folded
        the note's vector back into the running-average centroid even when
        the theme_members upsert was a no-op update. Calling assign twice
        on the same note would bump count to 3 (from 1→2→3) and drift the
        centroid toward the note's vector on every call.
        """
        path = _indexed_note(tmp_vault, "dupe", "retrieval scoring",
                             "retrieval scoring activation importance")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        # Seed a theme with a DIFFERENT centroid than the note, so that if
        # folding happens we can detect drift by comparing centroid values.
        seed_centroid = {t: 0.5 for t in vec}  # same terms, uniform weights
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", json.dumps(seed_centroid), 3,
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.commit()
        conn.close()

        # First assignment: legitimately new member → count should go 3→4.
        result1 = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result1 is not None

        conn = sqlite3.connect(db_path)
        count_after_1, centroid_after_1_json = conn.execute(
            "SELECT note_count, centroid FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        conn.close()
        assert count_after_1 == 4, f"first assign should bump 3→4, got {count_after_1}"
        centroid_after_1 = json.loads(centroid_after_1_json)

        # Second assignment: same note, already a member → count+centroid must NOT change.
        result2 = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result2 is not None

        conn = sqlite3.connect(db_path)
        count_after_2, centroid_after_2_json = conn.execute(
            "SELECT note_count, centroid FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        conn.close()
        assert count_after_2 == 4, (
            f"reassignment bumped note_count to {count_after_2} — "
            "already-member path should skip count update"
        )
        centroid_after_2 = json.loads(centroid_after_2_json)
        for term, v in centroid_after_1.items():
            assert centroid_after_2.get(term) == pytest.approx(v, rel=1e-9), (
                f"centroid drifted on reassignment (term={term!r}: "
                f"{v} → {centroid_after_2.get(term)})"
            )
        assert set(centroid_after_2) == set(centroid_after_1), (
            "centroid term set changed on reassignment"
        )

    def test_cross_project_theme_candidate(self, tmp_vault):
        """A theme with project=NULL should be a valid candidate for any project."""
        path = _indexed_note(tmp_vault, "cross", "retrieval scoring",
                             "retrieval scoring activation importance")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        # Cross-project theme: project IS NULL
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            ("Global Retrieval", "", json.dumps(vec), 1,
             "2026-04-16", "2026-04-16"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, "/some/other/path.md", "2026-04-16"),
        )
        conn.commit()
        conn.close()

        # Call with a specific project — the NULL-project theme should still be a candidate.
        result = vault_index.assign_to_theme(db_path, path, project="proj")
        assert result is not None, "Cross-project theme should have been matched"
        assert result["theme_id"] == theme_id
        assert result["similarity"] > 0.3

    def test_global_recall_considers_scoped_themes(self, tmp_vault):
        """project=None (global recall) must match scoped themes too.

        Regression: `project = ? OR project IS NULL` with project=None
        binds to `project = NULL` which is false in SQL, so only NULL-
        project themes were ever candidates. Scoped themes were invisible
        to global recall even when the note was semantically a perfect fit.
        """
        path = _indexed_note(tmp_vault, "global", "retrieval scoring",
                             "retrieval scoring activation importance")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        # A project-scoped theme (NOT null) that matches the note perfectly.
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Scoped Retrieval", "", json.dumps(vec), 1,
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, "/some/other/path.md", "2026-04-16"),
        )
        conn.commit()
        conn.close()

        # project=None should still see the scoped theme.
        result = vault_index.assign_to_theme(db_path, path, project=None)
        assert result is not None, (
            "Global recall (project=None) failed to match a scoped theme — "
            "SQL filter treated None as NULL (match nothing) instead of wildcard"
        )
        assert result["theme_id"] == theme_id


class TestDeleteNoteMaintainsThemeState:
    """Deleting a note must keep themes.note_count + centroid consistent."""

    def test_delete_decrements_count_and_unfolds_centroid(self, tmp_vault):
        """Deleting one of N members must set count=N-1 and reverse the fold."""
        path_a = _indexed_note(tmp_vault, "a", "retrieval scoring",
                               "retrieval scoring activation importance")
        path_b = _indexed_note(tmp_vault, "b", "more retrieval",
                               "retrieval scoring activation importance proximity")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec_a = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_a,)
        ).fetchone()[0])
        vec_b = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path_b,)
        ).fetchone()[0])
        # Hand-build the running-average centroid for a theme containing A+B.
        all_terms = set(vec_a) | set(vec_b)
        centroid = {t: (vec_a.get(t, 0.0) + vec_b.get(t, 0.0)) / 2 for t in all_terms}
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, 2, ?, ?, ?)",
            ("Retrieval", "", json.dumps(centroid),
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.executemany(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            [(theme_id, path_a, "2026-04-16"),
             (theme_id, path_b, "2026-04-16")],
        )
        conn.commit()
        conn.close()

        # Delete path_a via internal helper (same path as _sync's deletion branch).
        from vault_index import _delete_note, _connect
        conn = _connect(db_path)
        _delete_note(conn, path_a)
        conn.commit()

        # note_count must drop to 1, centroid must equal vec_b (only remaining member).
        row = conn.execute(
            "SELECT note_count, centroid FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        assert row is not None, "theme must still exist with 1 member"
        assert row["note_count"] == 1, (
            f"count did not decrement: expected 1, got {row['note_count']}"
        )
        remaining_centroid = json.loads(row["centroid"])
        for term in vec_b:
            assert remaining_centroid.get(term) == pytest.approx(vec_b[term], rel=1e-6), (
                f"centroid term {term!r} did not unfold to vec_b value"
            )

        # Membership row for path_a gone; path_b intact.
        members = {r[0] for r in conn.execute(
            "SELECT note_path FROM theme_members WHERE theme_id = ?", (theme_id,)
        ).fetchall()}
        conn.close()
        assert members == {path_b}

    def test_delete_last_member_cascades_theme_members(self, tmp_vault):
        """Dropping a theme must also clear any stale theme_members rows.

        Defense-in-depth: if an earlier invariant violation left two rows
        under a theme that claimed count=1, the last-member branch must
        not orphan the extra rows when it drops the themes row.
        """
        path = _indexed_note(tmp_vault, "invariant", "retrieval scoring",
                             "retrieval scoring activation")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        # Seed a theme claiming note_count=1 but with TWO member rows
        # (one for the note we'll delete, one stray). Simulates an
        # earlier invariant violation the cascade must clean up.
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, 1, ?, ?, ?)",
            ("Invariant", "", json.dumps(vec),
             "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.executemany(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            [
                (theme_id, path, "2026-04-16"),
                (theme_id, "/nonexistent/stray.md", "2026-04-16"),
            ],
        )
        conn.commit()
        conn.close()

        from vault_index import _delete_note, _connect
        conn = _connect(db_path)
        _delete_note(conn, path)
        conn.commit()

        # Both the theme AND any stray theme_members for it must be gone.
        theme_row = conn.execute(
            "SELECT id FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        stray_members = conn.execute(
            "SELECT note_path FROM theme_members WHERE theme_id = ?", (theme_id,)
        ).fetchall()
        conn.close()
        assert theme_row is None
        assert stray_members == [], (
            f"stale theme_members rows left behind after theme drop: "
            f"{[r[0] for r in stray_members]!r}"
        )

    def test_delete_last_member_drops_theme(self, tmp_vault):
        """Deleting the sole member must drop the theme rather than leave count=0."""
        path = _indexed_note(tmp_vault, "solo", "retrieval scoring",
                             "retrieval scoring activation")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        vec = json.loads(conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (path,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, 1, ?, ?, ?)",
            ("Solo", "", json.dumps(vec), "2026-04-16", "2026-04-16", "proj"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, path, "2026-04-16"),
        )
        conn.commit()
        conn.close()

        from vault_index import _delete_note, _connect
        conn = _connect(db_path)
        _delete_note(conn, path)
        conn.commit()

        theme_row = conn.execute(
            "SELECT id FROM themes WHERE id = ?", (theme_id,)
        ).fetchone()
        member_row = conn.execute(
            "SELECT note_path FROM theme_members WHERE theme_id = ?", (theme_id,)
        ).fetchone()
        conn.close()
        assert theme_row is None, "theme with 0 members must be dropped"
        assert member_row is None


class TestUpgradeWiresThemes:
    def test_upgrade_triggers_theme_assignment(self, tmp_vault, mock_config):
        """After upgrade_note_with_summary(), the note must join a seeded matching theme."""
        import obsidian_utils

        # Seed an indexed note in the same project and build a theme around its vector
        seed_path = _indexed_note(
            tmp_vault, "seed", "retrieval scoring",
            "retrieval scoring activation importance proximity bm25",
            project="test-project",
        )
        target_path = tmp_vault / "claude-sessions" / "2026-04-16-test-project-newnote.md"
        target_path.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "session_id: new-session\n"
            "project: test-project\n"
            "duration_minutes: 10.0\n"
            "tags:\n  - claude/session\n"
            "status: auto-logged\n"
            "---\n\n"
            "# Session: test-project (develop)\n\n"
            "## Summary\n"
            "AI summary unavailable \u2014 raw extraction below.\n\n"
            "## Conversation (raw)\n"
            "**User:** retrieval scoring?\n"
            "**Assistant:** activation plus importance plus proximity plus bm25.\n",
            encoding="utf-8",
        )

        import vault_index
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions"], db_path=db_path,
        )

        # Seed a theme centroid around the seed note's TF-IDF vector
        conn = sqlite3.connect(db_path)
        seed_vec = conn.execute(
            "SELECT tfidf_vector FROM notes WHERE path = ?", (seed_path,)
        ).fetchone()[0]
        assert seed_vec, "Seed note should have a TF-IDF vector after indexing"
        conn.execute(
            "INSERT INTO themes (name, summary, centroid, note_count, "
            "created_date, updated_date, project) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Retrieval", "", seed_vec, 1,
             "2026-04-16", "2026-04-16", "test-project"),
        )
        theme_id = conn.execute("SELECT id FROM themes").fetchone()[0]
        conn.execute(
            "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
            "VALUES (?, ?, 1.0, ?)",
            (theme_id, seed_path, "2026-04-16"),
        )
        conn.commit()
        conn.close()

        # Point obsidian_utils at this test DB by monkey-patching _default_db_path.
        original_default = vault_index._default_db_path
        try:
            vault_index._default_db_path = lambda: db_path
            summary = (
                "## Summary\n"
                "Retrieval scoring activation importance.\n\n"
                "## Key Decisions\n- None noted.\n\n"
                "## Changes Made\n- None noted.\n\n"
                "## Errors Encountered\nNone.\n\n"
                "## Open Questions / Next Steps\nNone.\n\n"
                "IMPORTANCE: 7\n"
            )
            status = obsidian_utils.upgrade_note_with_summary(
                str(target_path), summary,
                str(tmp_vault), "claude-sessions", "test-project",
                source="test",
            )
        finally:
            vault_index._default_db_path = original_default

        assert not status.startswith("Failed:"), f"upgrade failed: {status}"

        conn = sqlite3.connect(db_path)
        members = {
            r[0] for r in conn.execute(
                "SELECT note_path FROM theme_members WHERE theme_id = ?",
                (theme_id,),
            ).fetchall()
        }
        conn.close()
        assert str(target_path) in members, (
            "upgrade_note_with_summary did not trigger theme assignment"
        )

    def test_upgrade_survives_missing_vault_index(self, tmp_vault, mock_config):
        """If the DB file is missing, upgrade must still succeed (theme pipeline is best-effort)."""
        import obsidian_utils
        import vault_index

        target_path = tmp_vault / "claude-sessions" / "2026-04-16-test-project-missing.md"
        target_path.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "session_id: missing-db-session\n"
            "project: test-project\n"
            "duration_minutes: 5.0\n"
            "tags:\n  - claude/session\n"
            "status: auto-logged\n"
            "---\n\n"
            "# Session: test-project\n\n"
            "## Summary\n"
            "AI summary unavailable \u2014 raw extraction below.\n\n"
            "## Conversation (raw)\n"
            "**User:** hi\n**Assistant:** hello\n",
            encoding="utf-8",
        )

        # Point the DB path at a file that doesn't exist.
        nonexistent = str(tmp_vault / "nonexistent.db")
        original_default = vault_index._default_db_path
        try:
            vault_index._default_db_path = lambda: nonexistent
            summary = (
                "## Summary\n"
                "Short session.\n\n"
                "## Key Decisions\n- None noted.\n\n"
                "## Changes Made\n- None noted.\n\n"
                "## Errors Encountered\nNone.\n\n"
                "## Open Questions / Next Steps\nNone.\n\n"
                "IMPORTANCE: 3\n"
            )
            status = obsidian_utils.upgrade_note_with_summary(
                str(target_path), summary,
                str(tmp_vault), "claude-sessions", "test-project",
                source="test",
            )
        finally:
            vault_index._default_db_path = original_default

        assert not status.startswith("Failed:"), (
            f"upgrade must succeed even when DB is missing, got: {status}"
        )

    def test_upgrade_skips_theme_assignment_when_index_note_returns_false(
        self, tmp_vault, mock_config
    ):
        """If index_note returns False (no exception), assign_to_theme must NOT run.

        Regression: previously the pipeline used try/except/else, so a non-
        raising False return from index_note would still fall through to
        assign_to_theme on a stale or missing tfidf_vector.
        """
        import obsidian_utils
        import vault_index

        target_path = tmp_vault / "claude-sessions" / "2026-04-16-test-project-idxfail.md"
        target_path.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "session_id: idxfail-session\n"
            "project: test-project\n"
            "duration_minutes: 5.0\n"
            "tags:\n  - claude/session\n"
            "status: auto-logged\n"
            "---\n\n"
            "# Session: test-project\n\n"
            "## Summary\n"
            "AI summary unavailable \u2014 raw extraction below.\n\n"
            "## Conversation (raw)\n"
            "**User:** retrieval?\n**Assistant:** scoring.\n",
            encoding="utf-8",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions"], db_path=db_path,
        )

        calls: dict[str, int] = {"index_note": 0, "assign_to_theme": 0}
        original_index = vault_index.index_note
        original_assign = vault_index.assign_to_theme
        original_default = vault_index._default_db_path

        def fake_index_note(_db, _path):
            calls["index_note"] += 1
            return False  # signal failure without raising

        def fake_assign_to_theme(*args, **kwargs):
            calls["assign_to_theme"] += 1
            return original_assign(*args, **kwargs)

        try:
            vault_index._default_db_path = lambda: db_path
            vault_index.index_note = fake_index_note
            vault_index.assign_to_theme = fake_assign_to_theme

            summary = (
                "## Summary\nRetrieval scoring.\n\n"
                "## Key Decisions\n- None noted.\n\n"
                "## Changes Made\n- None noted.\n\n"
                "## Errors Encountered\nNone.\n\n"
                "## Open Questions / Next Steps\nNone.\n\n"
                "IMPORTANCE: 5\n"
            )
            status = obsidian_utils.upgrade_note_with_summary(
                str(target_path), summary,
                str(tmp_vault), "claude-sessions", "test-project",
                source="test",
            )
        finally:
            vault_index._default_db_path = original_default
            vault_index.index_note = original_index
            vault_index.assign_to_theme = original_assign

        assert not status.startswith("Failed:"), (
            f"upgrade must succeed even when reindex fails, got: {status}"
        )
        assert calls["index_note"] == 1, "index_note should have been called exactly once"
        assert calls["assign_to_theme"] == 0, (
            "assign_to_theme ran despite index_note returning False — "
            "reindex-failure gating regressed"
        )
