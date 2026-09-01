#!/bin/bash
# Secret Detection Script
# Scans staged files for potential secrets before commit.
# Runs secret content scanning and filename checks.
#
# Installed by /harden-repo

set -eo pipefail

echo "🔍 Checking for secrets in staged files..."

# Check for common secret patterns in added lines only (exclude harden-repo's own
# installed scripts, docs/, hooks, CI).
# Scanning only '+' lines avoids blocking commits that remove leaked secrets.
#
# The shipped exclusion list is deliberately minimal and generic. Anything
# listed here is never scanned in ANY repo hardened from now on, so repo-
# specific exclusions are opt-in DATA rather than shipped code: an optional
# `.secret-scan-excludes` file at the repo root, one git pathspec per line,
# blank lines and '#' comments ignored. A repo that does codegen or scaffolding
# under, say, templates/ can exclude it there without every other repo
# inheriting the blind spot.
#
# That file is an attack surface — anyone who can commit can widen the scan's
# blind spot by adding a line to it — which is precisely why every exclusion it
# contributes is announced on stdout on every run. An exclusion nobody can see
# IS the silent failure. Do not make this announcement conditional or quiet.
#
# The scripts/ entries name harden-repo's five installed artifacts one by one
# rather than excluding the directory. `:!scripts/*` meant those five files --
# they hold the scan's own detection patterns, so scanning them would make the
# gate block itself -- but consumer repos keep their own scripts there too
# (measured: yellowstone-photography has scripts/verify-build.sh, local-llm has
# scripts/test-gates.sh). The blanket entry turned the content scan off for
# those, so an AKIA-shaped string staged in one passed clean AND
# commit-preflight still attested `secrets,` (#84).
EXCLUDES=(
  ':!scripts/bump-version.sh' ':!scripts/check-assertion-strength.sh'
  ':!scripts/commit-preflight.sh' ':!scripts/git-flow-finish.sh'
  ':!scripts/pre-commit.sh'
  ':!docs/*' ':!*.md' ':!.claude/hooks/*' ':!.github/workflows/*'
)
# Snapshot of the shipped half, kept so the "did the DATA FILE empty the scan?"
# check below can compare what the shipped list alone would have scanned
# against what actually gets scanned. Taken before any extras are appended.
SHIPPED_EXCLUDES=("${EXCLUDES[@]}")
EXTRA_EXCLUDES=()
EXCLUDES_FILE=".secret-scan-excludes"

# The announcement is the only thing that makes an attacker-influenceable
# exclusion list acceptable, so it has to be un-forgeable. Entries reach a
# terminal verbatim otherwise, and one carrying ESC or CR can erase the header,
# wipe preceding entries, or make a wide pathspec render as a narrow one —
# hiding or misrepresenting the very exclusion the announcement exists to
# disclose. Every byte outside printable-ASCII plus space becomes '?', and a
# tab becomes a single space: tab is printable-ish enough to survive the class
# test, but an entry of eight tabs plus '- (nothing excluded)' indents itself
# off to the right of the real entries as misdirection. Nothing was ever hidden
# — the script's own '   - ' prefix still marks the line — but collapsing the
# tab costs nothing and removes the trick.
sanitize_for_display() {
  printf '%s' "$1" | LC_ALL=C tr '\t' ' ' | LC_ALL=C tr -c '[:print:][:blank:]' '?'
}

