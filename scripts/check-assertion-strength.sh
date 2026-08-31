#!/bin/bash
# Assertion-Strength Gate
#
# Scans STAGED test files for vacuous ("weak") assertions — the ones that keep a
# suite green while the feature is broken. Distilled from 386 session
# retrospectives: `expect(rows.length).toBeGreaterThanOrEqual(0)` shipped across
# three separate tasks; a `className.toContain(...)` assertion passed cleanly
# while buttons rendered at 27px on mobile.
#
# Usage:
#   ./scripts/check-assertion-strength.sh          # WARN mode (default) — never blocks
#   ASSERT_GATE=enforce ./scripts/check-assertion-strength.sh   # exit 1 on findings
#
# ── Rollout: WARN → enforce ──────────────────────────────────────────────
# This gate ships in WARN mode. It prints findings and always exits 0, so a
# noisy first week cannot block anyone's commit. Promote it to enforce by
# exporting ASSERT_GATE=enforce (in your shell profile or CI) once BOTH hold:
#
#   1. Two consecutive weeks of clean signal — every finding in that window was
#      either a genuine weak assertion that got strengthened, or a legitimate
#      `assert-ok:` suppression. No unexplained noise.
#   2. Suppression rate stays under 20% of total findings (printed on every
#      run). A higher rate means the smell list is mis-tuned, not that the
#      codebase is fine — fix the patterns before enforcing.
#
# Same phased pattern as cc-token-router: observe, tune, then enforce.
#
# ── Suppression ──────────────────────────────────────────────────────────
# A finding is suppressed by an `assert-ok: <reason>` comment either as the
# TRAILING comment on the SAME line, or on the line IMMEDIATELY ABOVE it:
#
#   expect(x).toBeDefined();  // assert-ok: presence is the whole contract here
#
#   # assert-ok: upstream returns None on cache miss, checked separately
#   assert cached is not None
#
# A non-empty reason is REQUIRED in both positions. A bare `assert-ok:` does
# not suppress anything; the finding is reported with a note saying so.
#
# The same-line form is anchored to end-of-line and rejects quotes and
# backticks in the reason, so an `assert-ok:` that merely appears inside a
# string literal cannot spoof a suppression.
#
# Suppressed findings are still REPORTED (as `suppressed (reason)`) but do not
# count toward the failure total.
#
# ── Scope / known limits ─────────────────────────────────────────────────
# grep cannot tell "the sole assertion in a test" from "one of six", so
# toBeDefined() / not.toBeNull() / `is not None` are flagged on EVERY
# occurrence. The suppression comment is the safety valve for the legitimate
# ones. "Source-presence" tests (asserting a string appears in the source file
# under test) are deliberately out of scope — detecting those needs AST
# analysis, not grep.
#
# ── Known limitations ────────────────────────────────────────────────────
# These are accepted trade-offs of a line-based grep gate, not oversights:
#
#   * Multi-line assertions are NOT detected. The scan is line-based, so an
#     `expect(\n  result\n).toBeDefined();` spread over three lines slips
#     through. Catching it needs AST analysis — same reasoning that put
#     "source-presence" tests out of scope.
#   * A smell appearing inside a docstring, a string literal, or a comment is
#     still flagged. grep cannot tell code from prose. The `assert-ok`
#     annotation is the escape hatch for those.
#   * `toHaveProperty('key,with,comma')` is misread as the two-arg (value-
#     checking) form and is therefore NOT flagged. The arity test is a comma
#     scan, not a parse.
#   * An `assert-ok:` reason may not contain a quote or a backtick — those
#     characters are what make the same-line annotation un-spoofable.
#
# Portability: BSD grep (macOS) and GNU grep. No `grep -P`, no ERE
# backreferences (rejected by several greps); the self-comparison smell is
# matched with bash's own =~ capture groups instead.
#
# Installed by /harden-repo. Self-contained — no project-specific paths.

