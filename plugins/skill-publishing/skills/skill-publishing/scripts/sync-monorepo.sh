#!/usr/bin/env bash
# sync-monorepo.sh — Sync skills and plugins from ~/.claude/skills/ into a monorepo directory
# Generates root README with catalog table, plugin section, and per-skill READMEs.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/references"
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)

# Load shared library
source "$SCRIPT_DIR/_lib.sh"

# Defaults
DRY_RUN=false
INIT_MODE=false
FORCE_LOCAL=false
GITHUB_USER=""
SKILLS_LIST=""
ADD_SKILL=""
ADD_PLUGIN=""
MONOREPO_DIR=""
AUTHOR="Abhishek"

usage() {
  cat <<'EOF'
Usage: sync-monorepo.sh [options] <monorepo-dir>

Syncs skills and plugins from ~/.claude/skills/ into a monorepo directory with a
generated root README containing a catalog table and plugin section.

Options:
  --dry-run              Preview changes without writing
  --skills <list>        Comma-separated skill names (default: all in monorepo)
                         Mutually exclusive with --add.
  --add <skill-name>     Add a new skill to the monorepo. Mutually exclusive
                         with --skills.
  --add-plugin <name>    Add a plugin from ./build/<name>/ to plugins/
  --github-user NAME     GitHub username (default: auto-detect via gh api)
  --author NAME          Name for LICENSE copyright (default: Abhishek)
  --init                 Initialize monorepo (create repo, first commit)
  --force-local          Sync even when the local ~/.claude/skills copy is OLDER
                         than the copy already in the monorepo (by default such a
                         skill is refused and skipped, see "Reversion guard")
  -h, --help             Show this help

Reversion guard:
  A skill's source is the local ~/.claude/skills copy when one exists, else the
  in-repo directory. If a stale local copy lingers after the skill has moved
  into the monorepo, syncing would silently overwrite newer in-repo content with
  older local content. Any skill whose in-repo SKILL.md version is strictly
  newer than the local one is therefore REFUSED and skipped; the rest of the
  sync still runs and the script exits 3. Use --force-local to override.

Exit status:
  0  success
  1  usage/setup error — bad/missing arguments, a --skills value that resolves
     to no valid skill, or an --add value naming a skill with no SKILL.md —
     or a manifest could not be published: its plugin build failed, its
     skills[] could not be read, or it declares a bare-string agents[] entry
     (the catalogue is then deliberately left un-regenerated rather than
     describing an unbuilt plugin or an emptied one)
  3  completed, but skills were refused by the reversion guard

  All three manifest failures are collected across the run and reported in one
  summary that names each, under its own reason, so several broken manifests
  take one re-run rather than one each.

  A --skills or --add value that matches no real skill is a usage error, not a
  build failure, but it deliberately shares exit 1 with one rather than mint a
  third code: the unknown-option and missing-monorepo-directory errors above
  already use 1 for "usage/setup error", and --add's no-names-matched case has
  used 1 since PR #76. This keeps 1 to its existing two senses instead of
  letting a third meaning accrete onto it silently.

  --skills and --add differ in WHAT they refuse. --skills is refused only when
  *every* named skill fails to resolve (a partial resolution is a legitimate
  run); --add is refused when *any* name it contributes fails, because --add
  names are typed one at a time to introduce a skill, so an unresolvable one is
  a typo rather than a subset.

  1 wins over 3: a run that both refused a skill and failed a build stops at the
  build failure, so the end-of-run REFUSED summary never prints — the refusal is
  still reported, but only as an inline line earlier in the log.

  --dry-run cannot predict a 1 from a failed BUILD. Plugins are not assembled at
  all under --dry-run, so a manifest that is well-formed but names a missing
  source previews as a clean plan and only fails on the real run. It DOES
  correctly predict the rest: a 3 (the reversion guard runs unconditionally); a
  1 from --skills or --add resolving to no valid skill (those guards run before
  any --dry-run gate, so a bad value refuses the preview exactly as it would
  refuse the real run); a 1 from a manifest whose skills[] cannot be read at
  all, since that read happens regardless of whether a build follows it; and a 1
  from a bare-string agents[] entry, which the main sync loop rejects before the
  build stage is reached. A --dry-run that hits any of those says so explicitly
  rather than repeating the real run's "already written" wording.

Stdin:
  Every list-driven loop reads its list from fd 3, and runs its body with stdin
  on /dev/null. The second half is what guarantees a child cannot consume the
  list: fd 3 is inherited across exec like any other descriptor, so it is a
  convention (nothing reads fd 3 unless written to) rather than a barrier, while
  the /dev/null makes stdin an immediate EOF for every child unconditionally.
  This script therefore never reads the caller's stdin from inside those loops.

Examples:
  sync-monorepo.sh --init ~/dev/claude-code-skills
  sync-monorepo.sh ~/dev/claude-code-skills
  sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills
  sync-monorepo.sh --add-plugin obsidian-brain ~/dev/claude-code-skills
  sync-monorepo.sh --dry-run ~/dev/claude-code-skills
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true; shift ;;
    --init)         INIT_MODE=true; shift ;;
    --skills)       SKILLS_LIST="$2"; shift 2 ;;
    --add)          ADD_SKILL="$2"; shift 2 ;;
    --add-plugin)   ADD_PLUGIN="$2"; shift 2 ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    --author)       AUTHOR="$2"; shift 2 ;;
    --force-local)  FORCE_LOCAL=true; shift ;;
    -h|--help)      usage ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)              MONOREPO_DIR="$1"; shift ;;
  esac
done

# Mutually exclusive: discover_skills() returns from the --add branch without
# ever reading SKILLS_LIST (#80's post-loop guard, further down, gates on
# SKILLS_LIST alone). Silently letting one win would mean --skills's value is
# accepted on the command line but never actually consulted — and worse, a
# --skills value that matched nothing would still surface as an error naming
# the *wrong* flag's value, since the guard has no way to know which flag
# actually produced the (empty) list it is refusing. Reject the combination
# outright rather than pick a silent winner.
if [[ -n "$ADD_SKILL" && -n "$SKILLS_LIST" ]]; then
  echo "Error: --add and --skills are mutually exclusive; pass one or the other" >&2
  exit 1
fi

if [[ -z "$MONOREPO_DIR" ]]; then
  echo "Error: monorepo directory is required" >&2
  echo "Usage: sync-monorepo.sh [options] <monorepo-dir>" >&2
  exit 1
fi

# skill_source_dir() now lives in _lib.sh (issue #78) — it is called from
# validate-pre-sync.sh too, and having two definitions is exactly the
# extract_field()-style duplication a fix once needed two rounds to fully close
# (#35, then #37). _lib.sh is sourced above, before this script sets
# MONOREPO_DIR, but the hoisted definition tolerates that (${MONOREPO_DIR:-});
# by the time anything here calls it, MONOREPO_DIR is set.

# Canonicalise a directory path for identity comparison. Non-existent paths are
# returned unchanged (nothing can be identical to them that matters here).
canonical_dir() {
  if [[ -d "$1" ]]; then (cd "$1" && pwd -P); else echo "$1"; fi
}

# True when version $1 is strictly newer than version $2. Semver-aware via
# `sort -V`, so 2.4.10 correctly beats 2.4.9 (a string compare would not).
# Either side empty/unparseable => false, so an unknown version never triggers
# a refusal.
version_gt() {
  local a="$1" b="$2"
  [[ -z "$a" || -z "$b" ]] && return 1
  [[ "$a" =~ ^[0-9]+(\.[0-9]+)*([.-][0-9A-Za-z.-]+)?$ ]] || return 1
  [[ "$b" =~ ^[0-9]+(\.[0-9]+)*([.-][0-9A-Za-z.-]+)?$ ]] || return 1
  [[ "$a" == "$b" ]] && return 1
  [[ "$(printf '%s\n%s\n' "$a" "$b" | sort -V | tail -1)" == "$a" ]]
}

# Skills refused by the reversion guard (newline-separated) and their count.
REFUSED_SKILLS=""
REFUSED_COUNT=0

# True when the reversion guard refused this skill, i.e. its local source is
# stale. EVERY writer that copies from skill_source_dir() must consult this
# before writing — the plugin build and plugin resync stages read the same
# local-first source, so an unguarded writer reverts exactly the content the
# guard just protected. Consulted only after the main sync loop has run.
skill_refused() {
  [[ -n "$REFUSED_SKILLS" ]] || return 1
  printf '%s' "$REFUSED_SKILLS" | grep -qxF "$1"
}

# --- Resolve GitHub user (via shared _lib.sh) ---
resolve_github_user

echo "GitHub user: $GITHUB_USER"
echo "Monorepo:    $MONOREPO_DIR"
echo "Source:      $SKILLS_HOME"
echo ""

# extract_field, extract_version, short_desc from _lib.sh

# --- Init mode: create monorepo directory and git repo ---
if $INIT_MODE; then
  if [[ -d "$MONOREPO_DIR/.git" ]]; then
    echo "Warning: $MONOREPO_DIR already has a .git directory. Skipping init."
    INIT_MODE=false
  else
    echo "Initializing monorepo at $MONOREPO_DIR..."
    if ! $DRY_RUN; then
      mkdir -p "$MONOREPO_DIR"
    fi
  fi
fi

# Filters a newline-separated list of top-level monorepo directory names down to
# those that are actually skills — same condition skill_source_dir() applies (a
# SKILL.md under either $SKILLS_HOME/<name> or $MONOREPO_DIR/<name>), so discovery
# can never disagree with sourcing. A directory the monorepo has for other reasons
# (docs, build) fails this test and is announced (not silently dropped) at
# non-error severity on stderr, so it never enters the sync loop and never
# produces the loop's "no SKILL.md" ERROR. Written to stderr, not stdout, because
# stdout here is captured by discover_skills()'s callers as the skill list itself.
filter_skill_candidates() {
  local name
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    # printf, not echo: bash's echo eats a leading -n/-e/-E, so a directory so
    # named would vanish from the list with no SKIP line either. Absurd in
    # practice, but not dropping things silently is this function's whole job.
    if [[ -n "$(skill_source_dir "$name")" ]]; then
      printf '%s\n' "$name"
    else
      printf '%s\n' "  SKIP (not a skill: no SKILL.md)  $name" >&2
    fi
  done
}

