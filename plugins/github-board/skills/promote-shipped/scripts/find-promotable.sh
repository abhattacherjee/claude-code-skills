#!/usr/bin/env bash
# find-promotable.sh — Filter board inventory to items eligible for "Done" promotion.
#
# Every candidate (status set, not already Done, closed Issue or merged PR) is
# assigned exactly one promoteClass. Three promote, six hold:
#
#   PROMOTE
#     merged            >=1 associated merged PR whose mergeCommit.oid is reachable
#                       from the default branch (typically main) — the work shipped.
#     wontfix           Issue closed with stateReason=NOT_PLANNED and NO merged PR.
#                       It can never acquire one, so the "merged" rule could never
#                       fire and the card would sit in a non-terminal column forever.
#     nopr              Closed issue, NOT marked NOT_PLANNED, with ZERO linked PRs
#                       of any kind. A closure with no PR at all is an
#                       administrative or findings-only one (the deliverable was
#                       filed issues, a local action, or supersession), not
#                       stalled work.
#                       Deliberately NOT stated as "closed as COMPLETED":
#                       stateReason is nullable and GitHub returns null for issues
#                       closed before that field existed. Requiring COMPLETED would
#                       park every such legacy issue in a hold class that can never
#                       resolve — the permanently-stuck card that `wontfix` exists
#                       to prevent. So the class promotes on what IS observed
#                       (closed, not NOT_PLANNED, no PRs) and claims nothing more.
#
#   HOLD
#     hold-unreleased   Has a merged PR, but none reachable from the base branch.
#                       THE critical guard: a PR merged to develop only is not yet
#                       released. Never relax this — it is what keeps the board
#                       honest between a develop merge and the release to main.
#     hold-unmerged-pr  Closed COMPLETED and linked PRs EXIST but none merged. This
#                       is genuine stalled work, which is exactly what "nopr" must
#                       not swallow.
#     hold-no-fallback  --no-fallback-discovery was passed, so an empty merged-PR
#                       set is uninformative (Git-Flow develop merges record no
#                       formal link). Refuses to guess.
#     hold-discovery-failed
#                       Fallback discovery could not run to completion (auth expiry,
#                       rate limit, missing scope, network or jq error). The PR set
#                       is UNKNOWN, not empty, so nothing about this issue could be
#                       verified — it is never promoted. An API failure must never
#                       be able to manufacture the "zero linked PRs" evidence that
#                       "nopr" promotes on.
#     hold-foreign-pr   No merged PR in the issue's repo, but a PR from ANOTHER repository,
#                       merged or not, claims the issue (a cross-repo closing reference or a
#                       timeline cross-reference). Its merge commit says nothing about this
#                       repo's releases, so the card is held for a human, never promoted
#                       (and never falls through to "nopr").
#     hold-other        Non-Issue content that reached Stage 2 without a merged PR.
#
# Ordering matters: "merged" is checked first, and hold-unreleased before wontfix,
# so an issue with a merged-but-unreleased PR is NEVER promoted early regardless of
# its stateReason.
#
# Distinguishing "nopr" from "hold-unmerged-pr" needs unmerged PRs in the payload.
# inventory-board.sh supplies them via closedByPullRequestsReferences(includeClosedPrs:true);
# .linkedPRCount counts ALL of them, while .mergedPRs holds only merged ones.
#
# PR association for a closed Issue is discovered in two layers:
#   a) closedByPullRequestsReferences (inventory `.issue.linkedPRs`) — the formal
#      closing link GitHub records ONLY for default-branch merges.
#   b) Git-Flow fallback (default ON; --no-fallback-discovery to disable): when an
#      issue has no merged linked PR (the normal case for PRs merged to `develop`,
#      where GitHub never records the closing link), discover merged PRs from the
#      issue timeline. A cross-referenced PR is kept ONLY if its body has a closing
#      keyword for THIS issue (Closes/Fixes/Resolves, optional colon, then #N,
#      owner/repo#N of this repo, or this repo's issue URL); connected/closer PRs are
#      kept directly. An unmerged PR found this way adds to .linkedPRCount, so the
#      issue is held as hold-unmerged-pr instead of promoted as "nopr". Only PRs in the issue's own repo are
#      kept (formal links included); a foreign one that claims the issue, merged or not,
#      holds it as hold-foreign-pr. Every discovered PR still passes through the same main-
#      reachability guard, so the fallback can only add genuinely-shipped items.
#
# The reachability check uses GitHub's compare API:
#   gh api /repos/{owner}/{repo}/compare/{merge_sha}...main
# When status is "ahead" or "identical", main contains merge_sha -> eligible.
#
# Exit codes: 0=ok (any number of candidates, including 0)
#             2=usage, or the inventory file cannot be read
#             5=inventory has no Done option ID — nothing to promote TO
# There is deliberately no auth exit here: this script reads a local inventory
# file. Its only network calls are the compare/timeline lookups, whose failures
# are classified (hold-discovery-failed / "could not verify"), not fatal.
#
# Usage:
#   find-promotable.sh <inventory.json>                       # JSON candidate set
#   find-promotable.sh <inventory.json> --human               # readable preview
#   find-promotable.sh <inventory.json> --base main           # default branch override
#   find-promotable.sh <inventory.json> --skip-main-check      # legacy (any merged PR)
#   find-promotable.sh <inventory.json> --no-fallback-discovery # only formal links

