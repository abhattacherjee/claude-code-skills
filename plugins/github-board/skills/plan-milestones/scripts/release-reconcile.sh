#!/usr/bin/env bash
# release-reconcile.sh — plan-milestones step 0: check each closed issue a merged PR names
# against the release that shipped it (#204).
#
# For each closed issue (stateReason COMPLETED, or none) named by a merged PR's closing
# keyword, it finds the first release tag that contains the PR's merge commit. Inside a tag,
# the issue belongs to that release's milestone (the exact vX.Y.Z title, else vX.Y), even when
# that milestone is closed. After the last tag, it belongs to the next-release milestone. Both
# come from lib/config.py, shared with move-card and promote-shipped. When several merged PRs
# name one issue, the earliest release wins: it shipped there first. A merge commit that no
# tag contains but that is older than the newest release tag (vX.Y.0 or vX.Y; a squashed
# release/* -> main merge breaks containment) gets a NOTE and no move. Hotfix tags are
# ignored for that date test.
#
# It also flags a closed issue whose linked PRs (closedByPullRequestsReferences) all failed to
# merge while a merged PR or a commit on develop or the default branch names it: the issue
# was closed through an abandoned PR while another one shipped the work. It writes nothing on
# GitHub; apply the moves with apply-plan.sh.
#
# Validation script: set -euo pipefail. Bash 3.2 safe.
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../../lib/config.sh"

usage() {
  cat <<'USAGE'
Usage: release-reconcile.sh --repo OWNER/REPO [--json FILE] [--no-fetch]

Run it from a full (not shallow) checkout of OWNER/REPO. It refuses (exit 2) when origin
is another repo or another host than github.com ($GH_HOST when set), or when the clone is
shallow. Then it runs `git fetch --tags origin` (skip with --no-fetch).

Prints one line per finding, then always a summary:
  MISMATCH #N: PR #P, commit <sha>, in <tag>|after <last tag>: <current|none> -> <target>
               [; also named by PR #Q (in <tag>|after <last tag>|in no tag, merged before
               <release tag>), ...]
  FLAG #N: closed with only unmerged linked PR(s) #A, but merged PR #P names it
  FLAG #N: closed with only unmerged linked PR(s) #A, but commit <sha> on <branch> names it
  NOTE #N: <why it was not checked or not moved>
  release check: N issues checked, M mismatches, K flagged[, C named only by a commit]

A merge commit that no tag contains, but that is older than the newest release tag, gets
"NOTE #N: PR #P merged before <release tag> but no tag contains it (squashed release?)"
and no move. This date test applies only when that tag's commit is not a merge (a squashed
or direct-commit release); after a merge release such a commit is "after <last tag>". A
release tag is vX.Y.0 or vX.Y; hotfix tags (vX.Y.Z, Z > 0) are ignored. With only hotfix
tags there is no release tag, so no date test applies. Known false NOTE: work merged to
develop during a squashed release's window gets the NOTE; it fails safe (no move).

"Checked" counts the issues whose milestone was compared. An issue that only a commit
names is checked for FLAG only, and counted apart.

Options:
  --repo O/R      The repo to check. Required.
  --json FILE     Write {"repo": "O/R", "closed_moves": [{"issue": N, "to": "<title>"}]} for
                  apply-plan.sh --plan FILE. An old FILE is deleted first, and nothing is
                  written when the run exits 1.
  --no-fetch      Do not run git fetch --tags origin first.
  -h, --help      This message

Exit codes: 0 it ran (with or without mismatches) · 1 the result is incomplete: git, gh or
            jq is missing; git fetch failed; a merged-PR list failed, was empty, or hit the
            1000-PR limit; a merged PR had no merge commit; the milestone list failed; an
            issue could not be read; or a merge commit is not in this clone · 2 usage, not a
            git checkout, a shallow clone, or a checkout of another repo or host
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
# A failed or refused run must not leave an old plan behind for apply-plan.sh to apply.
[ -z "$JSON_OUT" ] || rm -f "$JSON_OUT"
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

# --- the checkout must be REPO on the GitHub host -----------------------------------------
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]; then
  echo "ERROR: not inside a git checkout; run this from a checkout of $REPO" >&2
  exit 2
