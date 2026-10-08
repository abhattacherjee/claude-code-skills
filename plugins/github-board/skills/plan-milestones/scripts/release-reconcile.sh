#!/usr/bin/env bash
# release-reconcile.sh — plan-milestones step 0: check every closed issue's milestone against
# the release that shipped it (#204).
#
# For each closed issue (stateReason COMPLETED, or none) named by a merged PR's closing
# keyword, it finds the first release tag that contains the PR's merge commit. Inside a tag,
# the issue belongs to that release's milestone (the exact vX.Y.Z title, else vX.Y), even when
# that milestone is closed. After the last tag, it belongs to the next-release milestone. Both
# come from lib/config.py, shared with move-card and promote-shipped. When several merged PRs
# name one issue, the earliest release wins: it shipped there first.
#
# It also flags a closed issue whose linked PRs (closedByPullRequestsReferences) all failed to
# merge while a merged PR or a commit on develop or the default branch names it: the issue
# was closed through an abandoned PR while another one shipped the work. It reads only;
# apply the moves with apply-plan.sh.
#
# Validation script: set -euo pipefail. Bash 3.2 safe.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../../lib/config.sh"

usage() {
  cat <<'USAGE'
Usage: release-reconcile.sh --repo OWNER/REPO [--json FILE] [--no-fetch]

Run it from a checkout of OWNER/REPO. It refuses (exit 2) when the checkout's origin is
another repo, then runs `git fetch --tags origin` (skip with --no-fetch).

Prints one line per finding, then always a summary:
  MISMATCH #N: PR #P, commit <sha>, in <tag>|after <last tag>: <current|none> -> <target>
  FLAG #N: closed with only unmerged linked PR(s) #A, but merged PR #P names it
  NOTE #N: <why it was not checked>
  release check: N issues checked, M mismatches, K flagged

Options:
  --repo O/R      The repo to check. Required.
  --json FILE     Write {"repo": "O/R", "closed_moves": [{"issue": N, "to": "<title>"}]} for
                  apply-plan.sh --plan FILE. Not written when the run exits 1.
  --no-fetch      Do not run git fetch --tags origin first.
  -h, --help      This message

Exit codes: 0 it ran (with or without mismatches) · 1 a read failed (git fetch, a merged-PR
            list, the milestone list, or an issue), so the result is incomplete · 2 usage, not
            a git checkout, or a checkout of another repo
USAGE
}

REPO=""; JSON_OUT=""; FETCH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --repo|--json)
      [ $# -ge 2 ] || { echo "ERROR: $1 needs a value" >&2; usage >&2; exit 2; }
      if [ "$1" = "--repo" ]; then REPO="$2"; else JSON_OUT="$2"; fi
      shift 2 ;;
    --no-fetch) FETCH=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$REPO" ] || { echo "ERROR: --repo is required" >&2; usage >&2; exit 2; }
# The repo goes into REST paths and GraphQL variables: no extra segments, no . or .. part.
if ! printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' \
   || case "/$REPO/" in */./*|*/../*) true ;; *) false ;; esac; then
  echo "ERROR: --repo must be OWNER/REPO with no . or .. part, got: $REPO" >&2
  exit 2
fi
for tool in git gh jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool not found on PATH" >&2; exit 1; }
done

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# --- the checkout must be REPO ------------------------------------------------------------
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]; then
  echo "ERROR: not inside a git checkout; run this from a checkout of $REPO" >&2
  exit 2
fi
# The configured URL, not `git remote get-url`: get-url applies url.*.insteadOf rewrites, and
# a mirror rewrite would hide which repo this checkout is.
ORIGIN_URL=$(git config --get remote.origin.url || true)
url="${ORIGIN_URL%/}"; url="${url%.git}"
case "$url" in
  *://*) path="${url#*://}"; path="${path#*/}" ;;   # https://host/O/R, ssh://git@host/O/R
  *@*:*) path="${url#*:}" ;;                         # git@host:O/R
  *) path="" ;;
esac
if [ -z "$ORIGIN_URL" ] || [ "$(lower "$path")" != "$(lower "$REPO")" ]; then
  echo "ERROR: this checkout's origin is '${ORIGIN_URL:-none}', not $REPO; refusing." >&2
  echo "       run it from a checkout of $REPO, or pass the repo this checkout is." >&2
  exit 2
fi

