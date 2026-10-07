#!/usr/bin/env bash
# apply-promotions.sh — Move candidate items to Done and stamp each with a
# "Released in <tag>" comment on the linked GitHub issue/PR.
#
# Usage:
#   apply-promotions.sh <candidates.json> --dry-run     # preview only (no API writes)
#   apply-promotions.sh <candidates.json> --apply       # commit changes + comments
#
# Optional flags:
#   --release-tag <tag>      Force this release tag for all comments and release
#                            milestones (skip lookup)
#   --no-release-comment     Skip release comment entirely (still moves to Done, and
#                            still looks up the release to set the milestone)
#
# For each promoted item the script:
#   1. updateProjectV2ItemFieldValue → Status = Done (mutation)
#   2. Comments, branching on the candidate's .promoteClass:
#      - "merged"          → looks up the OLDEST GitHub Release whose tag contains
#                            the merge commit (per-repo+SHA cached) and posts
#                            "🚀 Released in <tag> ..."
#      - "nopr"/"wontfix"  → posts a fixed note explaining why the card was
#                            promoted without a merged PR (see nopr_comment_body).
#                            Idempotent via an HTML marker, so re-running a release
#                            does not stack duplicate comments.
#
#   3. "merged" class only: sets the item's milestone to the release milestone of
#      the tag from step 2 (or --release-tag): the exact vX.Y.Z title, else vX.Y,
#      leading v optional. Written through REST by number
#      (gh api -X PATCH repos/O/R/issues/N -F milestone=<number>), so a closed
#      milestone works. No change when it already matches; a warning and no write
#      when no single milestone matches. nopr/wontfix keep their milestone.
#
# Ordering is deliberate: the board move happens FIRST, then the milestone and the
# comment. The comment asserts "Promoted to Done", so it must never exist for an
# item whose mutation failed.
#
# Comment and milestone failures are reported but do NOT count as a promotion
# failure — the board move is the primary side-effect; the rest is annotation.
#
# Exit codes: 0=ok (includes "no candidates" and --dry-run)
#             1=one or more status mutations failed, OR the input projection
#               emitted fewer rows than there were candidates (board NOT in sync)
#             2=usage, unreadable input, or candidates.json missing project.id /
#               statusField.id / statusField.doneOptionId
#             3=auth: --apply without the write-capable `project` scope
# Note 3 is reachable only under --apply; --dry-run writes nothing and is exempt.
# A failed release COMMENT or MILESTONE write does not change the exit code (see above).

set -eu

usage() {
  cat <<EOF
Usage: apply-promotions.sh <candidates.json> (--dry-run | --apply)
                            [--release-tag TAG] [--no-release-comment]

Promotes each candidate's Status field to the Done option, then comments on the
linked issue/PR identifying which GitHub Release shipped the work.

Examples:
  apply-promotions.sh /tmp/cand.json --dry-run
  apply-promotions.sh /tmp/cand.json --apply
  apply-promotions.sh /tmp/cand.json --apply --release-tag v1.6.2
  apply-promotions.sh /tmp/cand.json --apply --no-release-comment
EOF
}

[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { usage; exit 0; }
[ $# -lt 2 ] && { usage >&2; exit 2; }

INPUT="$1"; shift
MODE="$1"; shift
case "$MODE" in
  --dry-run|--apply) : ;;
  *) usage >&2; exit 2 ;;
esac

FORCE_TAG=""
SKIP_COMMENT="false"
while [ $# -gt 0 ]; do
  case "$1" in
    --release-tag)
      [ $# -ge 2 ] || { echo "ERROR: --release-tag needs a value" >&2; exit 2; }
      FORCE_TAG="$2"; shift 2 ;;
    --no-release-comment) SKIP_COMMENT="true"; shift ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -r "$INPUT" ] || { echo "ERROR: cannot read $INPUT" >&2; exit 2; }