# --- Determine which skills to sync ---
discover_skills() {
  # If --add specified, add it to existing skills
  if [[ -n "$ADD_SKILL" ]]; then
    # Get existing skill dirs in monorepo (exclude plugins/, scripts/, .git, .github,
    # and any top-level directory that isn't a skill, e.g. docs/, build/)
    local existing=""
    if [[ -d "$MONOREPO_DIR" ]]; then
      existing=$(find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
        ! -name '.git' ! -name '.github' ! -name '.*' \
        ! -name 'plugins' ! -name 'scripts' \
        -exec basename {} \; 2>/dev/null | filter_skill_candidates | sort | tr '\n' ',')
    fi
    # ADD_SKILL itself is a user-typed name, like --skills below — kept unfiltered
    # so a genuine typo still surfaces the loop's existing ERROR, not a silent SKIP.
    #
    # printf, not echo, in both branches: bash's echo consumes a leading -n/-e/-E
    # as its own option. Here that bites only when $existing is empty (an --add
    # into a monorepo with no skills yet), where the argument is the bare name and
    # `--add -n` produced no output at all.
    #
    # The trailing `grep -v '^$'` drops blank lines, which is also what's left
    # when ADD_SKILL is itself nothing but separators (e.g. `--add ,`): grep has
    # nothing to match, exits 1, and under `set -e` that killed the run with
    # rc=1 and empty stderr — no explanation. Capture the combined list first
    # and, if it comes back empty, fail loudly and explain why instead of
    # letting grep's exit status propagate as an unexplained abort.
    local combined
    combined=$(printf '%s\n' "${existing}${ADD_SKILL}" | tr ',' '\n' | sort -u | grep -v '^$' || true)
    if [[ -z "$combined" ]]; then
      echo "Error: --add produced no skill names from: '$ADD_SKILL'" >&2
      exit 1
    fi

    # Every name --add contributes must resolve to a real SKILL.md before the
    # run is allowed to regenerate anything (closes #85; same shape as #80).
    #
    # Without this, `--add nosuchskill` against a POPULATED monorepo printed one
    # inline "ERROR: no SKILL.md …" from the sync loop, `continue`d, and went on
    # to rewrite the README, CHANGELOG and marketplace at exit 0 — the same
    # "reports success while not doing its job" shape #80 closed for --skills.
    # #80's post-loop guard cannot catch it: it fires only when *zero* names
    # resolved, and any monorepo holding at least one real skill contributes
    # resolvable names through $existing — filter_skill_candidates() only emits
    # names that already have a SKILL.md — so SKILLS_RESOLVED_COUNT is non-zero
    # there. (It IS zero for a monorepo holding no skills at all, which is the
    # narrower case #85 covered and this check also now catches.) #85 tracked the
    # narrower empty-monorepo case, where the count IS 0 but the guard is gated
    # on $SKILLS_LIST rather than $ADD_SKILL; a per-name check here subsumes it,
    # and fires earlier — before the sync loop writes anything at all.
    #
    # Only the --add-contributed names are checked, not $combined: $existing
    # came through filter_skill_candidates(), so those already resolve by
    # construction, and re-testing them would turn a monorepo carrying one
    # unrelated broken directory into a permanent --add outage.
    #
    # Split on commas rather than testing "$ADD_SKILL" whole: --add takes the
    # same comma-separated form as --skills (it is comma-split into $combined
    # two lines up), so a single skill_source_dir "$ADD_SKILL" test would look
    # for a skill literally named "a,b" and refuse a legitimate `--add a,b`.
    local _add_unresolved="" _add_name
    while IFS= read -r _add_name <&3; do
      [[ -z "$_add_name" ]] && continue
      if [[ -z "$(skill_source_dir "$_add_name")" ]]; then
        _add_unresolved="${_add_unresolved:+$_add_unresolved, }$_add_name"
      fi
    done 3<<< "$(printf '%s\n' "$ADD_SKILL" | tr ',' '\n')" </dev/null
    if [[ -n "$_add_unresolved" ]]; then
      echo "Error: --add named skills with no SKILL.md: $_add_unresolved" >&2
      echo "       Looked under $SKILLS_HOME/<name>/ and $MONOREPO_DIR/<name>/." >&2
      echo "       Nothing was synced; the monorepo README, CHANGELOG and" >&2
      echo "       marketplace catalogue are left untouched." >&2
      exit 1
    fi

    printf '%s\n' "$combined"
    return
  fi

  # If --skills specified, use that list
  if [[ -n "$SKILLS_LIST" ]]; then
    # Mirrors the --add branch above: a value that is nothing but separators
    # (e.g. `--skills ,`) reduces to blank lines after comma-splitting, and a
    # bare `grep -v '^$'` on an all-blank input exits 1 and would abort the
    # whole run under `set -e` with empty stderr — no explanation. Capture the
    # filtered result first and, if nothing survives, fail loudly and say why.
    #
    # `sort -u`, matching the --add branch's (#80, where this branch's own
    # `sort` was introduced): with a plain
    # `sort`, `--skills alpha,alpha` synced the same skill twice — two
    # "--- alpha ---" stanzas, two identical catalogue rows, two identical
    # `cp -r` install lines published as instructions, and a doubled count in
    # the summary, the README and the CHANGELOG. Everything agreed with
    # everything else, so nothing flagged it. Naming a skill twice in one
    # --skills value is a typo with exactly one sensible reading.
    local skills_filtered
    skills_filtered=$(printf '%s\n' "$SKILLS_LIST" | tr ',' '\n' | sort -u | grep -v '^$' || true)
    if [[ -z "$skills_filtered" ]]; then
      echo "Error: --skills produced no skill names from: '$SKILLS_LIST'" >&2
      exit 1
    fi
    printf '%s\n' "$skills_filtered"
    return
  fi

  # For --init with no --skills, default to the initial set
  # (Must check INIT_MODE before directory existence — init creates the dir first)
  if $INIT_MODE; then
    echo "conversation-search"
    echo "skill-authoring"
    echo "skill-publishing"
    return
  fi

  # If monorepo exists, sync skills already in it (exclude plugins/, scripts/, .git,
  # .github, and any top-level directory that isn't a skill, e.g. docs/, build/)
  if [[ -d "$MONOREPO_DIR" ]]; then
    find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
      ! -name '.git' ! -name '.github' ! -name '.*' \
      ! -name 'plugins' ! -name 'scripts' \
      -exec basename {} \; 2>/dev/null | filter_skill_candidates | sort
    return
  fi

  # Fallback: default set
  echo "conversation-search"
  echo "skill-authoring"
  echo "skill-publishing"
}

SKILLS_TO_SYNC=$(discover_skills)

# An empty list needs its own branch both times: `echo ""` emits a newline, so
# `wc -l` reports 1 skill that does not exist, and the `sed` below renders it as
# a bare "  - " bullet. Newly reachable — before discovery filtered non-skill
# directories, docs/ and build/ kept the list non-empty; a monorepo containing
# only those now yields nothing.
if [[ -z "$SKILLS_TO_SYNC" ]]; then
  SKILL_COUNT=0
else
  SKILL_COUNT=$(printf '%s\n' "$SKILLS_TO_SYNC" | wc -l | tr -d ' ')
fi

echo "Skills to sync ($SKILL_COUNT):"
if [[ -n "$SKILLS_TO_SYNC" ]]; then
  printf '%s\n' "$SKILLS_TO_SYNC" | sed 's/^/  - /'
fi
echo ""

# write_file, copy_file, copy_dir from _lib.sh

# --- Sync each skill ---
CATALOG_ROWS=""

# Counts every SKILLS_TO_SYNC entry that resolved to a real skill (found a
# SKILL.md), whether it was ultimately copied or refused by the reversion
# guard further down — a refusal is a legitimate outcome (exit 3), not the
# "no such skill" case this counter exists to catch.
#
# FOUR readers, not one — an earlier version of this comment said "read only by
# the explicit --skills guard after the loop (#80)", and that has been false
# since #81's third pass. The other three are all catalogue-describing figures:
# SKILLS_SYNCED_COUNT (this minus REFUSED_COUNT), the README template's
# {{SKILL_COUNT}} substitution, and the minimal-README fallback's "N reusable
# Agent Skills". Changing what this counts changes every published count in the
# monorepo, not just one guard's threshold. The full reasoning for why the
# catalogue-facing figure is this and NOT SKILLS_SYNCED_COUNT lives at the
# {{SKILL_COUNT}} substitution site; read it before touching either.
SKILLS_RESOLVED_COUNT=0

# Manifests the main sync loop refused for a bare-string agents[] entry.
# Declared HERE, before the loop, rather than alongside _FAILED_BUILDS in the
# auto-build stage below: this loop runs first, and a variable declared after it
# cannot collect from it. Folded into the same collected-failure exit as the
# auto-build stage's own lists, so all three report through one summary.
_BARE_ENTRY_MANIFESTS=""

# Line-wise, not `for SKILL_NAME in $SKILLS_TO_SYNC` (issue #81): unquoted word
# splitting breaks a skill directory whose name contains a space into separate
# tokens, each of which fails to resolve — two loud "no SKILL.md" ERRORs where
# there should have been one successful sync. A here-string, not a pipe: this
# loop assigns CATALOG_ROWS, REFUSED_SKILLS, REFUSED_COUNT and
# SKILLS_RESOLVED_COUNT, all read after the loop, and a pipe would run the body
# in a subshell and silently discard every one of them. A here-string on an
# empty $SKILLS_TO_SYNC still feeds one blank line, hence the guard below.
#
# `<&3` / `3<<<`, not plain stdin: `done <<< "$LIST"` makes the list the loop
# BODY's stdin, and this body shells out to gh, rsync, cp, diff, find and jq.
# Any child that reads stdin — because it is a filter by nature, or because a
# future version grows a prompt — consumes the rest of the skill list, and the
# loop then exits early having synced only the skills read so far. It exits 0
# while doing it, and every downstream figure agrees with the truncation:
# {{SKILL_COUNT}} is SKILLS_RESOLVED_COUNT, the catalogue is built from the
# same rows, and the CHANGELOG inventory iterates the same (already drained)
# list — so a two-thirds-empty catalogue is internally self-consistent and
# nothing flags it. The old `for SKILL_NAME in $SKILLS_TO_SYNC` had no such
# exposure; converting to `while read` created it.
#
# TWO mechanisms, and they are not equally strong — an earlier version of this
# comment claimed fd 3 alone meant "no child can reach the list at all", which
# is FALSE and was measured to be false:
#
#   1. `3<<<` moves the list off stdin. This is a CONVENTION, not a barrier.
#      fd 3 is inherited across exec like any other descriptor, so a child that
#      deliberately reads `<&3` consumes the list exactly as a stdin-reading
#      child did. Measured on a 4-line list: a body running `head -1 <&3` cut
#      the loop to 2 iterations. What fd 3 actually buys is that stdin is read
#      by filters *by nature* — cat, sed, grep, a future `gh` subcommand that
#      grows a prompt — whereas nothing reads fd 3 unless it was written to.
#      That is a real and sufficient reduction in exposure; it is not immunity.
#
#   2. `</dev/null` on the loop makes the stdin half UNCONDITIONAL. The body's
#      stdin is /dev/null rather than whatever the caller had, so every child
#      spawned here — gh, rsync, cp, diff, find, jq — gets immediate EOF and
#      cannot consume anything, deliberately or otherwise. It also removes the
#      one downside of moving the list off stdin: with the list on fd 3 the
#      body would otherwise inherit the caller's stdin, so a stdin-reading
#      child would HANG on an interactive terminal instead of truncating. A
#      hang is the better failure, but /dev/null avoids both.
#
# Together: (2) closes the reachable case; (1) means a child would have to name
# fd 3 explicitly to break it, which nothing does by accident. The same
# treatment is applied to every converted loop in this file and in
# validate-pre-sync.sh.
while IFS= read -r SKILL_NAME <&3; do
  [[ -z "$SKILL_NAME" ]] && continue
  SKILL_SRC=$(skill_source_dir "$SKILL_NAME")
  SKILL_DST="$MONOREPO_DIR/$SKILL_NAME"

  echo "--- $SKILL_NAME ---"

  if [[ -z "$SKILL_SRC" ]]; then
    echo "  ERROR: no SKILL.md in $SKILLS_HOME/$SKILL_NAME or $SKILL_DST, skipping"
    echo ""
    continue
  fi
  SKILL_MD="$SKILL_SRC/SKILL.md"
  SKILLS_RESOLVED_COUNT=$((SKILLS_RESOLVED_COUNT + 1))

  # When the source IS the destination (in-repo source directory), every copy
  # below would be a directory-onto-itself operation: `cp a a` fails and
  # `rsync -a --delete src/ src/` risks destroying the tree. Nothing needs
  # copying — the content is already where the monorepo wants it.
  SKILL_IN_PLACE=false
  if [[ "$(canonical_dir "$SKILL_SRC")" == "$(canonical_dir "$SKILL_DST")" ]]; then
    SKILL_IN_PLACE=true
    echo "  in-repo source — already in place, nothing to copy"
  fi

  # --- Reversion guard ---
  # skill_source_dir() is local-first, so a stale local copy left behind after a
  # skill moved into the monorepo still wins and this loop would copy it
  # backwards over newer in-repo content. Distinguish the two directions by
  # version: for a normal skill the in-repo copy is just the previous sync's
  # output, so it is older or equal — that is a legitimate forward sync.
  # Only a strictly newer in-repo version means the local copy is behind.
  SKILL_REVERTED=false
  if ! $SKILL_IN_PLACE && [[ -f "$SKILL_DST/SKILL.md" ]]; then
    SRC_VER=$(extract_version "$SKILL_MD")
    DST_VER=$(extract_version "$SKILL_DST/SKILL.md")
    if version_gt "$DST_VER" "$SRC_VER"; then
      if $FORCE_LOCAL; then
        echo "  WARNING: in-repo copy is NEWER (v$DST_VER) than the local source (v$SRC_VER)"
        echo "           --force-local given — overwriting it with the local copy."
      else
        echo "  REFUSED: syncing would revert newer in-repo content"
        echo "    local source: $SKILL_SRC (v$SRC_VER)"
        echo "    in-repo dest: $SKILL_DST (v$DST_VER)"
        echo "    The local copy is stale; copying it would downgrade the monorepo."
        echo "    To proceed deliberately, either:"
        echo "      - remove the stale local copy so the in-repo copy becomes the source:"
        echo "          rm -rf $SKILL_SRC"
        echo "      - or re-run with --force-local to let the local copy win."
        SKILL_REVERTED=true
        REFUSED_SKILLS="${REFUSED_SKILLS}${SKILL_NAME}"$'\n'
        REFUSED_COUNT=$((REFUSED_COUNT + 1))
        # Describe the skill by what the repo actually holds, so the catalog row
        # built below (and the root README generated from it) is not rewritten
        # with the stale local metadata of a skill we are declining to sync.
        SKILL_MD="$SKILL_DST/SKILL.md"
      fi
    elif [[ -n "$SRC_VER" && "$SRC_VER" == "$DST_VER" ]] \
         && ! diff -q "$SKILL_MD" "$SKILL_DST/SKILL.md" >/dev/null 2>&1; then
      echo "  NOTE: same version (v$SRC_VER) but content differs — treating as an"
      echo "        un-bumped local edit and syncing forward."
    fi
  fi

  # Extract metadata
  NAME=$(extract_field "$SKILL_MD" "name")
  DESCRIPTION=$(extract_field "$SKILL_MD" "description")
  VERSION=$(extract_version "$SKILL_MD")
  SHORT=$(short_desc "$DESCRIPTION")

  if [[ -z "$VERSION" ]]; then
    VERSION="1.0.0"
  fi

  # Check if individual repo exists
  INDIVIDUAL_REPO_URL=""
  # No per-call </dev/null needed: the loop itself is `done … </dev/null`, so
  # this child's stdin is already /dev/null. One mechanism at the loop, not one
  # per call site — see the loop's own comment.
  if gh repo view "$GITHUB_USER/$SKILL_NAME" --json url --jq '.url' >/dev/null 2>&1; then
    INDIVIDUAL_REPO_URL="https://github.com/$GITHUB_USER/$SKILL_NAME"
  fi

  # Build catalog row
  REPO_LINK=""
  if [[ -n "$INDIVIDUAL_REPO_URL" ]]; then
    REPO_LINK="[repo]($INDIVIDUAL_REPO_URL)"
  else
    REPO_LINK="—"
  fi
  CATALOG_ROWS="${CATALOG_ROWS}| [$SKILL_NAME](./$SKILL_NAME/) | $VERSION | $SHORT | $REPO_LINK |
