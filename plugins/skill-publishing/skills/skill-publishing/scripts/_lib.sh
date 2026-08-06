#!/usr/bin/env bash
# _lib.sh — Shared utility functions for skill-publishing scripts
# Source this file: source "$SCRIPT_DIR/_lib.sh"
# Requires: DRY_RUN variable set by the caller (default: false)

# Guard: prevent direct execution
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Error: source this file, don't execute it directly" >&2
  echo "Usage: source \"\$SCRIPT_DIR/_lib.sh\"" >&2
  exit 1
fi

# ============================================================
# Frontmatter extraction
# ============================================================

# Extract a top-level field from SKILL.md YAML frontmatter, decoding the YAML
# scalar style it is written in.
# Usage: extract_field <skill_md_path> <field_name>
#
# The previous implementation was `grep "^field:" | head -1 | sed` with two
# unconditional quote strips, which had three defects at once (issues #37, #102,
# and one unfiled). All three share a root cause — reading the line as raw text
# rather than as a YAML scalar — so they are closed together:
#
#   >- / |-   a block scalar carries no text on its own line, so the old reader
#             returned the literal indicator ">-" and prepare-plugin.sh wrote
#             that into the generated README (#37). In Markdown ">-" renders as
#             an empty blockquote, so the failure was silent.
#   "\"…\""   only the OUTER quote pair was removed, so every internal \" was
#             emitted verbatim into the README (#102).
#   unfiled   `s/^["']//; s/["']$//` fires on the first and last character
#             unconditionally and independently, so a PLAIN scalar that merely
#             starts with a quote — `description: "quoted" is a word` — lost its
#             leading ". Quotes are now stripped only when the value genuinely
#             opens and closes with the same quote character.
#
# awk rather than a YAML library: awk is already a dependency of this file
# (extract_section, extract_headings) and of validate-skill.sh, so this adds no
# new runtime requirement. validate-skill.sh:96 has its OWN single-argument
# extract_field which folds block scalars but does not unescape; it is the
# reference for the folding logic here, not shared code — the signatures differ.
#
# Portability: POSIX awk only, so this runs on macOS BSD awk and gawk alike. The
# quote characters are written as the octal escapes \047 and \042 so that no
# literal ' has to appear inside the shell-single-quoted program body.
#
# SINGLE-LINE OUTPUT IS A CONTRACT, not an accident of the implementation. Every
# consumer splices this value into a single-line context: sync-monorepo.sh:604
# builds a Markdown TABLE ROW out of it, and prepare-plugin.sh emits it as a
# `- \`name\` — <desc>` list item. A newline in the value breaks the table at
# exit 0 — a corrupt artifact with a green run. The old `grep | head -1` reader
# was structurally incapable of returning two lines; this one has to enforce
# that deliberately, at the single point where the value is built rather than at
# each of the five consumers. Three consequences, all intentional:
#   - a LITERAL `|` block scalar is FOLDED to spaces exactly like `>`, so it does
#     NOT preserve newlines the way YAML says it should. validate-skill.sh:121-131
#     folds `|` and `>` identically too, so the two readers agree on this point.
#     Folding a `|` block can CHANGE MEANING (two imperative lines become one
#     run-on sentence), so a multi-line `|` now emits a note on stderr naming the
#     file and field. It is a note rather than an error because the fold is the
#     contract; the author who wrote `|` is simply not getting what they asked
#     for and nothing else would tell them.
#   - `\n`, `\t` and `\r` in a double-quoted scalar decode to a SPACE, not to the
#     control character, so `"a\n\nb"` yields `a b`. The collapse acts on exactly
#     the whitespace the decode introduced — see unescape_double below — so a
#     deliberate double space anywhere in the value survives regardless of what
#     escapes appear elsewhere in it.
#   - a literal CR/VT/FF byte in the source line is replaced with a space at the
#     single emit() point. None of the three is a YAML escape, so they otherwise
#     travel into the value untouched and land inside a Markdown table cell.
#
# UNRECOGNIZED BLOCK HEADERS FAIL, they do not fall through. A value that begins
# with `|` or `>` but does not match the header grammar (`>10`, `>--`, `>2x`)
# used to reach the plain-scalar path and be returned AS the description — the
# literal indicator in the generated README, which is issue #37 exactly. That
# fail-open shape has now produced #37 three times, so extract_field writes a
# diagnostic to stderr and exits 3 instead.
#
# WHAT `exit 3` DOES IS A PROPERTY OF THE CALL SITE, NOT OF THIS FUNCTION. The
# previous version of this paragraph analysed prepare-plugin.sh's four reads and
# no others, which left three of the six calling scripts undescribed and implied
# a uniformity the code does not have. Every call site, in the same table form
# as the SKILLS_HOME analysis further down (line numbers are the assignment):
#
#     call site                          shape of the read            effect of exit 3
#     prepare-plugin.sh:420              bare `X=$(extract_field …)`  ABORTS the run
#     prepare-skill-repo.sh:69,70        bare `X=$(extract_field …)`  ABORTS the run
#     sync-monorepo.sh:579,580           bare `X=$(extract_field …)`  ABORTS the run
#     sync-monorepo.sh:1633              bare `X=$(extract_field …)`  ABORTS the run
#     sync-individual-repos.sh:219,220   bare `X=$(extract_field …)`  ABORTS the run
#     release-monorepo.sh:172            bare `X=$(extract_field …)`  ABORTS the run
#     prepare-plugin.sh:462,481,502      `2>/dev/null || echo ""`     SUPPRESSED to ""
#
#   (validate-skill.sh:159/188 are NOT in this table: that script has its own
#   single-argument extract_field — see the note above — and never calls this
#   one.)
#
#   ABORTS is the intended contract: a description the reader cannot decode must
#   stop the build, not become a corrupt artifact at exit 0. It holds only
#   because each of those is a bare assignment from a SINGLE command
#   substitution, whose rc is the command's and which `set -e` therefore acts
#   on. Two rewrites of that shape silently give the rc away, and BOTH have
#   already happened in this directory:
#
#     - `X=$(extract_field … | sed …)` — the rc is the PIPELINE's, i.e. the last
#       command's, i.e. sed's, and no script here sets `pipefail`. exit 3
#       arrived as rc 0 with an empty $X: a description-less CHANGELOG/release
#       inventory row written at exit 0, which is precisely the fail-open shape
#       this guard exists to remove. That was sync-monorepo.sh:1633 and
#       release-monorepo.sh:172 until they were rewritten as two statements.
#     - `X=$(short_desc "$(extract_field …)")` — measured, this swallows it too.
#       The assignment's rc is the OUTER substitution's (short_desc's, i.e.
#       sed's, i.e. 0); the inner substitution's 3 is discarded. So the fix is
#       deliberately `X=$(extract_field …)` then `Y=$(short_desc "$X")`, and any
#       future site that nests this read inside another command's word reopens
#       the hole with no visible change at the call.
#
#   SUPPRESSED is prepare-plugin.sh's three SECONDARY reads (462/481/502), which
#   already wrap the call in `2>/dev/null || echo ""`: for a non-primary skill,
#   command or agent the guard degrades to an empty description with the
#   diagnostic suppressed. Pre-existing behaviour, not introduced here, and named
#   so the next reader does not mistake the guard for total coverage.
#
#   TEST COVERAGE OF THIS TABLE IS PARTIAL, stated rather than implied.
#   scripts/test-sync-hygiene.sh drives a bad-header fixture through
#   prepare-plugin.sh:420 (rc pinned to exactly 3), through sync-monorepo.sh's
#   main loop at 579/580 (rc pinned to exactly 3, and no catalogue row or
#   CHANGELOG written), and through release-monorepo.sh:172 (rc pinned to exactly
#   3, and no versioned CHANGELOG entry written). sync-monorepo.sh:1633 has no
#   rc assertion and cannot get one: its own main loop reads every description
#   at 579/580 first, so a bad header can never reach line 1633 — what is pinned
#   there is the OUTPUT of the rewrite (the short_desc trailing period), not its
#   rc. prepare-skill-repo.sh and sync-individual-repos.sh have no harness
#   coverage at all, and the SUPPRESSED row is asserted only indirectly.
#
# Not handled, deliberately. Treat this as the audit's findings at the time it
# was run, NOT as a proof of exhaustiveness — the previous version of this
# comment claimed to be exhaustive and was already missing the block-scalar
# newline and blank-line cases now listed below:
#   - a trailing `# comment` on a plain scalar is preserved rather than stripped
#     (the old reader kept it too; changing that is unrelated scope);
#   - flow collections/anchors/aliases are not parsed;
#   - a QUOTED scalar wrapped across several lines (valid YAML line folding) is
#     read as its first line only, so it keeps a leading quote and loses the
#     rest. Block scalars are the supported way to wrap, and are handled above.
#   - double-quoted \uXXXX / \xXX numeric escapes yield the literal letter, not
#     the code point; only \n, \t, \r are given a meaning of their own (a space).
#   - a BLANK LINE inside a block scalar is dropped rather than becoming the
#     paragraph break YAML gives it, for the same single-line reason.
#   - chomping and indentation indicators are ACCEPTED but ignored: `>`, `>-`,
#     `>+`, `>2`, `>-2` and `>2-` all parse, and all fold the same way. Trailing
#     newlines are meaningless once the value is one line. Anything else after a
#     `|`/`>` is rejected rather than ignored — see the guard above.
#   - a literal SOH (\001) byte in a double-quoted scalar becomes a space: that
#     byte is used as the internal marker for decoded whitespace, so it is
#     neutralised on entry. Other stray control bytes reach emit(), which maps
#     CR/VT/FF to a space and passes the rest through.
# Audited across all 44 SKILL.md files in the monorepo: none uses a flow
# collection, anchor, numeric escape, or a multi-line quoted scalar for a
# top-level field, so every one of these is latent rather than live. Re-run that
# audit before relying on this list.
extract_field() {
  local skill_md="$1"
  local field="$2"
  awk -v field="$field" '
    BEGIN {
      SQ = "\047"; DQ = "\042"
      # Internal marker for whitespace this parser DECODED, so the collapse
      # below can tell it apart from whitespace the author wrote. SOH is not
      # legal content in a description; unescape_double neutralises any literal
      # occurrence on entry so it cannot be confused with a marker.
      SENT = "\001"
      SENTRUN = "[ \t]*" SENT "([ \t]*" SENT ")*[ \t]*"
    }

    # The SINGLE output point, so every exit path gets the same scrub. A literal
    # CR, VT or FF byte in the source line is not a YAML escape and so reaches
    # here untouched, and the value is spliced into a Markdown table row
    # (sync-monorepo.sh:604) and a list item, where a bare CR corrupts the cell.
    # They become a space — the same meaning \r already has when written as an
    # escape. printf "%s", never a bare value used as a format: descriptions
    # contain %.
    function emit(s) {
      gsub(/[\r\v\f]/, " ", s)
      printf "%s\n", s
    }

    # Double-quoted YAML: \n, \t and \r become a SPACE (see the single-line
    # contract above — a control character here would break the Markdown table
    # row this value ends up in); every other \<c> yields a literal <c>, which
    # is what turns \" into " and \\ into \. Scanned left to right in ONE pass
    # so a trailing \\" cannot be mistaken for an escaped quote.
    #
    # The decoded whitespace is written as SENT rather than as a space directly,
    # so the collapse acts on EXACTLY the whitespace this function introduced.
    # The earlier version set a `sawws` flag and then collapsed every run of
    # spaces in the whole value, which made the rewrite NON-LOCAL: measured,
    # "Cost:  100  USD." kept its double spaces, but appending "\tNote." to the
    # END silently reformatted the BEGINNING. A run of SENT (with any literal
    # spaces or tabs touching it) becomes one space; at either end it disappears.
    # With no escape decoded there is no SENT, so nothing is rewritten and the
    # value is returned byte-for-byte.
    function unescape_double(s,   out, i, n, c) {
      gsub(SENT, " ", s)
      out = ""; n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c == "\\" && i < n) {
          i++
          c = substr(s, i, 1)
          if (c == "n" || c == "t" || c == "r") out = out SENT
          else                                  out = out c
        } else {
          out = out c
        }
      }
      if (index(out, SENT)) {
        sub("^" SENTRUN, "", out)
        sub(SENTRUN "$", "", out)
        gsub(SENTRUN, " ", out)
      }
      return out
    }

    # Single-quoted YAML has exactly one escape: a doubled quote.
    function unescape_single(s,   out, i, n, c) {
      out = ""; n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c == SQ && substr(s, i + 1, 1) == SQ) { out = out SQ; i++ }
        else out = out c
      }
      return out
    }

    # Collect the frontmatter into an array rather than streaming it: a block
    # scalar needs the lines AFTER the key, which a line-at-a-time reader
    # cannot see.
    $0 == "---" { d++; if (d >= 2) exit; next }
    d == 1 { fm[++nf] = $0 }

    END {
      pat = "^" field ":"
      for (i = 1; i <= nf; i++) if (fm[i] ~ pat) { idx = i; break }
      if (!idx) exit 0

      val = fm[idx]
      sub(pat "[ \t]*", "", val)
      sub(/[ \t]+$/, "", val)

      # FAIL-CLOSED on a `|`/`>` that is not a legal block header. This test runs
      # BEFORE the block branch on purpose: without it an unrecognized header
      # falls through to the plain-scalar path and the INDICATOR is returned as
      # the description — `description: >10` measured as `[>10]`, `>--` as
      # `[>--]`. That is the failure mode of issue #37, and the fail-open shape has
      # now produced it three times. See the caller analysis in the header
      # comment for why exit 3 is the right contract at prepare-plugin.sh:420.
      if (val ~ /^[|>]/ && val !~ /^[|>]([0-9][+-]?|[+-][0-9]?)?[ \t]*(#.*)?$/) {
        printf "extract_field: %s: unrecognized block-scalar header for %s: %s\n", FILENAME, field, val > "/dev/stderr"
        exit 3
      }

      # Block scalar: > or |, with optional indentation and chomping indicators
      # and an optional trailing comment.
      #
      # The indicators may appear in EITHER order — YAML permits chomping before
      # indentation — so `>-2` and `>2-` are both legal headers. The earlier
      # `[0-9]*[+-]?` accepted only the second, which meant `description: >-2`
      # fell through to the plain-scalar path and returned the literal ">-2":
      # the exact failure of issue #37, reproduced inside the fix for #37. Hence the
      # explicit two-branch alternation rather than a looser character class,
      # which would also match nonsense like `>--` or `>22`.
      if (val ~ /^[|>]([0-9][+-]?|[+-][0-9]?)?[ \t]*(#.*)?$/) {
        # NOT `fold = (substr(val,1,1) == ">")`: | folds to spaces too, because
        # the return value must stay single-line. See the contract above.
        out = ""; first = 1; nlines = 0
        for (i = idx + 1; i <= nf; i++) {
          line = fm[i]
          if (line ~ /^[^ \t]/) break        # a non-indented line ends the block
          if (line ~ /^[ \t]*$/) continue    # skip blanks (no double separators)
          sub(/^[ \t]+/, "", line)
          sub(/[ \t]+$/, "", line)           # else the join would double-space
          nlines++
          if (first) { out = line; first = 0 }
          else       { out = out " " line }
        }
        # Folding a LITERAL block is correct here (single-line contract) but it
        # can change MEANING, and did so silently: measured, a `|` block of
        # "Deletes the cache" / "Only when --force is given" comes back as one
        # run-on sentence. An author who wrote `|` asked for newlines; nothing
        # else in the pipeline would tell them they are not getting any. A note,
        # not an error — the fold is deliberate.
        if (substr(val, 1, 1) == "|" && nlines > 1) {
          printf "extract_field: %s: %s is a literal (|) block scalar of %d lines, folded to one line to keep the value single-line; write it as > if the fold is intended\n", FILENAME, field, nlines > "/dev/stderr"
        }
        emit(out)
        exit 0
      }

      # Quoted scalar: strip ONLY when the same quote both opens and closes the
      # value. `"quoted" is a word` opens with a quote but does not close with
      # one, so it is a plain scalar and is returned untouched.
      #
      # This NARROWS the ambiguity, it does not resolve it: `"a" and "b"` also
      # opens and closes with `"` and is still stripped (to `a" and "b`), as is
      # any plain scalar whose first and last characters happen to be the same
      # quote. Distinguishing those needs a real YAML parse of the whole line;
      # the old reader mangled both this case and the far commoner
      # `"quoted" is a word`, and only the latter is closed here.
      n = length(val)
      if (n >= 2) {
        f = substr(val, 1, 1); l = substr(val, n, 1)
        if (f == DQ && l == DQ) { emit(unescape_double(substr(val, 2, n - 2))); exit 0 }
        if (f == SQ && l == SQ) { emit(unescape_single(substr(val, 2, n - 2))); exit 0 }
      }

      emit(val)
    }
  ' "$skill_md"
}

# Extract metadata.version from SKILL.md frontmatter
# Usage: extract_version <skill_md_path>
extract_version() {
  local skill_md="$1"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "version:" | head -1 | \
    sed 's/.*version:[[:space:]]*//; s/^[\"'"'"']//; s/[\"'"'"']$//'
}

# Trim description at "Use when:" to produce a short description
# Usage: short_desc <description_text>
#
# printf, not `echo "$1"`: bash's builtin echo consumes a leading -n/-e/-E as an
# option, so a description legitimately starting with one would lose it (and,
# for -n, the trailing newline too). Unreachable in today's catalogue, which is
# exactly why it would not be noticed when it stops being unreachable.
short_desc() {
  printf '%s\n' "$1" | sed 's/\. Use when:.*/\./'
}

# Extract content under a ## heading (returns lines until next ## or EOF)
# Uses awk for BSD/GNU portability, perl for blank-line trimming.
# Usage: extract_section <file> <heading_text>
# Example: extract_section SKILL.md "Quick Check"
extract_section() {
  local file="$1"
  local heading="$2"
  awk -v h="$heading" '
    $0 == "## " h { found=1; next }
    found && /^## / { exit }
    found { print }
  ' "$file" 2>/dev/null | perl -0777 -pe 's/\A\s*\n//; s/\n\s*\z//'
}

# Extract ## heading titles from markdown (after frontmatter)
# Usage: extract_headings <file> [max_count]
# Returns one heading per line, frontmatter skipped
extract_headings() {
  local file="$1"
  local max="${2:-10}"
  awk '/^---$/{fm++; next} fm>=2{print}' "$file" 2>/dev/null | \
    grep '^## ' | head -"$max" | sed 's/^## //'
}

# ============================================================
# File operations (DRY_RUN-aware)
# ============================================================

# Write content to a file (skip if exists, unless overwrite=true)
# Usage: write_file <filepath> <content> <label> [overwrite]
# Requires: DRY_RUN variable in calling scope
write_file() {
  local filepath="$1"
  local content="$2"
  local label="$3"
  local overwrite="${4:-false}"

  if [[ -f "$filepath" ]] && [[ "$overwrite" != "true" ]]; then
    echo "  SKIP    $label (already exists)"
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$filepath" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD CREATE  $label"
    fi
  else
    mkdir -p "$(dirname "$filepath")"
    echo "$content" > "$filepath"
    if [[ "$overwrite" == "true" ]]; then
      echo "  SYNCED  $label"
    else
      echo "  CREATED $label"
    fi
  fi
}

# Copy a single file
# Usage: copy_file <src> <dst> <label>
# Requires: DRY_RUN variable in calling scope
copy_file() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -f "$src" ]]; then
    return
  fi

  # Source and destination are the same file (in-repo source directory):
  # `cp a a` fails, and under `set -e` that aborts the whole sync. `-ef`
  # compares device + inode, so symlink and hardlink aliases are caught too.
  if [[ "$src" -ef "$dst" ]]; then
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$dst" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD COPY    $label"
    fi
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  SYNCED  $label"
  fi
}

