#!/usr/bin/env python3
"""Tuning harness for /compress Step 3.5 rank-gap delta guard.

Reads scripts/compress_rank_gap_corpus.json, runs each query against the
live vault index using the same search_vault() path as /compress SKILL.md
Step 3.5, and prints a markdown table showing true-positive / false-
positive / false-negative counts at each candidate MIN_RANK_DELTA value.

Usage:
    python3 scripts/tune_compress_rank_gap.py

No arguments. Reads vault_path from ~/.claude/obsidian-brain-config.json
and the corpus from scripts/compress_rank_gap_corpus.json (relative to
repo root).

Exit codes: always 0. This is a reporting tool, not a CI gate.
"""

import json
import os
import sys
from pathlib import Path

# Path bootstrap: add hooks/ so we can import the plugin's modules
REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

from compress_guard import is_high_confidence_match  # noqa: E402
from obsidian_utils import load_config  # noqa: E402
from vault_index import ensure_index, search_vault  # noqa: E402


THRESHOLD_GRID = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]
CORPUS_PATH = REPO_ROOT / "scripts" / "compress_rank_gap_corpus.json"


def _run_query(db, query):
    """Run the same search that SKILL.md Step 3.5 runs. Returns sorted results."""
    results = search_vault(db, query, note_type="claude-insight", limit=3)
    results += search_vault(db, query, note_type="claude-decision", limit=3)
    results.sort(key=lambda r: r["rank"])
    return results


def _score_corpus(corpus_entries, results_by_id, min_delta):
    """Score the corpus at a given MIN_RANK_DELTA threshold."""
    tp = tn = fp = fn = skipped = 0
    for entry in corpus_entries:
        results = results_by_id.get(entry["id"])
        if not results:
            skipped += 1
            continue
        predicted = is_high_confidence_match(results, min_delta=min_delta)
        expected = entry["expected_match"]
        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and expected:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn, "skipped": skipped}


def main():
    # Resolve vault path
    try:
        config = load_config()
    except Exception as exc:
        print(f"Could not load ~/.claude/obsidian-brain-config.json: {exc}")
        print("Run /obsidian-setup first.")
        return 0
    vault_path = config.get("vault_path")
    if not vault_path or not os.path.isdir(vault_path):
        print(f"Config vault_path missing or invalid: {vault_path!r}")
        return 0

    # Load corpus
    if not CORPUS_PATH.exists():
        print(f"Corpus not found: {CORPUS_PATH}")
        return 0
    with open(CORPUS_PATH, "r", encoding="utf-8") as fh:
        corpus = json.load(fh)
    entries = corpus.get("queries", [])
    if not entries:
        print("Corpus is empty. Add queries to scripts/compress_rank_gap_corpus.json.")
        return 0

    # Open the vault index
    folders = [
        config.get("sessions_folder", "claude-sessions"),
        config.get("insights_folder", "claude-insights"),
    ]
    db = ensure_index(vault_path, folders)

    # Run each query once, cache results
    print(f"# Tuning sweep — {len(entries)} queries against {vault_path}\n")
    print("## Per-query results\n")
    print("| id | query | top rank | #2 rank | delta | expected |")
    print("|---|---|---|---|---|---|")
    results_by_id = {}
    for entry in entries:
        results = _run_query(db, entry["query"])
        results_by_id[entry["id"]] = results
        if not results:
            print(f"| {entry['id']} | `{entry['query']}` | — | — | — | {entry['expected_match']} (SKIPPED: no results) |")
            continue
        top_rank = results[0]["rank"]
        if len(results) >= 2:
            second_rank = results[1]["rank"]
            delta = abs(top_rank) - abs(second_rank)
            print(f"| {entry['id']} | `{entry['query']}` | {top_rank:.2f} | {second_rank:.2f} | {delta:.2f} | {entry['expected_match']} |")
        else:
            print(f"| {entry['id']} | `{entry['query']}` | {top_rank:.2f} | — | — | {entry['expected_match']} |")

    # All-empty diagnostic (before sweep so the user sees it)
    total_skipped = sum(1 for r in results_by_id.values() if not r)
    if total_skipped == len(entries):
        print("\nWARN: All corpus queries returned no results from the vault.")
        print("      Check that vault_path is correct and the index is populated.")
        print("      Run /vault-reindex if the index needs a rebuild.\n")

    # Sweep thresholds
    print("\n## Threshold sweep\n")
    print("| MIN_RANK_DELTA | TP | TN | FP | FN | skipped | score (TP+TN)/total | repro #45 |")
    print("|---|---|---|---|---|---|---|---|")
    repro_results = results_by_id.get("replay-pr43-snapshot", [])
    for t in THRESHOLD_GRID:
        score = _score_corpus(entries, results_by_id, min_delta=t)
        total = score["tp"] + score["tn"] + score["fp"] + score["fn"]
        if total == 0:
            ratio = float("nan")
        else:
            ratio = (score["tp"] + score["tn"]) / total
        if repro_results:
            repro_pass = is_high_confidence_match(repro_results, min_delta=t)
        else:
            repro_pass = "skipped"
        print(
            f"| {t:.2f} | {score['tp']} | {score['tn']} | {score['fp']} | {score['fn']} | "
            f"{score['skipped']} | {ratio:.2f} | {repro_pass} |"
        )

    print("\n## Selection guidance\n")
    print("- Hard constraint: MIN_RANK_DELTA must be < 4.75 so the issue #45")
    print("  repro case resolves True (see spec).")
    print("- Pick the feasible threshold with the best (TP+TN)/total score.")
    print("- Ties broken toward lower thresholds (more permissive = fewer")
    print("  silent duplicates; users can always decline the update prompt).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