MODE="${ASSERT_GATE:-warn}"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
    echo "⏭️  Not a git repository — skipping assertion-strength gate"
    exit 0
fi
cd "$REPO_ROOT" || exit 0

# ── Smell patterns ───────────────────────────────────────────────────────
# Cheap pre-filter: a genuine superset of every smell below, so we spawn one
# grep per file instead of one per smell. A line the pre-filter rejects is
# never seen by a classifier, so the pre-filter must NEVER be narrower than
# one — in particular it must not encode whitespace the classifiers tolerate
# (`toBeDefined( )`, `assert  x  is  not  None`). Anchor each alternative on
# the matcher NAME, and leave the whitespace handling to the classifier.
PREFILTER='toBeGreaterThanOrEqual\(|toBeDefined\(|toBeNull\(|className.*\.toContain\(|typeof|toHaveProperty\(|\.toEqual\(|is[[:space:]]+not[[:space:]]+None|>=[[:space:]]*0'

# Classifier regexes (bash ERE, evaluated with [[ =~ ]] so we get capture groups)
RE_GTE_ZERO='toBeGreaterThanOrEqual\([[:space:]]*0[[:space:]]*\)'
RE_DEFINED='toBeDefined\([[:space:]]*\)'
RE_NOT_NULL='not\.toBeNull\([[:space:]]*\)'
# Matches both `className.toContain(` and the far more common
# `expect(el.className).toContain(` form from the retro citation.
RE_CLASSNAME='className[[:space:]]*\)?[[:space:]]*\.toContain\('
RE_TYPEOF='expect\([[:space:]]*typeof[[:space:]]'
RE_HAVEPROP='toHaveProperty\(([^()]*)\)'
RE_SELFCMP='expect\(([^()]*)\)[[:space:]]*\.toEqual\(([^()]*)\)'
RE_PY_NOT_NONE='(^|[^[:alnum:]_])assert[[:space:]]+.+[[:space:]]is[[:space:]]+not[[:space:]]+None([^[:alnum:]_]|$)'
RE_PY_LEN_ZERO='(^|[^[:alnum:]_])assert[[:space:]]+len\(.*\)[[:space:]]*>=[[:space:]]*0([^[:alnum:]_]|$)'

# `assert-ok: <reason>` as the TRAILING // or # comment on the line. Anchoring
# to end-of-line and banning quotes/backticks in the reason is what stops
# `expect(nav.hashFor('#assert-ok: x')).toBeDefined();` from spoofing one.
RE_SUPPRESS="(//|#)[[:space:]]*assert-ok:[[:space:]]*([^\"'\`]*)\$"
# The line-ABOVE form only counts when the annotation is on a line of its own.
# A trailing annotation on a line of code belongs to that line's finding and
# must not leak down onto the next assertion.
RE_SUPPRESS_OWN_LINE='^[[:space:]]*(//|#)[[:space:]]*assert-ok:[[:space:]]*(.*)$'

TOTAL=0
ACTIVE=0
SUPPRESSED=0
SCANNED=0

# trim_ws <string> — result in $REPLY (no subshell, keeps the hot loop cheap)
trim_ws() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    REPLY="$s"
}

# strip_comments <string> — removes /* ... */ blocks; result in $REPLY.
# `expect(x/* note */).toEqual(x)` is still a self-comparison; the comment must
# not be allowed to defeat the string compare.
strip_comments() {
    local s="$1"
    while [[ $s == *"/*"*"*/"* ]]; do
        s="${s%%/\**}${s#*\*/}"
    done
    REPLY="$s"
}

# report <file> <lineno> <smell> <text> <reason-or-empty> <suppressed:true|false>
report() {
    TOTAL=$((TOTAL + 1))
    if [ "$6" = "true" ]; then
        SUPPRESSED=$((SUPPRESSED + 1))
        echo "   ✅ $1:$2: $3 -- suppressed ($5)"
    else
        ACTIVE=$((ACTIVE + 1))
        echo "   ⚠️  $1:$2: $3"
    fi
    echo "        $4"
}

