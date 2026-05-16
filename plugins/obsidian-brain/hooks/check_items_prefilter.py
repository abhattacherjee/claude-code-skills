"""L2 pre-filter for /check-items Stage 4.

Deterministic triage that classifies items with no plausible completion
evidence as ACTIVE/STALE without dispatching a claude -p sub-agent.
Python stdlib only. Per spec docs/superpowers/specs/2026-05-15-check-items-call-reduction-design.md.
"""
from __future__ import annotations

import os
import re
import time

STOPWORDS = frozenset({
    "the", "and", "or", "for", "of", "to", "in", "is", "a", "an",
    "that", "this", "with", "on", "by", "it", "as", "be", "are",
})

COMPLETION_SIGNAL_TOKENS = frozenset({
    "done", "shipped", "merged", "closed", "fixed", "resolved",
    "released", "deprecated", "removed", "reverted", "completed",
})

_COMPLETION_SIGNAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in COMPLETION_SIGNAL_TOKENS) + r")\b",
    re.IGNORECASE,
)

REF_PATTERN = re.compile(r'(?<!\w)#\d+\b|\b[0-9a-f]{7,40}\b')

_WORD_RE = re.compile(r'\w+')


def _content_tokens(text: str) -> list[str]:
    """Extract content-bearing tokens from text. Drops stopwords and tokens shorter than 3 chars."""
    if not text:
        return []
    return [t for t in _WORD_RE.findall(text)
            if t.lower() not in STOPWORDS and len(t) > 2]


# Length threshold for "distinctive" tokens in Rule 2 of has_classifiable_evidence.
# Tokens shorter than this need either snake_case or interior mixed-case to qualify
# as a distinctive Rule-2 signal. Tuned empirically against PR #173's reference
# payload — see docs/superpowers/specs/2026-05-16-l2-prefilter-completion-signal-design.md.
_DISTINCTIVE_MIN_LEN = 8


def _is_distinctive(token: str) -> bool:
    """Return True if `token` is specific enough to be a meaningful Rule-2 signal.

    A distinctive token is one of:
      - Contains '_' (snake_case identifiers like `last_session_anchor`).
      - Has length >= `_DISTINCTIVE_MIN_LEN` (long enough to be a domain term).
      - Has interior mixed-case (CamelCase like `resolveAnchor`, `RangeAnchors`)
        — sentence-start Title-case like `Add`, `Fix`, `Run` is NOT distinctive,
        which is why mixed-case checks the substring `token[1:]` rather than
        the whole token.

    Generic short lowercase words ('now', 'add', 'fix', 'chip', 'session')
    are NOT distinctive — they overlap accidentally across unrelated shipped
    features in an active project's completion corpus.
    """
    if not token:
        return False
    if "_" in token:
        return True
    if len(token) >= _DISTINCTIVE_MIN_LEN:
        return True
    # Mixed-case must be interior (e.g. CamelCase `resolveAnchor`, `RangeAnchors`)
    # — sentence-start Title-case like `Add`, `Fix`, `Run` is a false positive.
    has_interior_upper = any(c.isupper() for c in token[1:])
    has_lower = any(c.islower() for c in token)
    return has_interior_upper and has_lower


def _has_nearby_completion_signal(haystack: str, content_tokens: list[str],
                                  window: int = 120) -> bool:
    """Return True if any completion-signal token appears within `window` chars
    of any content-token hit in `haystack`.

    Both haystack and tokens are matched case-insensitively.
    Completion-signal matching uses word boundaries (`_COMPLETION_SIGNAL_RE`)
    to avoid false positives from substrings like `unmerged`, `enclosed`,
    `redone`, `undone` that contain signal substrings but are not signals.
    """
    if not haystack or not content_tokens:
        return False
    h = haystack.lower()
    for tok in content_tokens:
        tok_l = tok.lower()
        if not tok_l:
            continue
        idx = 0
        while True:
            i = h.find(tok_l, idx)
            if i == -1:
                break
            lo = max(0, i - window)
            hi = min(len(h), i + len(tok_l) + window)
            slice_ = h[lo:hi]
            if _COMPLETION_SIGNAL_RE.search(slice_):
                return True
            idx = i + 1
    return False