# Copy a directory via rsync (excluding .git, .claude, .DS_Store)
# Usage: copy_dir <src> <dst> <label>
# Requires: DRY_RUN variable in calling scope
copy_dir() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -d "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    local count
    count=$(find "$src" -type f | wc -l | tr -d ' ')
    echo "  WOULD COPY    $label ($count files)"
  else
    mkdir -p "$dst"
    rsync -a --delete --exclude='.git' --exclude='.claude' --exclude='.DS_Store' "$src/" "$dst/"
    echo "  SYNCED  $label"
  fi
}

# ============================================================
# GitHub / path utilities
# ============================================================

# Auto-detect GitHub username via gh CLI
# Usage: resolve_github_user
# Sets GITHUB_USER in caller scope (expects it to exist, possibly empty)
resolve_github_user() {
  if [[ -z "$GITHUB_USER" ]]; then
    GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
    if [[ -z "$GITHUB_USER" ]]; then
      echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
      exit 1
    fi
  fi
}

# Expand ~ to $HOME in a path
# Usage: resolve_tilde <path>
resolve_tilde() {
  echo "${1/#\~/$HOME}"
}

# Resolve a manifest-declared source path.
#   $1 = the raw source string from the manifest
#   $2 = the directory containing the manifest
# A leading ~ expands to $HOME. An absolute path is returned unchanged. A
# relative path resolves against the MANIFEST's directory, not the caller's
# cwd, so in-repo-source manifests work from anywhere. An empty source stays
# empty so callers report "source not found" rather than silently assembling
# the manifest's own directory.
resolve_source_path() {
  local raw="$1" manifest_dir="$2" expanded
  if [[ -z "$raw" ]]; then
    echo ""
    return
  fi
  expanded="$(resolve_tilde "$raw")"
  case "$expanded" in
    /*) echo "$expanded" ;;
    *)  echo "${manifest_dir%/}/$expanded" ;;
  esac
}

# Resolve a skill's authoring source: the local skills home if present, else an
# in-repo top-level directory (the arrangement introduced when skills moved into
# the monorepo). Local-first precedence keeps behaviour identical while both
# copies exist, and hands over automatically once the local copy is removed.
# Echoes nothing when the skill has no source anywhere.
# Usage: skill_source_dir <skill-name>
# Requires: SKILLS_HOME set by the caller. Deliberately unwrapped, unlike
#   MONOREPO_DIR below — an unset SKILLS_HOME must abort rather than silently
#   resolve to "/<name>/SKILL.md".
#
#   An earlier version said "every current caller sets it before sourcing this
#   file". That is FALSE: "before sourcing this file" ties "caller" to the
#   scripts that source _lib.sh, and two of the six do not set SKILLS_HOME.
#   Measured, because the first correction of this comment ALSO got it wrong —
#   it said three, having inherited the list from the MONOREPO_DIR paragraph
#   below without re-deriving it:
#
#     script                     sets SKILLS_HOME   calls skill_source_dir
#     prepare-plugin.sh                 no                   no
#     prepare-skill-repo.sh             no                   no
#     release-monorepo.sh               yes                  no
#     sync-individual-repos.sh          yes                  no      <- sets it
#     sync-monorepo.sh                  yes                  yes
#     validate-pre-sync.sh              yes                  yes
#
#   What is true is narrower: every caller of this FUNCTION sets it. Sourcing
#   is not calling, and the two that do not set it never call it.
#
#   Note this is the same shape as the MONOREPO_DIR case documented two
#   paragraphs down — correct today only because the call site that would break
#   it does not exist yet. Stated here too so the two read consistently rather
#   than one carrying the caveat and the other implying a guarantee.
#
#   Hence the explicit guard below. `set -u` alone reports
#   "_lib.sh: line NNN: SKILLS_HOME: unbound variable", which blames THIS file
#   for a contract the caller broke; the guard names the calling script instead.
#   It does not disturb the ratified bare-$SKILLS_HOME decision — an unset value
#   still aborts loudly rather than silently resolving to "/<name>/SKILL.md".
#
# References ${MONOREPO_DIR:-}, not $MONOREPO_DIR: this file is sourced by
# scripts (prepare-plugin.sh, prepare-skill-repo.sh, sync-individual-repos.sh)
# that never set MONOREPO_DIR, and under `set -u` an unset variable referenced
# inside a *called* function still aborts the script. Callers that do have a
# monorepo directory (sync-monorepo.sh, validate-pre-sync.sh) already set
# MONOREPO_DIR before calling this, so their behaviour is unchanged.
#
# The elif guards with `-n` explicitly rather than relying on `-f "${x:-}/…"`
# alone: with MONOREPO_DIR unset, "${MONOREPO_DIR:-}/$name/SKILL.md" collapses
# to "/$name/SKILL.md" — a root-relative path outside both trees that a
# caller with no monorepo directory could still match by accident (e.g.
# name=tmp against a real /tmp/SKILL.md). Unreachable today only because no
# current caller without MONOREPO_DIR set calls this function at all — which
# is exactly the "correct only because the next call site doesn't exist yet"
# shape this batch exists to close.
skill_source_dir() {
  local name="$1"
  if [[ -z "${SKILLS_HOME:-}" ]]; then
    # rc 2, matching the usage-error code the entry-point scripts already use,
    # because this IS a usage error — a caller-contract breach, not a lookup
    # failure. $0 names the script that forgot, which is the whole point.
    echo "Error: skill_source_dir() requires SKILLS_HOME; it is unset (caller: $0)." >&2
    echo "       Sourcing _lib.sh does not set it. sync-monorepo.sh and" >&2
    echo "       validate-pre-sync.sh default it to \$HOME/.claude/skills." >&2
    return 2
  fi
  if [[ -f "$SKILLS_HOME/$name/SKILL.md" ]]; then
    echo "$SKILLS_HOME/$name"
  elif [[ -n "${MONOREPO_DIR:-}" && -f "${MONOREPO_DIR}/$name/SKILL.md" ]]; then
    echo "${MONOREPO_DIR}/$name"
  fi
}

# --- Manifest shape (issue #73) ----------------------------------------------
#
# A legacy plugin-manifest.json declares skills as bare strings:
#     "skills": ["my-skill"]
# rather than the current object form:
#     "skills": [{"name": "my-skill", "source": "."}]
# A bare string means "the skill lives in this manifest's own directory", so
# {"name": <string>, "source": "."} is the faithful normalisation —
# resolve_source_path "." "$MANIFEST_DIR" yields the manifest's own directory.
#
# Bare strings are normalisable in skills[] ONLY. A skill's source is a
# directory, so "." has a meaning there; commands[] and agents[] sources are
# *files*, for which there is no defensible default. Callers reject a bare
# string in those rather than guessing — see prepare-plugin.sh.

# Write a shape-normalised copy of a manifest.
#   $1 = source manifest, $2 = destination path (overwritten)
# Callers point every subsequent `.skills[…]` read at the copy instead of
# teaching each read site the legacy shape: prepare-plugin.sh has eight such
# reads, and a fix that converts some of them still dies with
# `jq: error … Cannot index string with "name"` from whichever it missed.
#
# `.skills = ((.skills // []) | map(…))`, deliberately not the terser
# `(.skills // []) |= map(…)`: the latter is not a valid path expression when
# `.skills` is absent — jq 1.7.1 fails with "Invalid path expression with
# result []" — which would turn a manifest declaring no skills at all (legal
# today: `.skills | length` is 0) into a hard error.
normalize_manifest() {
  local src="$1" dst="$2"
  jq '.skills = ((.skills // []) | map(if type == "string" then {name: ., source: "."} else . end))' \
    "$src" > "$dst"
}

# Emit a manifest's skill names, one per line, tolerating the legacy
# bare-string form. For callers that need only the names and so do not need a
# normalised copy on disk. Entries with no name are skipped rather than
# emitting a blank line.
manifest_skill_names() {
  jq -r '(.skills // [])[] | (if type == "string" then . else .name end) // empty' "$1"
}

# Emit the bare-string entries of manifest $1's array $2 ("commands"/"agents"),
# comma-joined; empty when the array is absent or fully object-form.
manifest_bare_entries() {
  jq -r --arg key "$2" \
    '[(.[$key] // [])[] | select(type == "string")] | join(", ")' "$1"
}