"

  # Refused above: the catalog row is kept (from the in-repo metadata), so
  # this skill's row is unchanged, but nothing is copied for this skill. The
  # README's overall "N reusable Agent Skills" figure (built further down)
  # deliberately uses SKILLS_RESOLVED_COUNT, not SKILLS_SYNCED_COUNT, for
  # exactly this reason: SKILLS_RESOLVED_COUNT counts every name that
  # resolved to a real SKILL.md — refused or not — so it stays in step with
  # the catalogue's actual row count regardless of how many were refused.
  # SKILLS_SYNCED_COUNT (resolved minus refused) undercounts the catalogue by
  # REFUSED_COUNT whenever anything here is refused, and shipped as exactly
  # that regression once already (issue #81, third pass) — do not repeat it.
  if $SKILL_REVERTED; then
    echo ""
    continue
  fi

  if ! $SKILL_IN_PLACE; then
    # Copy SKILL.md
    copy_file "$SKILL_MD" "$SKILL_DST/SKILL.md" "$SKILL_NAME/SKILL.md"

    # Copy scripts/
    if [[ -d "$SKILL_SRC/scripts" ]]; then
      copy_dir "$SKILL_SRC/scripts" "$SKILL_DST/scripts" "$SKILL_NAME/scripts/"
      # Preserve execute permissions
      if ! $DRY_RUN; then
        find "$SKILL_DST/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
      fi
    fi

    # Copy references/
    if [[ -d "$SKILL_SRC/references" ]]; then
      copy_dir "$SKILL_SRC/references" "$SKILL_DST/references" "$SKILL_NAME/references/"
    fi
  fi

  # Copy agents declared in plugin-manifest.json (if any)
  MANIFEST="$SKILL_SRC/plugin-manifest.json"
  if [[ -f "$MANIFEST" ]]; then
    AGENT_COUNT=$(jq -r '.agents // [] | length' "$MANIFEST" 2>/dev/null)
    # Bare-string agents[] entries are refused, same as prepare-plugin.sh (#73).
    # That guard lived only there, and this loop runs FIRST — so on a manifest
    # carrying `"agents": ["x"]` the run died right below at
    # `jq -r ".agents[0].name"` with a raw `jq: error … Cannot index string
    # with "name"` and rc=5, and prepare-plugin.sh's friendly explanation never
    # printed because the sync never reached the auto-build stage. Checked here
    # too, with the same message text, so whichever script meets the manifest
    # first says the same actionable thing.
    #
    # Scoped to agents[] alone, unlike prepare-plugin.sh's commands+agents
    # sweep: agents[] is the only array this loop indexes, so it is the only one
    # whose shape can break it. A bare commands[] entry is still refused by
    # prepare-plugin.sh at the auto-build stage below, which is the script that
    # actually reads it.
    #
    # Recorded into _BARE_ENTRY_MANIFESTS and exited on after the auto-build
    # stage, NOT left to that stage to catch. An earlier version of this guard
    # claimed "the very next stage runs prepare-plugin.sh against this same
    # manifest, which exits 1 on it", and that is false whenever the build does
    # not run: prepare-plugin.sh is invoked only when _NEEDS_BUILD is true, so
    # adding `"agents": ["x"]` to an ALREADY-PUBLISHED plugin's manifest without
    # touching its SKILL.md — the natural way to add an agent, in exactly the
    # legacy bare-string form this batch exists to tolerate — left the drift
    # check finding nothing, the build never running, the declared agents
    # silently not copied, and README/CHANGELOG/marketplace all regenerated at
    # exit 0. Measured pre/post on one fixture: rc 5 (fatal, nothing written)
    # before the guard existed, rc 0 with the catalogue regenerated after it.
    #
    # SIX conditions leave prepare-plugin.sh un-run and would have bypassed the
    # claimed net identically, not the three an earlier draft of this comment
    # listed: --dry-run; a shadowed manifest; the standalone-marketplace skip
    # (git-flow); --add-plugin targeting this same plugin; the skill having been
    # refused by the reversion guard; and PREPARE_SCRIPT not being executable,
    # which skips the entire stage. The seventh is the one above — no drift, so
    # _NEEDS_BUILD is simply false.
    #
    # That made this guard a LOUDNESS REGRESSION: before it, such a manifest
    # died at `jq -r ".agents[$ai].name"` with rc=5 — ugly, but fatal, and
    # nothing downstream was written. Trading a loud abort for a quiet ERROR
    # line above a successful-looking run is the exact defect shape this whole
    # batch exists to remove.
    #
    # Collected rather than `exit 1` here so a run with several broken manifests
    # still names all of them in one pass, matching the auto-build stage.
    _BARE_AGENTS=$(manifest_bare_entries "$MANIFEST" agents 2>/dev/null || true)
    if [[ -n "$_BARE_AGENTS" ]]; then
      echo "  ERROR: agent entry must be an object with 'name' and 'source', not a bare string: $_BARE_AGENTS" >&2
      echo "         in $MANIFEST" >&2
      _BARE_ENTRY_MANIFESTS="${_BARE_ENTRY_MANIFESTS:+$_BARE_ENTRY_MANIFESTS }$MANIFEST"
      AGENT_COUNT=0
    fi
    if [[ "$AGENT_COUNT" -gt 0 ]]; then
      if ! $DRY_RUN; then
        mkdir -p "$SKILL_DST/agents"
      fi
      for (( ai=0; ai<AGENT_COUNT; ai++ )); do
        AGENT_NAME=$(jq -r ".agents[$ai].name" "$MANIFEST")
        AGENT_SRC=$(jq -r ".agents[$ai].source" "$MANIFEST")
        # Resolve ~ and relative paths against the manifest's own directory
        # (SKILL_SRC, since MANIFEST is "$SKILL_SRC/plugin-manifest.json") —
        # matches prepare-plugin.sh's resolve_source_path for agents[].source.
        AGENT_SRC_RESOLVED=$(resolve_source_path "$AGENT_SRC" "$SKILL_SRC")
        if [[ -f "$AGENT_SRC_RESOLVED" ]]; then
          copy_file "$AGENT_SRC_RESOLVED" "$SKILL_DST/agents/$AGENT_NAME.md" "$SKILL_NAME/agents/$AGENT_NAME.md"
        else
          echo "  Warning: agent source not found: $AGENT_SRC_RESOLVED"
        fi
      done
    fi
  fi

  if ! $SKILL_IN_PLACE; then
    # Copy CHANGELOG.md if it exists
    copy_file "$SKILL_SRC/CHANGELOG.md" "$SKILL_DST/CHANGELOG.md" "$SKILL_NAME/CHANGELOG.md"

    # Copy LICENSE if it exists
    copy_file "$SKILL_SRC/LICENSE" "$SKILL_DST/LICENSE" "$SKILL_NAME/LICENSE"
  fi

  # Per-skill README.md: copy local if it exists, otherwise generate.
  # An in-place source needs no copy — its own README is already the destination.
  if [[ -f "$SKILL_SRC/README.md" ]]; then
    if ! $SKILL_IN_PLACE; then
      # Use the skill's own README (preserves fork context, custom sections, etc.)
      copy_file "$SKILL_SRC/README.md" "$SKILL_DST/README.md" "$SKILL_NAME/README.md"
    fi
  else
    # Generate a default README with monorepo install instructions
    SKILL_README="# $NAME

$SHORT

## Installation