def has_classifiable_evidence(group: dict, evidence: dict) -> bool:
    """Return True if the group has plausible completion evidence.

    Zone-aware rules (first match wins):
      1. Ref shortcut: REF_PATTERN matches #N or commit-sha in canonical_text.
      2. Completion-zone overlap: any content-token from canonical_text
         appears in (merged_prs_text + closed_issues_text + releases_text +
         changelog_excerpt). These buckets pre-encode completion.
      3. Activity-zone proximity: a content-token appears in
         (commits_text + fts_mentions_text) AND a COMPLETION_SIGNAL_TOKENS
         entry occurs within the proximity window of that hit (see
         `_has_nearby_completion_signal`, default 120 chars).

    Otherwise returns False; the caller produces a synthetic STALE/ACTIVE
    classification via synthetic_classification().

    Args:
        group: Group dict carrying canonical text under 'representative' or
               'canonical_text'. If neither is present (or both empty),
               returns False.
        evidence: Dict with optional keys: commits_text, merged_prs_text,
                  closed_issues_text, releases_text, changelog_excerpt,
                  fts_mentions_text. Any missing key is treated as empty.

    Returns:
        True if the sub-agent should classify this item; False if L2 can
        synthesize a result deterministically.
    """
    canonical_text = group.get("representative") or group.get("canonical_text", "")

    # Rule 1: explicit issue/PR/commit-sha reference
    if REF_PATTERN.search(canonical_text):
        return True

    tokens = _content_tokens(canonical_text)
    if not tokens:
        return False

    # Rule 2: completion-zone overlap (buckets pre-encode completion).
    # Require a DISTINCTIVE token match — generic English content-tokens
    # (`now`, `add`, `fix`) overlap accidentally across unrelated shipped
    # features in an active project's completion corpus.
    completion_haystack = "\n".join([
        evidence.get("merged_prs_text") or "",
        evidence.get("closed_issues_text") or "",
        evidence.get("releases_text") or "",
        evidence.get("changelog_excerpt") or "",
    ]).lower()
    distinctive_tokens = [t for t in tokens if _is_distinctive(t)]
    if any(t.lower() in completion_haystack for t in distinctive_tokens):
        return True

    # Rule 3: activity-zone proximity (requires completion-signal verb nearby)
    activity_haystack = "\n".join([
        evidence.get("commits_text") or "",
        evidence.get("fts_mentions_text") or "",
    ])
    return _has_nearby_completion_signal(activity_haystack, tokens)


_STALE_THRESHOLD_DAYS = 90
_STALE_THRESHOLD_SECS = _STALE_THRESHOLD_DAYS * 86_400


def synthetic_classification(group: dict, now: float | None = None) -> dict:
    """Produce a synthetic classification record for a group with no evidence.

    Decision matrix (per spec § L2 Decision matrix):
    - Item age > 90 days since oldest (smallest) member mtime → STALE / LOW
    - Item age <= 90 days                                     → ACTIVE / LOW

    Age is derived from the oldest (smallest) mtime across the group's
    'instances' list. If mtime is 0 or missing, defaults to 0 (epoch),
    which yields an age larger than any threshold → STALE.

    The returned record shape matches _validate_classifier_payload():
        group_id, classification, confidence, canonical_text,
        evidence_citation, action_required.
    Plus the L2-specific marker: prefiltered=True.
    L2 synthetic records are NOT written to the L1 cache.

    Args:
        group: Group dict with 'group_id', 'representative' (canonical text),
               and 'instances' list. Each instance may carry 'mtime' (float,
               seconds since epoch; threaded from member dicts in classify_groups_with_agent).
        now: Current time as float (seconds since epoch). Defaults to time.time().
             Injectable for deterministic tests.

    Returns:
        Classification dict compatible with the classifier output schema.
    """
    if now is None:
        now = time.time()

    instances = group.get("instances", [])
    mtimes = [float(inst.get("mtime", 0)) for inst in instances]
    earliest_mtime = min(mtimes) if mtimes else 0.0

    age_secs = now - earliest_mtime
    classification = "STALE" if age_secs > _STALE_THRESHOLD_SECS else "ACTIVE"

    canonical_text = group.get("representative") or group.get("canonical_text", "")

    return {
        "group_id": group.get("group_id"),
        "classification": classification,
        "confidence": "LOW",
        "canonical_text": canonical_text,
        "evidence_citation": None,
        "action_required": None,
        "prefiltered": True,
    }


def is_prefilter_enabled() -> bool:
    """Return True unless CHECK_ITEMS_PREFILTER=off (case-insensitive).

    Default: enabled. Set CHECK_ITEMS_PREFILTER=off to skip L2 and route
    all L1-miss items directly to the sub-agent (useful for A/B comparison
    and debugging). L1 cache is unaffected by this flag.
    """
    val = os.environ.get("CHECK_ITEMS_PREFILTER", "on")
    return val.strip().lower() != "off"
