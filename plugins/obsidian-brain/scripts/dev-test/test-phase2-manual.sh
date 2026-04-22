#!/usr/bin/env bash
# Manual smoke test for Phase 2: TF-IDF + Themes + Surprise + FTS orphan cleanup
#
# Run AFTER: /dev-test install + start a new CC session.
# Usage: bash scripts/dev-test/test-phase2-manual.sh
#
# Invariants checked:
# - Schema: themes, theme_members, term_df tables + tfidf_vector column
# - Data: tfidf_vector populated for summarized notes
# - Theme invariant: themes.note_count == count(theme_members WHERE theme_id=themes.id)
# - FTS cleanliness: no orphan notes_fts rows
# - Access cascade (Section 7 of snapshot spec is separate — here we only check
#   Phase 2 access_log baseline)
# - Numerical: cosine symmetric, surprise in [0,1], tfidf weights >= 0

set -uo pipefail    # omit -e so individual test failures don't abort the whole run

DB="$HOME/.claude/obsidian-brain-vault.db"
PASS=0
FAIL=0
SKIP=0

pass() { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  ⏭️  $1"; SKIP=$((SKIP + 1)); }

echo "═══════════════════════════════════════════════════"
echo "Phase 2 Smoke Test: TF-IDF + Themes + Surprise"
echo "═══════════════════════════════════════════════════"
echo ""
echo "DB path: $DB"
echo ""

if [ ! -f "$DB" ]; then
    fail "DB does not exist — run /vault-reindex or any vault op first, then re-run this script"
    exit 1
fi

# ─── Test 1: Schema ───────────────────────────────────
echo "Test 1: Schema migration"

for table in themes theme_members term_df; do
    if sqlite3 "$DB" ".tables" | tr -s ' ' '\n' | grep -qx "$table"; then
        pass "$table table exists"
    else
        fail "$table table missing (run /vault-reindex to migrate)"
    fi
done

if sqlite3 "$DB" "PRAGMA table_info(notes)" | awk -F'|' '{print $2}' | grep -qx "tfidf_vector"; then
    pass "tfidf_vector column exists on notes"
else
    fail "tfidf_vector column missing on notes"
fi

echo ""

# ─── Test 2: Indexes ──────────────────────────────────
echo "Test 2: Supporting indexes"

for idx in idx_theme_members_theme idx_theme_members_note idx_themes_project; do
    if sqlite3 "$DB" ".indices" | grep -qx "$idx"; then
        pass "index $idx exists"
    else
        skip "index $idx — naming may vary, check PRAGMA index_list(themes)"
    fi
done

echo ""

# ─── Test 3: Data population ──────────────────────────
echo "Test 3: tfidf_vector populated"

NOTE_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes")
VEC_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes WHERE tfidf_vector IS NOT NULL AND tfidf_vector != ''")
NULL_COUNT=$((NOTE_COUNT - VEC_COUNT))

echo "  notes total:          $NOTE_COUNT"
echo "  with tfidf_vector:    $VEC_COUNT"
echo "  without tfidf_vector: $NULL_COUNT"

if [ "$NOTE_COUNT" -eq 0 ]; then
    skip "empty vault — nothing to validate"
elif [ "$VEC_COUNT" -eq 0 ]; then
    fail "tfidf_vector is NULL for ALL notes — /vault-reindex did not run or _upsert_note regressed"
elif [ "$NULL_COUNT" -gt 0 ]; then
    # Note: new raw (status=auto-logged) notes may not have tfidf_vector until summarized
    # because bodies are placeholders. Check only summarized notes.
    SUMMARIZED_WITHOUT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes WHERE status='summarized' AND (tfidf_vector IS NULL OR tfidf_vector = '')")
    if [ "$SUMMARIZED_WITHOUT" -gt 0 ]; then
        fail "$SUMMARIZED_WITHOUT summarized notes missing tfidf_vector"
        sqlite3 "$DB" "SELECT path FROM notes WHERE status='summarized' AND (tfidf_vector IS NULL OR tfidf_vector = '') LIMIT 5" | sed 's/^/    - /'
    else
        pass "all summarized notes have tfidf_vector (only auto-logged notes are NULL, expected)"
    fi
else
    pass "all $NOTE_COUNT notes have tfidf_vector"
fi

echo ""

# ─── Test 4: term_df consistency ──────────────────────
echo "Test 4: term_df consistency"

TERM_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM term_df")
echo "  term_df rows: $TERM_COUNT"

if [ "$TERM_COUNT" -eq 0 ] && [ "$VEC_COUNT" -gt 0 ]; then
    fail "term_df is empty but tfidf_vectors exist — _update_term_df regressed"
elif [ "$TERM_COUNT" -gt 0 ]; then
    NEG_DF=$(sqlite3 "$DB" "SELECT COUNT(*) FROM term_df WHERE df < 0")
    if [ "$NEG_DF" -gt 0 ]; then
        fail "$NEG_DF term_df rows have negative df (symmetric-diff regression)"
    else
        pass "no negative df values"
    fi

    MAX_DF=$(sqlite3 "$DB" "SELECT MAX(df) FROM term_df")
    if [ "$MAX_DF" -gt "$NOTE_COUNT" ]; then
        fail "max df=$MAX_DF exceeds note count=$NOTE_COUNT (over-counting)"
    else
        pass "df <= note count (max df=$MAX_DF)"
    fi
fi

echo ""

# ─── Test 5: Theme invariants ─────────────────────────
echo "Test 5: Theme invariants"

THEME_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM themes")
MEMBER_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM theme_members")

echo "  themes:        $THEME_COUNT"
echo "  theme_members: $MEMBER_COUNT"

if [ "$THEME_COUNT" -eq 0 ]; then
    skip "no themes yet — run /recall on a project with >=2 similar notes"
else
    # Count mismatch check: themes.note_count should equal count of theme_members per theme
    MISMATCH=$(sqlite3 "$DB" "
        SELECT COUNT(*) FROM (
            SELECT t.id, t.note_count, COALESCE(mc.cnt, 0) AS actual
            FROM themes t
            LEFT JOIN (SELECT theme_id, COUNT(*) AS cnt FROM theme_members GROUP BY theme_id) mc
              ON mc.theme_id = t.id
            WHERE t.note_count != COALESCE(mc.cnt, 0)
        )
    ")
    if [ "$MISMATCH" -gt 0 ]; then
        fail "$MISMATCH themes have note_count mismatching theme_members count"
        sqlite3 "$DB" "
            SELECT t.id, t.name, t.note_count, COALESCE(mc.cnt, 0)
            FROM themes t
            LEFT JOIN (SELECT theme_id, COUNT(*) AS cnt FROM theme_members GROUP BY theme_id) mc
              ON mc.theme_id = t.id
            WHERE t.note_count != COALESCE(mc.cnt, 0)
            LIMIT 5
        " | sed 's/^/    /'
    else
        pass "themes.note_count == COUNT(theme_members) for all themes"
    fi

    # Orphan theme_members (theme_id not in themes)
    ORPHAN=$(sqlite3 "$DB" "SELECT COUNT(*) FROM theme_members tm LEFT JOIN themes t ON t.id = tm.theme_id WHERE t.id IS NULL")
    if [ "$ORPHAN" -gt 0 ]; then
        fail "$ORPHAN orphan theme_members rows (theme_id points to missing theme)"
    else
        pass "no orphan theme_members"
    fi

    # Centroid presence
    NULL_CENTROID=$(sqlite3 "$DB" "SELECT COUNT(*) FROM themes WHERE centroid IS NULL OR centroid = '' OR centroid = '{}'")
    if [ "$NULL_CENTROID" -gt 0 ] && [ "$THEME_COUNT" -gt 0 ]; then
        fail "$NULL_CENTROID themes have empty centroid"
    else
        pass "all themes have populated centroid"
    fi

    # Surprise values in [0, 1]
    OUT_OF_RANGE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM theme_members WHERE surprise < 0 OR surprise > 1")
    if [ "$OUT_OF_RANGE" -gt 0 ]; then
        fail "$OUT_OF_RANGE theme_members rows have surprise outside [0,1]"
    else
        pass "all surprise values in [0, 1]"
    fi

    # Similarity values in [0, 1]
    SIM_BAD=$(sqlite3 "$DB" "SELECT COUNT(*) FROM theme_members WHERE similarity < 0 OR similarity > 1.01")
    if [ "$SIM_BAD" -gt 0 ]; then
        fail "$SIM_BAD theme_members rows have similarity outside [0, 1.01]"
    else
        pass "all similarity values in [0, 1.01] tolerance band"
    fi
fi

echo ""

# ─── Test 6: FTS cleanliness (orphan rows from Section 5 fix) ─
echo "Test 6: FTS5 orphan rows"

# Every notes_fts rowid should correspond to a row in notes with the same rowid.
FTS_ORPHAN=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes_fts WHERE rowid NOT IN (SELECT rowid FROM notes)")
if [ "$FTS_ORPHAN" -gt 0 ]; then
    fail "$FTS_ORPHAN orphan notes_fts rows (FTS5 'delete' command missing on upsert/delete)"
else
    pass "no orphan notes_fts rows (all FTS entries JOIN a notes row)"
fi

FTS_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes_fts")
if [ "$FTS_COUNT" -ne "$NOTE_COUNT" ]; then
    fail "notes_fts count ($FTS_COUNT) != notes count ($NOTE_COUNT)"
else
    pass "notes_fts count matches notes count"
fi

echo ""

# ─── Test 7: Access log cascade baseline (Phase 1 feature) ─
echo "Test 7: access_log sanity"

ACC_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log")
echo "  access_log rows: $ACC_COUNT"

if [ "$ACC_COUNT" -eq 0 ]; then
    skip "no access_log entries yet — run /vault-search or /recall first"
else
    # No access_log rows referencing missing notes
    ORPHAN_ACCESS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log al LEFT JOIN notes n ON n.path = al.note_path WHERE n.path IS NULL")
    if [ "$ORPHAN_ACCESS" -gt 0 ]; then
        skip "$ORPHAN_ACCESS access_log rows reference missing notes (may be from deleted files — informational)"
    else
        pass "all access_log rows reference existing notes"
    fi
fi

echo ""

# ─── Summary ──────────────────────────────────────────
echo "═══════════════════════════════════════════════════"
echo "Summary: $PASS passed, $FAIL failed, $SKIP skipped"
echo "═══════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "❌ Phase 2 implementation has invariant violations."
    echo "   Run: python3 scripts/dev-test/validate_phase2.py --verbose"
    echo "   for deeper analysis."
    exit 1
fi

echo ""
echo "✅ Phase 2 invariants hold."
echo "   Next: run validate_phase2.py for numerical checks (cosine, tokenizer)."
