"""Tests for surprise detection (Phase 2)."""

import pytest

import vault_index


class TestDetectSurprise:
    def test_negated_shared_term_scores_above_threshold(self):
        text = "retrieval scoring is not reliable at 10k notes. activation does not help."
        centroid = {"retrieval": 1.0, "scoring": 1.0, "activation": 1.0}
        note_vec = {"retrieval": 1.0, "scoring": 1.0, "activation": 1.0}
        score = vault_index.detect_surprise(text, note_vec, centroid)
        assert score > 0.5

    def test_agreement_text_scores_zero(self):
        text = "retrieval scoring is reliable. activation is useful."
        centroid = {"retrieval": 1.0, "scoring": 1.0, "activation": 1.0}
        note_vec = {"retrieval": 1.0, "scoring": 1.0, "activation": 1.0}
        score = vault_index.detect_surprise(text, note_vec, centroid)
        assert score == 0.0

    def test_no_shared_terms_returns_zero(self):
        text = "retrieval scoring is not reliable"
        centroid = {"pasta": 1.0, "garlic": 1.0}
        note_vec = {"retrieval": 1.0, "scoring": 1.0}
        score = vault_index.detect_surprise(text, note_vec, centroid)
        assert score == 0.0

    def test_negation_outside_window_does_not_count(self):
        words = ["not"] + ["filler"] * 30 + ["retrieval"]
        text = " ".join(words)
        score = vault_index.detect_surprise(
            text, {"retrieval": 1.0}, {"retrieval": 1.0},
        )
        assert score == 0.0

    def test_score_is_clamped_to_unit_interval(self):
        text = "retrieval never scoring never activation never importance never"
        centroid = {
            "retrieval": 1.0, "scoring": 1.0, "activation": 1.0, "importance": 1.0,
        }
        note_vec = dict(centroid)
        score = vault_index.detect_surprise(text, note_vec, centroid)
        assert 0.0 <= score <= 1.0

    def test_expanded_contractions_registered(self):
        """won't/isn't/wasn't/didn't/couldn't/shouldn't must all register."""
        # Each phrase puts a distinct contraction within window of "retrieval"
        for contraction in ("won\u2019t", "isn't", "wasn't", "didn't",
                            "couldn't", "shouldn't", "wouldn't", "doesn't"):
            text = f"{contraction} trust retrieval scoring here"
            score = vault_index.detect_surprise(
                text, {"retrieval": 1.0}, {"retrieval": 1.0},
            )
            assert score > 0, (
                f"contraction {contraction!r} did not register as a "
                "negation — _NEGATION_TERMS may be missing the bare form"
            )

    def test_contractions_match_negation_terms(self):
        """Apostrophe'd negations ("don't"/"can't") must match the negation set.

        Regression: _TOKEN_RE = [a-z0-9]+ strips apostrophes, so "don't"
        tokenized to "don" and "t" — neither of which appeared in
        _NEGATION_TERMS. Apostrophed negations in note text were silently
        ignored by the surprise score. detect_surprise now normalizes
        apostrophes (including smart quotes) out before tokenization.
        """
        # Straight apostrophe
        text_straight = "don't trust retrieval scoring here"
        score_straight = vault_index.detect_surprise(
            text_straight, {"retrieval": 1.0}, {"retrieval": 1.0},
        )
        assert score_straight > 0, (
            "straight-apostrophe negation 'don't' did not register — "
            "apostrophe normalization missing"
        )

        # Smart quote (U+2019) — common from copy/pasted prose
        text_smart = "can\u2019t trust retrieval scoring here"
        score_smart = vault_index.detect_surprise(
            text_smart, {"retrieval": 1.0}, {"retrieval": 1.0},
        )
        assert score_smart > 0, (
            "smart-apostrophe negation 'can\u2019t' did not register — "
            "smart-quote normalization missing"
        )