DATA=$(cat "$INPUT")
PROJECT_ID=$(echo "$DATA" | jq -r '.project.id')
FIELD_ID=$(echo "$DATA" | jq -r '.statusField.id')
DONE_OPT=$(echo "$DATA" | jq -r '.statusField.doneOptionId')
# The resolver's last tier is a substring match on done|released|shipped, on
# boards whose real columns include "Done in develop". Print the NAME so the
# operator approving a dry-run can see which column is about to be written.
DONE_NAME=$(echo "$DATA" | jq -r '
  .statusField.doneOptionName
  // ([(.statusField.options // [])[] | select(.id == .statusField.doneOptionId) | .name][0])
  // ""')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "null" ]; then
  echo "ERROR: candidates.json missing project.id" >&2; exit 2
fi
# Unguarded, a missing statusField.id reaches the mutation as the literal string
# "null" and every item fails individually with an opaque GraphQL error.
if [ -z "$FIELD_ID" ] || [ "$FIELD_ID" = "null" ]; then
  echo "ERROR: candidates.json missing statusField.id" >&2; exit 2
fi
if [ -z "$DONE_OPT" ] || [ "$DONE_OPT" = "null" ]; then
  echo "ERROR: candidates.json missing statusField.doneOptionId" >&2; exit 2
fi

COUNT=$(echo "$DATA" | jq '.candidates | length')
# Distinct itemIds — what the projection below is expected to emit after its
# one-row-per-item dedup. Compared against rows actually processed at the end.
# `// ""` matches the projection: its `join` renders a null itemId as an empty
# field and the awk dedup collapses every empty one to a single row, so counting
# null and "" as distinct here would false-trip the reconciliation after a fully
# successful run.
EXPECTED_ROWS=$(echo "$DATA" | jq '[.candidates[] | (.itemId // "")] | unique | length' 2>/dev/null) \
  || EXPECTED_ROWS=""
case "$EXPECTED_ROWS" in
  ''|*[!0-9]*)
    # `.candidates` is not a list of objects. Left unchecked this reached the
    # `-ne` below as an empty string and died with a bash error instead of a
    # diagnosis.
    echo "ERROR: candidates.json .candidates is not a list of objects — cannot count" >&2
    echo "       the rows this run should process. Nothing was attempted." >&2
    exit 2 ;;
esac
echo "Project: $(echo "$DATA" | jq -r '.project.title') (#$(echo "$DATA" | jq -r '.project.number'))"
echo "Mode: $MODE"
echo "Candidates: $COUNT"
if [ -n "$DONE_NAME" ] && [ "$DONE_NAME" != "null" ]; then
  echo "Target column: $DONE_NAME  (option $DONE_OPT)"
else
  echo "Target column: (name unavailable in candidates.json)  (option $DONE_OPT)"
fi
if [ "$SKIP_COMMENT" = "true" ]; then
  echo "Release comment: disabled (--no-release-comment)"
elif [ -n "$FORCE_TAG" ]; then
  echo "Release comment: forced tag '$FORCE_TAG'"
else
  echo "Release comment: auto-detect smallest containing release per item"
fi
echo ""

[ "$COUNT" = "0" ] && { echo "No candidates to promote. Exiting."; exit 0; }

CACHE_DIR=$(mktemp -d)
trap 'rm -rf "$CACHE_DIR"' EXIT

# Row separator for both read-loops: ASCII unit separator, written as the escape
# \u001f in jq and $'\037' in bash. Never as a raw control byte, which does not
# survive editing and silently leaves an empty IFS. `clean` strips CR/LF AND the
# separator itself from field VALUES, so neither a newline nor a stray \u001f in a
# title can split one row into two. Guarding only the characters that used to
# break rows, and not the one this rework introduced, would reopen the same class.
JQ_CLEAN='def clean: if . == null then "" else tostring | gsub("[\r\n\u001f]"; " ") end;'
RELEASE_ROWS_JQ="$JQ_CLEAN"'
  .[] | [(.tag_name|clean), (.html_url|clean), (.published_at|clean)] | join("\u001f")'