set -eu

usage() {
  cat <<EOF
Usage: find-promotable.sh <inventory.json> [--human] [--base BRANCH] [--skip-main-check] [--no-fallback-discovery]

Filters inventory-board.sh output to Done-promotion candidates. By default,
requires that at least one of the candidate's merged PRs has its merge commit
reachable from the repo's main branch (proves the work shipped, not just merged
to develop).

Flags:
  --human                  Readable preview instead of JSON
  --base BRANCH            Branch to ancestry-check against (default: main)
  --skip-main-check        Skip the reachability check (every merged PR counts)
  --no-fallback-discovery  Disable timeline-based PR discovery for issues with no
                           formal closing link (the Git-Flow develop-merge case)
EOF
}

[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { usage; exit 0; }
[ $# -lt 1 ] && { usage >&2; exit 2; }

INPUT="$1"
HUMAN="false"
BASE_BRANCH="main"
SKIP_MAIN="false"
FALLBACK="true"
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --human) HUMAN="true"; shift ;;
    --base)
      # Without this, `shift 2` with one arg left returns non-zero and `set -e`
      # exits 1 silently — no usage, no message.
      [ $# -ge 2 ] || { echo "ERROR: --base needs a branch name" >&2; exit 2; }
      BASE_BRANCH="$2"; shift 2 ;;
    --skip-main-check) SKIP_MAIN="true"; shift ;;
    --no-fallback-discovery) FALLBACK="false"; shift ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -r "$INPUT" ] || { echo "ERROR: cannot read $INPUT" >&2; exit 2; }
INV=$(cat "$INPUT")

DONE_OPT=$(echo "$INV" | jq -r '.statusField.doneOptionId // ""')
if [ -z "$DONE_OPT" ] || [ "$DONE_OPT" = "null" ]; then
  echo "ERROR: inventory has no Done option ID. Skill cannot promote without a target." >&2
  exit 5
fi