if [ "$(git rev-parse --is-shallow-repository 2>/dev/null || true)" = "true" ]; then
  echo "WARN: this is a shallow clone, so tag containment cannot be trusted. Commits it lacks" >&2
  echo "      are reported as not checked. Run git fetch --unshallow origin for a full check." >&2
fi

if [ "$FETCH" -eq 1 ]; then
  if ! FETCH_ERR=$(git fetch --tags --quiet origin 2>&1); then
    echo "ERROR: git fetch --tags origin failed: $(printf '%s' "$FETCH_ERR" | tr '\n' ' ' | cut -c1-300)" >&2
    exit 1
  fi
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# --- merged PRs and the issues they name --------------------------------------------------
if ! DEFAULT=$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name 2>"$TMP/err") \
   || [ -z "$DEFAULT" ]; then
  echo "ERROR: could not read the default branch of $REPO: $(tr '\n' ' ' < "$TMP/err")" >&2
  exit 1
fi
BASES="develop"
[ "$DEFAULT" = "develop" ] || BASES="develop $DEFAULT"

# The closing keywords GitHub accepts: the same rule as find-promotable.sh's fallback
# (promote-shipped/scripts/find-promotable.sh, jq_filter in discover_linked_prs), which
# tests one issue number. Here the number is captured instead. A keyword, an optional
# colon, then #N, this repo's owner/repo#N, or this repo's issue URL. GitHub records no
# closing link for a merge to a non-default base, so the body is the only record.
REPO_RE=$(printf '%s' "$REPO" | sed 's/[.]/\\./g')
CLOSE_RE='(?i)(close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+(('"$REPO_RE"')?#|https?://github\.com/'"$REPO_RE"'/issues/)([0-9]+)\b'