# find_release_for_commit <repo> <sha>
# Echoes JSON {tag, url, published_at}, "null" when no release contains the commit,
# or the sentinel "unavailable" when the release listing itself could not be
# fetched. "unavailable" is NOT "null": an empty list cached after a failed API
# call would silently suppress the release comment for every remaining item in
# that repo and report it as "no release contains <sha>".
find_release_for_commit() {
  local repo="$1" sha="$2"
  [ -z "$sha" ] || [ "$sha" = "null" ] && { echo "null"; return; }
  local repo_slug="${repo//\//_}"
  local cache_file="$CACHE_DIR/release_${repo_slug}_${sha}"
  if [ -f "$cache_file" ]; then cat "$cache_file"; return; fi

  local releases_file="$CACHE_DIR/releases_${repo_slug}"
  local failed_marker="$CACHE_DIR/releases_failed_${repo_slug}"
  [ -f "$failed_marker" ] && { echo "unavailable"; return; }
  if [ ! -f "$releases_file" ]; then
    # --paginate applies --jq to EACH PAGE separately, so a sort inside --jq only
    # orders within a page. GitHub returns releases newest-first, so that walked
    # the 30 newest before any older one and stamped issues with a too-new tag.
    # Fetch raw, then sort ONCE across the concatenated pages.
    local raw rc
    set +e
    raw=$(gh api "/repos/${repo}/releases" --paginate 2>&1)
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      echo "WARN: could not list releases for ${repo} (gh exit $rc): $(echo "$raw" | tr '\n' ' ' | cut -c1-160)" >&2
      echo "      release comments for this repo will be reported as FAILED, not skipped." >&2
      : > "$failed_marker"
      echo "unavailable"; return
    fi
    if ! echo "$raw" | jq -s 'add // [] | map(select(.draft == false)) | sort_by(.published_at)' > "$releases_file" 2>/dev/null; then
      echo "WARN: could not parse the release listing for ${repo} (unexpected payload)." >&2
      rm -f "$releases_file"
      : > "$failed_marker"
      echo "unavailable"; return
    fi
  fi

  local result="null"
  # Unit separator, not tab: tab is IFS WHITESPACE, so a run of them folds and an
  # empty field shifts every later column left. A release with a null html_url
  # would otherwise put the timestamp in the link. Same fix as the candidates loop.
  while IFS=$'\037' read -r tag url pub; do
    [ -z "$tag" ] && continue
    local cmp_status
    # A FAILED compare is NOT "this release does not contain the commit". Falling
    # through to the next (newer) release on error means one transient 5xx on the
    # true container stamps the issue with a too-new tag: the same wrong-tag
    # outcome the pagination fix exists to prevent, arriving via the error path.
    cmp_status=$(gh api "/repos/${repo}/compare/${sha}...${tag}" --jq '.status' 2>&1) \
      || cmp_status="error"
    case "$cmp_status" in
      ahead|identical)
        result=$(jq -n --arg t "$tag" --arg u "$url" --arg p "$pub" \
          '{tag:$t, url:$u, published_at:$p}')
        break ;;
      behind|diverged) : ;;
      *)
        echo "WARN: compare failed for ${repo} ${sha}...${tag}: $(echo "$cmp_status" | tr '\n' ' ' | cut -c1-160)" >&2
        echo "      cannot tell which release contains this commit; claiming none." >&2
        result="unavailable"
        break ;;
    esac
  done < <(jq -r "$RELEASE_ROWS_JQ" "$releases_file")

  # Never cache "unavailable": it is a transient API failure, not a fact about
  # this SHA. Caching it would let one 5xx suppress the tag for the whole run.
  if [ "$result" = "unavailable" ]; then
    echo "$result"
    return
  fi
  echo "$result" | tee "$cache_file"
}