# ── Staged file selection ────────────────────────────────────────────────
# -z keeps filenames with spaces (and any other special character) intact.
FILES=()
while IFS= read -r -d '' path; do
    [ -n "$path" ] || continue
    # *test* also covers anything under a tests/ directory, at any depth.
    case "$path" in
        *test*|*spec*) ;;
        *) continue ;;
    esac
    [ -f "$path" ] || continue   # deleted/renamed away since staging
    FILES+=("$path")
done < <(git diff --cached --name-only --diff-filter=ACM -z 2>/dev/null)

if [ ${#FILES[@]} -eq 0 ]; then
    echo "✅ Assertion-strength: no staged test files to scan"
    exit 0
fi

# ── Scan ─────────────────────────────────────────────────────────────────
for file in "${FILES[@]}"; do
    SCANNED=$((SCANNED + 1))

    # -I makes grep treat binary files as non-matching, so they are skipped.
    # Without it grep emits a `Binary file <path> matches` summary line, which
    # this parser would then mistake for a `<lineno>:<text>` hit.
    hits=$(grep -nIE -e "$PREFILTER" -- "$file" 2>/dev/null)
    [ -n "$hits" ] || continue

    # Line-above suppressions for this file: ANN[<lineno>] = <reason>, with
    # ANN_SEEN[<lineno>] recording that an annotation was present at all — a
    # reason-less `assert-ok:` must be distinguishable from no annotation.
    unset ANN ANN_SEEN
    ANN=()
    ANN_SEEN=()
    anns=$(grep -nIE -e 'assert-ok:' -- "$file" 2>/dev/null)
    if [ -n "$anns" ]; then
        while IFS= read -r ann; do
            [ -n "$ann" ] || continue
            ann_no="${ann%%:*}"
            ann_text="${ann#*:}"
            if [[ $ann_text =~ $RE_SUPPRESS_OWN_LINE ]]; then
                trim_ws "${BASH_REMATCH[2]}"
                ANN[ann_no]="$REPLY"
                ANN_SEEN[ann_no]=1
            fi
        done <<< "$anns"
    fi

    while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        lineno="${hit%%:*}"
        text="${hit#*:}"

        # `.not.` inverts two of these matchers into precise, falsifiable
        # assertions, which must NOT be flagged:
        #   expect(x).not.toBeDefined()            — asserts the value IS undefined
        #   expect(p).not.toHaveProperty('secret') — asserts a key is ABSENT
        # Blank the negated occurrences out of a scratch copy of the line so
        # only the positive forms ever reach those two classifiers.
        pos="${text//.not.toBeDefined/.notNegated}"
        pos="${pos//.not.toHaveProperty/.notNegated}"

        # Which smells does this line carry? (a line may carry more than one)
        #
        # Each regex is gated behind a literal glob test. Globs are far cheaper
        # than regcomp/regexec in bash 3.2 (which does not cache compiled
        # patterns), and the gate keeps the scan well inside its time budget on
        # a large staged diff.
        smells=()
        [[ $text == *toBeGreaterThanOrEqual* ]] && [[ $text =~ $RE_GTE_ZERO ]]    && smells+=("toBeGreaterThanOrEqual(0)")
        [[ $pos == *toBeDefined* ]]             && [[ $pos =~ $RE_DEFINED ]]      && smells+=("toBeDefined()")
        [[ $text == *toBeNull* ]]               && [[ $text =~ $RE_NOT_NULL ]]    && smells+=("not.toBeNull()")
        [[ $text == *className* ]]              && [[ $text =~ $RE_CLASSNAME ]]   && smells+=("className.toContain()")
        [[ $text == *typeof* ]]                 && [[ $text =~ $RE_TYPEOF ]]      && smells+=("expect(typeof ...)")
        [[ $text == *None* ]]                   && [[ $text =~ $RE_PY_NOT_NONE ]] && smells+=("assert ... is not None")
        [[ $text == *len\(* ]]                  && [[ $text =~ $RE_PY_LEN_ZERO ]] && smells+=("assert len(...) >= 0")

        # toHaveProperty() with a single argument asserts presence, not value.
        if [[ $pos == *toHaveProperty\(* ]] && [[ $pos =~ $RE_HAVEPROP ]]; then
            case "${BASH_REMATCH[1]}" in
                *,*) ;;   # two-arg form checks the value — that is a strong assertion
                *) smells+=("toHaveProperty() single-arg") ;;
            esac
        fi

        # Self-comparison: expect(X).toEqual(X) can never fail.
        # POSIX ERE has no portable backreference, so capture both sides with
        # bash's own =~ groups and compare them as strings. =~ only ever reports
        # the LEFTMOST match, so walk the line, dropping the matched prefix each
        # time, or a second pair on the same line would go unchecked.
        if [[ $text == *toEqual\(* ]]; then
            rest="$text"
            while [[ $rest =~ $RE_SELFCMP ]]; do
                matched="${BASH_REMATCH[0]}"
                strip_comments "${BASH_REMATCH[1]}"; trim_ws "$REPLY"; lhs="$REPLY"
                strip_comments "${BASH_REMATCH[2]}"; trim_ws "$REPLY"; rhs="$REPLY"
                if [ -n "$lhs" ] && [ "$lhs" = "$rhs" ]; then
                    smells+=("self-comparison")
                    break
                fi
                rest="${rest#*"$matched"}"
            done
        fi

        [ ${#smells[@]} -eq 0 ] && continue

        # Suppression: the trailing comment on this line, else the line
        # immediately above. A non-empty reason is required in both positions.
        reason=""
        is_suppressed=false
        needs_reason=false
        if [[ $text == *assert-ok:* ]] && [[ $text =~ $RE_SUPPRESS ]]; then
            trim_ws "${BASH_REMATCH[2]}"
            if [ -n "$REPLY" ]; then
                reason="$REPLY"
                is_suppressed=true
            else
                needs_reason=true
            fi
        elif [ -n "${ANN_SEEN[$((lineno - 1))]-}" ]; then
            above="${ANN[$((lineno - 1))]-}"
            if [ -n "$above" ]; then
                reason="$above"
                is_suppressed=true
            else
                needs_reason=true
            fi
        fi

        trim_ws "$text"
        shown="$REPLY"
        for smell in "${smells[@]}"; do
            report "$file" "$lineno" "$smell" "$shown" "$reason" "$is_suppressed"
        done
        if [ "$needs_reason" = true ]; then
            echo "        ↳ 'assert-ok:' with no reason — a reason is required, so this was NOT suppressed"
        fi
    done <<< "$hits"
done

# ── Summary ──────────────────────────────────────────────────────────────
if [ "$TOTAL" -eq 0 ]; then
    echo "✅ Assertion-strength: no weak assertions in $SCANNED staged test file(s)"
    exit 0
fi

RATE=$((SUPPRESSED * 100 / TOTAL))
echo ""
echo "📊 Assertion-strength: $TOTAL finding(s) in $SCANNED staged test file(s) — $ACTIVE active, $SUPPRESSED suppressed"
echo "   Suppression rate: ${RATE}% ($SUPPRESSED/$TOTAL) — target <20%"

if [ "$MODE" = "enforce" ] && [ "$ACTIVE" -gt 0 ]; then
    echo "❌ Assertion-strength gate FAILED (ASSERT_GATE=enforce): $ACTIVE unsuppressed weak assertion(s)"
    echo "   Strengthen the assertion, or annotate it with 'assert-ok: <reason>'"
    exit 1
fi

if [ "$ACTIVE" -gt 0 ]; then
    echo "⚠️  WARN mode — not blocking. Set ASSERT_GATE=enforce to make these fail the commit."
fi
exit 0