if [ -f "$EXCLUDES_FILE" ]; then
  # `|| [ -n "$line" ]` is load-bearing: plain `read` returns non-zero at EOF
  # even when it did read a final line that lacks a trailing newline, and the
  # naive loop silently drops that line — i.e. silently scans a path the repo
  # believes it excluded.
  excludes_line_no=0
  while IFS= read -r line || [ -n "$line" ]; do
    excludes_line_no=$((excludes_line_no + 1))
    # A CRLF-saved file and a leading UTF-8 BOM both yield entries that match
    # nothing while still being announced as active. That fails closed — the
    # path is scanned, not skipped — but the announcement then tells the user a
    # path is excluded when it is not, and the announcement is the thing they
    # are supposed to trust. Normalise both so it agrees with the pathspec.
    line="${line%$'\r'}"
    if [ "$excludes_line_no" -eq 1 ]; then
      line="${line#$'\xef\xbb\xbf'}"
    fi
    # Leading whitespace is stripped for the comment test ONLY: `  # note` used
    # to become the pathspec `:!  # note`, inert yet announced as a real
    # exclusion. The entry itself is still taken verbatim — a git pathspec can
    # legitimately contain spaces, so general trimming would silently change
    # what it matches. Only blank and '#' lines are skipped.
    line_body="${line#"${line%%[!$' \t']*}"}"
    case "$line_body" in
      ''|'#'*) continue ;;
    esac
    EXTRA_EXCLUDES+=(":!$line")
    EXCLUDES+=(":!$line")
  done < "$EXCLUDES_FILE"

  echo "ℹ️  $EXCLUDES_FILE adds ${#EXTRA_EXCLUDES[@]} exclusion(s) to the secret content scan:"
  for extra_exclude in "${EXTRA_EXCLUDES[@]}"; do
    printf '   - %s\n' "$(sanitize_for_display "${extra_exclude#:!}")"
  done

  # The file is read from the WORKING TREE, not the index or HEAD, so a local
  # edit that widens the blind spot stays in force indefinitely while `git log`
  # and every PR diff show only the benign committed version. Purely a
  # disclosure: it never touches the exclusion set or the exit code, and every
  # edge case (no HEAD yet, file untracked, `git show` failing for any reason)
  # stays silent rather than guessing.
  if committed_excludes=$(git show "HEAD:./$EXCLUDES_FILE" 2>/dev/null); then
    if [ "$committed_excludes" != "$(cat "$EXCLUDES_FILE" 2>/dev/null)" ]; then
      echo "   (note: $EXCLUDES_FILE differs from the copy committed at HEAD —"
      echo "    the exclusions above are in force locally but are not what the"
      echo "    repository history shows.)"
    fi
  fi
fi

# The shipped exclusions were silent in a way the data file is not. Every entry
# the data file contributes is announced above, and checks A and B below say
# when those entries emptied the scan -- but a SHIPPED entry that swallowed a
# staged file said nothing at all, and only a repo that happens to have a data
# file reached the reporting at all. `scripts/*` was exactly that blind spot
# (#84). Hold the shipped half to the same standard: name the staged files it
# dropped, on every run, whether or not a data file exists.
#
# A notice, never a failure -- these paths are excluded on purpose, and a repo
# that legitimately commits only excluded files must still be able to commit.
# A git failure here is not fatal either: this block only DISCLOSES, and the
# STAGED_DIFF read further down refuses the commit on the same failure. Warning
# and carrying on avoids adding a second way to block a commit for a reporting
# feature, while still never passing the failure off as "nothing was dropped".
if ALL_STAGED=$(git diff --cached --name-only 2>/dev/null) &&
   SHIPPED_SCANNED=$(git diff --cached --name-only -- "${SHIPPED_EXCLUDES[@]}" 2>/dev/null); then
  SHIPPED_DROPPED=$(printf '%s\n' "$ALL_STAGED" | SHIPPED_SCANNED="$SHIPPED_SCANNED" awk '
    BEGIN { n = split(ENVIRON["SHIPPED_SCANNED"], a, "\n"); for (i = 1; i <= n; i++) still_scanned[a[i]] = 1 }
    $0 != "" && !($0 in still_scanned)')
  if [ -n "$SHIPPED_DROPPED" ]; then
    echo "ℹ️  The shipped exclusions keep these staged file(s) out of the secret content scan:"
    printf '%s\n' "$SHIPPED_DROPPED" | while IFS= read -r dropped_file; do
      printf '   - %s\n' "$(sanitize_for_display "$dropped_file")"
    done
  fi
else
  echo "⚠️  Could not list the staged files the shipped exclusions dropped."
fi

# Exclusions may NARROW the scan; they must never EMPTY it. A single entry like
# `*`, `.`, `/`, `!` or `**` expands to a pathspec that excludes the entire
# tree: `git diff --cached` returns nothing, grep finds nothing, and the run
# reports ✅ having inspected zero bytes — while the announcement prints that
# entry looking exactly like a legitimate one. Blocklisting the known
# nullifiers would be whack-a-mole (`[a-z]*` nullifies too), so this is
# enforced behaviourally instead.
#
# Two INDEPENDENT checks, on two different axes, answering two different
# questions. A runs on every invocation regardless of what is staged and can
# refuse the commit; B only reports on the commit in hand.
#
# CHECK A — "does the data file leave the REPOSITORY scannable at all?"
# Over-broadness is a property of the data file versus the tree, not versus one
# commit's staged set, so evaluating it only when a particular commit happens to
# empty the scan asks the question far too rarely.
#
# It is measured on the SCAN'S OWN YARDSTICK and DIFFERENTIALLY. "Scannable"
# here has to mean exactly what it means to the content scan below, or the check
# counts files the scan never reads as proof that the scan can still read
# something. It cannot: the scan applies `${SHIPPED_EXCLUDES[@]}` before it
# applies anything from the data file, so a survivor under `scripts/`, `docs/`,
# `*.md`, `.claude/hooks/` or `.github/workflows/` is no more scannable than the
# data file itself. A repo tracking `src/lib.py` and `scripts/deploy.sh` with the
# single entry
#     src/*
# leaves `scripts/deploy.sh` in the raw index and nothing at all in the scan:
# measured against the raw index that lone entry scores as narrow, the content
# scan is a permanent no-op, and an `AKIA…` key staged under `src/` commits clean
# with a ✅. Both sides therefore carry the shipped list — BASE_SURVIVORS is what
# the shipped exclusions alone leave scannable, SET_SURVIVORS what is left once
# the data file's entries are added — and only a set that takes a NON-EMPTY base
# to an EMPTY set is over-broad.
#
# The differential half is what stops the check blaming the innocent. A repo the
# shipped list alone already empties — a docs-only repo, a repo of nothing but
# `scripts/` — has an empty BASE_SURVIVORS, and the data file did not do that, so
# it is skipped rather than blamed. That is the same reasoning check B's baseline
# uses, and it subsumes the old "is anything tracked at all" precondition: a repo
# whose only tracked file is the data file has an empty base too, so there is
# nothing to measure and nothing to name.
#
# It is measured over the WHOLE ENTRY SET at once, never entry by entry: git
# INTERSECTS the exclusions, and that intersection is not distributive over a
# per-entry test. An ordinary two-directory repo needs no adversary to
# demonstrate it — tracked `src/lib.py`, `src/creds.py`, `test/test_lib.py` with
#     src/*
#     test/*
# in the data file leaves 1 survivor under the first entry alone, 2 under the
# second, and 0 under both. Every per-entry test passes; the content scan is a
# permanent no-op for that repo, for every future commit, and an `AKIA…` key
# staged under `src/` commits clean with a ✅.
#
# The data file itself is DISCOUNTED from both survivor sets, for the same reason
# the shipped exclusions are applied to them: `.secret-scan-excludes` lives at
# the repository root and is a tracked file, so virtually no entry covers it and
# it survives almost every exclusion set — leaving the set above looking "narrow"
# no matter how much of the tree it swallows. The `src/*` + `test/*` repo above
# measured 1 survivor, `.secret-scan-excludes`, and passed. A file whose only
# content is the exclusion list is a self-reference, not scannable project
# content: it can never be the thing the content scan protects, so counting it as
# the survivor that proves the repo scannable proves nothing.
#
# Blame is still attributed per entry where it can be: an entry that empties the
# tree on its OWN — measured on the same yardstick, shipped exclusions applied
# and the data file discounted, so the set test and the per-entry test can never
# disagree about what a survivor is — is named individually, and only when none
# does are the entries reported as jointly over-broad. Printing the single-entry
# message when no single entry is at fault would name an innocent line — a
# confident message that is simply wrong.
#
# CHECK B — "did the data file empty THIS commit's scan?" A notice, not a
# failure. An entry that is narrow against the repository can still legitimately
# cover everything one commit touches: a pure template-reconciliation commit here
# (`.github/workflows/ci.yml`, `CHANGELOG.md`, `scripts/*` and
# `templates/scripts/*` together) empties the scan without a single over-broad
# entry existing, and telling its author to "narrow the entries" — when every
# entry is already narrow and there is nothing to narrow — leaves deleting a real
# exclusion or bypassing the hook as the only ways out. A security control that
# blocks routine work gets switched off. The notice's claim that every entry is
# narrow is true only because check A has already passed: a survivor of the whole
# SET survives every individual entry too, and A measures survivors on the scan's
# own yardstick, so a passing A proves each entry leaves genuinely SCANNABLE
# files behind. A must therefore run first.
#
# B's trigger is measured against the SHIPPED list, never against the raw staged
# set: the shipped exclusions already cover `docs/` and `*.md`, so a docs-only or
# README-only commit legitimately scans nothing and must still pass. With no data
# file the two sets are identical by construction, so it can never fire.
#
# The data file is DISCOUNTED from BOTH sides of that trigger, exactly as it is
# in check A and for the same self-reference reason. Undiscounted, the one commit
# this notice matters most for silenced it: widening the blind spot and landing
# the secret it hides in a SINGLE commit stages `.secret-scan-excludes` itself,
# and that file is not shipped-excluded and rarely matches its own entries, so
# its own `+src/*` line keeps the actual-scan side non-empty and no notice fires
# at all. The only distinguishing output was the HEAD-drift note above, which
# fires on every commit that edits the file and says nothing about the scan being
# empty. Discounting both sides keeps the comparison like-for-like and about
# PROJECT content. The residue is narrow and deliberate: a commit whose only
# content-bearing staged file is the data file AND whose own entries cover the
# data file scans nothing and gets no notice — the only thing unscanned there is
# the exclusion list, every entry of which is announced verbatim above. The
# `STAGED_DIFF` capture that feeds the actual pattern scan is NOT discounted: the
# data file is still scanned for secrets like any other file.
#
# Both sides of that comparison measure CONTENT, not filenames. A staged change
# that contributes no scannable line — a mode-only change (`chmod +x`), a binary
# file, an empty file — keeps the file LIST non-empty while the content scan
# inspects zero bytes, so a filename-based trigger stayed silent for exactly the
# commits this notice exists to flag: an excluded secret file plus a `chmod +x`
# on another file printed ✅ with no notice at all. Applied to both sides so the
# comparison stays like-for-like, and a commit staging only mode changes with no
# data file present still produces no notice (the whole block is gated on the
# data file having contributed entries, and such a commit has an empty baseline
# either way).
#
# Every capture here sends stderr to /dev/null and never folds it in with
# `2>&1`: git can exit 0 and still write to stderr — a stale `core.fsmonitor`
# pointing at a missing hook makes every one of these commands print `fatal:
# cannot exec ...` while succeeding — and a captured `fatal:` line turns an
# EMPTY result into a non-empty one, which silently disables these checks
# entirely. The captured text is never read; only the exit status is.
if [ ${#EXTRA_EXCLUDES[@]} -gt 0 ]; then
  # ── Check A: is the repository still scannable at all? ──
  # Both survivor sets carry the SHIPPED exclusions and discount the data file —
  # see the yardstick and discount rationale above. BASE_SURVIVORS doubles as the
  # "is there anything to measure at all?" precondition: empty means the shipped
  # list alone already left nothing scannable, which the data file did not cause
  # and must not be blamed for.
  #
  # Known limitation, kept deliberately: this check establishes scan SCOPE —
  # whether a tracked file survives shipped ∪ extras — not content-readability.
  # A repo whose only in-scope survivor is binary (a checked-in `logo.png`,
  # say) passes here even though the content scan below can read no `+` line
  # from it. That is a different class from the pathspec-scope gaps this check
  # exists to close: the survivor genuinely IS in the scan's scope, and the
  # notice this check backstops still fires on the commit that matters. Making
  # this check content-aware would mean classifying every survivor's
  # readability on every commit — expensive, fragile, and disproportionate to
  # a gap that already fails loud rather than silent.
  if ! BASE_SURVIVORS=$(git ls-files -- "${SHIPPED_EXCLUDES[@]}" ":!$EXCLUDES_FILE" 2>/dev/null); then
    echo ""
    echo "❌ ERROR: Failed to read the tracked file list for secret scanning."
    exit 1
  fi
  if [ -n "$BASE_SURVIVORS" ]; then
    if ! SET_SURVIVORS=$(git ls-files -- "${EXCLUDES[@]}" ":!$EXCLUDES_FILE" 2>/dev/null); then
      echo ""
      echo "❌ ERROR: Failed to evaluate the exclusions from $EXCLUDES_FILE."
      exit 1
    fi
    if [ -z "$SET_SURVIVORS" ]; then
      SOLO_OVERBROAD=()
      for guard_entry in "${EXTRA_EXCLUDES[@]}"; do
        if ! entry_survivors=$(git ls-files -- "${SHIPPED_EXCLUDES[@]}" "$guard_entry" ":!$EXCLUDES_FILE" 2>/dev/null); then
          echo ""
          echo "❌ ERROR: Failed to evaluate an exclusion from $EXCLUDES_FILE."
          exit 1
        fi
        if [ -z "$entry_survivors" ]; then
          SOLO_OVERBROAD+=("${guard_entry#:!}")
        fi
      done
      echo ""
      echo "❌ ERROR: $EXCLUDES_FILE excludes EVERY tracked file the secret scan"
      echo "could still have read!"
      echo ""
      # "Survives" means survives the SCAN, not the index: a file the shipped
      # exclusions already cover was never going to be read, so it cannot stand
      # as proof that something still is. Same for the data file itself.
      if [ ${#SOLO_OVERBROAD[@]} -gt 0 ]; then
        echo "Each of these entries excludes the ENTIRE repository on its own — no"
        echo "scannable file survives it:"
        for overbroad_entry in "${SOLO_OVERBROAD[@]}"; do
          printf '  %s\n' "$(sanitize_for_display "$overbroad_entry")"
        done
      else
        echo "No single entry here is over-broad — each one leaves other scannable"
        echo "files behind — but TOGETHER they cover the whole repository, so"
        echo "nothing is left for the content scan to inspect:"
        for joint_entry in "${EXTRA_EXCLUDES[@]}"; do
          printf '  %s\n' "$(sanitize_for_display "${joint_entry#:!}")"
        done
      fi
      # Context only, on a path that is already exiting 1: if this cannot be
      # read the refusal still stands, it just loses one section.
      GUARD_BASELINE=$(git diff --cached --name-only -- "${SHIPPED_EXCLUDES[@]}" 2>/dev/null) || GUARD_BASELINE=""
      if [ -n "$GUARD_BASELINE" ]; then
        echo ""
        echo "Without $EXCLUDES_FILE, these staged file(s) would have been scanned:"
        printf '%s\n' "$GUARD_BASELINE" | while IFS= read -r baseline_file; do
          printf '  %s\n' "$(sanitize_for_display "$baseline_file")"
        done
      fi
      echo ""
      echo "The content scan can inspect nothing — not in this commit and not in any"
      echo "future one — so it cannot vouch for this commit or any that follow."
      echo "Exclusions may narrow the scan; they must never empty it."
      echo ""
      echo "Remove or narrow the entries above — a bare '*', '.', '/', '!' or '**'"
      echo "excludes the whole repository."
      exit 1
    fi
  fi

  # ── Check B: did the data file empty THIS commit's content scan? ──
  # `:!$EXCLUDES_FILE` on BOTH sides — the trigger only. Without it the data
  # file's own staged diff sits on the actual side and suppresses the notice on
  # the widen-and-land-in-one-commit case this exists to catch; see above.
  if ! SCAN_BASELINE_DIFF=$(git diff --cached -- "${SHIPPED_EXCLUDES[@]}" ":!$EXCLUDES_FILE" 2>/dev/null) ||
     ! SCAN_ACTUAL_DIFF=$(git diff --cached -- "${EXCLUDES[@]}" ":!$EXCLUDES_FILE" 2>/dev/null); then
    echo ""
    echo "❌ ERROR: Failed to read staged diffs for secret scanning."
    exit 1
  fi
  # `grep -q` is deliberately not used: it closes the pipe on its first match,
  # and under `pipefail` the producer's SIGPIPE would become the status of the
  # whole pipeline. Capture and test for emptiness instead.
  BASELINE_CONTENT=$(printf '%s\n' "$SCAN_BASELINE_DIFF" | grep '^+' | grep -v '^+++') || BASELINE_CONTENT=""
  ACTUAL_CONTENT=$(printf '%s\n' "$SCAN_ACTUAL_DIFF" | grep '^+' | grep -v '^+++') || ACTUAL_CONTENT=""
  if [ -n "$BASELINE_CONTENT" ] && [ -z "$ACTUAL_CONTENT" ]; then
    if ! SCAN_BASELINE=$(git diff --cached --name-only -- "${SHIPPED_EXCLUDES[@]}" 2>/dev/null) ||
       ! SCAN_ACTUAL=$(git diff --cached --name-only -- "${EXCLUDES[@]}" 2>/dev/null); then
      echo ""
      echo "❌ ERROR: Failed to read staged file list for secret scanning."
      exit 1
    fi
    # Name only the files the DATA FILE actually removed from the scan's scope.
    # The baseline list alone would also name files that are still in scope and
    # merely contributed no scannable line — the `chmod +x` that motivated the
    # content-based trigger is exactly such a file — telling the reader the data
    # file excluded something it did not. This cannot come out empty while the
    # notice is firing: the trigger means some staged file OTHER THAN the data
    # file contributed content to the baseline and none survived into the actual
    # scan, so at least one content-bearing file was removed. The lists here are
    # NOT discounted — if the data file's own entries also cover the data file,
    # saying so is informative rather than misleading.
    SCAN_REMOVED=$(printf '%s\n' "$SCAN_BASELINE" | SCAN_ACTUAL="$SCAN_ACTUAL" awk '
      BEGIN { n = split(ENVIRON["SCAN_ACTUAL"], a, "\n"); for (i = 1; i <= n; i++) still_scanned[a[i]] = 1 }
      $0 != "" && !($0 in still_scanned)')
    echo ""
    echo "⚠️  NOTICE: the secret CONTENT scan inspected nothing in this commit."
    echo ""
    echo "$EXCLUDES_FILE covers every staged file the shipped exclusions did not"
    echo "already cover, so no staged content reached the pattern scan. Without it"
    echo "these would have been scanned:"
    printf '%s\n' "$SCAN_REMOVED" | while IFS= read -r baseline_file; do
      printf '  %s\n' "$(sanitize_for_display "$baseline_file")"
    done
    echo ""
    echo "This is not an error: every entry above is narrow — check A has already"
    echo "established that each one leaves other files IN THE SCAN'S SCOPE"
    echo "elsewhere in the repository — so this commit simply touches only"
    echo "excluded paths. The .env check and the secret-filename gate still apply"
    echo "below."
  fi
fi

# Same `2>/dev/null` discipline as the guard above. Benign here rather than
# load-bearing — an injected `fatal:` line does not start with '+', so the grep
# below drops it — but the value is used for a decision, and relying on the
# shape of git's error text to stay harmless is not a property worth depending
# on.
if ! STAGED_DIFF=$(git diff --cached -- "${EXCLUDES[@]}" 2>/dev/null); then
  echo ""
  echo "❌ ERROR: Failed to read staged diff for secret scanning."
  exit 1
fi

# Hoisted out of the pipeline below so its exit status can be read separately
# from the two structural greps, and so the failure path can be exercised by
# substituting a pattern that does not compile.
SECRET_PATTERN="(sk-[a-zA-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|private_key|-----BEGIN.*PRIVATE KEY-----|ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|xox[bsapr]-[a-zA-Z0-9-]+|password\s*[:=]\s*['\"][^'\"]{8,})"

# grep exit 1 is "no match"; grep exit 2 is "grep itself FAILED". Run as one
# pipeline ending in `2>/dev/null` the two were indistinguishable, and a failure
# fell straight through to "✅ No secret content detected" — the entire content
# scan silently disabled while the run reported success over an uninspected
# diff. Invalid UTF-8 in staged content cannot reach it (measured: BSD grep on
# macOS exits 1 on that), so the realistic trigger is a future edit to
# SECRET_PATTERN that does not compile as an ERE — the one change whose blast
# radius is the whole scan.
#
# Split into one grep per statement rather than kept as a single pipeline
# because `pipefail` reports the RIGHTMOST non-zero status: a 2 from `grep '^+'`
# followed by a legitimate 1 from `grep -v '^+++'` would be reported as 1 and
# read as "no match". Per stage they cannot be confused. A 1 from either
# structural grep is legitimate — a staged diff with no added lines — and must
# stay "no match"; a 2 from ANY stage is fatal. grep's own stderr is
# deliberately not discarded here: "brackets ([ ]) not balanced" is the whole
# diagnosis, and nothing is captured with `2>&1`, so it cannot corrupt a value.
scan_grep_failed() {
  echo ""
  echo "❌ ERROR: the secret content scan could not run."
  echo ""
  echo "grep exited $2 on the '$1' stage. Exit 2 means grep FAILED — it does not"
  echo "mean the diff is clean. The most likely cause is an edit to SECRET_PATTERN"
  echo "in this script that no longer compiles as a POSIX extended regex; grep's"
  echo "own message above says which."
  echo ""
  echo "Refusing the commit: a scan that did not run cannot vouch for anything."
  exit 1
}

scan_status=0
SCAN_ADDED=$(printf '%s\n' "$STAGED_DIFF" | grep '^+') || scan_status=$?
if [ "$scan_status" -ge 2 ]; then
  scan_grep_failed "added-line" "$scan_status"
fi

scan_status=0
SCAN_ADDED=$(printf '%s\n' "$SCAN_ADDED" | grep -v '^+++') || scan_status=$?
if [ "$scan_status" -ge 2 ]; then
  scan_grep_failed "diff-header" "$scan_status"
fi

scan_status=0
SCAN_HITS=$(printf '%s\n' "$SCAN_ADDED" | grep -E "$SECRET_PATTERN") || scan_status=$?
if [ "$scan_status" -ge 2 ]; then
  scan_grep_failed "pattern" "$scan_status"
fi

if [ "$scan_status" -eq 0 ]; then
  printf '%s\n' "$SCAN_HITS"
  echo ""
  echo "❌ ERROR: Potential secret detected in staged files!"
  echo ""
  echo "Found patterns that look like:"
  echo "  - OpenAI API keys (sk-...)"
  echo "  - AWS access keys (AKIA...)"
  echo "  - Private keys (-----BEGIN...PRIVATE KEY-----)"
  echo "  - GitHub tokens (ghp_..., gho_..., github_pat_...)"
  echo "  - Slack tokens (xox...)"
  echo "  - Password assignments"
  echo ""
  echo "Please remove secrets before committing."
  echo "Use environment variables instead!"
  exit 1
fi

# Check for .env files (except .env.example and .env.local.example)
STAGED_ENV=$(git diff --cached --name-only | grep -E '\.env(\..+)?$' | grep -v '\.example$' || true)
if [ -n "$STAGED_ENV" ]; then
  echo ""
  echo "❌ ERROR: Attempting to commit .env file(s)!"
  echo ""
  echo "The following .env files are staged:"
  echo "$STAGED_ENV"
  echo ""
  echo "These files should NEVER be committed."
  echo "Run: git reset HEAD <file>"
  exit 1
fi

# Check for common secret filenames
SECRET_FILES=$(git diff --cached --name-only | grep -E '(credentials\.json|serviceAccount\.json|\.pem$|\.key$|\.p12$|\.pfx$)' || true)
if [ -n "$SECRET_FILES" ]; then
  # Block truly binary secret containers that content scan cannot inspect
  BINARY_SECRET_FILES=$(echo "$SECRET_FILES" | grep -E '\.(p12|pfx)$' || true)
  if [ -n "$BINARY_SECRET_FILES" ]; then
    echo ""
    echo "❌ ERROR: Binary secret files staged (cannot be content-scanned):"
    echo "$BINARY_SECRET_FILES"
    echo ""
    echo "These file types commonly contain private keys or certificates."
    echo "Run: git reset HEAD <file>"
    exit 1
  fi

  # The filename gate is authoritative, not advisory: the content scan above
  # carries pathspec exclusions (scripts/, docs/, *.md, hooks, CI, plus
  # anything this repo's .secret-scan-excludes adds), so a plaintext PEM key
  # committed under any of those paths is never scanned at all — and a
  # DER-encoded .key/.pem produces no '+' lines for grep to read even outside
  # them. Never downgrade this to a warning.
  echo ""
  echo "❌ ERROR: Secret-bearing filenames staged:"
  echo "$SECRET_FILES"
  echo ""
  echo "These file types commonly contain private keys or credentials."
  echo "Run: git reset HEAD <file>"
  exit 1
fi

echo "✅ No secret content detected in staged diffs"