# milestone_for_tag <repo> <tag>
# Prints "<number><TAB><title>" of the release milestone for <tag>: the exact X.Y.Z
# title first, then X.Y, with the leading "v" optional on both sides. Prints nothing,
# with one WARN per repo and tag, when no milestone matches, more than one does, or
# the tag is not shaped like a version. Returns 2 when the milestone list could not
# be read. Like the release listing, a failed list is never cached as an empty one:
# that would report every item in the repo as "no milestone matches".
milestone_for_tag() {
  local repo="$1" tag="$2"
  local slug="${repo//\//_}"
  local ms_file="$CACHE_DIR/milestones_${slug}"
  local failed_marker="$CACHE_DIR/milestones_failed_${slug}"
  local warned
  warned="$CACHE_DIR/milestone_warned_${slug}_$(printf '%s' "$tag" | tr -c 'A-Za-z0-9._-' '_')"
  [ -f "$failed_marker" ] && return 2
  if [ ! -f "$ms_file" ]; then
    # state=all: the release milestone is usually closed by the time this runs.
    # No --jq: gh applies it per page. `jq -s add` joins the pages whether gh merged
    # them into one array or printed them back to back.
    local raw rc errf="$CACHE_DIR/milestones_err_${slug}"
    set +e
    raw=$(gh api "repos/${repo}/milestones?state=all&per_page=100" --paginate 2>"$errf")
    rc=$?
    set -e
    # Empty output with exit 0 is not "no milestones" (gh prints [] for that).
    if [ "$rc" -ne 0 ] || [ -z "$raw" ] || ! printf '%s' "$raw" \
         | jq -s 'add // [] | map({title, number, state})' > "$ms_file.tmp" 2>/dev/null; then
      echo "WARN: could not list milestones for ${repo} (gh exit $rc): $(tr '\n' ' ' < "$errf" | cut -c1-160)" >&2
      echo "      release milestones for this repo will be reported as FAILED, not skipped." >&2
      rm -f "$ms_file.tmp"
      : > "$failed_marker"
      return 2
    fi
    mv "$ms_file.tmp" "$ms_file"
  fi

  local core="${tag#v}" exact="" minor=""
  if printf '%s' "$core" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    exact="$core"; minor="${core%.*}"
  elif printf '%s' "$core" | grep -Eq '^[0-9]+\.[0-9]+$'; then
    exact="$core"
  else
    [ -f "$warned" ] || echo "WARN: release tag '${tag}' is not vX.Y.Z or vX.Y; no release milestone set for ${repo}." >&2
    : > "$warned"
    return 0
  fi

  # Exact first; vX.Y only when no exact title exists. More than one match at the
  # first level that has any is refused, never resolved by picking one.
  local hit
  hit=$(jq -r --arg e "$exact" --arg m "$minor" '
    def pick($t): [.[] | select(((.title // "") | ltrimstr("v")) == $t)];
    pick($e) as $x
    | (if ($x | length) > 0 or $m == "" then $x else pick($m) end)
    | if length == 1 and (.[0].number | type) == "number"
        then "\(.[0].number)\t\(.[0].title)"
      elif length == 0 then "none"
      else "ambiguous: " + (map("\(.title) #\(.number)") | join(", ")) end' "$ms_file") || return 2
  case "$hit" in
    none)
      [ -f "$warned" ] || echo "WARN: no milestone titled ${exact}${minor:+ or ${minor}} (leading v optional) in ${repo}; release milestone for ${tag} not set." >&2
      : > "$warned" ;;
    ambiguous*)
      [ -f "$warned" ] || echo "WARN: ${hit} in ${repo} for ${tag}; release milestone not set." >&2
      : > "$warned" ;;
    *) printf '%s\n' "$hit" ;;
  esac
  return 0
}

# --- no-merged-PR annotations (promoteClass = nopr | wontfix) -----------------
# Every such comment carries this marker so re-running a release does not stack
# duplicates. Re-runs are normal (a failed apply is retried), so idempotency here
# is not optional.
PROMOTE_MARKER="gh-board-promote:no-merged-pr"

# has_promote_marker <issue-url> -> 0 if this skill already annotated the issue.
# On lookup failure returns 1 (treat as un-annotated and post): a duplicate comment
# is a cosmetic problem, a missing audit trail is a real one.
has_promote_marker() {
  local url="$1" n
  n=$(gh issue view "$url" --json comments \
        --jq "[.comments[].body | select(contains(\"$PROMOTE_MARKER\"))] | length" 2>/dev/null) || return 1
  [ -n "$n" ] && [ "$n" != "0" ]
}

# nopr_comment_body <promoteClass>
nopr_comment_body() {
  if [ "$1" = "wontfix" ]; then
    cat <<'EOF'
<!-- gh-board-promote:no-merged-pr -->
## Promoted to Done — closed as not planned

This issue closed as **not planned**, so it can never acquire a merged PR and the
standard "closed issue + merged PR reachable from the default branch" rule could
never fire. Left in a non-terminal column it would block that column from draining
on every future release, so it is promoted here as resolved-without-delivery.

Deliberately **not** given a release milestone — release milestones denote what
shipped, and this did not ship.

Reopen if the premise changes.

_Promoted automatically by `promote-shipped`._
EOF
  else
    cat <<'EOF'
<!-- gh-board-promote:no-merged-pr -->
## Promoted to Done — no merged PR

This issue is closed, is **not** marked *not planned*, and has **zero linked pull
requests**, so the standard "closed issue + merged PR reachable from the default
branch" rule did not apply. It was promoted on the no-PR rule: a closure with no
linked PR at all is an administrative or findings-only one — the deliverable was
filed issues, a local action, or supersession by another issue — not stalled work.

If code for this is in fact sitting in an unmerged PR, reopen and link it. That is
the case this rule is built to exclude: an issue with linked-but-unmerged PRs is
held back, never promoted.

_Promoted automatically by `promote-shipped`._
EOF
  fi
}

MUTATION='mutation($pid:ID!, $iid:ID!, $fid:ID!, $oid:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$pid
    itemId:$iid
    fieldId:$fid
    value:{singleSelectOptionId:$oid}
  }) {
    projectV2Item { id }
  }
}'

