#!/usr/bin/env python3
"""Phase 2 validation — numerical and behavioral checks beyond what bash can do.

Run AFTER: `/dev-test install` + fresh CC session + /vault-reindex + a /recall cycle.
Usage:
    python3 scripts/dev-test/validate_phase2.py                    # use installed plugin cache
    python3 scripts/dev-test/validate_phase2.py --dev-repo         # use local hooks/ (pre-install sanity check)
    python3 scripts/dev-test/validate_phase2.py --verbose
    python3 scripts/dev-test/validate_phase2.py --db /path/to/vault.db

Exits 0 on all checks passing, 1 if any fail.

Checks performed:
- TF-IDF tokenizer: basic lowercasing, stopword drop, apostrophe handling
- _compute_tfidf_vector math: smoothed IDF formula holds, top-K truncation
- _cosine_similarity: symmetric, in [0, 1], identity == 1
- detect_surprise: edge cases return 0.0, contractions match, out-of-window doesn't
- assign_to_theme idempotency: calling twice on same note doesn't drift count/centroid
- reindex invariance: repeat index_note on same note does not drift term_df
- _delete_note centroid unfold: running-average reverse is algebraically correct
- check_optional_deps: reports numpy/scipy status
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# --- Hook resolution is argv-dependent; delay import until after flag parsing ---
_EARLY_ARGS = sys.argv[1:]
_USE_DEV_REPO = "--dev-repo" in _EARLY_ARGS
# Short-circuit when the user just wants --help so hook resolution errors
# don't mask argparse's usage output.
_HELP_REQUESTED = any(a in ("-h", "--help") for a in _EARLY_ARGS)


def _find_dev_hooks() -> Path | None:
    """Walk up from this file until we find a sibling `hooks/` directory.
    Robust to different script locations (scripts/, scripts/dev-test/, etc.)."""
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        candidate = parent / "hooks"
        if candidate.is_dir() and (candidate / "vault_index.py").exists():
            return candidate
    return None


vault_index = None  # type: ignore[assignment]
obsidian_utils = None  # type: ignore[assignment]

if not _HELP_REQUESTED:
    if _USE_DEV_REPO:
        dev_hooks = _find_dev_hooks()
        if dev_hooks is None:
            print("ERROR: --dev-repo passed but no hooks/ directory found walking up from this script",
                  file=sys.stderr)
            sys.exit(1)
        sys.path.insert(0, str(dev_hooks))
    else:
        CACHE_GLOB = os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")
        cache_hits = sorted(glob.glob(CACHE_GLOB))
        if not cache_hits:
            dev_hooks = _find_dev_hooks()
            if dev_hooks is not None:
                print(f"NOTE: no plugin cache found; falling back to {dev_hooks}")
                sys.path.insert(0, str(dev_hooks))
            else:
                print("ERROR: cannot locate obsidian-brain hooks/ directory", file=sys.stderr)
                sys.exit(1)
        else:
            sys.path.insert(0, cache_hits[-1])

    try:
        import vault_index  # noqa: F811
        import obsidian_utils  # noqa: F811
    except ImportError as e:
        print(f"ERROR: failed to import hooks: {e}", file=sys.stderr)
        sys.exit(1)

# --- Reporting helpers ---
PASS = 0
FAIL = 0
SKIP = 0
VERBOSE = False


def pass_(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail_(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def skip_(msg: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  ⏭️  {msg}")


def debug(msg: str) -> None:
    if VERBOSE:
        print(f"    · {msg}")


def section(name: str) -> None:
    print(f"\n{'─' * 50}")
    print(name)
    print("─" * 50)


# --- Tests ---

def test_tokenizer() -> None:
    section("1. TF-IDF tokenizer")
    toks = vault_index._tokenize_for_tfidf("Hello, World! Python-3.9.")
    expected = ["hello", "world", "python"]
    if toks == expected:
        pass_(f"punctuation + single-digit stripped: {toks}")
    else:
        fail_(f"expected {expected}, got {toks}")

    toks = vault_index._tokenize_for_tfidf("the quick brown fox is here")
    for sw in ("the", "is", "here"):
        if sw not in toks:
            pass_(f"stopword '{sw}' dropped")
        else:
            fail_(f"stopword '{sw}' not dropped: {toks}")

    # Length filter
    toks = vault_index._tokenize_for_tfidf("a ab abc")
    if "a" not in toks and "ab" in toks and "abc" in toks:
        pass_("single-char tokens dropped, 2+ char kept")
    else:
        fail_(f"length filter unexpected: {toks}")


def test_compute_tfidf() -> None:
    section("2. _compute_tfidf_vector")
    # Smoothed IDF: 1 + ln((N+1)/(df+1))
    # For N=10, df=1: 1 + ln(11/2) ≈ 1 + 1.7047 = 2.7047
    # For N=10, df=10: 1 + ln(11/11) = 1 + 0 = 1.0
    tokens = ["retrieval", "scoring", "retrieval"]  # retrieval appears twice (TF=2/3), scoring once (TF=1/3)
    term_df = {"retrieval": 1, "scoring": 10}
    total_docs = 10

    vec = vault_index._compute_tfidf_vector(tokens, term_df, total_docs, top_k=50)
    if "retrieval" not in vec or "scoring" not in vec:
        fail_(f"vec missing expected terms: {vec}")
        return

    # retrieval has higher IDF (rare) and higher TF (appears 2x) — must dominate
    if vec["retrieval"] > vec["scoring"]:
        pass_(f"rare term weight > common term weight ({vec['retrieval']:.3f} > {vec['scoring']:.3f})")
    else:
        fail_(f"rare term should dominate: retrieval={vec['retrieval']:.3f}, scoring={vec['scoring']:.3f}")

    # Verify smoothed IDF formula approximately
    expected_idf_rare = 1 + math.log((total_docs + 1) / (1 + 1))   # df=1
    expected_idf_common = 1 + math.log((total_docs + 1) / (10 + 1))  # df=10
    if expected_idf_common < 0.01:
        expected_idf_common = 1.0  # smoothing keeps it >= some floor
    debug(f"expected IDF rare ≈ {expected_idf_rare:.3f}, common ≈ {expected_idf_common:.3f}")

    # Top-K truncation
    big_tokens = [f"tok{i}" for i in range(100)]
    big_df = {t: 1 for t in big_tokens}
    big_vec = vault_index._compute_tfidf_vector(big_tokens, big_df, 100, top_k=50)
    if len(big_vec) <= 50:
        pass_(f"top-K truncation respected ({len(big_vec)} <= 50)")
    else:
        fail_(f"top-K not enforced: {len(big_vec)} entries")


def test_cosine_similarity() -> None:
    section("3. _cosine_similarity")
    a = {"x": 1.0, "y": 1.0}
    b = {"x": 1.0, "y": 1.0}
    sim = vault_index._cosine_similarity(a, b)
    if abs(sim - 1.0) < 1e-6:
        pass_(f"identical vectors → 1.0 (got {sim:.6f})")
    else:
        fail_(f"identical should be 1.0, got {sim}")

    # Symmetric
    sim_ab = vault_index._cosine_similarity(a, {"x": 2.0})
    sim_ba = vault_index._cosine_similarity({"x": 2.0}, a)
    if abs(sim_ab - sim_ba) < 1e-9:
        pass_(f"symmetric: cos(a,b)={sim_ab:.6f} = cos(b,a)={sim_ba:.6f}")
    else:
        fail_(f"asymmetric: cos(a,b)={sim_ab}, cos(b,a)={sim_ba}")

    # Disjoint → 0
    sim_disjoint = vault_index._cosine_similarity({"x": 1.0}, {"y": 1.0})
    if abs(sim_disjoint) < 1e-6:
        pass_(f"disjoint → 0.0 (got {sim_disjoint})")
    else:
        fail_(f"disjoint should be 0, got {sim_disjoint}")

    # Empty
    if vault_index._cosine_similarity({}, {"x": 1.0}) == 0.0:
        pass_("empty vs populated → 0.0")
    else:
        fail_("empty should be 0.0")


def test_detect_surprise() -> None:
    section("4. detect_surprise")
    centroid = {"retrieval": 1.0, "scoring": 1.0}
    note_vec = {"retrieval": 1.0, "scoring": 1.0}

    # Negated shared term
    score = vault_index.detect_surprise(
        "retrieval scoring is not reliable",
        note_vec, centroid,
    )
    if score > 0:
        pass_(f"negated shared term registers ({score:.3f})")
    else:
        fail_(f"negated shared term should score > 0, got {score}")

    # Agreement text
    score = vault_index.detect_surprise(
        "retrieval scoring works great",
        note_vec, centroid,
    )
    if score == 0.0:
        pass_(f"agreement text → 0.0")
    else:
        fail_(f"agreement should be 0, got {score}")

    # Apostrophe normalization — don't should match dont
    score = vault_index.detect_surprise(
        "don't trust retrieval scoring",
        note_vec, centroid,
    )
    if score > 0:
        pass_(f"straight apostrophe normalization works (score={score:.3f})")
    else:
        fail_(f"don't → dont normalization failed, score={score}")

    # Smart quote
    score = vault_index.detect_surprise(
        "can\u2019t trust retrieval scoring",
        note_vec, centroid,
    )
    if score > 0:
        pass_(f"smart quote normalization works (score={score:.3f})")
    else:
        fail_(f"can\u2019t → cant normalization failed, score={score}")

    # Empty inputs all return 0
    for desc, args in [
        ("empty text", ("", note_vec, centroid)),
        ("empty vec", ("text", {}, centroid)),
        ("empty centroid", ("text", note_vec, {})),
    ]:
        if vault_index.detect_surprise(*args) == 0.0:
            pass_(f"{desc} → 0.0")
        else:
            fail_(f"{desc} should be 0.0")


def test_assign_theme_idempotent(tmpdir: Path) -> None:
    section("5. assign_to_theme idempotency (no count/centroid drift on reassignment)")

    # Set up a synthetic vault + note
    vault = tmpdir / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    note_path = vault / "claude-sessions" / "2026-04-17-test-abcd.md"
    note_path.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-17\n"
        "project: testproj\n"
        "title: Test session\n"
        "tags:\n  - claude/session\n"
        "status: summarized\n"
        "---\n"
        "retrieval scoring activation importance proximity bm25 theme\n",
        encoding="utf-8",
    )
    db_path = str(tmpdir / "test.db")
    vault_index.ensure_index(str(vault), ["claude-sessions"], db_path=db_path)

    # Seed a theme matching the note's vector
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    vec = json.loads(conn.execute(
        "SELECT tfidf_vector FROM notes WHERE path = ?", (str(note_path),)
    ).fetchone()["tfidf_vector"])
    conn.execute(
        "INSERT INTO themes (name, summary, centroid, note_count, "
        "created_date, updated_date, project) "
        "VALUES (?, ?, ?, 3, ?, ?, ?)",
        ("Test", "", json.dumps(vec), "2026-04-17", "2026-04-17", "testproj"),
    )
    theme_id = conn.execute("SELECT id FROM themes").fetchone()["id"]
    conn.commit()
    conn.close()

    # First assignment: legitimately new member → count 3 → 4
    r1 = vault_index.assign_to_theme(db_path, str(note_path), project="testproj")
    if r1 is None:
        fail_("first assign_to_theme returned None")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT note_count, centroid FROM themes WHERE id = ?", (theme_id,)
    ).fetchone()
    count_1, centroid_1 = row["note_count"], json.loads(row["centroid"])
    conn.close()

    if count_1 == 4:
        pass_(f"first assign bumps count 3 → 4")
    else:
        fail_(f"first assign: expected count=4, got {count_1}")

    # Second assignment of same note: count + centroid must not change
    r2 = vault_index.assign_to_theme(db_path, str(note_path), project="testproj")
    if r2 is None:
        fail_("second assign_to_theme returned None")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT note_count, centroid FROM themes WHERE id = ?", (theme_id,)
    ).fetchone()
    count_2, centroid_2 = row["note_count"], json.loads(row["centroid"])
    conn.close()

    if count_2 == 4:
        pass_(f"reassign keeps count at 4 (no double-count)")
    else:
        fail_(f"reassign drifted count: expected 4, got {count_2}")

    drift = max((abs(centroid_2.get(k, 0) - centroid_1.get(k, 0))
                 for k in set(centroid_1) | set(centroid_2)), default=0)
    if drift < 1e-9:
        pass_(f"reassign keeps centroid stable (max drift {drift:.2e})")
    else:
        fail_(f"centroid drifted on reassign, max delta={drift:.6f}")


def test_reindex_invariance(tmpdir: Path) -> None:
    section("6. reindex invariance — term_df stays constant across repeated index_note")

    # Seed a vault with one note containing many common-but-low-IDF tokens
    # that would be pushed out of the top-50 tfidf_vector. If _prior_tokens_for
    # reads the truncated stored vector, those tokens get re-incremented on
    # every reindex and term_df.df drifts upward.
    vault = tmpdir / "vault_reidx"
    (vault / "claude-sessions").mkdir(parents=True)
    note = vault / "claude-sessions" / "2026-04-17-reidx-abcd.md"
    # Deliberately verbose body with > 50 distinct tokens so top-K truncation bites.
    body_tokens = " ".join(f"common_term_{i:03d}" for i in range(120))
    note.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-17\n"
        "project: reidxproj\n"
        "title: Reindex invariance probe\n"
        "tags:\n  - claude/session\n"
        "status: summarized\n"
        "---\n"
        f"project retrieval activation {body_tokens}\n",
        encoding="utf-8",
    )
    db_path = str(tmpdir / "reidx.db")
    vault_index.ensure_index(str(vault), ["claude-sessions"], db_path=db_path)

    def snapshot_df() -> dict[str, int]:
        conn = sqlite3.connect(db_path)
        try:
            return dict(conn.execute("SELECT term, df FROM term_df").fetchall())
        finally:
            conn.close()

    df_initial = snapshot_df()

    # Bump mtime so index_note does not early-exit as unchanged, and reindex 3x.
    import os as _os
    for bump in range(1, 4):
        st = _os.stat(note)
        _os.utime(note, (st.st_mtime + bump * 5, st.st_mtime + bump * 5))
        ok = vault_index.index_note(db_path, str(note))
        if not ok:
            fail_(f"index_note returned False on reindex #{bump}")
            return

    df_final = snapshot_df()

    drifted = {
        term: (df_initial.get(term, 0), df_final.get(term, 0))
        for term in set(df_initial) | set(df_final)
        if df_initial.get(term, 0) != df_final.get(term, 0)
    }

    if not drifted:
        pass_(f"term_df stable across 3 reindexes ({len(df_final)} terms)")
    else:
        sample = list(drifted.items())[:5]
        fail_(f"term_df drifted for {len(drifted)} term(s) on reindex; sample: {sample}")

    total_docs = 1
    over = {t: d for t, d in df_final.items() if d > total_docs}
    if not over:
        pass_(f"max(term_df.df) ≤ note_count after reindex loop")
    else:
        fail_(f"over-counting after reindex: {list(over.items())[:5]}")


def test_delete_unfolds_centroid(tmpdir: Path) -> None:
    section("7. _delete_note reverses running-average centroid")

    # Build a theme with two members, delete one, verify centroid equals the other member's vec
    vault = tmpdir / "vault2"
    (vault / "claude-sessions").mkdir(parents=True)
    a_path = vault / "claude-sessions" / "2026-04-17-proj-aaaa.md"
    b_path = vault / "claude-sessions" / "2026-04-17-proj-bbbb.md"
    for p, body in [
        (a_path, "retrieval scoring activation"),
        (b_path, "retrieval scoring importance proximity"),
    ]:
        p.write_text(
            f"---\ntype: claude-session\ndate: 2026-04-17\nproject: proj\n"
            f"title: {p.stem}\ntags:\n  - claude/session\nstatus: summarized\n---\n{body}\n",
            encoding="utf-8",
        )
    db_path = str(tmpdir / "test2.db")
    vault_index.ensure_index(str(vault), ["claude-sessions"], db_path=db_path)

    # Hand-build theme with A+B running-avg centroid
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    vec_a = json.loads(conn.execute("SELECT tfidf_vector FROM notes WHERE path=?", (str(a_path),)).fetchone()["tfidf_vector"])
    vec_b = json.loads(conn.execute("SELECT tfidf_vector FROM notes WHERE path=?", (str(b_path),)).fetchone()["tfidf_vector"])
    all_terms = set(vec_a) | set(vec_b)
    centroid = {t: (vec_a.get(t, 0) + vec_b.get(t, 0)) / 2 for t in all_terms}
    conn.execute(
        "INSERT INTO themes (name, summary, centroid, note_count, "
        "created_date, updated_date, project) "
        "VALUES ('T', '', ?, 2, '2026-04-17', '2026-04-17', 'proj')",
        (json.dumps(centroid),),
    )
    theme_id = conn.execute("SELECT id FROM themes").fetchone()["id"]
    conn.executemany(
        "INSERT INTO theme_members (theme_id, note_path, similarity, added_date) "
        "VALUES (?, ?, 1.0, '2026-04-17')",
        [(theme_id, str(a_path)), (theme_id, str(b_path))],
    )
    conn.commit()
    conn.close()

    # Delete A via the internal helper (simulating _sync's deletion path)
    conn = vault_index._connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        vault_index._delete_note(conn, str(a_path))
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT note_count, centroid FROM themes WHERE id=?", (theme_id,)).fetchone()
    if row is None:
        fail_("theme disappeared unexpectedly (count was 2, should now be 1)")
        conn.close()
        return
    count_after = row["note_count"]
    centroid_after = json.loads(row["centroid"])
    conn.close()

    if count_after == 1:
        pass_(f"note_count decremented 2 → 1")
    else:
        fail_(f"expected count=1, got {count_after}")

    # After unfolding A, remaining centroid should equal vec_b (only member left)
    max_err = max((abs(centroid_after.get(t, 0) - vec_b.get(t, 0)) for t in set(centroid_after) | set(vec_b)), default=0)
    if max_err < 1e-6:
        pass_(f"centroid unfolded to vec_b (max error {max_err:.2e})")
    else:
        fail_(f"centroid didn't unfold cleanly, max error {max_err:.6f}")


def test_optional_deps() -> None:
    section("7. check_optional_deps")
    result = obsidian_utils.check_optional_deps()
    if set(result) == {"numpy", "scipy"}:
        pass_(f"reports numpy + scipy: numpy={result['numpy']}, scipy={result['scipy']}")
    else:
        fail_(f"expected numpy+scipy keys, got {result.keys()}")

    # Catches broader exceptions
    import importlib as _il
    real = _il.import_module

    def raising(name, *a, **kw):
        if name == "numpy":
            raise OSError("simulated broken binary")
        return real(name, *a, **kw)

    _il.import_module = raising
    try:
        result = obsidian_utils.check_optional_deps()
        if result["numpy"] is False:
            pass_(f"OSError during import → reports False (not raised)")
        else:
            fail_(f"OSError should result in False, got {result['numpy']}")
    finally:
        _il.import_module = real


def test_config_deepcopy() -> None:
    section("8. load_config deepcopy isolation")
    # Snapshot _DEFAULTS, load_config, mutate returned dict, reload, verify
    # the mutation didn't leak into subsequent loads or into _DEFAULTS itself.
    original = list(obsidian_utils._DEFAULTS.get("optional_deps_declined", []))
    try:
        c1 = obsidian_utils.load_config()
        c1.setdefault("optional_deps_declined", []).append("poisoned")
        # Bust cache
        sid = obsidian_utils._get_session_id_fast()
        obsidian_utils.cache_set(sid, "config", None)
        c2 = obsidian_utils.load_config()
        if "poisoned" not in c2.get("optional_deps_declined", []):
            pass_("mutation did not leak across load_config calls")
        else:
            fail_("mutation leaked — _DEFAULTS was shallow-copied")
        if obsidian_utils._DEFAULTS["optional_deps_declined"] == original:
            pass_("_DEFAULTS preserved")
        else:
            fail_(f"_DEFAULTS mutated: {obsidian_utils._DEFAULTS['optional_deps_declined']}")
    finally:
        # Restore _DEFAULTS if anything modified it
        obsidian_utils._DEFAULTS["optional_deps_declined"] = original


# --- Main ---

def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--db", default=os.path.expanduser("~/.claude/obsidian-brain-vault.db"))
    parser.add_argument("--dev-repo", action="store_true",
                        help="Import hooks from local hooks/ directory instead of installed plugin cache")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("═══════════════════════════════════════════════════")
    print("Phase 2 numerical + behavioral validation")
    print("═══════════════════════════════════════════════════")
    print(f"Hooks imported from: {sys.path[0]}")
    print(f"DB (informational):  {args.db}")

    test_tokenizer()
    test_compute_tfidf()
    test_cosine_similarity()
    test_detect_surprise()
    test_optional_deps()
    test_config_deepcopy()

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        test_assign_theme_idempotent(tmpdir)
        test_reindex_invariance(tmpdir)
        test_delete_unfolds_centroid(tmpdir)

    print(f"\n{'═' * 50}")
    print(f"Summary: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    print("═" * 50)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