: > "$TMP/refs"           # issue <TAB> pr <TAB> sha, one per merged PR naming the issue
for base in $BASES; do
  if ! PRS=$(gh pr list --repo "$REPO" --state merged --base "$base" --limit 1000 \
               --json number,body,mergeCommit,baseRefName 2>"$TMP/err"); then
    echo "ERROR: could not list merged PRs into $base: $(tr '\n' ' ' < "$TMP/err")" >&2
    exit 1
  fi
  # Empty output is not "no PRs" (gh prints [] for that).
  if [ -z "$PRS" ] || ! printf '%s' "$PRS" | jq -e 'type == "array"' >/dev/null 2>&1; then
    echo "ERROR: could not list merged PRs into $base: gh returned no output or not a list" >&2
    exit 1
  fi
  if [ "$(printf '%s' "$PRS" | jq 'length')" -ge 1000 ]; then
    echo "WARN: 1000 merged PRs into $base (the --limit); older ones were not read." >&2
  fi
  printf '%s' "$PRS" | jq -r --arg re "$CLOSE_RE" '
    .[] | select((.mergeCommit.oid // "") != "") | . as $p
    | [(.body // "") | match($re; "g") | .captures[-1].string | tonumber] | unique[]
    | "\(.)\t\($p.number)\t\($p.mergeCommit.oid)"' >> "$TMP/refs"
done

# Commits on develop and the default branch that name an issue: evidence for the flag only.
: > "$TMP/crefs"          # issue <TAB> sha
CREFS=""
for base in $BASES; do
  if git rev-parse --verify -q "refs/remotes/origin/$base^{commit}" >/dev/null; then
    CREFS="$CREFS refs/remotes/origin/$base"
  fi
done
if [ -n "$CREFS" ]; then
  # shellcheck disable=SC2086  # CREFS is a list of ref names, split on purpose
  git log --format='%H%x1f%B%x1e' $CREFS | jq -R -s -r --arg re "$CLOSE_RE" '
    split("\u001e")[] | sub("^\\s+"; "") | select(. != "") | split("\u001f")
    | .[0] as $sha | [(.[1] // "") | match($re; "g") | .captures[-1].string | tonumber]
    | unique[] | "\(.)\t\($sha)"' > "$TMP/crefs"
fi

# --- release tags --------------------------------------------------------------------------
VER_RE='^v?[0-9]+\.[0-9]+(\.[0-9]+)?$'
git tag --list --sort=v:refname | grep -E "$VER_RE" > "$TMP/tags" || true
LAST_TAG=$(awk 'END { print }' "$TMP/tags")
[ -n "$LAST_TAG" ] || echo "WARN: no release tag (vX.Y or vX.Y.Z) in this checkout; every merged issue counts as after the last release." >&2

# sha <TAB> rank <TAB> tag. rank is the tag's place in version order; 999999 after the last
# tag; -1 when the commit is not in this clone (shallow, or never fetched).
: > "$TMP/shas"
cut -f3 "$TMP/refs" | sort -u | while IFS= read -r sha; do
  [ -n "$sha" ] || continue
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    printf '%s\t-1\t\n' "$sha"; continue
  fi
  first=$(git tag --contains "$sha" --sort=v:refname | grep -E "$VER_RE" | awk 'NR == 1' || true)
  if [ -z "$first" ]; then
    printf '%s\t999999\t\n' "$sha"
  else
    printf '%s\t%s\t%s\n' "$sha" "$(grep -nxF "$first" "$TMP/tags" | cut -d: -f1)" "$first"
  fi
done > "$TMP/shas"

# issue <TAB> rank <TAB> pr <TAB> sha <TAB> tag, earliest release first per issue.
awk -F'\t' 'NR == FNR { rank[$1] = $2; tag[$1] = $3; next }
            { printf "%s\t%s\t%s\t%s\t%s\n", $1, rank[$3], $2, $3, tag[$3] }' \
  "$TMP/shas" "$TMP/refs" | sort -t "$(printf '\t')" -k1,1n -k2,2n -k3,3n -u > "$TMP/rows"

# --- each issue ---------------------------------------------------------------------------
MS_CACHE="$TMP/milestones.json"
NEXT_DONE=0; NEXT_NUM=""; NEXT_TITLE=""
next_release() {          # sets NEXT_NUM / NEXT_TITLE once; returns 2 on a failed read
  if [ "$NEXT_DONE" -eq 0 ]; then
    local out
    out=$(gb_next_release --repo "$REPO" --cache "$MS_CACHE") || return 2
    NEXT_DONE=1
    if [ -n "$out" ]; then NEXT_NUM="${out%%$'\t'*}"; NEXT_TITLE="${out#*$'\t'}"; fi
  fi
  return 0
}

QUERY='query($o:String!,$n:String!,$num:Int!){repository(owner:$o,name:$n){issueOrPullRequest(number:$num){__typename ... on Issue{number state stateReason milestone{number title} closedByPullRequestsReferences(first:25,includeClosedPrs:true){nodes{number merged}}}}}}'
OWNER="${REPO%%/*}"; NAME="${REPO#*/}"
CHECKED=0; FLAGGED=0; UNREAD=""
: > "$TMP/mismatch"; : > "$TMP/flag"; : > "$TMP/note"; : > "$TMP/moves"

{ cut -f1 "$TMP/refs"; cut -f1 "$TMP/crefs"; } | sort -n -u > "$TMP/issues"
while IFS= read -r num; do
  [ -n "$num" ] || continue
  if ! RAW=$(gh api graphql -f query="$QUERY" -f o="$OWNER" -f n="$NAME" -F num="$num" 2>"$TMP/err"); then
    if grep -q "Could not resolve to an issue or pull request" "$TMP/err"; then
      echo "NOTE #$num: named by a closing keyword, but not found in $REPO" >> "$TMP/note"
    else
      echo "WARN: could not read #$num: $(tr '\n' ' ' < "$TMP/err" | cut -c1-200)" >&2
      UNREAD="$UNREAD #$num"
    fi
    continue
  fi
  NODE=$(printf '%s' "$RAW" | jq -c '.data.repository.issueOrPullRequest // empty' 2>/dev/null || true)
  KIND=$(printf '%s' "$NODE" | jq -r '.__typename // ""' 2>/dev/null || true)
  if [ "$KIND" != "Issue" ] && [ "$KIND" != "PullRequest" ]; then
    echo "WARN: could not read #$num: unexpected reply $(printf '%s' "$RAW" | tr '\n' ' ' | cut -c1-120)" >&2
    UNREAD="$UNREAD #$num"
    continue
  fi
  [ "$KIND" = "Issue" ] || continue
  # Only issues closed as done. Open, not planned and duplicate are not release work.
  printf '%s' "$NODE" | jq -e '.state == "CLOSED" and ((.stateReason // "COMPLETED") == "COMPLETED")' \
    >/dev/null || continue
  CHECKED=$((CHECKED + 1))

  # Step-5 flag: every linked PR unmerged, yet merged work names the issue.
  UNMERGED=$(printf '%s' "$NODE" | jq -r '(.closedByPullRequestsReferences.nodes // []) as $l
    | if ([$l[] | select(.merged == true)] | length) == 0     # no links: "" below, no flag
      then [$l[] | "#\(.number)"] | join(" ") else "" end')
  ISSUE_ROWS=$(awk -F'\t' -v n="$num" '$1 == n' "$TMP/rows")
  if [ -n "$UNMERGED" ]; then
    if [ -n "$ISSUE_ROWS" ]; then
      by="merged PR #$(printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' 'NR == 1 { print $3 }')"
    else
      by="commit $(awk -F'\t' -v n="$num" '$1 == n { print substr($2, 1, 7); exit }' "$TMP/crefs") on develop"
    fi
    echo "FLAG #$num: closed with only unmerged linked PR(s) $UNMERGED, but $by names it" >> "$TMP/flag"
    FLAGGED=$((FLAGGED + 1))
  fi

  # Milestone check: merged PRs only.
  [ -n "$ISSUE_ROWS" ] || continue
  if printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' '$2 == -1 { bad = 1 } END { exit !bad }'; then
    echo "WARN: #$num: a merge commit is not in this clone, so its release is unknown." >&2
    UNREAD="$UNREAD #$num"
    continue
  fi
  IFS=$'\t' read -r _ rank prn sha tag <<EOF
$(printf '%s\n' "$ISSUE_ROWS" | awk 'NR == 1')
EOF
  if [ "$rank" = 999999 ]; then
    where="after ${LAST_TAG:-the last tag (none)}"
    rc=0; next_release || rc=$?
    if [ "$rc" -ne 0 ]; then
      echo "ERROR: could not read the next-release milestone of $REPO (see above)." >&2
      exit 1
    fi
    if [ -z "$NEXT_NUM" ]; then
      echo "NOTE #$num: merged $where, but there is no next-release milestone (see above)" >> "$TMP/note"
      continue
    fi
    TNUM="$NEXT_NUM"; TTITLE="$NEXT_TITLE"
  else
    where="in $tag"
    rc=0; HIT=$(gb_milestone_for_tag --repo "$REPO" --tag "$tag" --cache "$MS_CACHE" 2>"$TMP/err") || rc=$?
    if [ "$rc" -ne 0 ] || [ -z "$HIT" ]; then
      echo "ERROR: $(tr '\n' ' ' < "$TMP/err" | sed 's/^github-board: error: //')" >&2
      exit 1
    fi
    case "$HIT" in
      skip$'\t'*)
        echo "NOTE #$num: merged $where, but ${HIT#skip$'\t'}" >> "$TMP/note"
        continue ;;
    esac
    TNUM="${HIT%%$'\t'*}"; TTITLE="${HIT#*$'\t'}"
  fi
  CUR_NUM=$(printf '%s' "$NODE" | jq -r '.milestone.number // ""')
  [ "$CUR_NUM" != "$TNUM" ] || continue
  CUR=$(printf '%s' "$NODE" | jq -r '.milestone.title // "none"')
  ALSO=$(printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' -v last="${LAST_TAG:-the last tag (none)}" '
    NR > 1 { printf "%s#%s (%s)", (n++ ? ", " : "; also named by PR "), $3,
                    ($2 == 999999 ? "after " last : "in " $5) }')
  echo "MISMATCH #$num: PR #$prn, commit ${sha:0:7}, $where: $CUR -> $TTITLE$ALSO" >> "$TMP/mismatch"
  printf '%s\t%s\n' "$num" "$TTITLE" >> "$TMP/moves"
done < "$TMP/issues"

# --- report ---------------------------------------------------------------------------------
cat "$TMP/mismatch" "$TMP/flag" "$TMP/note"
MISMATCHES=$(awk 'END { print NR }' "$TMP/moves")
if [ -n "$UNREAD" ]; then
  NUNREAD=$(printf '%s\n' $UNREAD | awk 'END { print NR }')
  echo "$NUNREAD issue(s) could not be checked:$UNREAD (see the warnings above); the result is incomplete."
fi
echo "release check: $CHECKED issues checked, $MISMATCHES mismatches, $FLAGGED flagged"
if [ -n "$UNREAD" ]; then
  [ -z "$JSON_OUT" ] || echo "$JSON_OUT not written: the result is incomplete." >&2
  exit 1
fi

if [ -n "$JSON_OUT" ]; then
  jq -R -s --arg repo "$REPO" '
    {repo: $repo,
     closed_moves: [split("\n")[] | select(. != "") | split("\t")
                    | {issue: (.[0] | tonumber), to: .[1]}]}' "$TMP/moves" > "$JSON_OUT"
fi
exit 0