# Pre-flight (apply only): the write-capable `project` scope. discover-boards.sh
# and inventory-board.sh both verify read:project before doing anything; this is
# the one script that MUTATES, so failing here beats failing N times mid-flight
# with half the board moved. --dry-run writes nothing and is deliberately exempt.
if [ "$MODE" = "--apply" ]; then
  # Same invocation as discover-boards.sh and inventory-board.sh — kept identical
  # on purpose, pinned by test_scope_preflight_is_identical_across_scripts.
  # Both flags are load-bearing, and they close DIFFERENT holes:
  #   --hostname  `gh auth status` reports "on each known GitHub host", so without
  #               this a grep across the output passes when ANY host has the scope.
  #               Read-only on github.com plus a write-capable GHES login would
  #               sail through. `gh api graphql` targets $GH_HOST (default
  #               github.com), so the check must ask about that host only.
  #   --active    a host can have several accounts; only the active one is used.
  # No login on that host prints no "Token scopes" line at all, which lands in the
  # warn branch below rather than a spurious hard failure.
  SCOPES_LINE=$(gh auth status --active --hostname "${GH_HOST:-github.com}" 2>&1 \
                | grep -i "Token scopes" || true)
  if [ -z "$SCOPES_LINE" ] || echo "$SCOPES_LINE" | grep -Eqi "scopes:[[:space:]]*('?none'?)?[[:space:]]*\$"; then
    # No scopes REPORTED is not the same as the scope being absent. A fine-grained
    # PAT carries permissions rather than OAuth scopes and reports "none"; a bare
    # GH_TOKEN often prints no scopes line at all. Both can be fully Projects-write
    # capable, so hard-failing here would block a valid setup — and the refresh
    # command below is a dead end for a PAT. Warn, proceed, and let the first
    # mutation surface the real error.
    echo "WARN: could not read OAuth scopes for the active account (fine-grained PAT" >&2
    echo "      or GH_TOKEN?). The write-capable 'project' scope is UNVERIFIED — if the" >&2
    echo "      token cannot write Projects, the first item below will fail and say so." >&2
  elif ! echo "$SCOPES_LINE" | grep -Eq '(^|[^:[:alnum:]_-])project([^:[:alnum:]_-]|$)'; then
    # Scopes ARE reported and `project` is genuinely absent. `read:project` also
    # contains the substring "project", so the scope is matched as a whole token.
    echo "ERROR: gh CLI lacks the write-capable 'project' scope (found:${SCOPES_LINE#*:})." >&2
    echo "OAuth login:        gh auth refresh -s read:project,project" >&2
    echo "Personal token:     grant the token Projects write access in GitHub settings" >&2
    echo "                    (a fine-grained PAT needs the 'Projects' repository/org" >&2
    echo "                    permission set to Read and write); gh auth refresh cannot" >&2
    echo "                    change a PAT's permissions." >&2
    exit 3
  fi
fi

OK=0
FAIL=0
COMMENT_OK=0
COMMENT_SKIPPED=0
COMMENT_FAIL=0
MS_SET=0
MS_SAME=0
MS_SKIPPED=0
MS_FAIL=0
FAILED_ITEMS="[]"