### From this monorepo

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/$SKILL_NAME ~/.claude/skills/$SKILL_NAME
rm -rf /tmp/claude-code-skills
\`\`\`

### Sparse checkout (minimal download)

\`\`\`bash
git clone --filter=blob:none --sparse https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set $SKILL_NAME
cp -r $SKILL_NAME ~/.claude/skills/$SKILL_NAME
rm -rf /tmp/ccs
\`\`\`"

    # Add individual repo install if it exists
    if [[ -n "$INDIVIDUAL_REPO_URL" ]]; then
      SKILL_README="$SKILL_README

### From individual repo

\`\`\`bash
git clone $INDIVIDUAL_REPO_URL.git ~/.claude/skills/$SKILL_NAME
\`\`\`"
    fi

    SKILL_README="$SKILL_README

## Updating

\`\`\`bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r $SKILL_NAME ~/.claude/skills/$SKILL_NAME

# If installed from individual repo
git -C ~/.claude/skills/$SKILL_NAME pull
\`\`\`

## What It Does

$SHORT

## Compatibility

This skill follows the **Agent Skills** standard — a \`SKILL.md\` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)"

    write_file "$SKILL_DST/README.md" "$SKILL_README" "$SKILL_NAME/README.md" "true"
  fi

  echo ""
done 3<<< "$SKILLS_TO_SYNC" </dev/null

# --- Guard: an explicit --skills value that matched no real skill must not
# proceed to rebuild the catalogue (#80, second half). The discover_skills()
# branch above already refuses a --skills value that produces no names at all
# (e.g. `--skills ,`) before this loop ever runs; this catches the quieter
# case where every named skill fails to resolve a SKILL.md (e.g. `--skills
# nosuchskill`) — the loop only prints an inline "ERROR: no SKILL.md ..." per
# name and `continue`s, so without this the run would still reach exit 0
# having synced nothing and then regenerate the README/CHANGELOG/marketplace
# from whatever was already on disk. Sited here — after the main sync loop,
# before the plugin auto-build stage and every stage that follows it — so
# nothing downstream runs on a wasted invocation.
#
# Discovery-driven runs (no --skills given) are deliberately exempt: a
# monorepo that genuinely has no skills yet is a legitimate zero, not a usage
# error, and must keep exiting 0 (see the "empty monorepo" fixture).
if [[ -n "$SKILLS_LIST" && "$SKILLS_RESOLVED_COUNT" -eq 0 ]]; then
  echo "" >&2
  echo "Error: --skills matched no valid skills (no SKILL.md found) from: '$SKILLS_LIST'" >&2
  echo "       Nothing was synced; the monorepo README, CHANGELOG and" >&2
  echo "       marketplace catalogue are left untouched." >&2
  exit 1
fi

# Skills actually synced: resolved minus refused (issue #81, second pass).
# SKILL_COUNT is the discovered/requested count, printed above the loop as the
# *plan* before anything has been attempted — legitimately SKILL_COUNT, left
# alone. Every stage below that describes "how many skills" in the past
# tense — the README template's {{SKILL_COUNT}} substitution, the minimal-
# README fallback description, the CHANGELOG's "Synced N skills" entry, the
# --init git commit message, and the closing "Sync complete." line — is a
# claim about what actually happened, and must use this figure instead.
SKILLS_SYNCED_COUNT=$((SKILLS_RESOLVED_COUNT - REFUSED_COUNT))

# --- Discover and sync plugins ---
discover_plugins() {
  # Scan $MONOREPO_DIR/plugins/ for directories with .claude-plugin/plugin.json
  if [[ -d "$MONOREPO_DIR/plugins" ]]; then
    find "$MONOREPO_DIR/plugins" -maxdepth 1 -mindepth 1 -type d \
      -exec basename {} \; 2>/dev/null | sort
  fi
}

# --- Auto-discover and build plugins from plugin-manifest.json files ---
# Plugin-first: any skill with a plugin-manifest.json is automatically assembled
# and synced as a plugin. No --add-plugin needed for known plugins.
PREPARE_SCRIPT="$SCRIPT_DIR/prepare-plugin.sh"
AUTO_BUILT_PLUGINS=""
# Two lists, not one, because the two failures are not the same event and the
# summary must not claim more than happened: _FAILED_BUILDS is a build that was
# ATTEMPTED and failed; _UNREADABLE_MANIFESTS is a manifest whose skills[] could
# not be read, where no build was attempted at all. Reporting the second as
# "plugin build failed" was itself a message claiming more than occurred, in a
# change set whose whole theme is that messages must not do that.
#
# Space-separated, matching AUTO_BUILT_PLUGINS' idiom. Collected across the
# stage and acted on once, together with _BARE_ENTRY_MANIFESTS from the main
# sync loop, in the combined check after this block.
#
# Which of the three a --dry-run can produce: _UNREADABLE_MANIFESTS from this
# stage (the build does not run under --dry-run, but the manifest is read
# regardless), and _BARE_ENTRY_MANIFESTS from the main sync loop, whose guard is
# not gated on DRY_RUN either — verified: a --dry-run over an already-published
# plugin with `"agents": ["x"]` exits 1. Only _FAILED_BUILDS is unreachable under
# --dry-run, because only it needs a build to have been attempted. That is
# deliberate: both of the others are defects a dry run can genuinely see, so it
# should say so rather than predict a clean run that will not happen.
_FAILED_BUILDS=""
_UNREADABLE_MANIFESTS=""

if [[ -x "$PREPARE_SCRIPT" ]]; then
  # Auto-built plugins are assembled into a throwaway temp directory, never the
  # caller's cwd — otherwise a sync run from the monorepo root leaves an
  # untracked ./build/ tree that a routine `git add -A` would commit. One temp
  # dir covers the whole auto-build stage; each plugin gets its own subdir.
  _AUTO_BUILD_TMP="$(mktemp -d)"
  trap 'rm -rf "$_AUTO_BUILD_TMP"' EXIT

  # Manifests live either in the local skills home or in an in-repo top-level
  # skill directory. Local ones are scanned first so they take precedence.
  # Records "<plugin-name><TAB><manifest-path>" for each name already claimed.
  _SEEN_MANIFESTS=""

  for _MANIFEST in "$SKILLS_HOME"/*/plugin-manifest.json "$MONOREPO_DIR"/*/plugin-manifest.json; do
    [[ ! -f "$_MANIFEST" ]] && continue
    _MANIFEST_SKILL=$(basename "$(dirname "$_MANIFEST")")
    _MANIFEST_NAME=$(jq -r '.name // ""' "$_MANIFEST" 2>/dev/null)
    [[ -z "$_MANIFEST_NAME" ]] && _MANIFEST_NAME="$_MANIFEST_SKILL"

    # Local-first precedence. Announce every shadowed manifest by name — a
    # silent skip here is exactly what makes a stale source invisible.
    # No `exit` in the awk body: an early-exiting reader is the same shape as the
    # `echo … | head -1` removed from the CHANGELOG stage below, and it is
    # likewise evaluated with the EXIT trap already registered — the condition
    # that turns a silent SIGPIPE into a visible "write error: Broken pipe".
    # $_SEEN_MANIFESTS is a few KiB at this repo's scale, far under the 64 KiB
    # pipe buffer, so it cannot fire today; keeping the reader draining its input
    # means it cannot start to. `!f` keeps first-match-wins semantics.
    _SHADOWED_BY=$(printf '%s' "$_SEEN_MANIFESTS" | awk -F'\t' -v n="$_MANIFEST_NAME" '$1==n && !f {print $2; f=1}')
    if [[ -n "$_SHADOWED_BY" ]]; then
      echo "  SKIP (shadowed)  $_MANIFEST  —  already claimed by $_SHADOWED_BY"
      continue
    fi
    _SEEN_MANIFESTS="${_SEEN_MANIFESTS}${_MANIFEST_NAME}"$'\t'"${_MANIFEST}"$'\n'

    # Standalone plugins — distributed via their own marketplace, not this monorepo.
    # Add new entries here when migrating other plugins out.
    case "$_MANIFEST_NAME" in
      git-flow)
        echo "  SKIP (standalone marketplace: abhattacherjee/git-flow)  $_MANIFEST_NAME"
        continue
        ;;
    esac

    # Skip if --add-plugin targets this same plugin (handled below)
    [[ "$ADD_PLUGIN" == "$_MANIFEST_NAME" ]] && continue

    # One read of this manifest's skill names, shared by the reversion-guard
    # check immediately below and the drift check after it. manifest_skill_names()
    # tolerates the legacy bare-string `"skills": ["name"]` form (#73): before it,
    # both sites' `jq -r '.skills[…].name'` errored into `2>/dev/null` on such a
    # manifest, so the reversion guard saw no skills to check and the drift check
    # saw no first skill and never rebuilt the plugin at all.
    #
    # A failed read is recorded as a build failure, NOT swallowed. The earlier
    # `2>/dev/null || true` here claimed to keep "the pre-existing tolerance of
    # an unreadable manifest", and that was only half true. At the base commit
    # there were two reads: the reversion guard's `for _PLUGIN_SKILL in $(jq …)`
    # — a command substitution in a `for` word-list, which does not trip
    # `set -e`, so genuinely tolerant — and the drift check's
    # `_FIRST_SKILL=$(jq …)`, an ASSIGNMENT, which under `set -e` did abort the
    # run. Consolidating both onto one tolerant read silently downgraded the
    # second from fatal to skipped, on the destructive path: with
    # $_MANIFEST_SKILL_NAMES empty, $_REFUSED_IN_PLUGIN stays empty, so the
    # reversion guard does not fire and the plugin is rebuilt from the stale
    # local source the main loop just refused, then `rsync -a --delete`'d over
    # the published copy under a reassuring "AUTO-SYNCED" line.
    #
    # This is reachable: `"skills": [123]` makes manifest_skill_names exit 5
    # (`Cannot index number with string "name"`), and the `.name` read further
    # up succeeds on the same file, so nothing earlier catches it.
    #
    # stderr is captured SEPARATELY, on the failure path only — never merged
    # into $_MANIFEST_SKILL_NAMES. On the success path that variable *is* the
    # skill-name list: it feeds the reversion guard and _FIRST_SKILL. A `2>&1`
    # here would let any jq diagnostic that accompanies a zero exit become a
    # phantom skill name, and a phantom _FIRST_SKILL resolves nowhere, so the
    # drift check falls through, _NEEDS_BUILD stays false, and the plugin is
    # silently never rebuilt — #73 re-entering through its own fix. No such
    # warning is reachable for this filter today; merging a diagnostic stream
    # into data that is then read as data is unsafe by construction regardless.
    # The second invocation runs only when the first failed, so the success
    # path still costs one jq.
    if ! _MANIFEST_SKILL_NAMES=$(manifest_skill_names "$_MANIFEST" 2>/dev/null); then
      _MANIFEST_READ_ERR=$(manifest_skill_names "$_MANIFEST" 2>&1 >/dev/null || true)
      echo "  ERROR: cannot read skills[] from $_MANIFEST" >&2
      sed 's/^/    | /' <<< "$_MANIFEST_READ_ERR" >&2 || true
      _UNREADABLE_MANIFESTS="${_UNREADABLE_MANIFESTS:+$_UNREADABLE_MANIFESTS }$_MANIFEST"
      continue
    fi

    # A skill refused by the reversion guard must not be rebuilt into a plugin
    # either: prepare-plugin.sh reads the same stale local source, so the rsync
    # below would revert plugins/<name>/ exactly as the main loop would have.
    if [[ -n "$REFUSED_SKILLS" ]]; then
      _REFUSED_IN_PLUGIN=""
      # Line-wise (issue #81): a manifest skill name containing a space would
      # otherwise be split into fragments, neither of which matches the
      # refused name skill_refused() actually recorded — the reversion guard
      # would then silently miss its own refusal and let the plugin rebuild
      # over the stale local source it exists to protect against. Here-string,
      # not a pipe: _REFUSED_IN_PLUGIN is read immediately after this loop, in
      # the current shell. On fd 3, not stdin: see the main sync loop's comment —
      # the body is pure bash today, but a stdin-consuming child added later
      # would silently truncate the list of skills this guard checks, which is
      # the one list whose truncation lets the guard miss its own refusal.
      while IFS= read -r _PLUGIN_SKILL <&3; do
        [[ -z "$_PLUGIN_SKILL" ]] && continue
        if skill_refused "$_PLUGIN_SKILL"; then
          _REFUSED_IN_PLUGIN="${_REFUSED_IN_PLUGIN:+$_REFUSED_IN_PLUGIN }$_PLUGIN_SKILL"
        fi
      done 3<<< "$_MANIFEST_SKILL_NAMES" </dev/null
      if [[ -n "$_REFUSED_IN_PLUGIN" ]]; then
        echo "  SKIP (reversion guard)  plugins/$_MANIFEST_NAME  —  stale local source for: $_REFUSED_IN_PLUGIN"
        continue
      fi
    fi

    # Check if source skill content has changed vs the monorepo plugin copy.
    # Build if: (a) plugin doesn't exist in monorepo yet, or (b) source has drifted.
    _NEEDS_BUILD=false
    _PLUGIN_DST="$MONOREPO_DIR/plugins/$_MANIFEST_NAME"

    if [[ ! -d "$_PLUGIN_DST/.claude-plugin" ]]; then
      _NEEDS_BUILD=true
    else
      # Quick drift check: compare SKILL.md versions. First line of the shared
      # name list above; parameter expansion rather than `| head -1`, which
      # would put a first-line reader on the far end of a pipe (the EPIPE shape
      # removed from the CHANGELOG stage below).
      _FIRST_SKILL="${_MANIFEST_SKILL_NAMES%%$'\n'*}"
      if [[ -n "$_FIRST_SKILL" ]]; then
        _FIRST_SRC_DIR=$(skill_source_dir "$_FIRST_SKILL")
        _SRC_MD="${_FIRST_SRC_DIR:+$_FIRST_SRC_DIR/SKILL.md}"
        _DST_MD="$_PLUGIN_DST/skills/$_FIRST_SKILL/SKILL.md"
        if [[ -f "$_SRC_MD" && -f "$_DST_MD" ]]; then
          if ! diff -q "$_SRC_MD" "$_DST_MD" >/dev/null 2>&1; then
            _NEEDS_BUILD=true
          fi
        elif [[ -f "$_SRC_MD" ]]; then
          _NEEDS_BUILD=true
        fi
      fi
    fi

    if $_NEEDS_BUILD; then
      echo "--- Auto-build plugin: $_MANIFEST_NAME ---"
      if $DRY_RUN; then
        echo "  WOULD BUILD + SYNC  plugins/$_MANIFEST_NAME/"
      else
        # Build the plugin via prepare-plugin.sh, into the temp stage dir.
        # The child's output is captured rather than discarded: on the failure
        # path below it holds the only actionable line (e.g.
        # "ERROR: skill source not found: <path>"), and since the stage is a
        # mktemp -d removed by the EXIT trap, there is no longer a partial
        # ./build/<name>/ tree left in the caller's cwd to post-mortem instead.
        # The log lives in the stage root, NOT in $_BUILD_DIR: prepare-plugin.sh
        # starts with `rm -rf "$OUTPUT_DIR"`, which would unlink the log out from
        # under the open descriptor and leave it reading empty.
        _BUILD_DIR="$_AUTO_BUILD_TMP/$_MANIFEST_NAME"
        _BUILD_LOG="$_AUTO_BUILD_TMP/$_MANIFEST_NAME.log"
        if "$PREPARE_SCRIPT" --output-dir "$_BUILD_DIR" --github-user "$GITHUB_USER" "$_MANIFEST" >"$_BUILD_LOG" 2>&1; then
          if [[ -d "$_BUILD_DIR/.claude-plugin" ]]; then
            # Preserve hand-written README if it exists in destination
            _PRESERVED_README=""
            if [[ -f "$_PLUGIN_DST/README.md" ]]; then
              _PRESERVED_README=$(mktemp)
              cp "$_PLUGIN_DST/README.md" "$_PRESERVED_README"
            fi

            mkdir -p "$_PLUGIN_DST"
            rsync -a --delete --exclude='.DS_Store' "$_BUILD_DIR/" "$_PLUGIN_DST/"

            # Restore preserved README
            _PRESERVED_MSG=""
            if [[ -n "$_PRESERVED_README" ]]; then
              cp "$_PRESERVED_README" "$_PLUGIN_DST/README.md"
              rm -f "$_PRESERVED_README"
              _PRESERVED_MSG=" (README preserved)"
            fi

            find "$_PLUGIN_DST" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
            echo "  AUTO-SYNCED  plugins/$_MANIFEST_NAME/$_PRESERVED_MSG"
            AUTO_BUILT_PLUGINS="${AUTO_BUILT_PLUGINS:+$AUTO_BUILT_PLUGINS }$_MANIFEST_NAME"
          else
            echo "  Warning: build produced no plugin at $_BUILD_DIR"
          fi
        else
          # A failed build is fatal (#73). Surface the child's own diagnosis
          # first: with the build stage a mktemp -d that the EXIT trap removes,
          # it is the only artifact the failure ever produces, and a bare
          # "failed" line leaves it undiagnosable.
          #
          # Recorded rather than exited on right here so a run with several
          # broken manifests names all of them in one pass instead of one per
          # re-run. The exit happens at the end of this loop — still ahead of
          # every stage that regenerates the catalogue.
          #
          # The record is written FIRST, before the log is echoed. $_BUILD_LOG
          # is named after $_MANIFEST_NAME, which is free text out of the
          # manifest's `.name`: a `/` in it makes the `>"$_BUILD_LOG"` redirect
          # fail, so no log file exists, so `sed` on it fails, and under `set -e`
          # that kills the run before _FAILED_BUILDS is ever assigned — losing
          # the whole point of collecting failures, since the summary that names
          # every broken manifest in one pass then never prints. `|| true` on
          # the sed for the same reason: reporting the failure must not be able
          # to destroy the record of it.
          echo "  ERROR: prepare-plugin.sh failed for $_MANIFEST" >&2
          _FAILED_BUILDS="${_FAILED_BUILDS:+$_FAILED_BUILDS }$_MANIFEST"
          sed 's/^/    | /' "$_BUILD_LOG" >&2 || true
        fi
      fi
      echo ""
    fi
  done

