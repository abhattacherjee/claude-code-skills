#!/usr/bin/env bash
# milestone-report.sh — gather milestone + open-issue state for focus triage.
#
# Emits, per open milestone: its theme (the description), open/closed counts, and
# every open issue with labels, age, and an ACCRETION flag.
#
# Accretion = the issue was created AFTER the newest already-closed issue in that
# milestone. That is the signature of a milestone drifting: its scoping cohort is
# done, and newer work keeps landing in the open milestone by default.
#
# Context-gathering script: set -eu WITHOUT pipefail (head/grep in pipes are expected
# to close early; see skill-authoring's set-flags pitfall).
set -eu

usage() {
  cat <<'USAGE'
Usage: milestone-report.sh [OPTIONS]

Gathers milestone and open-issue state so milestone membership can be judged
against each milestone's stated theme.

Options:
  --repo OWNER/REPO   Target repo (default: current directory's gh repo)
  --milestone TITLE   Only report this milestone (default: all open milestones)
  --unassigned        Also list open issues with NO milestone
  --json              Machine-readable output
  -h, --help          This message

Exit codes: 0 ok · 1 error · 2 usage

Examples:
  milestone-report.sh
  milestone-report.sh --milestone v3.6 --unassigned
  milestone-report.sh --json > /tmp/ms.json
USAGE
}

REPO=""; ONLY_MS=""; AS_JSON=0; SHOW_UNASSIGNED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --milestone) ONLY_MS="${2:-}"; shift 2 ;;
    --unassigned) SHOW_UNASSIGNED=1; shift ;;
    --json) AS_JSON=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null 2>&1 || { echo "ERROR: gh not found on PATH" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found on PATH" >&2; exit 1; }

if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)
  [ -n "$REPO" ] || { echo "ERROR: not in a gh repo and --repo not given" >&2; exit 1; }
fi

# state=all is load-bearing: the milestones endpoint returns ONLY open milestones by
# default, so closed ones are invisible and the version-numbering history is lost.
MILESTONES=$(gh api "repos/$REPO/milestones?state=all&per_page=100" --paginate 2>/dev/null) \
  || { echo "ERROR: could not read milestones for $REPO" >&2; exit 1; }

ISSUES=$(gh issue list --repo "$REPO" --state all --limit 1000 \
           --json number,title,state,labels,milestone,createdAt 2>/dev/null) \
  || { echo "ERROR: could not read issues for $REPO" >&2; exit 1; }

REPORT=$(jq -n \
  --argjson ms "$MILESTONES" \
  --argjson iss "$ISSUES" \
  --arg only "$ONLY_MS" \
  --arg repo "$REPO" '
  def prio: (.labels | map(.name) | map(select(test("^P[0-9]"))) | first) // "unprioritised";
  def agedays($now): (($now - (.createdAt | fromdateiso8601)) / 86400) | floor;
  ($iss | map(select(.milestone != null))) as $assigned |
  (now) as $now |
  {
    repo: $repo,
    milestones: [
      $ms[]
      | select(.state == "open")
      | select($only == "" or .title == $only)
      | . as $m
      | ($assigned | map(select(.milestone.title == $m.title))) as $mine
      | ($mine | map(select(.state == "CLOSED")) | map(.createdAt) | sort | last) as $newest_closed
      | {
          title: $m.title,
          number: $m.number,
          theme: (($m.description // "") | if . == "" then null else . end),
          has_theme: (($m.description // "") != ""),
          due_on: $m.due_on,
          open_count: ($mine | map(select(.state == "OPEN")) | length),
          closed_count: ($mine | map(select(.state == "CLOSED")) | length),
          newest_closed_createdAt: $newest_closed,
          open_issues: [
            $mine[] | select(.state == "OPEN")
            | {
                number, title,
                labels: (.labels | map(.name)),
                priority: prio,
                createdAt,
                age_days: agedays($now),
                accretion: (if $newest_closed == null then false
                            else (.createdAt > $newest_closed) end)
              }
          ] | sort_by(.priority, .number)
        }
    ],
    unassigned_open: [
      $iss[] | select(.state == "OPEN") | select(.milestone == null)
      | {number, title, labels: (.labels | map(.name)), priority: prio,
         createdAt, age_days: agedays($now)}
    ] | sort_by(.priority, .number)
  }')

if [ "$AS_JSON" -eq 1 ]; then
  printf '%s\n' "$REPORT"
  exit 0
fi

printf '%s\n' "$REPORT" | jq -r --argjson show_un "$SHOW_UNASSIGNED" '
  "repo: \(.repo)\n" +
  (.milestones | map(
    "═══ \(.title)  (milestone #\(.number))  open=\(.open_count) closed=\(.closed_count)" +
    (if .due_on then "  due=\(.due_on[0:10])" else "  due=none" end) + "\n" +
    (if .has_theme
       then "THEME: \(.theme)\n"
       else "THEME: ⚠ NONE SET — membership cannot be judged on theme; set one first.\n" end) +
    (if (.open_issues | length) == 0 then "  (no open issues)\n"
     else (.open_issues | map(
       "  #\(.number)  \(.priority)" +
       (if .accretion then "  [ACCRETION]" else "" end) +
       "  \(.age_days)d  \(.title[0:88])"
     ) | join("\n")) + "\n" end) +
    (if ((.open_issues | map(select(.accretion)) | length) == (.open_issues | length))
        and ((.open_issues | length) > 0) and (.closed_count > 0)
       then "  ⚠ EVERY open issue post-dates the newest closed one — this milestone'"'"'s\n" +
            "    original scope is finished and it is now absorbing new work by default.\n"
       else "" end)
  ) | join("\n")) +
  (if $show_un == 1 and (.unassigned_open | length) > 0
     then "\n═══ NO MILESTONE  (\(.unassigned_open | length) open)\n" +
          (.unassigned_open | map("  #\(.number)  \(.priority)  \(.age_days)d  \(.title[0:88])") | join("\n")) + "\n"
     else "" end)
'