# Stage 1 — coarse filter (status + closed-issue/merged-PR). Closed issues are
# included even without a formal merged linked PR; Stage 1.5 fallback discovery
# will try to find their closing PR from the timeline.
COARSE=$(echo "$INV" | jq --arg doneOpt "$DONE_OPT" '
  {
    project: .project,
    statusField: .statusField,
    candidates: [
      .items[]
      | select(.statusOptionId != null)
      | select(.statusOptionId != $doneOpt)
      | select(
          (.contentType == "Issue" and .issue.state == "CLOSED")
          or
          (.contentType == "PullRequest" and .pullRequest.merged == true)
        )
      | {
          itemId,
          status,
          statusOptionId,
          contentType,
          number: (.issue.number // .pullRequest.number),
          title: (.issue.title // .pullRequest.title),
          url: (.issue.url // .pullRequest.url),
          repo: (.issue.repo // .pullRequest.repo),
          stateReason: (if .contentType == "Issue" then (.issue.stateReason // null) else null end),
          # ALL linked PRs, merged or not — the signal that separates a genuine
          # no-PR closure from work stalled in an unmerged PR.
          linkedPRCount: (if .contentType == "Issue" then ((.issue.linkedPRs // []) | length) else 0 end),
          # Only PRs in the repo of the issue count (see discover_prs_for_issue). A merged
          # PR from another repo is kept aside in foreignPRs, which holds the card.
          mergedPRs: (
            if .contentType == "Issue" then
              ((.issue.repo // "") | ascii_downcase) as $ir
              | [(.issue.linkedPRs // [])[]
                 | select(.merged == true)
                 | select(((.repo // "") | ascii_downcase) == $ir)
                 | {number, baseRefName, mergedAt, mergeCommitOid, repo, discovered: false}]
            else
              [{number: .pullRequest.number,
                baseRefName: .pullRequest.baseRefName,
                mergedAt: .pullRequest.mergedAt,
                mergeCommitOid: .pullRequest.mergeCommitOid,
                repo: .pullRequest.repo,
                discovered: false}]
            end
          ),
          foreignPRs: (
            if .contentType == "Issue" then
              ((.issue.repo // "") | ascii_downcase) as $ir
              | [(.issue.linkedPRs // [])[]
                 | select(.merged == true)
                 | select(((.repo // "") | ascii_downcase) != $ir)
                 | {number, repo, merged: true}]
            else [] end
          )
        }
    ]
  }
')

# Stage 1.5 — Git-Flow fallback PR discovery for closed issues with no formal
# merged link. Searches the issue timeline; cross-referenced PRs require a closing
# keyword for THIS issue. Discovered PRs are tagged discovered:true and still go
# through the Stage 2 main-reachability guard.
#
# Echoes a JSON array on success, or the literal sentinel FAILED when the PR set
# could not be determined. FAILED is NOT "[]": an empty array is evidence (this
# issue has no closing PR) and feeds the promoting "nopr" class, so a failed API
# call collapsing to [] would promote unverified work. Fail closed instead.
discover_prs_for_issue() {
  local repo="$1" num="$2"
  local owner="${repo%%/*}" name="${repo##*/}"
  if [ -z "$owner" ] || [ -z "$name" ] || [ -z "$num" ] || [ "$num" = "null" ]; then
    echo "[find-promotable] discovery skipped: malformed reference repo='$repo' num='$num'" >&2
    echo "FAILED"; return
  fi
  local gql_query='
    query($owner:String!,$repo:String!,$num:Int!){
      repository(owner:$owner,name:$repo){
        issue(number:$num){
          timelineItems(last:80, itemTypes:[CLOSED_EVENT, CONNECTED_EVENT, CROSS_REFERENCED_EVENT]){
            nodes{
              __typename
              ... on ClosedEvent { closer { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} repository{nameWithOwner} } } }
              ... on ConnectedEvent { subject { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} repository{nameWithOwner} } } }
              ... on CrossReferencedEvent { source { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} repository{nameWithOwner} } } }
            }
          }
        }
      }
    }'
  # Only a PR in the ISSUE's repo can close the issue. A CrossReferencedEvent can come from
  # any repo, and a foreign PR's `fixes #N` closes #N of ITS OWN repo, so it must never be
  # credited here (its merge commit would also be checked against the wrong repo). A foreign
  # PR that does claim this issue is returned as {foreign:true} so the candidate is held, not
  # promoted on the "no linked PR" rule. The repo and number are checked before they are
  # pasted into the filter below as literals.
  if ! printf '%s' "$repo" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' \
     || ! printf '%s' "$num" | grep -Eq '^[0-9]+$'; then
    echo "[find-promotable] discovery skipped: malformed reference repo='$repo' num='$num'" >&2
    echo "FAILED"; return
  fi
  local repo_lc repo_re
  repo_lc=$(printf '%s' "$repo" | tr '[:upper:]' '[:lower:]')
  # Regex-escape the dots; the other allowed characters are literal in a regex.
  repo_re=$(printf '%s' "$repo" | sed 's/[.]/\\\\./g')
  local jq_filter
  # The closing forms GitHub accepts: a keyword, an optional colon, then #N, owner/repo#N or
  # the issue's full URL (https://github.com/owner/repo/issues/N). Only THIS repo's
  # owner/repo#N or URL counts; a URL for another repo's issue closes that issue, not ours.
  # Unmerged PRs are kept too (merged:false): an open or abandoned closing PR is stalled
  # work, so it must count as a linked PR and hold the card, never vanish into "nopr".
  jq_filter='[ .data.repository.issue.timelineItems.nodes[]
    | {t:.__typename, pr:(.closer // .subject // .source)}
    | select(.pr != null and (.pr|type)=="object" and .pr.__typename=="PullRequest")
    | select( (.t=="ClosedEvent" or .t=="ConnectedEvent")
              or ( (.pr.body // "") | test("(?i)(close[sd]?|fix(e[sd])?|resolve[sd]?):?\\s+(('"${repo_re}"')?#|https?://github\\.com/'"${repo_re}"'/issues/)'"${num}"'\\b") ) )
    | ((.pr.repository.nameWithOwner // "") | ascii_downcase) as $prRepo
    | {number:.pr.number, baseRefName:.pr.baseRefName, mergedAt:.pr.mergedAt, mergeCommitOid:.pr.mergeCommit.oid,
       repo:"'"${repo}"'", foreign:($prRepo != "'"${repo_lc}"'"), prRepo:.pr.repository.nameWithOwner,
       merged:(.pr.merged==true), discovered:true}
  ] | unique_by([.prRepo, .number])'
  # stdout and rc are captured SEPARATELY so an API/jq failure is distinguishable
  # from a genuine empty result. owner/repo are String! (-f, no type inference);
  # num is a real Int! so it keeps -F.
  local out rc
  set +e
  out=$(gh api graphql -f query="$gql_query" \
    -f owner="$owner" -f repo="$name" -F num="$num" \
    --jq "$jq_filter" 2>&1)
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "[find-promotable] timeline discovery FAILED for ${repo}#${num} (gh exit $rc): $(echo "$out" | tr '\n' ' ' | cut -c1-200)" >&2
    echo "FAILED"; return
  fi
  if [ -z "$out" ]; then
    echo "[find-promotable] timeline discovery returned no output for ${repo}#${num}" >&2
    echo "FAILED"; return
  fi
  echo "$out"
}

if [ "$FALLBACK" = "true" ]; then
  WORK=$(echo "$COARSE" | jq -c '.candidates[]')
  DISCOVERED_CANDS="[]"
  while IFS= read -r CAND; do
    [ -z "$CAND" ] && continue
    CTYPE=$(echo "$CAND" | jq -r '.contentType')
    HAS_PR=$(echo "$CAND" | jq '(.mergedPRs // []) | length')
    if [ "$CTYPE" = "Issue" ] && [ "$HAS_PR" = "0" ]; then
      REPO=$(echo "$CAND" | jq -r '.repo // ""')
      NUM=$(echo "$CAND" | jq -r '.number // ""')
      FOUND=$(discover_prs_for_issue "$REPO" "$NUM")
      if [ "$FOUND" = "FAILED" ]; then
        # Leave mergedPRs untouched (still empty) and flag the candidate: Stage 3
        # classifies it hold-discovery-failed, which never promotes.
        CAND=$(echo "$CAND" | jq '. + {discoveryFailed: true}')
      else
        CAND=$(echo "$CAND" | jq --argjson f "$FOUND" \
          '.mergedPRs = [$f[] | select(.merged and (.foreign | not)) | del(.foreign, .prRepo, .merged)]
           | .foreignPRs = ((.foreignPRs // []) + [$f[] | select(.foreign) | {number, repo: .prRepo, merged}])
           | .linkedPRCount = ((.linkedPRCount // 0) + ([$f[] | select((.merged | not) and (.foreign | not))] | length))')
      fi
    fi
    DISCOVERED_CANDS=$(jq -n --argjson a "$DISCOVERED_CANDS" --argjson b "$CAND" '$a + [$b]')
  done <<<"$WORK"
  COARSE=$(echo "$COARSE" | jq --argjson c "$DISCOVERED_CANDS" '.candidates = $c')
fi

# Stage 2 — main-reachability check per merged PR. Skip if requested.
if [ "$SKIP_MAIN" = "true" ]; then
  echo "$COARSE" | {
    if [ "$HUMAN" = "true" ]; then
      jq -r '
        "Project: \(.project.title)",
        "Promotable candidates: \([.candidates[] | select((.mergedPRs // []) | length > 0)] | length)  (--skip-main-check)",
        "",
        (.candidates[] | select((.mergedPRs // []) | length > 0) | "  #\(.number)  \(.title[0:70])\n         current: \(.status)  ->  Done\n         repo: \(.repo)  PRs: \([.mergedPRs[] | "#\(.number)->\(.baseRefName)"] | join(", "))\n         \(.url)\n")
      '
    else
      # Legacy path: only merged-PR items, tagged so apply-promotions.sh picks the
      # release-comment branch. The no-PR classes are deliberately NOT reachable
      # here — without the reachability check there is no evidence to reason from.
      jq '.candidates |= map(select((.mergedPRs // []) | length > 0) | . + {promoteClass: "merged"})
          | . + {held: []}'
    fi
  }
  exit 0
fi

# Per-repo+sha cache so we don't re-check the same SHA twice in one run.
CACHE_DIR=$(mktemp -d)
trap 'rm -rf "$CACHE_DIR"' EXIT

is_in_main() {
  local repo="$1" sha="$2"
  [ -z "$sha" ] || [ "$sha" = "null" ] && { echo "no-sha"; return; }
  local cache_key cache_file
  cache_key=$(echo "${repo}_${sha}" | tr '/' '_')
  cache_file="$CACHE_DIR/$cache_key"
  if [ -f "$cache_file" ]; then cat "$cache_file"; return; fi
  local status
  # The VERDICT here is already right — "error" is its own class, reported as
  # "could not verify" and never as "not in $BASE_BRANCH". Only the REASON was
  # being discarded, the same half of the defect fixed in apply-promotions.sh.
  status=$(gh api "/repos/${repo}/compare/${sha}...${BASE_BRANCH}" --jq '.status' 2>&1) || {
    echo "[find-promotable] compare failed for ${repo} ${sha}...${BASE_BRANCH}: $(echo "$status" | tr '\n' ' ' | cut -c1-160)" >&2
    status="error"
  }
  case "$status" in
    ahead|identical) echo "yes" | tee "$cache_file" ;;
    behind|diverged) echo "no" | tee "$cache_file" ;;
    *)               echo "error" | tee "$cache_file" ;;
  esac
}

WORK=$(echo "$COARSE" | jq -c '.candidates[]')
ENRICHED_CANDS="[]"
while IFS= read -r CAND; do
  [ -z "$CAND" ] && continue
  TAGGED_PRS="[]"
  while IFS= read -r PR; do
    [ -z "$PR" ] && continue
    # The candidate's repo, never the PR's: only same-repo PRs reach this point, and the
    # reachability verdict must be about the repo the issue lives in.
    REPO=$(echo "$CAND" | jq -r '.repo // ""')
    SHA=$(echo "$PR" | jq -r '.mergeCommitOid // ""')
    REACH=$(is_in_main "$REPO" "$SHA")
    TAGGED=$(echo "$PR" | jq --arg r "$REACH" '. + {inMain: $r}')
    TAGGED_PRS=$(jq -n --argjson a "$TAGGED_PRS" --argjson b "$TAGGED" '$a + [$b]')
  done < <(echo "$CAND" | jq -c '.mergedPRs[]')
  ENRICHED_CAND=$(echo "$CAND" | jq --argjson prs "$TAGGED_PRS" '.mergedPRs = $prs')
  ENRICHED_CANDS=$(jq -n --argjson a "$ENRICHED_CANDS" --argjson b "$ENRICHED_CAND" '$a + [$b]')
done <<<"$WORK"

# Stage 3 — assign exactly one promoteClass per candidate. See the header block for
# the full taxonomy and why the ordering is load-bearing.
CLASSIFIED=$(jq -n --argjson cands "$ENRICHED_CANDS" --arg fallback "$FALLBACK" '
  $cands | map(. + {promoteClass: (
    if   ((.mergedPRs // []) | any(.inMain == "yes"))  then "merged"
    elif ((.mergedPRs // []) | length) > 0             then "hold-unreleased"
    elif .contentType != "Issue"                       then "hold-other"
    elif ((.foreignPRs // []) | length) > 0            then "hold-foreign-pr"
    elif $fallback != "true"                           then "hold-no-fallback"
    elif (.discoveryFailed // false)                   then "hold-discovery-failed"
    elif .stateReason == "NOT_PLANNED"                 then "wontfix"
    elif ((.linkedPRCount // 0) == 0)                  then "nopr"
    else                                                    "hold-unmerged-pr"
    end
  )})
')

PROMOTE_CLASSES='["merged","wontfix","nopr"]'

FINAL=$(jq -n \
  --argjson project "$(echo "$COARSE" | jq '.project')" \
  --argjson statusField "$(echo "$COARSE" | jq '.statusField')" \
  --argjson cands "$CLASSIFIED" \
  --argjson promote "$PROMOTE_CLASSES" \
  '{
    project: $project,
    statusField: $statusField,
    candidates: ($cands | map(select(.promoteClass as $c | $promote | index($c)))),
    held:       ($cands | map(select(.promoteClass as $c | $promote | index($c) | not)))
  }'
)

DROPPED=$(echo "$FINAL" | jq '.held')

if [ "$HUMAN" = "true" ]; then
  PROMOTE_COUNT=$(echo "$FINAL" | jq '.candidates | length')
  DROPPED_COUNT=$(echo "$DROPPED" | jq 'length')
  PROJECT=$(echo "$FINAL" | jq -r '.project.title')
  echo "Project: $PROJECT"
  echo "Target column: $(echo "$FINAL" | jq -r '.statusField.doneOptionName // "(name unknown)"') [$(echo "$FINAL" | jq -r '.statusField.doneOptionId')]"
  echo "Base branch: $BASE_BRANCH (must contain PR merge commit)"
  echo "Promotable candidates: $PROMOTE_COUNT"
  echo "$FINAL" | jq -r --arg base "$BASE_BRANCH" '
    # NOT named "label" — that is a reserved jq keyword (label $out | ...) and
    # defining it is a compile error, which set -e turns into a silent exit.
    def class_label($c):
      if   $c == "merged"  then "Promote (merged PR in \($base))"
      elif $c == "nopr"    then "Promote (no-PR completion)"
      elif $c == "wontfix" then "Promote (closed not planned)"
      else "Promote (\($c))" end;
    def why:
      if   .promoteClass == "merged"  then
        "PRs in \($base): " + ([.mergedPRs[] | select(.inMain == "yes")
          | "#\(.number)->\(.baseRefName)\(if .discovered then " (discovered)" else "" end)"] | join(", "))
      elif .promoteClass == "nopr"    then "zero linked PRs, not marked not-planned"
      elif .promoteClass == "wontfix" then "stateReason=NOT_PLANNED, no merged PR"
      else "" end;
    (.candidates | group_by(.promoteClass)[]
      | "", "  " + class_label(.[0].promoteClass) + ": \(length)",
        (.[] | "    #\(.number)  \(.title[0:66])\n           \(.status) -> Done   (\(why))\n           \(.url)")
    )
  '
  if [ "$PROMOTE_COUNT" = "0" ]; then
    echo "(nothing to promote — board is in sync with $BASE_BRANCH)"
  fi
  if [ "$DROPPED_COUNT" -gt 0 ]; then
    echo ""
    echo "  HELD BACK: $DROPPED_COUNT"
    echo "$DROPPED" | jq -r --arg base "$BASE_BRANCH" '
      # An "error" reachability result means the compare API call failed, so
      # containment in $base is UNKNOWN — never phrase it as "not in $base".
      # Note the result is cached per (repo,sha), so one transient failure sticks
      # for the rest of the run.
      def reach($r):
        if $r == "yes" then "in \($base)"
        elif $r == "no" then "not in \($base)"
        elif $r == "no-sha" then "no merge commit recorded"
        else "could not verify" end;
      def why:
        if   .promoteClass == "hold-unreleased"  then
          "not confirmed released: " + ([.mergedPRs[] | "#\(.number)->\(.baseRefName) (\(reach(.inMain)))"] | join(", "))
        elif .promoteClass == "hold-unmerged-pr" then
          "\(.linkedPRCount) linked PR(s), none merged — work may be stalled"
        elif .promoteClass == "hold-no-fallback" then
          "no formal closing link and --no-fallback-discovery was passed"
        elif .promoteClass == "hold-foreign-pr" then
          "PR(s) from another repository claim this issue: " + ([.foreignPRs[] | "\(.repo)#\(.number)\(if .merged == false then " (unmerged)" else "" end)"] | join(", ")) + " — not verified here; not promoted"
        elif .promoteClass == "hold-discovery-failed" then
          "PR discovery failed (API/auth/rate-limit) — could not verify; not promoted"
        else "no merged PR" end;
      .[] | "    #\(.number)  \(.title[0:66])\n           \(why)"
    '
  fi
else
  echo "$FINAL"
fi