fi

# --- Collected-failure gate (#73) ---
# A manifest that could not be published must stop the run. Everything after
# this point regenerates the monorepo's catalogue — the root README's plugin
# table, the CHANGELOG entry and .claude-plugin/marketplace.json — from the
# published plugins/ tree. Continuing would publish a catalogue describing a
# plugin this run failed to build, at whatever version was already on disk, and
# report exit 0 while doing it. That is the "reports success while not doing its
# job" shape, and before this it was exactly what happened.
#
# OUTSIDE the `[[ -x "$PREPARE_SCRIPT" ]]` block, deliberately. Two of the three
# lists are filled inside it, but _BARE_ENTRY_MANIFESTS is filled by the main
# sync loop, which runs whether or not prepare-plugin.sh is even present. Nested
# inside, a missing or non-executable prepare-plugin.sh would silently disarm
# the bare-entry refusal along with the build ones.
#
# The trade-off is deliberate. Stopping here leaves skills synced but the
# README/CHANGELOG/marketplace not regenerated — inconsistent, but loud, fully
# git-recoverable, and fixed by re-running after the manifest is corrected.
if [[ -n "$_FAILED_BUILDS$_UNREADABLE_MANIFESTS$_BARE_ENTRY_MANIFESTS" ]]; then
  echo "" >&2
  echo "Error: refusing to continue — one or more manifests could not be published." >&2
  # Named separately rather than lumped under one "build failed" line: only the
  # first is a build that ran and failed. Calling a read error or a rejected
  # entry a "build failure" is a message claiming more than happened, which is
  # the defect class this whole batch exists to remove.
  if [[ -n "$_FAILED_BUILDS" ]]; then
    echo "       plugin build failed:        $_FAILED_BUILDS" >&2
  fi
  if [[ -n "$_UNREADABLE_MANIFESTS" ]]; then
    echo "       skills[] could not be read: $_UNREADABLE_MANIFESTS" >&2
  fi
  if [[ -n "$_BARE_ENTRY_MANIFESTS" ]]; then
    echo "       bare-string agents[] entry: $_BARE_ENTRY_MANIFESTS" >&2
  fi
  echo "       The diagnosis for each is above." >&2
  # Under --dry-run nothing was written at all, so the "already written"
  # sentence would be false. Verified: a --dry-run over a manifest with
  # "skills": [123] reached this gate and printed it.
  if $DRY_RUN; then
    echo "       Nothing was written — this was a --dry-run." >&2
  else
    echo "       Skills synced before this point are already written; the" >&2
    echo "       monorepo README, CHANGELOG and marketplace catalogue are" >&2
    echo "       deliberately NOT regenerated, so they cannot come to describe" >&2
    echo "       a manifest this run could not publish." >&2
  fi
  echo "       Fix the manifest and re-run." >&2
  exit 1
fi

# Add new plugin from build directory if --add-plugin specified (manual override)
if [[ -n "$ADD_PLUGIN" ]]; then
  PLUGIN_BUILD="./build/$ADD_PLUGIN"
  if [[ ! -d "$PLUGIN_BUILD" ]]; then
    echo "Error: plugin build directory not found: $PLUGIN_BUILD" >&2
    echo "Run: prepare-plugin.sh <manifest-file> first" >&2
    exit 1
  fi
  if [[ ! -f "$PLUGIN_BUILD/.claude-plugin/plugin.json" ]]; then
    echo "Error: $PLUGIN_BUILD is not a valid plugin (missing .claude-plugin/plugin.json)" >&2
    exit 1
  fi

  PLUGIN_DST="$MONOREPO_DIR/plugins/$ADD_PLUGIN"
  echo "--- Plugin: $ADD_PLUGIN ---"

  if $DRY_RUN; then
    echo "  WOULD COPY  plugins/$ADD_PLUGIN/"
  else
    # Preserve hand-written README if it exists in the destination.
    PRESERVED_README=""
    if [[ -f "$PLUGIN_DST/README.md" ]]; then
      PRESERVED_README=$(mktemp)
      cp "$PLUGIN_DST/README.md" "$PRESERVED_README"
    fi

    mkdir -p "$PLUGIN_DST"
    rsync -a --delete --exclude='.DS_Store' "$PLUGIN_BUILD/" "$PLUGIN_DST/"

    # Restore preserved README (overwrite auto-generated template)
    PRESERVED_FILES=""
    if [[ -n "$PRESERVED_README" ]]; then
      cp "$PRESERVED_README" "$PLUGIN_DST/README.md"
      rm -f "$PRESERVED_README"
      PRESERVED_FILES="README"
    fi
    if [[ -n "$PRESERVED_FILES" ]]; then
      echo "  SYNCED  plugins/$ADD_PLUGIN/ ($PRESERVED_FILES preserved)"
    else
      echo "  SYNCED  plugins/$ADD_PLUGIN/"
    fi

    # Preserve execute permissions on scripts
    find "$PLUGIN_DST" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
  fi
  echo ""
fi

