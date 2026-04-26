"""Pure predicate for the /compress Step 3.5 high-confidence match filter.

Kept in its own module so the tuning harness (scripts/tune_compress_rank_gap.py)
and pytest (tests/test_compress_rank_gap.py) can import it directly rather
than shelling out through the SKILL.md embedded block.

MIN_RANK_DELTA is empirically tuned against scripts/compress_rank_gap_corpus.json.
Hard constraint: must be < 4.75 so the issue #45 repro case (top -29.46,
runner-up -24.71) resolves to match: True. The full tuning protocol lives
in the external spec-docs repository at
superpowers/specs/2026-04-23-compress-rank-gap-delta-guard-design.md
(github.com/abhattacherjee/spec-docs).
"""

MIN_RANK_STRENGTH = -5.0  # top result's FTS5 rank must be <= this (stronger = more negative)
MIN_RANK_DELTA = 0.25     # tuned against scripts/compress_rank_gap_corpus.json on 2026-04-23


def is_high_confidence_match(results, min_strength=None, min_delta=None):
    """Return True if the top search result is a high-confidence match.

    Arguments:
        results: list of dicts with a "rank" field. Callers must pass the
            list sorted most-negative first (as SKILL.md Step 3.5 does).
        min_strength: optional override for MIN_RANK_STRENGTH.
        min_delta: optional override for MIN_RANK_DELTA.

    Returns:
        bool. True only if (a) results is non-empty, (b) top.rank passes
        the absolute-strength gate, and (c) either there is no runner-up
        or the |top.rank| - |runner_up.rank| gap exceeds the delta gate.
    """
    if min_strength is None:
        min_strength = MIN_RANK_STRENGTH
    if min_delta is None:
        min_delta = MIN_RANK_DELTA

    if not results:
        return False
    top = results[0]
    if top["rank"] > min_strength:
        return False
    if len(results) < 2:
        return True
    return (abs(top["rank"]) - abs(results[1]["rank"])) > min_delta
