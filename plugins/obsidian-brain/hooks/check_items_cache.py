"""
Cache module for /check-items classifier results.

Per spec section Persistence and cache invalidation (lines 410-494).
Python stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_DIR: Path = Path.home() / ".claude" / "obsidian-brain"
CACHE_PATH: Path = CACHE_DIR / "check-items-classifications.json"

# The following constants are used by Tasks 4-7 (load_cache,
# save_cache, partition, update_cache).  They live here so the module is
# the single authoritative home for cache policy values.

SCHEMA_VERSION = 1

TTL_DONE = 86_400          # 24h
TTL_NEEDS_ACTION = 86_400  # 24h
TTL_STALE = 86_400         # 24h
TTL_ACTIVE = 604_800       # 7d


_MARKDOWN_RE = re.compile(r"[*_`~\[\]()#>]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_markdown(text: str) -> str:
    return _MARKDOWN_RE.sub("", text)


def canonical_hash(text: str) -> str:
    """
    Compute a stable canonical hash for a check-item text string.

    Stable across cosmetic whitespace/markdown edits; busts on real content
    rename.  Uses SHA-256 with whitespace and markdown normalization, then
    truncates to 16 hex chars (64-bit prefix) as the cache key.

    Spec: "Canonical hash" (Persistence and cache invalidation, lines 410-494).
    """
    stripped = _strip_markdown(text or "")
    normalized = _WHITESPACE_RE.sub(" ", stripped).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _empty_cache() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "runs": {}}


def load_cache() -> dict[str, Any]:
    """
    Load the cache. On corruption or schema-version mismatch, warn to stderr
    and return an empty cache. Never blocks the pipeline.
    """
    if not CACHE_PATH.exists():
        return _empty_cache()
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[check-items-cache] WARNING: cache load failed ({exc}); using empty cache",
              file=sys.stderr)
        return _empty_cache()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        print(f"[check-items-cache] WARNING: cache schema mismatch; using empty cache",
              file=sys.stderr)
        return _empty_cache()
    data.setdefault("runs", {})
    return data


def save_cache(data: dict[str, Any]) -> None:
    """Atomically write the cache with 0o600 permissions."""
    CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(CACHE_DIR), suffix=".tmp", encoding="utf-8"
    )
    try:
        json.dump(data, tmp, indent=2, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, str(CACHE_PATH))
    os.chmod(str(CACHE_PATH), 0o600)


def _ttl_for(classification: str) -> int:
    return {
        "DONE": TTL_DONE,
        "NEEDS-ACTION": TTL_NEEDS_ACTION,
        "STALE": TTL_STALE,
    }.get(classification, TTL_ACTIVE)


def _mtime_matches(cached_members: list[dict], current_members: list[dict]) -> bool:
    """True iff all current member mtimes match cached within 1s tolerance."""
    cached_by_key = {(m.get("file"), m.get("line")): m.get("mtime") for m in cached_members}
    for cm in current_members:
        cached_mtime = cached_by_key.get((cm.get("file"), cm.get("line")))
        if cached_mtime is None:
            return False
        try:
            if abs(float(cm.get("mtime", 0)) - float(cached_mtime)) > 1.0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def partition(
    groups: list[dict],
    cache: dict,
    project: str,
    head_sha: str,
    force: bool = False,
    now: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Apply invalidation rules in spec order (first match wins):
        force -> new -> head_changed -> mtime_changed -> ttl_expired.
    Returns (known_unchanged, needs_reclassification). Groups routed to
    `needs` carry `_reason` for dashboard visibility. Groups routed to
    `known` carry `_cached_classification` / `_cached_confidence` /
    `_cached_evidence_citation` / `_cached_action_required` (NOT `_reason`).
    """
    if now is None:
        now = time.time()
    run = cache.get("runs", {}).get(project, {})
    cached_groups_by_hash = {
        g["canonical_hash"]: g
        for g in run.get("groups", [])
        if isinstance(g, dict) and isinstance(g.get("canonical_hash"), str)
    }
    cached_head = run.get("project_head_at_classify")

    known: list[dict] = []
    needs: list[dict] = []

    for g in groups:
        h = g.get("canonical_hash")
        if force:
            g["_reason"] = "force"
            needs.append(g)
            continue
        cached = cached_groups_by_hash.get(h)
        if cached is None:
            g["_reason"] = "new"
            needs.append(g)
            continue
        if cached_head != head_sha:
            g["_reason"] = "head_changed"
            needs.append(g)
            continue
        if not _mtime_matches(cached.get("members", []), g.get("members", [])):
            g["_reason"] = "mtime_changed"
            needs.append(g)
            continue
        try:
            classified_ts = float(cached.get("classified_ts", 0))
        except (TypeError, ValueError):
            classified_ts = 0.0
        if now - classified_ts > _ttl_for(cached.get("classification", "ACTIVE")):
            g["_reason"] = "ttl_expired"
            needs.append(g)
            continue
        g["_cached_classification"] = cached.get("classification")
        g["_cached_confidence"] = cached.get("confidence")
        g["_cached_evidence_citation"] = cached.get("evidence_citation")
        g["_cached_action_required"] = cached.get("action_required")
        known.append(g)

    return known, needs


def update_cache(
    cache: dict,
    project: str,
    all_groups: list[dict],
    fresh_classifications: list[dict],
    head_sha: str,
    now: float | None = None,
) -> dict:
    """
    Merge fresh classifications into the cache and GC entries whose
    canonical_hash is no longer in the current run.

    1. Build a hash set from all_groups (the current run's groups).
    2. Keep cached groups whose hash is in the current set; evict the rest.
    3. Overwrite by canonical_hash with any fresh classifications.
    4. Bump last_run_ts and project_head_at_classify.
    """
    if now is None:
        now = time.time()
    current_hashes = {g.get("canonical_hash") for g in all_groups}
    fresh_by_hash = {fc.get("canonical_hash"): fc for fc in fresh_classifications}

    cache.setdefault("schema_version", SCHEMA_VERSION)
    cache.setdefault("runs", {})
    run = cache["runs"].setdefault(project, {})
    existing_groups = run.get("groups", [])

    surviving: list[dict] = []
    seen: set[str] = set()
    for g in existing_groups:
        h = g.get("canonical_hash")
        if h not in current_hashes:
            continue
        if h in fresh_by_hash:
            surviving.append(_freeze_classification(fresh_by_hash[h], now))
        else:
            surviving.append(g)
        seen.add(h)

    for h, fc in fresh_by_hash.items():
        if h in seen or h not in current_hashes:
            continue
        surviving.append(_freeze_classification(fc, now))

    run["groups"] = surviving
    run["last_run_ts"] = int(now)
    run["project_head_at_classify"] = head_sha
    return cache


def _freeze_classification(fc: dict, now: float) -> dict:
    """Normalize a fresh classification dict into the on-disk cache entry shape."""
    return {
        "canonical_hash": fc.get("canonical_hash"),
        "canonical_text": fc.get("canonical_text") or fc.get("representative", ""),
        "members": fc.get("members", []),
        "classification": fc.get("classification"),
        "confidence": fc.get("confidence"),
        "evidence_citation": fc.get("evidence_citation"),
        "action_required": fc.get("action_required"),
        "classified_ts": fc.get("classified_ts", int(now)),
    }
