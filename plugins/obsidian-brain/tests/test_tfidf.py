"""Tests for TF-IDF primitives: tokenization, vector math, cosine similarity."""

import json
import math
import sqlite3

import pytest

import vault_index


class TestTokenize:
    def test_strips_punctuation_and_lowercases(self):
        toks = vault_index._tokenize_for_tfidf("Hello, World! Python-3.9.")
        assert toks == ["hello", "world", "python"]

    def test_drops_stopwords(self):
        toks = vault_index._tokenize_for_tfidf("the quick brown fox is here")
        assert "the" not in toks
        assert "is" not in toks
        assert "here" not in toks
        assert "quick" in toks
        assert "brown" in toks

    def test_drops_single_char_tokens(self):
        toks = vault_index._tokenize_for_tfidf("a b c debugging")
        assert toks == ["debugging"]

    def test_empty_input(self):
        assert vault_index._tokenize_for_tfidf("") == []
        assert vault_index._tokenize_for_tfidf("the a an") == []

    def test_is_deterministic_and_preserves_order(self):
        text = "retrieval scoring retrieval activation scoring"
        toks = vault_index._tokenize_for_tfidf(text)
        assert toks == ["retrieval", "scoring", "retrieval", "activation", "scoring"]


class TestComputeTfidf:
    def test_sparse_vector_top_k(self):
        """TF×IDF keeps only the top_k heaviest terms."""
        tokens = ["retrieval"] * 5 + ["scoring"] * 3 + ["noise"] * 1
        df = {"retrieval": 1, "scoring": 2, "noise": 50}
        total_docs = 100
        vec = vault_index._compute_tfidf_vector(tokens, df, total_docs, top_k=2)
        assert set(vec.keys()) == {"retrieval", "scoring"}
        # retrieval has the lowest df → highest IDF AND highest TF → should win
        assert vec["retrieval"] > vec["scoring"] > 0

    def test_rare_term_outranks_common_term_at_equal_tf(self):
        tokens = ["obsidian", "python"]
        df = {"obsidian": 1, "python": 80}
        total_docs = 100
        vec = vault_index._compute_tfidf_vector(tokens, df, total_docs, top_k=2)
        assert vec["obsidian"] > vec["python"]

    def test_empty_tokens_returns_empty_dict(self):
        assert vault_index._compute_tfidf_vector([], {}, 10) == {}

    def test_missing_df_treats_term_as_brand_new(self):
        """A term absent from term_df should score as if df=0 (max IDF)."""
        tokens = ["mystery"]
        vec = vault_index._compute_tfidf_vector(tokens, {}, total_docs=100, top_k=5)
        assert "mystery" in vec
        assert vec["mystery"] > 0

    def test_single_term_single_doc_corpus(self):
        """Smoothing must keep IDF strictly positive even when df = total_docs."""
        tokens = ["alpha"]
        vec = vault_index._compute_tfidf_vector(
            tokens, {"alpha": 1}, total_docs=1, top_k=5,
        )
        assert vec["alpha"] > 0


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        v = {"a": 2.0, "b": 1.0}
        assert vault_index._cosine_similarity(v, dict(v)) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        v1 = {"a": 1.0, "b": 1.0}
        v2 = {"c": 1.0, "d": 1.0}
        assert vault_index._cosine_similarity(v1, v2) == 0.0

    def test_partial_overlap(self):
        v1 = {"a": 1.0, "b": 1.0}
        v2 = {"a": 1.0, "c": 1.0}
        assert vault_index._cosine_similarity(v1, v2) == pytest.approx(0.5)

    def test_empty_vector_returns_zero(self):
        assert vault_index._cosine_similarity({}, {"a": 1.0}) == 0.0
        assert vault_index._cosine_similarity({"a": 1.0}, {}) == 0.0
        assert vault_index._cosine_similarity({}, {}) == 0.0

    def test_order_independent(self):
        v1 = {"a": 3.0, "b": 4.0}
        v2 = {"b": 4.0, "a": 3.0}
        assert vault_index._cosine_similarity(v1, v2) == pytest.approx(1.0)