# --- Auto-resync plugins when bare skill content changes ---
# After syncing bare skills, check if any plugin copies have drifted.
# Patches skill content directly (SKILL.md, scripts/, references/, agents/)
# without touching plugin README/plugin.json (those are managed separately).
# CHANGELOG.md IS synced from source to keep version history in sync.
if [[ -d "$MONOREPO_DIR/plugins" ]]; then
  PLUGINS_RESYNCED=0
  for _PLUGIN_DIR in "$MONOREPO_DIR/plugins"/*/; do
    [[ ! -d "$_PLUGIN_DIR" ]] && continue
    _PLUGIN_NAME=$(basename "$_PLUGIN_DIR")
    _PLUGIN_DRIFTED=false

    # Every copy below resolves its source through the same local-first
    # skill_source_dir() the main loop refused, so without this the resync
    # reverts plugins/<name>/ — the copy installers actually receive — right
    # after the sync announced it had refused to. Announce the skipped skills
    # once per plugin, then skip them individually in each stage: a plugin
    # whose OTHER skills legitimately drifted must still resync those.
    _PLUGIN_REFUSED=""
    for _PREF_DIR in "$_PLUGIN_DIR"skills/*/; do
      [[ ! -d "$_PREF_DIR" ]] && continue
      _PREF_NAME=$(basename "$_PREF_DIR")
      if skill_refused "$_PREF_NAME"; then
        _PLUGIN_REFUSED="${_PLUGIN_REFUSED:+$_PLUGIN_REFUSED }$_PREF_NAME"
      fi
    done
    if [[ -n "$_PLUGIN_REFUSED" ]]; then
      echo "  SKIP (reversion guard)  plugins/$_PLUGIN_NAME resync  —  stale local source for: $_PLUGIN_REFUSED"
    fi

    # Check each skill in the plugin against its source
    for _PSKILL_MD in "$_PLUGIN_DIR"skills/*/SKILL.md; do
      [[ ! -f "$_PSKILL_MD" ]] && continue
      _SNAME=$(basename "$(dirname "$_PSKILL_MD")")
      if skill_refused "$_SNAME"; then continue; fi
      _SNAME_SRC=$(skill_source_dir "$_SNAME")
      _SRC_MD="${_SNAME_SRC:+$_SNAME_SRC/SKILL.md}"
      if [[ -f "$_SRC_MD" ]] && ! diff -q "$_PSKILL_MD" "$_SRC_MD" >/dev/null 2>&1; then
        _PLUGIN_DRIFTED=true; break
      fi
    done

    # Check scripts
    if ! $_PLUGIN_DRIFTED; then
      for _PSCRIPTS in "$_PLUGIN_DIR"skills/*/scripts; do
        [[ ! -d "$_PSCRIPTS" ]] && continue
        _SNAME=$(basename "$(dirname "$_PSCRIPTS")")
        if skill_refused "$_SNAME"; then continue; fi
        _SNAME_SRC=$(skill_source_dir "$_SNAME")
        _SRC_SCRIPTS="${_SNAME_SRC:+$_SNAME_SRC/scripts}"
        if [[ -n "$_SRC_SCRIPTS" && -d "$_SRC_SCRIPTS" ]]; then
          _SDIFF=$(diff -rq "$_PSCRIPTS" "$_SRC_SCRIPTS" 2>/dev/null | grep -v '.DS_Store' || true)
          if [[ -n "$_SDIFF" ]]; then _PLUGIN_DRIFTED=true; break; fi
        fi
      done
    fi

    # Check agents
    if ! $_PLUGIN_DRIFTED; then
      for _PAGENT in "$_PLUGIN_DIR"agents/*.md; do
        [[ ! -f "$_PAGENT" ]] && continue
        _AFILE=$(basename "$_PAGENT")
        _SRC_AGENT="$HOME/.claude/agents/$_AFILE"
        if [[ -f "$_SRC_AGENT" ]] && ! diff -q "$_PAGENT" "$_SRC_AGENT" >/dev/null 2>&1; then
          _PLUGIN_DRIFTED=true; break
        fi
      done
    fi

    # Check CHANGELOGs (skill-level and plugin-root)
    if ! $_PLUGIN_DRIFTED; then
      for _PCL in "$_PLUGIN_DIR"skills/*/CHANGELOG.md; do
        [[ ! -f "$_PCL" ]] && continue
        _SNAME=$(basename "$(dirname "$_PCL")")
        if skill_refused "$_SNAME"; then continue; fi
        _SNAME_SRC=$(skill_source_dir "$_SNAME")
        _SRC_CL="${_SNAME_SRC:+$_SNAME_SRC/CHANGELOG.md}"
        if [[ -f "$_SRC_CL" ]] && ! diff -q "$_PCL" "$_SRC_CL" >/dev/null 2>&1; then
          _PLUGIN_DRIFTED=true; break
        fi
      done
    fi

    if $_PLUGIN_DRIFTED; then
      echo "--- Plugin resync: $_PLUGIN_NAME ---"
      _PATCHED=""

      # Patch skill files
      for _PSKILL_DIR in "$_PLUGIN_DIR"skills/*/; do
        [[ ! -d "$_PSKILL_DIR" ]] && continue
        _SNAME=$(basename "$_PSKILL_DIR")
        # Guards SKILL.md, scripts/, references/ and CHANGELOG.md below in one
        # place — all four copy from the same refused local source.
        if skill_refused "$_SNAME"; then continue; fi
        _SRC=$(skill_source_dir "$_SNAME")
        [[ -z "$_SRC" ]] && continue

        # SKILL.md
        if [[ -f "$_SRC/SKILL.md" ]] && ! diff -q "$_PSKILL_DIR/SKILL.md" "$_SRC/SKILL.md" >/dev/null 2>&1; then
          if $DRY_RUN; then
            echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/skills/$_SNAME/SKILL.md"
          else
            cp "$_SRC/SKILL.md" "$_PSKILL_DIR/SKILL.md"
            _PATCHED="${_PATCHED:+$_PATCHED, }SKILL.md"
          fi
        fi

        # scripts/
        if [[ -d "$_SRC/scripts" && -d "$_PSKILL_DIR/scripts" ]]; then
          _SDIFF=$(diff -rq "$_PSKILL_DIR/scripts" "$_SRC/scripts" 2>/dev/null | grep -v '.DS_Store' || true)
          if [[ -n "$_SDIFF" ]]; then
            if $DRY_RUN; then
              echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/skills/$_SNAME/scripts/"
            else
              rsync -a --delete --exclude='.DS_Store' "$_SRC/scripts/" "$_PSKILL_DIR/scripts/"
              find "$_PSKILL_DIR/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
              _PATCHED="${_PATCHED:+$_PATCHED, }scripts"
            fi
          fi
        fi

        # references/
        if [[ -d "$_SRC/references" && -d "$_PSKILL_DIR/references" ]]; then
          _RDIFF=$(diff -rq "$_PSKILL_DIR/references" "$_SRC/references" 2>/dev/null | grep -v '.DS_Store' || true)
          if [[ -n "$_RDIFF" ]]; then
            if $DRY_RUN; then
              echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/skills/$_SNAME/references/"
            else
              rsync -a --delete --exclude='.DS_Store' "$_SRC/references/" "$_PSKILL_DIR/references/"
              _PATCHED="${_PATCHED:+$_PATCHED, }references"
            fi
          fi
        fi

        # CHANGELOG.md — sync from source skill to plugin skill directory
        if [[ -f "$_SRC/CHANGELOG.md" && -f "$_PSKILL_DIR/CHANGELOG.md" ]]; then
          if ! diff -q "$_PSKILL_DIR/CHANGELOG.md" "$_SRC/CHANGELOG.md" >/dev/null 2>&1; then
            if $DRY_RUN; then
              echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/skills/$_SNAME/CHANGELOG.md"
            else
              cp "$_SRC/CHANGELOG.md" "$_PSKILL_DIR/CHANGELOG.md"
              _PATCHED="${_PATCHED:+$_PATCHED, }CHANGELOG.md"
            fi
          fi
        fi
      done

      # CHANGELOG.md — also sync to plugin root (top-level CHANGELOG)
      # Use the first skill's CHANGELOG as the plugin-level CHANGELOG
      _FIRST_SKILL_DIR=$(ls -d "$_PLUGIN_DIR"skills/*/ 2>/dev/null | head -1)
      _FIRST_SNAME=""
      [[ -n "$_FIRST_SKILL_DIR" ]] && _FIRST_SNAME=$(basename "$_FIRST_SKILL_DIR")
      # A refused first skill would drag the plugin-root CHANGELOG backwards too,
      # leaving the plugin advertising a version its files no longer are.
      if [[ -n "$_FIRST_SNAME" ]] && ! skill_refused "$_FIRST_SNAME"; then
        _FIRST_SNAME_SRC=$(skill_source_dir "$_FIRST_SNAME")
        _FIRST_SRC_CL="${_FIRST_SNAME_SRC:+$_FIRST_SNAME_SRC/CHANGELOG.md}"
        if [[ -f "$_FIRST_SRC_CL" && -f "$_PLUGIN_DIR/CHANGELOG.md" ]]; then
          if ! diff -q "$_PLUGIN_DIR/CHANGELOG.md" "$_FIRST_SRC_CL" >/dev/null 2>&1; then
            if $DRY_RUN; then
              echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/CHANGELOG.md"
            else
              cp "$_FIRST_SRC_CL" "$_PLUGIN_DIR/CHANGELOG.md"
              _PATCHED="${_PATCHED:+$_PATCHED, }root CHANGELOG.md"
            fi
          fi
        fi
      fi

      # Patch agent files
      if [[ -d "$_PLUGIN_DIR/agents" ]]; then
        for _PAGENT in "$_PLUGIN_DIR"agents/*.md; do
          [[ ! -f "$_PAGENT" ]] && continue
          _AFILE=$(basename "$_PAGENT")
          _SRC_AGENT="$HOME/.claude/agents/$_AFILE"
          if [[ -f "$_SRC_AGENT" ]] && ! diff -q "$_PAGENT" "$_SRC_AGENT" >/dev/null 2>&1; then
            if $DRY_RUN; then
              echo "  WOULD UPDATE  plugins/$_PLUGIN_NAME/agents/$_AFILE"
            else
              cp "$_SRC_AGENT" "$_PAGENT"
              _PATCHED="${_PATCHED:+$_PATCHED, }agents/$_AFILE"
            fi
          fi
        done
      fi

      if ! $DRY_RUN && [[ -n "$_PATCHED" ]]; then
        echo "  RESYNCED  plugins/$_PLUGIN_NAME/ ($_PATCHED)"
      fi
      PLUGINS_RESYNCED=$((PLUGINS_RESYNCED + 1))
    fi
  done

  if [[ $PLUGINS_RESYNCED -gt 0 ]]; then
    echo ""
  fi
fi

# Build plugin catalog rows for README
PLUGINS_TO_LIST=$(discover_plugins)
PLUGIN_COUNT=0
PLUGIN_CATALOG_ROWS=""

if [[ -n "$PLUGINS_TO_LIST" ]]; then
  # Line-wise (issue #81): a plugin's manifest `name` (and therefore its
  # published directory name) is unconstrained free text and can contain a
  # space. Word-splitting it here would look for plugins/<fragment>/ instead
  # of the real plugins/<name>/, find nothing, and silently drop the plugin
  # from PLUGIN_COUNT and the catalog table with no error at all. Here-string,
  # not a pipe: PLUGIN_COUNT and PLUGIN_CATALOG_ROWS are read after the loop.
  # On fd 3, not stdin: see the main sync loop's comment. This body shells out
  # to jq, find and wc, so it has the exposure directly.
  while IFS= read -r PLUGIN_NAME <&3; do
    [[ -z "$PLUGIN_NAME" ]] && continue
    PLUGIN_DIR="$MONOREPO_DIR/plugins/$PLUGIN_NAME"
    PLUGIN_JSON="$PLUGIN_DIR/.claude-plugin/plugin.json"
    if [[ -f "$PLUGIN_JSON" ]]; then
      P_VERSION=$(jq -r '.version // "?"' "$PLUGIN_JSON")
      P_DESC=$(jq -r '.description // ""' "$PLUGIN_JSON")
      # Count skills and commands in the plugin
      P_SKILLS=0
      P_CMDS=0
      if [[ -d "$PLUGIN_DIR/skills" ]]; then
        P_SKILLS=$(find "$PLUGIN_DIR/skills" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
      fi
      if [[ -d "$PLUGIN_DIR/commands" ]]; then
        P_CMDS=$(find "$PLUGIN_DIR/commands" -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
      fi
      PLUGIN_CATALOG_ROWS="${PLUGIN_CATALOG_ROWS}| [$PLUGIN_NAME](./plugins/$PLUGIN_NAME/) | $P_VERSION | $P_SKILLS | $P_CMDS | $P_DESC |
"
      PLUGIN_COUNT=$((PLUGIN_COUNT + 1))
    fi
  done 3<<< "$PLUGINS_TO_LIST" </dev/null
fi

# --- Generate root README ---
echo "--- Root files ---"

# Build catalog table
CATALOG_TABLE="| Skill | Version | Description | Individual Repo |
|-------|---------|-------------|-----------------|
$CATALOG_ROWS"

# Read template and replace placeholders
if [[ -f "$TEMPLATE_DIR/monorepo-readme-template.md" ]]; then
  # Extract everything after the --- separator (skip the template header)
  ROOT_README=$(sed '1,/^---$/d' "$TEMPLATE_DIR/monorepo-readme-template.md")
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{GITHUB_USER}}|$GITHUB_USER|g")
  # SKILLS_RESOLVED_COUNT, not SKILL_COUNT and NOT SKILLS_SYNCED_COUNT (issue
  # #81, third pass): this placeholder describes the catalogue table right
  # below it, so it must match the catalogue's actual row count. A refused
  # skill still gets a catalog row (CATALOG_ROWS is built before the
  # reversion guard's `continue`, deliberately — see the comment where that
  # row is added, above), so the catalogue's row count is
  # SKILLS_RESOLVED_COUNT (every name that resolved to a real SKILL.md,
  # refused or not) rather than SKILLS_SYNCED_COUNT (resolved minus refused,
  # which undercounts the catalogue whenever anything was refused).
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{SKILL_COUNT}}|$SKILLS_RESOLVED_COUNT|g")
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{LAST_UPDATED}}|$TODAY|g")
  # Build install-all commands (one cp -r per skill)
  INSTALL_ALL_CMDS=""
  # Line-wise (issue #81): word-splitting a space-named skill here would turn
  # one real skill into two bogus, non-functional `cp -r` lines instead of the
  # one correct command — wrong instructions published with a straight face,
  # not merely a miscount. Here-string, not a pipe: INSTALL_ALL_CMDS is read
  # immediately after this loop. On fd 3 plus `</dev/null`, not stdin: see the
  # main sync loop's comment — pure-bash body today, uniform treatment so a
  # later addition cannot reintroduce the STDIN truncation silently. It is not
  # proof against a child that names fd 3 outright; nothing here is.
  while IFS= read -r SKILL_NAME <&3; do
    [[ -z "$SKILL_NAME" ]] && continue
    INSTALL_ALL_CMDS="${INSTALL_ALL_CMDS}cp -r /tmp/claude-code-skills/$SKILL_NAME ~/.claude/skills/$SKILL_NAME
"
  done 3<<< "$SKILLS_TO_SYNC" </dev/null

  # Build plugin section (only if plugins exist)
  PLUGIN_SECTION=""
  if [[ $PLUGIN_COUNT -gt 0 ]]; then
    PLUGIN_TABLE="| Plugin | Version | Skills | Commands | Description |
|--------|---------|--------|----------|-------------|
$PLUGIN_CATALOG_ROWS"

    PLUGIN_SECTION="## Plugins

Plugins bundle skills, commands, agents, and hooks into a single installable package.

$PLUGIN_TABLE

### Install via Claude Code (Recommended)

Add this repo as a plugin marketplace, then install individual plugins:

\`\`\`shell
# Add the marketplace (one-time setup)
/plugin marketplace add $GITHUB_USER/claude-code-skills

# Install a plugin
/plugin install PLUGIN_NAME@claude-code-skills
\`\`\`

To browse all available plugins interactively, run \`/plugin\` and go to the **Discover** tab.

### Install via Script

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`

### Uninstall a Plugin

\`\`\`bash
# Via Claude Code
/plugin uninstall PLUGIN_NAME@claude-code-skills

# Via script
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`"
  fi

  # Replace multi-line placeholders (catalog table, install-all commands, plugin section)
  TMPFILE=$(mktemp)
  echo "$ROOT_README" | while IFS= read -r line; do
    if [[ "$line" == *"{{SKILL_CATALOG_TABLE}}"* ]]; then
      echo "$CATALOG_TABLE"
    elif [[ "$line" == *"{{SKILL_INSTALL_ALL_COMMANDS}}"* ]]; then
      printf "%s" "$INSTALL_ALL_CMDS"
    elif [[ "$line" == *"{{PLUGIN_SECTION}}"* ]]; then
      if [[ -n "$PLUGIN_SECTION" ]]; then
        echo "$PLUGIN_SECTION"
      fi
    else
      echo "$line"
    fi
  done > "$TMPFILE"
  ROOT_README=$(cat "$TMPFILE")
  rm -f "$TMPFILE"
else
  echo "  Warning: monorepo-readme-template.md not found, generating minimal README"
  # SKILLS_RESOLVED_COUNT (issue #81, third pass): same reasoning as the
  # template branch above — this describes $CATALOG_TABLE's actual contents,
  # immediately below it, and the catalogue's row count is
  # SKILLS_RESOLVED_COUNT, not SKILLS_SYNCED_COUNT (see that comment).
  ROOT_README="# Claude Code Skills

A curated collection of $SKILLS_RESOLVED_COUNT reusable Agent Skills.

## Skills

$CATALOG_TABLE

## License

MIT

---
*Last synced: $TODAY*"
fi

write_file "$MONOREPO_DIR/README.md" "$ROOT_README" "README.md" "true"

# --- Update root CHANGELOG.md (audit log style) ---
# The root CHANGELOG tracks monorepo-level events only.
# Per-skill change details live in <skill>/CHANGELOG.md.
#
# Strategy: prepend a new sync entry to the existing file.
# If today already has a "Monorepo sync" entry, replace it (idempotent).

CHANGELOG_HEADER="# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own \`CHANGELOG.md\` within its directory.

Format: Monorepo-level events only. For per-skill change details, see \`<skill>/CHANGELOG.md\`.
"

# Build a compact skill inventory: name + version
SKILL_INVENTORY=""
# Line-wise (issue #81): a space-named skill split into fragments here resolves
# neither via skill_source_dir(), so it silently vanishes from the CHANGELOG's
# inventory instead of getting its own "- `name` vX.Y.Z" line. Here-string, not
# a pipe: SKILL_INVENTORY is read immediately after this loop. On fd 3, not
# stdin: see the main sync loop's comment. This body shells out to sed and grep
# (via extract_version/extract_field), so it has the exposure directly.
while IFS= read -r SKILL_NAME <&3; do
  [[ -z "$SKILL_NAME" ]] && continue
  SKILL_SRC=$(skill_source_dir "$SKILL_NAME")
  SKILL_MD="${SKILL_SRC:+$SKILL_SRC/SKILL.md}"
  # Refused skills were not copied, so describe them by what the repo actually
  # holds — reading the stale local copy here would record a version the
  # monorepo never received. Mirrors the catalog-row handling in the main loop
  # (issue #81, third pass): the inventory, like the catalogue, still lists a
  # refused skill — it did not vanish from the monorepo, it just didn't get a
  # fresh copy this run — so its entry is annotated rather than omitted. Without
  # this, "Synced 0 skills" would sit directly above a non-empty bullet list
  # with no explanation of what that entry is doing there.
  INVENTORY_REFUSED_NOTE=""
  if skill_refused "$SKILL_NAME"; then
    INVENTORY_REFUSED_NOTE=" (REFUSED — stale local source, not synced this run)"
    if [[ -f "$MONOREPO_DIR/$SKILL_NAME/SKILL.md" ]]; then
      SKILL_MD="$MONOREPO_DIR/$SKILL_NAME/SKILL.md"
    fi
  fi
  if [[ -f "$SKILL_MD" ]]; then
    VERSION=$(extract_version "$SKILL_MD")
    SHORT_DESC=$(extract_field "$SKILL_MD" "description" | sed 's/\. Use when:.*//')
    SKILL_INVENTORY="${SKILL_INVENTORY}