while IFS=$'\037' read -r ITEM_ID NUMBER TITLE STATUS URL REPO PCLASS MERGE_SHA FOREIGN; do
  LINE_PREFIX="  #${NUMBER}  ${TITLE:0:60}"

  # A "merged" candidate whose only merged PR lives in another repository is refused: that
  # PR's merge commit says nothing about this repo's releases. find-promotable.sh never
  # emits one; this guards an old or hand-edited candidates file. Nothing is moved and
  # nothing is commented, and it counts as a failure (exit 1).
  if [ "$FOREIGN" = "1" ]; then
    echo "${LINE_PREFIX}"
    echo "    REFUSED: its merged PR is from another repository, not $REPO — not moved, no comment"
    FAIL=$((FAIL + 1))
    FAILED_ITEMS=$(jq -n --argjson cur "$FAILED_ITEMS" --arg id "$ITEM_ID" --arg num "$NUMBER" \
      '$cur + [{itemId: $id, number: ($num | tonumber? // $num), error: "refused: merged PR from another repository"}]')
    continue
  fi

  # Resolve release info for this candidate (used in dry-run preview AND apply).
  # Only the "merged" class has a merge commit to resolve a release from; the
  # no-merged-PR classes get a fixed explanatory note instead. The lookup runs with
  # --no-release-comment too, because the release milestone needs the tag.
  RELEASE_JSON="null"
  RELEASE_LABEL=""
  if [ "$PCLASS" = "merged" ]; then
    if [ -n "$FORCE_TAG" ]; then
      RELEASE_JSON=$(jq -n --arg t "$FORCE_TAG" '{tag:$t, url:null, published_at:null}')
    else
      RELEASE_JSON=$(find_release_for_commit "$REPO" "$MERGE_SHA")
    fi
  fi
  if [ "$SKIP_COMMENT" = "false" ]; then
    if [ "$PCLASS" != "merged" ]; then
      RELEASE_LABEL="no-merged-PR note (${PCLASS})"
    elif [ -n "$FORCE_TAG" ]; then
      RELEASE_LABEL="$FORCE_TAG (forced)"
    elif [ "$RELEASE_JSON" = "unavailable" ]; then
      RELEASE_LABEL="(release UNAVAILABLE for $REPO — see WARN above)"
    elif [ "$RELEASE_JSON" != "null" ]; then
      RELEASE_LABEL="$(echo "$RELEASE_JSON" | jq -r '.tag') (auto-detected)"
    else
      RELEASE_LABEL="(no release contains $MERGE_SHA)"
    fi
  fi

  # Release milestone ("merged" only; nopr/wontfix did not ship in a release).
  # MS_ACTION: set | same | skip | fail, or empty for the other classes. The current
  # milestone is read from the candidate by item id, not projected as a new column.
  MS_ACTION=""; MS_NUM=""; MS_TITLE=""; MS_TAG=""; MS_NOTE=""; CUR_LABEL=""
  if [ "$PCLASS" = "merged" ]; then
    if [ "$RELEASE_JSON" = "unavailable" ]; then
      MS_ACTION="fail"; MS_NOTE="UNAVAILABLE — the release for $REPO is unknown (see WARN above)"
    elif [ "$RELEASE_JSON" = "null" ]; then
      MS_ACTION="skip"; MS_NOTE="skipped — no release contains $MERGE_SHA"
    elif ! printf '%s' "$NUMBER" | grep -Eq '^[1-9][0-9]*$' \
         || ! printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
      # Both go into a REST path; "7/lock" would PATCH another endpoint.
      MS_ACTION="fail"; MS_NOTE="FAILED — malformed issue number or repo ('$NUMBER' in '$REPO')"
    else
      MS_TAG=$(echo "$RELEASE_JSON" | jq -r '.tag')
      if MS_HIT=$(milestone_for_tag "$REPO" "$MS_TAG"); then
        if [ -z "$MS_HIT" ]; then
          MS_ACTION="skip"; MS_NOTE="skipped — no single milestone matches $MS_TAG (see WARN)"
        else
          MS_NUM="${MS_HIT%%$'\t'*}"; MS_TITLE="${MS_HIT#*$'\t'}"
          CUR_JSON=$(echo "$DATA" | jq -c --arg id "$ITEM_ID" "$JQ_CLEAN"'
            [.candidates[] | select((.itemId | clean) == $id)][0]
            | if type == "object" and has("milestone") then .milestone else "unknown" end')
          CUR_NUM=$(echo "$CUR_JSON" | jq -r 'if type == "object" then (.number // "" | tostring) else "" end')
          CUR_LABEL=$(echo "$CUR_JSON" | jq -r 'if type == "object" then (.title // "untitled")
                                                elif . == null then "none" else "unknown" end')
          if [ -n "$CUR_NUM" ] && [ "$CUR_NUM" = "$MS_NUM" ]; then
            MS_ACTION="same"
          else
            MS_ACTION="set"
          fi
        fi
      else
        MS_ACTION="fail"; MS_NOTE="UNAVAILABLE — could not list milestones for $REPO (see WARN above)"
      fi
    fi
  fi
  case "$MS_ACTION" in
    set)  MS_SET=$((MS_SET + 1)) ;;
    same) MS_SAME=$((MS_SAME + 1)) ;;
    skip) MS_SKIPPED=$((MS_SKIPPED + 1)) ;;
    fail) MS_FAIL=$((MS_FAIL + 1)) ;;
  esac

  if [ "$MODE" = "--dry-run" ]; then
    echo "${LINE_PREFIX}"
    echo "    would: $STATUS  →  Done   (item $ITEM_ID)"
    [ "$SKIP_COMMENT" = "false" ] && echo "    would comment: $RELEASE_LABEL"
    # Printed only when the milestone would change, or cannot be checked.
    case "$MS_ACTION" in
      set)  echo "    would set milestone: $CUR_LABEL -> $MS_TITLE ($MS_TAG)" ;;
      fail) echo "    milestone: $MS_NOTE" ;;
    esac
    OK=$((OK + 1))
    continue
  fi

  # Phase 1: status mutation
  # -f (not -F) for every one: pid/iid/fid are ID! and oid is String!. -F does
  # type inference, so an all-numeric value would be sent as an Int and rejected.
  RESP=$(gh api graphql -f query="$MUTATION" \
    -f pid="$PROJECT_ID" -f iid="$ITEM_ID" -f fid="$FIELD_ID" -f oid="$DONE_OPT" 2>&1) || {
    echo "${LINE_PREFIX}"
    echo "    FAIL (status mutation): $RESP"
    FAIL=$((FAIL + 1))
    # No board move, so no milestone write either: take back the count made above.
    case "$MS_ACTION" in
      set)  MS_SET=$((MS_SET - 1)) ;;
      same) MS_SAME=$((MS_SAME - 1)) ;;
      skip) MS_SKIPPED=$((MS_SKIPPED - 1)) ;;
      fail) MS_FAIL=$((MS_FAIL - 1)) ;;
    esac
    FAILED_ITEMS=$(jq -n --argjson cur "$FAILED_ITEMS" --arg id "$ITEM_ID" --arg num "$NUMBER" --arg err "$RESP" \
      '$cur + [{itemId: $id, number: ($num | tonumber? // $num), error: $err}]')
    continue
  }
  echo "${LINE_PREFIX}"
  echo "    OK:    $STATUS  →  Done"
  OK=$((OK + 1))

  # Phase 2: release milestone (best-effort, like the comment; never undoes the move).
  case "$MS_ACTION" in
    set)
      # REST by number: the only call that can assign a closed milestone.
      if MERR=$(gh api -X PATCH "repos/$REPO/issues/$NUMBER" -F milestone="$MS_NUM" 2>&1 >/dev/null); then
        echo "    milestone: set — $CUR_LABEL -> $MS_TITLE ($MS_TAG)"
      else
        echo "    milestone: FAILED — $(echo "${MERR:-}" | head -1) (item still moved to Done)"
        MS_SET=$((MS_SET - 1)); MS_FAIL=$((MS_FAIL + 1))
      fi ;;
    skip) echo "    milestone: $MS_NOTE" ;;
    fail) echo "    milestone: $MS_NOTE (item still moved to Done)" ;;
  esac

  # Phase 3: release comment (best-effort, doesn't gate promotion success)
  if [ "$SKIP_COMMENT" = "true" ]; then
    COMMENT_SKIPPED=$((COMMENT_SKIPPED + 1))
    continue
  fi

  # No-merged-PR classes get the fixed explanatory note instead of a release tag.
  # Checked BEFORE the RELEASE_JSON test, which would otherwise report the
  # misleading "no release contains merge " for an item that never had a merge.
  if [ "$PCLASS" != "merged" ]; then
    if has_promote_marker "$URL"; then
      echo "    comment: skipped — already annotated by this skill"
      COMMENT_SKIPPED=$((COMMENT_SKIPPED + 1))
    elif CERR=$(gh issue comment "$URL" --body "$(nopr_comment_body "$PCLASS")" 2>&1 >/dev/null); then
      echo "    comment: posted — no-merged-PR note ($PCLASS)"
      COMMENT_OK=$((COMMENT_OK + 1))
    else
      # Keep the reason: a locked conversation and an expired token are different
      # problems and used to be indistinguishable.
      echo "    comment: FAILED on $URL — $(echo "${CERR:-}" | head -1) (item still moved to Done)"
      COMMENT_FAIL=$((COMMENT_FAIL + 1))
    fi
    continue
  fi

  if [ "$RELEASE_JSON" = "unavailable" ]; then
    # Counted as a comment FAILURE, not a skip: we do not know whether a release
    # contains this commit, and "skipped" would read as "checked, nothing found".
    echo "    comment: FAILED — could not determine the release for $REPO (item still moved to Done)"
    COMMENT_FAIL=$((COMMENT_FAIL + 1))
    continue
  fi

  if [ "$RELEASE_JSON" = "null" ]; then
    echo "    comment: skipped — no release contains merge $MERGE_SHA"
    COMMENT_SKIPPED=$((COMMENT_SKIPPED + 1))
    continue
  fi

  TAG=$(echo "$RELEASE_JSON" | jq -r '.tag')
  RURL=$(echo "$RELEASE_JSON" | jq -r '.url // ""')
  PUB=$(echo "$RELEASE_JSON" | jq -r '.published_at // "" | (if . == "" or . == null then "" else .[0:10] end)')

  if [ -n "$RURL" ] && [ -n "$PUB" ]; then
    BODY="🚀 Released in [\`${TAG}\`](${RURL}) (published ${PUB}). Moved to Done on the project board."
  elif [ -n "$RURL" ]; then
    BODY="🚀 Released in [\`${TAG}\`](${RURL}). Moved to Done on the project board."
  else
    BODY="🚀 Released in \`${TAG}\`. Moved to Done on the project board."
  fi

  if CERR=$(gh issue comment "$URL" --body "$BODY" 2>&1 >/dev/null); then
    echo "    comment: posted — $TAG"
    COMMENT_OK=$((COMMENT_OK + 1))
  else
    echo "    comment: FAILED on $URL — $(echo "${CERR:-}" | head -1) (item still moved to Done)"
    COMMENT_FAIL=$((COMMENT_FAIL + 1))
  fi
