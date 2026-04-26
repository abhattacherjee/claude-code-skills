"""Tests for hooks/compress_guard.py — /compress Step 3.5 rank-gap predicate.

Covers boundary cases for `is_high_confidence_match()`, the pure predicate
extracted from /compress SKILL.md Step 3.5. The helper is imported
directly — no FTS5 fixture needed since the predicate takes a pre-sorted
results list.
"""

from compress_guard import (
    MIN_RANK_DELTA,
    MIN_RANK_STRENGTH,
    is_high_confidence_match,
)


def test_empty_results_rejects():
    assert is_high_confidence_match([]) is False


def test_equal_ranks_rejects():
    """Delta = 0 when top and runner-up have identical ranks.

    FTS5 can produce identical rank values for near-identical notes. The
    strict '>' delta gate rejects (0 is never > any positive MIN_RANK_DELTA),
    so the guard correctly asks the user to choose rather than auto-picking.
    """
    results = [{"rank": -10.0}, {"rank": -10.0}]
    assert is_high_confidence_match(results) is False


def test_single_result_matches_when_rank_strong():
    # rank -10 is stronger than min_strength -5.0
    assert is_high_confidence_match([{"rank": -10.0}]) is True


def test_single_result_rejects_when_rank_weak():
    # rank -3 is weaker than min_strength -5.0
    assert is_high_confidence_match([{"rank": -3.0}]) is False


def test_delta_above_threshold_matches():
    # delta = |−29| − |−20| = 9, above default MIN_RANK_DELTA
    results = [{"rank": -29.0}, {"rank": -20.0}]
    assert is_high_confidence_match(results) is True


def test_delta_below_threshold_rejects():
    # delta ≈ 0.1 (|-29| - |-28.9| = 0.1000...142 due to IEEE 754);
    # below the current THRESHOLD_GRID minimum of 0.25, so this case
    # rejects at every grid-selectable MIN_RANK_DELTA.
    results = [{"rank": -29.0}, {"rank": -28.9}]
    assert is_high_confidence_match(results) is False


def test_issue_45_repro_case():
    """Executable form of the issue #45 bug definition.

    Real ranks from the vault: top -29.46, runner-up -24.71, delta 4.75.
    Must resolve True under the shipped MIN_RANK_DELTA — a failing
    assertion here means the fix did not land. The shipped constant
    must be strictly less than 4.75.
    """
    results = [{"rank": -29.46}, {"rank": -24.71}]
    assert is_high_confidence_match(results) is True


def test_weak_top_rank_rejects():
    # List is sorted most-negative first (predicate's documented contract):
    # -4.0 is the "top" at index 0, -3.0 is the runner-up at index 1. Top
    # rank -4 still fails the strength gate (-4 > -5). The strength gate
    # fires before the delta gate is evaluated — no strong #2 is needed
    # to prove the point.
    results = [{"rank": -4.0}, {"rank": -3.0}]
    assert is_high_confidence_match(results) is False


def test_delta_at_threshold_boundary_rejects():
    """Strict > comparison: delta exactly at threshold must reject.

    Predicate uses `delta > min_delta`, not `>=`. This test locks that
    semantic so a future tuning change to a different MIN_RANK_DELTA
    value still correctly rejects the at-threshold case.
    Guards against an off-by-one drift toward `>=`.
    """
    # delta = |−29| − |−28.75| = 0.25, exactly equals default MIN_RANK_DELTA (0.25) → reject.
    # Input values are multiples of 0.25, so they're exact binary fractions (no IEEE 754
    # rounding); this makes the at-threshold equality check reliable. Future boundary tests
    # should pick similarly-exact inputs rather than (say) 0.1, which is not exactly representable.
    results = [{"rank": -29.0}, {"rank": -28.75}]
    assert is_high_confidence_match(results) is False
    # With a custom min_delta=0.15, same input has delta 0.25 > 0.15 → accept
    assert is_high_confidence_match(results, min_delta=0.15) is True


def test_custom_thresholds_respected():
    # Sub-test 1: strength gate only (single result, delta gate bypassed)
    results_single = [{"rank": -8.0}]
    assert is_high_confidence_match(results_single) is True  # -8 <= default -5.0
    assert (
        is_high_confidence_match(results_single, min_strength=-10.0) is False
    )  # -8 > -10 fails custom strength gate

    # Sub-test 2: delta gate (two results; strength gate passes for both calls)
    results_pair = [{"rank": -8.0}, {"rank": -7.9}]
    assert is_high_confidence_match(results_pair) is False  # delta 0.1 below default 0.25
    assert (
        is_high_confidence_match(results_pair, min_delta=0.05) is True
    )  # delta 0.1 above custom min_delta=0.05


def test_constants_are_exposed():
    # Import-level contract: callers can reference the defaults.
    assert isinstance(MIN_RANK_STRENGTH, float)
    assert isinstance(MIN_RANK_DELTA, float)
    assert MIN_RANK_STRENGTH <= 0.0
    assert MIN_RANK_DELTA > 0.0
    # Hard constraint from issue #45 — fix is not complete without this.
    assert MIN_RANK_DELTA < 4.75