class TestUpdateTermDf:
    def test_insert_increments_fresh_terms(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = vault_index._connect(db_path)
        try:
            vault_index._update_term_df(
                conn, old_terms=set(), new_terms={"retrieval", "scoring"},
            )
            rows = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        finally:
            conn.close()
        assert rows == {"retrieval": 1, "scoring": 1}

    def test_replace_adjusts_df(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = vault_index._connect(db_path)
        try:
            vault_index._update_term_df(
                conn, old_terms=set(), new_terms={"alpha", "beta"},
            )
            vault_index._update_term_df(
                conn, old_terms={"alpha", "beta"}, new_terms={"alpha", "gamma"},
            )
            rows = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        finally:
            conn.close()
        assert rows.get("alpha") == 1
        assert rows.get("gamma") == 1
        assert rows.get("beta", 0) == 0

    def test_delete_purges_terms_when_df_hits_zero(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = vault_index._connect(db_path)
        try:
            vault_index._update_term_df(conn, old_terms=set(), new_terms={"solo"})
            vault_index._update_term_df(conn, old_terms={"solo"}, new_terms=set())
            rows = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        finally:
            conn.close()
        assert "solo" not in rows


class TestUpsertStoresTfidf:
    def test_first_insert_writes_tfidf_vector(self, tmp_vault):
        """After ensure_index indexes a real note, its row carries a non-empty vector."""
        (tmp_vault / "claude-sessions" / "2026-04-16-proj-alpha.md").write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            "title: Retrieval scoring research\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            "Retrieval scoring with activation and importance signals.\n",
            encoding="utf-8",
        )
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT tfidf_vector FROM notes").fetchone()
        conn.close()
        assert row is not None
        assert row[0], "tfidf_vector should be non-empty JSON"
        vec = json.loads(row[0])
        assert isinstance(vec, dict) and len(vec) > 0
        # Corpus-wide term 'retrieval' or 'scoring' should be present
        assert any("retriev" in k or "scor" in k for k in vec)

    def test_term_df_reflects_indexed_corpus(self, tmp_vault):
        for slug, body in [("a", "alpha beta"), ("b", "alpha gamma")]:
            (tmp_vault / "claude-sessions" / f"2026-04-16-proj-{slug}.md").write_text(
                "---\n"
                "type: claude-session\n"
                "date: 2026-04-16\n"
                "project: proj\n"
                f"title: Doc {slug}\n"
                "tags:\n  - claude/session\n"
                "status: summarized\n"
                "---\n"
                f"{body}\n",
                encoding="utf-8",
            )
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        df = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        conn.close()
        assert df.get("alpha") == 2
        assert df.get("beta") == 1
        assert df.get("gamma") == 1

    def test_delete_removes_from_term_df(self, tmp_vault):
        """Deleting a note decrements term_df and prunes zeros."""
        note = tmp_vault / "claude-sessions" / "2026-04-16-proj-solo.md"
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            "title: Solo\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            "uniquewordalpha uniquewordbeta\n",
            encoding="utf-8",
        )
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        # Sanity: terms exist
        conn = sqlite3.connect(db_path)
        df = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        assert df.get("uniquewordalpha") == 1
        conn.close()

        # Remove the file and re-sync (triggers _delete_note)
        note.unlink()
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        df_after = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        theme_rows = conn.execute(
            "SELECT COUNT(*) FROM theme_members WHERE note_path = ?",
            (str(note),),
        ).fetchone()[0]
        conn.close()
        assert "uniquewordalpha" not in df_after
        assert "uniquewordbeta" not in df_after
        assert theme_rows == 0

    def test_update_adjusts_term_df_symmetric_diff(self, tmp_vault):
        """Changing a note's body decrements removed terms and increments added ones."""
        note = tmp_vault / "claude-sessions" / "2026-04-16-proj-evo.md"
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            "title: Evolving\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            "uniquetermone uniquetermtwo\n",
            encoding="utf-8",
        )
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Capture the current mtime so we can bump it deterministically.
        # Several filesystems (e.g. HFS+, some network mounts) have 1s mtime
        # resolution; time.sleep(0.01) can leave mtime unchanged and cause
        # _sync() to skip the reindex, flaking the test.
        import os
        prev_mtime = note.stat().st_mtime
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            "title: Evolving\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            "uniquetermone uniquetermthree\n",
            encoding="utf-8",
        )
        # Force mtime forward by 2 seconds regardless of filesystem resolution.
        os.utime(note, (prev_mtime + 2, prev_mtime + 2))
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        df = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        conn.close()
        assert df.get("uniquetermone") == 1
        assert df.get("uniquetermthree") == 1
        assert df.get("uniquetermtwo", 0) == 0

    def test_reindex_does_not_drift_term_df(self, tmp_vault):
        """Reindexing the same note must not bump term_df for any term.

        Regression test for the top-K asymmetry bug where common-but-low-IDF
        terms (pushed out of the stored top-50 tfidf_vector) were
        incremented on every reindex because _prior_terms_for read the
        truncated vector instead of the full token set.
        """
        import os

        note = tmp_vault / "claude-sessions" / "2026-04-16-proj-reidx.md"
        # > 50 distinct tokens so the stored vector is meaningfully truncated.
        body_tokens = " ".join(f"ctoken{i:03d}" for i in range(80))
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            "title: Reindex probe\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            f"project retrieval activation {body_tokens}\n",
            encoding="utf-8",
        )
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        df_initial = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        conn.close()

        # Reindex the same note 3× via index_note (the hot path) with mtime bumps.
        for bump in range(1, 4):
            st = os.stat(note)
            os.utime(note, (st.st_mtime + bump * 5, st.st_mtime + bump * 5))
            ok = vault_index.index_note(db_path, str(note))
            assert ok, f"index_note returned False on reindex #{bump}"

        conn = sqlite3.connect(db_path)
        df_final = dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        conn.close()

        assert df_final == df_initial, (
            f"term_df drifted across reindexes; "
            f"{len(set(df_final) ^ set(df_initial))} term(s) added/removed, "
            f"{sum(1 for k in df_final if df_final[k] != df_initial.get(k))} changed"
        )
        # No term can exceed the total note count.
        for term, df in df_final.items():
            assert df <= 1, f"term {term!r} over-counted: df={df} > note_count=1"