- \`$SKILL_NAME\` v${VERSION:-?.?.?}${INVENTORY_REFUSED_NOTE} — $SHORT_DESC"
  fi
done 3<<< "$SKILLS_TO_SYNC" </dev/null

# SKILLS_SYNCED_COUNT, not SKILL_COUNT (issue #81, second pass): "Synced" is
# past tense — a claim about what happened, persisted into the CHANGELOG —
# not the discovered/requested count.
SYNC_ENTRY="## [$TODAY] — Monorepo sync

Synced $SKILLS_SYNCED_COUNT skills from local source.
$SKILL_INVENTORY
"

# Preserve existing entries, replacing today's "Monorepo sync" if present.
# If the top entry is a versioned release (from release-monorepo.sh), keep it.
EXISTING_ENTRIES=""
SKIP_SYNC_ENTRY=false
if [[ -f "$MONOREPO_DIR/CHANGELOG.md" ]]; then
  # Extract all ## entries
  ALL_ENTRIES=$(awk '/^## \[/{found=1} found{print}' "$MONOREPO_DIR/CHANGELOG.md")
  # Parameter expansion, not `echo … | head -1`. `head` exits after the first
  # line, so `echo` races it and takes EPIPE once the entry text is well past
  # the 64 KiB pipe buffer. Normally the SIGPIPE kills echo silently; with an
  # EXIT trap registered, bash no longer leaves SIGPIPE at its default
  # disposition in the command-substitution subshell — the trap does not run
  # there, but echo's write() now returns EPIPE and gets reported:
  #   sync-monorepo.sh: line NNNN: echo: write error: Broken pipe
  # Stripping from the first newline is equivalent for every input, allocates
  # no subshell, and cannot race a reader.
  FIRST_ENTRY="${ALL_ENTRIES%%$'\n'*}"

  if echo "$FIRST_ENTRY" | grep -q "## \[$TODAY\] — Monorepo sync"; then
    # Today's sync entry exists — replace it with fresh one
    EXISTING_ENTRIES=$(echo "$ALL_ENTRIES" | awk '/^## \[/{count++} count>=2{print}')
  elif echo "$FIRST_ENTRY" | grep -qE "## \[[0-9]+\.[0-9]+\.[0-9]+\] - $TODAY"; then
    # Today's versioned release exists (from release-monorepo.sh) — don't clobber it
    EXISTING_ENTRIES="$ALL_ENTRIES"
    SKIP_SYNC_ENTRY=true
  else
    EXISTING_ENTRIES="$ALL_ENTRIES"
  fi
fi

if $SKIP_SYNC_ENTRY; then
  ROOT_CHANGELOG="${CHANGELOG_HEADER}
${EXISTING_ENTRIES}"
else
  ROOT_CHANGELOG="${CHANGELOG_HEADER}${SYNC_ENTRY}"
  if [[ -n "$EXISTING_ENTRIES" ]]; then
    ROOT_CHANGELOG="${ROOT_CHANGELOG}
${EXISTING_ENTRIES}"
  fi
fi

write_file "$MONOREPO_DIR/CHANGELOG.md" "$ROOT_CHANGELOG" "CHANGELOG.md" "true"

# --- .gitignore ---
# /build/ is here because prepare-plugin.sh's default --output-dir is
# ./build/<plugin-name>/: any plugin build run from the monorepo root drops a
# tree there, and the "Next steps" banner this script prints ends in
# `git add -A`. A monorepo generated without this line would commit it.
# Root-anchored deliberately: an unanchored `build/` matches at every depth, so
# a plugin that legitimately ships plugins/<name>/build/ would be silently
# excluded from that same `git add -A`.
GITIGNORE=".DS_Store
*.swp
*~
.claude/
/build/"

write_file "$MONOREPO_DIR/.gitignore" "$GITIGNORE" ".gitignore"

# write_file does not overwrite, so the template above only ever reaches a
# freshly --init-ed monorepo. An already-published one keeps whatever .gitignore
# it has and gets a bare "SKIP    .gitignore (already exists)" line, which reads
# exactly like "already correct" — so the fix above would reach nobody who
# already has a monorepo, silently. Say so instead.
#
# Advisory, never fatal: the file belongs to the monorepo, not to this script,
# and refusing to sync over a hand-edited .gitignore would be a far worse
# failure than the untracked build/ tree this warns about. The test is for the
# literal root-anchored line, matching what the template writes; a monorepo
# ignoring build/ some other way gets a NOTE it can ignore.
if [[ -f "$MONOREPO_DIR/.gitignore" ]] && ! grep -qxF '/build/' "$MONOREPO_DIR/.gitignore"; then
  echo "  NOTE: .gitignore exists but has no '/build/' line — prepare-plugin.sh"
  echo "        writes ./build/<name>/ by default, and the 'git add -A' in the"
  echo "        Next steps below would commit it. Add: /build/"
fi

# --- LICENSE ---
LICENSE_CONTENT="MIT License

Copyright (c) $YEAR $AUTHOR

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."

write_file "$MONOREPO_DIR/LICENSE" "$LICENSE_CONTENT" "LICENSE"

# --- CONTRIBUTING.md (monorepo variant from template) ---
if [[ -f "$TEMPLATE_DIR/CONTRIBUTING-template.md" ]]; then
  # Write scope content to temp file for awk multiline replacement
  SCOPE_TMP=$(mktemp)
  cat > "$SCOPE_TMP" <<'SCOPE_EOF'
### Adding a new skill

1. Create a new directory at the repo root (e.g., `my-skill/`)
2. Add a `SKILL.md` with valid YAML frontmatter
3. Optionally add `scripts/` and `references/` directories

### Improving an existing skill

- Edit the skill's `SKILL.md` to improve instructions or metadata
- Add or improve scripts in the skill's `scripts/` directory
- Add or update reference material in the skill's `references/` directory
- Fix bugs or improve documentation
SCOPE_EOF

  # Single-line replacements with sed, multiline with awk
  CONTRIBUTING_TMP=$(mktemp)
  sed "s|{{REPO_NAME}}|claude-code-skills|g; s|{{GITHUB_USER}}|$GITHUB_USER|g; s|{{VALIDATE_COMMAND}}|scripts/validate-skill.sh <skill-directory>|g" \
    "$TEMPLATE_DIR/CONTRIBUTING-template.md" > "$CONTRIBUTING_TMP"
  # Replace {{CONTRIBUTING_SCOPE}} line with scope file contents
  awk -v scopefile="$SCOPE_TMP" '{
    if ($0 ~ /\{\{CONTRIBUTING_SCOPE\}\}/) {
      while ((getline line < scopefile) > 0) print line
      close(scopefile)
    } else print
  }' "$CONTRIBUTING_TMP" > "$CONTRIBUTING_TMP.out"
  mv "$CONTRIBUTING_TMP.out" "$CONTRIBUTING_TMP"

  CONTRIBUTING_CONTENT=$(cat "$CONTRIBUTING_TMP")
  rm -f "$SCOPE_TMP" "$CONTRIBUTING_TMP"
  write_file "$MONOREPO_DIR/CONTRIBUTING.md" "$CONTRIBUTING_CONTENT" "CONTRIBUTING.md" "true"
fi

# --- .github/PULL_REQUEST_TEMPLATE.md ---
if [[ -f "$TEMPLATE_DIR/PR_TEMPLATE-template.md" ]]; then
  PR_TEMPLATE_CONTENT=$(cat "$TEMPLATE_DIR/PR_TEMPLATE-template.md")
  if $DRY_RUN; then
    echo "  WOULD UPDATE  .github/PULL_REQUEST_TEMPLATE.md"
  else
    mkdir -p "$MONOREPO_DIR/.github"
    echo "$PR_TEMPLATE_CONTENT" > "$MONOREPO_DIR/.github/PULL_REQUEST_TEMPLATE.md"
    echo "  SYNCED  .github/PULL_REQUEST_TEMPLATE.md"
  fi
fi

# --- .github/workflows/validate-skill.yml (monorepo variant) ---
if [[ -f "$TEMPLATE_DIR/workflow-monorepo.yml" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  .github/workflows/validate-skill.yml"
  else
    mkdir -p "$MONOREPO_DIR/.github/workflows"
    cp "$TEMPLATE_DIR/workflow-monorepo.yml" "$MONOREPO_DIR/.github/workflows/validate-skill.yml"
    echo "  SYNCED  .github/workflows/validate-skill.yml"
  fi
fi

# --- scripts/validate-skill.sh (copy from skill-publishing) ---
VALIDATE_SRC="$SCRIPT_DIR/validate-skill.sh"
if [[ -f "$VALIDATE_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/validate-skill.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$VALIDATE_SRC" "$MONOREPO_DIR/scripts/validate-skill.sh"
    chmod +x "$MONOREPO_DIR/scripts/validate-skill.sh"
    echo "  SYNCED  scripts/validate-skill.sh"
  fi
fi

# --- scripts/validate-plugin.sh (copy from skill-publishing) ---
VALIDATE_PLUGIN_SRC="$SCRIPT_DIR/validate-plugin.sh"
if [[ -f "$VALIDATE_PLUGIN_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/validate-plugin.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$VALIDATE_PLUGIN_SRC" "$MONOREPO_DIR/scripts/validate-plugin.sh"
    chmod +x "$MONOREPO_DIR/scripts/validate-plugin.sh"
    echo "  SYNCED  scripts/validate-plugin.sh"
  fi
fi

# --- scripts/install-plugin.sh (copy from skill-publishing) ---
INSTALL_PLUGIN_SRC="$SCRIPT_DIR/install-plugin.sh"
if [[ -f "$INSTALL_PLUGIN_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/install-plugin.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$INSTALL_PLUGIN_SRC" "$MONOREPO_DIR/scripts/install-plugin.sh"
    chmod +x "$MONOREPO_DIR/scripts/install-plugin.sh"
    echo "  SYNCED  scripts/install-plugin.sh"
  fi
fi

# --- .claude-plugin/marketplace.json (auto-generated) ---
# Build marketplace.json so the monorepo can be added as a plugin marketplace
# via: /plugin marketplace add GITHUB_USER/claude-code-skills
if [[ $PLUGIN_COUNT -gt 0 ]]; then
  MARKETPLACE_PLUGINS=""
  # On fd 3 for the same reason as every other list-driven loop in this file:
  # this body spawns dirname and three jq invocations per iteration, and a
  # process substitution on plain stdin is the loop body's stdin exactly as a
  # here-string is. None of those children reads stdin today — but that is the
  # argument already rejected at the install-all loop, whose comment reads
  # "uniform treatment so a later addition cannot reintroduce the STDIN
  # truncation silently". Leaving this one out would have made that rule apply
  # everywhere except the one loop that actually spawns things.
  while IFS= read -r pjson <&3; do
    pdir=$(dirname "$(dirname "$pjson")")
    pname=$(jq -r '.name // ""' "$pjson" 2>/dev/null)
    pdesc=$(jq -r '.description // ""' "$pjson" 2>/dev/null)
    pver=$(jq -r '.version // ""' "$pjson" 2>/dev/null)
    if [[ -n "$pname" ]]; then
      if [[ -n "$MARKETPLACE_PLUGINS" ]]; then
        MARKETPLACE_PLUGINS="$MARKETPLACE_PLUGINS,"
      fi
      # Use relative path from monorepo root
      rel_path="./plugins/$pname"
      MARKETPLACE_PLUGINS="$MARKETPLACE_PLUGINS
    {
      \"name\": \"$pname\",
      \"source\": \"$rel_path\",
      \"description\": \"$pdesc\",
      \"version\": \"$pver\"
    }"
    fi
  done 3< <(find "$MONOREPO_DIR/plugins" -maxdepth 3 -name "plugin.json" -path "*/.claude-plugin/*" 2>/dev/null | sort) </dev/null

  MARKETPLACE_JSON="{
  \"name\": \"claude-code-skills\",
  \"owner\": {
    \"name\": \"$AUTHOR\"
  },
  \"metadata\": {
    \"description\": \"Reusable Agent Skills and Plugins for Claude Code\",
    \"version\": \"$(date +%Y.%m.%d)\"
  },
  \"plugins\": [$MARKETPLACE_PLUGINS
  ]
}"

  if $DRY_RUN; then
    echo "  WOULD UPDATE  .claude-plugin/marketplace.json"
  else
    mkdir -p "$MONOREPO_DIR/.claude-plugin"
    echo "$MARKETPLACE_JSON" > "$MONOREPO_DIR/.claude-plugin/marketplace.json"
    echo "  SYNCED  .claude-plugin/marketplace.json"
  fi
fi

echo ""

# --- Init mode: git init + create repo ---
if $INIT_MODE && ! $DRY_RUN; then
  echo "Initializing git repository..."
  cd "$MONOREPO_DIR"
  git init
  git add -A
  # SKILLS_SYNCED_COUNT, not SKILL_COUNT (issue #81, second pass): "synced" is
  # past tense, persisted into a commit message this time.
  git commit -m "Initial commit: $SKILLS_SYNCED_COUNT skills synced from local source"

  echo ""
  echo "Creating GitHub repository..."
  gh repo create claude-code-skills --public \
    --description "A curated collection of reusable Agent Skills for Claude Code, Cursor, Codex CLI, and Gemini CLI" \
    --source . --push

  echo ""
  echo "Monorepo initialized and pushed to GitHub."
  echo "URL: https://github.com/$GITHUB_USER/claude-code-skills"
elif $INIT_MODE && $DRY_RUN; then
  echo "WOULD: git init, commit, and create GitHub repo 'claude-code-skills'"
fi

# --- Summary ---
echo ""
if $DRY_RUN; then
  echo "Dry run complete. No files were written."
else
  # SKILLS_SYNCED_COUNT, not SKILL_COUNT (issue #81): SKILL_COUNT is how many
  # names discover_skills() produced, which under the unquoted-loop bug this
  # task fixes was not the same thing as how many the loop actually processed
  # — a name that IFS-split into unresolvable fragments was still counted here
  # even though nothing was copied for it. SKILLS_SYNCED_COUNT (computed once,
  # right after the main loop — see its definition above) is
  # SKILLS_RESOLVED_COUNT minus REFUSED_COUNT: every other stage that reports
  # this same figure in the past tense uses the identical variable, so there is
  # one honest number instead of several that could drift apart.
  echo "Sync complete. $SKILLS_SYNCED_COUNT skills synced to $MONOREPO_DIR"
  if [[ -n "$AUTO_BUILT_PLUGINS" ]]; then
    echo "Auto-built plugins: $AUTO_BUILT_PLUGINS"
  fi
  if ! $INIT_MODE; then
    echo ""
    echo "Next steps:"
    echo "  cd $MONOREPO_DIR"
    echo "  git add -A && git diff --cached --stat"
    echo "  git commit -m \"Sync skills ($TODAY)\""
    echo "  git push"
  fi
fi

# A run that declined to sync part of its input has not succeeded, so exit
# non-zero (3, distinct from the exit-1 usage/setup errors) after doing all the
# work it safely could. Callers and CI then see the skip instead of a clean 0.
if [[ "$REFUSED_COUNT" -gt 0 ]]; then
  echo ""
  echo "REFUSED $REFUSED_COUNT skill(s) — stale local source would have reverted newer in-repo content:"
  printf '%s' "$REFUSED_SKILLS" | sed 's/^/  - /'
  echo "Remove the stale local copies, or re-run with --force-local to override."
  exit 3
fi