fi
# The configured URL, not `git remote get-url`: get-url applies url.*.insteadOf rewrites, and
# a mirror rewrite would hide which repo this checkout is.
ORIGIN_URL=$(git config --get remote.origin.url || true)
url="${ORIGIN_URL%/}"; url="${url%.git}"
host=""; path=""
case "$url" in
  *://*) rest="${url#*://}"; host="${rest%%/*}"; path="${rest#*/}"   # https://host/O/R, ssh://git@host:22/O/R
         [ "$rest" != "$host" ] || path="" ;;
  /*|./*|../*) ;;                                                     # a local path
  *:*) host="${url%%:*}"; path="${url#*:}" ;;                         # [git@]host:O/R
esac
host="${host##*@}"; host="${host%%:*}"
WANT_HOST="${GH_HOST:-github.com}"
if [ -z "$ORIGIN_URL" ] || [ "$(lower "$host")" != "$(lower "$WANT_HOST")" ] \
   || [ "$(lower "$path")" != "$(lower "$REPO")" ]; then
  echo "ERROR: this checkout's origin is '${ORIGIN_URL:-none}', not $REPO on $WANT_HOST; refusing." >&2
  echo "       run it from a checkout of $REPO, or pass the repo this checkout is." >&2
  exit 2
fi

# A shallow clone lacks commits, and a commit it does have can look contained in no tag:
# that reads as "after the last tag" and would move a shipped issue. Refuse, never guess.
if [ "$(git rev-parse --is-shallow-repository 2>/dev/null || true)" = "true" ]; then
  echo "ERROR: shallow clone: run git fetch --unshallow origin, then re-run" >&2
  exit 2
fi

if [ "$FETCH" -eq 1 ]; then
  if ! FETCH_ERR=$(git fetch --tags --quiet origin 2>&1); then
    echo "ERROR: git fetch --tags origin failed: $(printf '%s' "$FETCH_ERR" | tr '\n' ' ' | cut -c1-300)" >&2
    exit 1
  fi
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
INCOMPLETE=""            # reads that leave the result incomplete; exit 1 at the end

# --- merged PRs and the issues they name --------------------------------------------------
if ! DEFAULT=$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name 2>"$TMP/err") \
   || [ -z "$DEFAULT" ]; then
  echo "ERROR: could not read the default branch of $REPO: $(tr '\n' ' ' < "$TMP/err")" >&2
  exit 1
fi
BASES="develop"
[ "$DEFAULT" = "develop" ] || BASES="develop $DEFAULT"

# The closing keywords GitHub accepts: the same rule as find-promotable.sh's fallback
# (promote-shipped/scripts/find-promotable.sh, jq_filter in discover_prs_for_issue), which
# tests one issue number. Here the number is captured instead. A keyword, an optional
# colon, then #N, this repo's owner/repo#N, or this repo's issue URL. GitHub records no
# closing link for a merge to a non-default base, so the body is the only record.
# The keyword needs a word boundary on its left: "Encloses #10" is not "closes #10". It is
# written (^|[^A-Za-z0-9_]), not a lookbehind, because find-promotable.sh runs the same rule
# through gh --jq, whose Go regexp (RE2) has no look-around. The issue number stays the last
# capture group (captures[-1]). The issue URL uses the host this checkout was validated against (github.com, or $GH_HOST).
REPO_RE=$(printf '%s' "$REPO" | sed 's/[.]/\\./g')
HOST_RE=$(printf '%s' "$WANT_HOST" | sed 's/[.]/\\./g')
CLOSE_RE='(?i)(^|[^A-Za-z0-9_])(close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+(('"$REPO_RE"')?#|https?://'"$HOST_RE"'/'"$REPO_RE"'/issues/)([0-9]+)\b'

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
    INCOMPLETE="$INCOMPLETE; the merged PRs into $base past the 1000-PR limit"
  fi
  NOSHA=$(printf '%s' "$PRS" | jq -r '[.[] | select((.mergeCommit.oid // "") == "") | "#\(.number)"]
                                      | join(" ")')
  if [ -n "$NOSHA" ]; then
    echo "WARN: merged PR(s) with no merge commit in the reply: $NOSHA" >&2
    INCOMPLETE="$INCOMPLETE; merged PR(s) $NOSHA (no merge commit)"
  fi
  printf '%s' "$PRS" | jq -r --arg re "$CLOSE_RE" '
    .[] | select((.mergeCommit.oid // "") != "") | . as $p
    | [(.body // "") | match($re; "g") | .captures[-1].string | tonumber] | unique[]
    | "\(.)\t\($p.number)\t\($p.mergeCommit.oid)"' >> "$TMP/refs"
done

# Commits on develop and the default branch that name an issue: evidence for the flag only.
: > "$TMP/crefs"          # issue <TAB> sha <TAB> branch, develop first
HAVE_REF=0
for base in $BASES; do
  git rev-parse --verify -q "refs/remotes/origin/$base^{commit}" >/dev/null || continue
  HAVE_REF=1
  git log --format='%H%x1f%B%x1e' "refs/remotes/origin/$base" | jq -R -s -r --arg re "$CLOSE_RE" --arg b "$base" '
    split("\u001e")[] | sub("^\\s+"; "") | select(. != "") | split("\u001f")
    | .[0] as $sha | [(.[1] // "") | match($re; "g") | .captures[-1].string | tonumber]
    | unique[] | "\(.)\t\($sha)\t\($b)"' >> "$TMP/crefs"
done
if [ "$HAVE_REF" -eq 0 ]; then
  echo "WARN: neither origin/develop nor origin/$DEFAULT exists here, so commit evidence for FLAG is unavailable." >&2
fi

# --- release tags, in version order -------------------------------------------------------
# Our own key, not --sort=v:refname: that sorts "2.0" before "v1.0", because it compares the
# names as text up to the first digit.
VER_RE='^v?[0-9]+\.[0-9]+(\.[0-9]+)?$'
version_sort() {          # stdin: tag names; stdout: version tags, lowest first
  grep -E "$VER_RE" | awk '{ s = $0; sub(/^v/, "", s); n = split(s, a, ".")
                             printf "%d %d %d %s\n", a[1], a[2], (n > 2 ? a[3] : 0), $0 }' \
    | sort -k1,1n -k2,2n -k3,3n -k4,4 | awk '{ print $4 }'
}
git tag --list | version_sort > "$TMP/tags" || true
LAST_TAG=$(awk 'END { print }' "$TMP/tags")
[ -n "$LAST_TAG" ] || echo "WARN: no release tag (vX.Y or vX.Y.Z) in this checkout; every merged issue counts as after the last release." >&2
# The squash date test uses the newest RELEASE tag: vX.Y.0 or vX.Y. A hotfix tag (vX.Y.Z,
# Z > 0) sits on main only, so develop work merged before it is still unreleased, not
# squashed into it. It applies only when that tag's commit has one parent (a squashed or
# direct-commit release). A merge release holds its branch's history, so a commit it does
# not hold was merged to develop after the release branch was cut: unreleased work.
RELEASE_TAG=$(grep -E '^v?[0-9]+\.[0-9]+(\.0)?$' "$TMP/tags" | awk 'END { print }' || true)
RELEASE_DATE=""
if [ -n "$RELEASE_TAG" ]; then
  # The tagger date of an annotated tag, else the date of the commit it points at.
  RELEASE_DATE=$(git for-each-ref --format='%(taggerdate:unix)' "refs/tags/$RELEASE_TAG")
  [ -n "$RELEASE_DATE" ] || RELEASE_DATE=$(git log -1 --format=%ct "$RELEASE_TAG^{commit}")
  # rev-list --parents prints the commit, then its parents: 3+ words is a merge.
  if [ "$(git rev-list --parents -n 1 "$RELEASE_TAG^{commit}" | wc -w)" -gt 2 ]; then
    RELEASE_DATE=""
  fi
fi

# sha <TAB> rank <TAB> tag. rank is the tag's place in version order (1 = lowest); for a
# commit no tag contains, 999998 when it is older than the newest release tag (squashed?)
# and 999999 when it is newer; -1 when the commit is not in this clone.
: > "$TMP/shas"
cut -f3 "$TMP/refs" | sort -u | while IFS= read -r sha; do
  [ -n "$sha" ] || continue
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    printf '%s\t-1\t\n' "$sha"; continue
  fi
  first=$(git tag --contains "$sha" | grep -E "$VER_RE" \
          | awk 'NR == FNR { rank[$0] = FNR; next } ($0 in rank) { print rank[$0] "\t" $0 }' \
                "$TMP/tags" - | sort -k1,1n | awk 'NR == 1' || true)
  if [ -n "$first" ]; then
    printf '%s\t%s\n' "$sha" "$first"
  elif [ -n "$RELEASE_DATE" ] && [ "$(git log -1 --format=%ct "$sha")" -le "$RELEASE_DATE" ]; then
    printf '%s\t999998\t\n' "$sha"
  else
    printf '%s\t999999\t\n' "$sha"
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
    # --after-tag: the tags were just fetched, so the newest one is known here.
    out=$(gb_next_release --repo "$REPO" --cache "$MS_CACHE" --after-tag "$LAST_TAG") || return 2
    NEXT_DONE=1
    if [ -n "$out" ]; then NEXT_NUM="${out%%$'\t'*}"; NEXT_TITLE="${out#*$'\t'}"; fi
  fi
  return 0
}

QUERY='query($o:String!,$n:String!,$num:Int!){repository(owner:$o,name:$n){issueOrPullRequest(number:$num){__typename ... on Issue{number state stateReason milestone{number title} closedByPullRequestsReferences(first:25,includeClosedPrs:true){nodes{number merged}}}}}}'
OWNER="${REPO%%/*}"; NAME="${REPO#*/}"
CHECKED=0; FLAGGED=0; COMMIT_ONLY=0; UNREAD=""
LAST_LABEL="${LAST_TAG:-the last tag (none)}"
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

  # Step-5 flag: every linked PR unmerged, yet merged work names the issue.
  UNMERGED=$(printf '%s' "$NODE" | jq -r '(.closedByPullRequestsReferences.nodes // []) as $l
    | if ([$l[] | select(.merged == true)] | length) == 0     # no links: "" below, no flag
      then [$l[] | "#\(.number)"] | join(" ") else "" end')
  ISSUE_ROWS=$(awk -F'\t' -v n="$num" '$1 == n' "$TMP/rows")
  if [ -n "$UNMERGED" ]; then
    if [ -n "$ISSUE_ROWS" ]; then
      by="merged PR #$(printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' 'NR == 1 { print $3 }')"
    else
      by=$(awk -F'\t' -v n="$num" '$1 == n { print "commit " substr($2, 1, 7) " on " $3; exit }' "$TMP/crefs")
    fi
    echo "FLAG #$num: closed with only unmerged linked PR(s) $UNMERGED, but $by names it" >> "$TMP/flag"
    FLAGGED=$((FLAGGED + 1))
  fi

  # Milestone check: merged PRs only.
  if [ -z "$ISSUE_ROWS" ]; then
    COMMIT_ONLY=$((COMMIT_ONLY + 1))
    continue
  fi
  if printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' '$2 == -1 { bad = 1 } END { exit !bad }'; then
    echo "WARN: #$num: a merge commit is not in this clone, so its release is unknown." >&2
    UNREAD="$UNREAD #$num"
    continue
  fi
  IFS=$'\t' read -r _ rank prn sha tag <<EOF
$(printf '%s\n' "$ISSUE_ROWS" | awk 'NR == 1')
EOF
  CUR=$(printf '%s' "$NODE" | jq -r '.milestone.title // "none"')
  if [ "$rank" = 999998 ]; then
    echo "NOTE #$num: PR #$prn merged before $RELEASE_TAG but no tag contains it (squashed release?); milestone left as $CUR" >> "$TMP/note"
    continue
  elif [ "$rank" = 999999 ]; then
    where="after $LAST_LABEL"
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
    if [ "$rc" -ne 0 ]; then
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
  CHECKED=$((CHECKED + 1))
  CUR_NUM=$(printf '%s' "$NODE" | jq -r '.milestone.number // ""')
  [ "$CUR_NUM" != "$TNUM" ] || continue
  ALSO=$(printf '%s\n' "$ISSUE_ROWS" | awk -F'\t' -v last="$LAST_LABEL" -v rel="$RELEASE_TAG" '
    NR > 1 { printf "%s#%s (%s)", (n++ ? ", " : "; also named by PR "), $3,
                    ($2 == 999999 ? "after " last : ($2 == 999998 ? "in no tag, merged before " rel : "in " $5)) }')
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
[ -z "$INCOMPLETE" ] || echo "Not read:${INCOMPLETE#;} (see the warnings above); the result is incomplete."
SUMMARY="release check: $CHECKED issues checked, $MISMATCHES mismatches, $FLAGGED flagged"
[ "$COMMIT_ONLY" -eq 0 ] || SUMMARY="$SUMMARY, $COMMIT_ONLY named only by a commit"
echo "$SUMMARY"
if [ -n "$UNREAD" ] || [ -n "$INCOMPLETE" ]; then
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