done < <(echo "$DATA" | jq -r "$JQ_CLEAN"'
  .candidates[]
  | [
      (.itemId|clean),
      (.number|clean),
      (.title|clean),
      (.status|clean),
      (.url|clean),
      (.repo|clean),
      ((.promoteClass // "merged")|clean),
      # map|.[0] rather than a generator: a generator yields NOTHING for the
      # no-merged-PR classes, which silently drops the column and shifts every
      # field in the read. This always emits exactly 9 columns (with the next one).
      # Only a PR in the repo of the candidate (case-insensitive) supplies the merge SHA.
      ((.repo // "") | ascii_downcase) as $cr
      | ((.mergedPRs // []) | map(select((.inMain == "yes" or .inMain == null)
                                         and (((.repo // "") | ascii_downcase) == $cr)))) as $own
      | ((($own[0].mergeCommitOid) // "")|clean),
      # 9th column: 1 when a "merged" candidate has merged PRs but none in its own repo.
      (if ((.promoteClass // "merged") == "merged") and ($own | length) == 0
          and ((.mergedPRs // []) | length) > 0 then "1" else "0" end)
    ] | join("\u001f")
' | awk -F'\037' '!seen[$1]++')   # one row per item
# Emitting 8 columns was never enough: with IFS=$'\t' an EMPTY column vanishes,
# because tab is IFS whitespace and runs of it fold. `repo` and `status` are
# `// null` by construction, so one null repo shifted promoteClass into the merge
# SHA and a shipped item took the no-merged-PR comment branch. The unit separator
# preserves empty fields; `clean` keeps CR/LF and stray separators out of values.

# The while-read above is fed by a process substitution, so a jq projection error
# emits ZERO rows, runs the body ZERO times, and the summary below reads as
# "board is in sync" when nothing was touched. Reconcile: EXPECTED_ROWS is the
# DISTINCT itemId count, because the awk above collapses duplicate item rows.
PROCESSED=$((OK + FAIL))
if [ "$PROCESSED" -ne "$EXPECTED_ROWS" ]; then
  echo "" >&2
  echo "ERROR: processed $PROCESSED of $EXPECTED_ROWS candidate rows ($COUNT candidates in)." >&2
  echo "       The input projection failed, so some or all candidates were never" >&2
  echo "       attempted — the board is NOT in sync. Fix the input and re-run." >&2
  exit 1
fi

echo ""
echo "Promotions: $OK ok, $FAIL failed"
if [ "$MODE" = "--apply" ] && [ "$SKIP_COMMENT" = "false" ]; then
  echo "Comments:   $COMMENT_OK posted, $COMMENT_SKIPPED skipped, $COMMENT_FAIL failed"
fi
if [ $((MS_SET + MS_SAME + MS_SKIPPED + MS_FAIL)) -gt 0 ]; then
  if [ "$MODE" = "--apply" ]; then
    echo "Milestones: $MS_SET set, $MS_SAME unchanged, $MS_SKIPPED skipped, $MS_FAIL failed"
  else
    echo "Milestones: $MS_SET to set, $MS_SAME unchanged, $MS_SKIPPED skipped, $MS_FAIL cannot check"
  fi
fi
if [ "$MODE" = "--dry-run" ]; then
  echo "(dry-run; re-run with --apply to commit)"
fi

if [ "$COMMENT_FAIL" -gt 0 ]; then
  # Deliberately NOT an error exit: comment failures are non-fatal by contract (see
  # the header). But a total release-API outage would otherwise read as a clean run,
  # so name it explicitly.
  echo ""
  echo "ACTION NEEDED: $COMMENT_FAIL release comment(s) failed — the board moves"
  echo "               themselves succeeded. Re-check the items marked 'comment: FAILED'"
  echo "               above and annotate them by hand if the failure persists."
fi

if [ "$MODE" = "--apply" ] && [ "$MS_FAIL" -gt 0 ]; then
  # Non-fatal, like the comments: the board moves succeeded.
  echo ""
  echo "ACTION NEEDED: $MS_FAIL release milestone(s) not set — the board moves"
  echo "               themselves succeeded. Re-check the items marked 'milestone:'"
  echo "               above and fix them by hand, or re-run this command."
fi

if [ "$FAIL" -gt 0 ]; then
  echo "Failed items:"
  echo "$FAILED_ITEMS" | jq -r '.[] | "  #\(.number)  \(.error[0:120])"'
  exit 1
fi
