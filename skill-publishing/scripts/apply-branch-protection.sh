#!/usr/bin/env bash
# apply-branch-protection.sh — Apply GitHub rulesets to skill repos
# Configures branch protection via rulesets (available on GitHub Free for public repos)
set -eu

GITHUB_USER=""
DRY_RUN=false
APPLY_ALL=false
REPOS=()

# All repos that should have protection
ALL_REPOS=(
  claude-code-skills
  claudeception
  conversation-search
  skill-authoring
  skill-publishing
  changelog-keeper
  worktree
)

usage() {
  cat <<'EOF'
Usage: apply-branch-protection.sh [options] [repo-name...]

Applies GitHub rulesets to skill repos to enforce PR-based workflow:
  - Block direct pushes to main (require PRs)
  - Require 1 approval on PRs
  - Require 'validate' CI check to pass
  - Block force pushes and branch deletion
  - Allow repo admin bypass (for sync scripts)

Options:
  --all                Apply to all 6 repos
  --dry-run            Show what would be applied without making changes
  --github-user NAME   GitHub username (default: auto-detect via gh api)
  -h, --help           Show this help

Examples:
  apply-branch-protection.sh --all                      # All repos
  apply-branch-protection.sh claude-code-skills          # One repo
  apply-branch-protection.sh --dry-run --all             # Preview
  apply-branch-protection.sh --dry-run claude-code-skills

Repos affected by --all:
  claude-code-skills, claudeception, conversation-search,
  skill-authoring, skill-publishing, changelog-keeper
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)          APPLY_ALL=true; shift ;;
    --dry-run)      DRY_RUN=true; shift ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    -h|--help)      usage ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)              REPOS+=("$1"); shift ;;
  esac
done

# Determine target repos
if $APPLY_ALL; then
  REPOS=("${ALL_REPOS[@]}")
elif [[ ${#REPOS[@]} -eq 0 ]]; then
  echo "Error: specify repo names or use --all" >&2
  echo "Usage: apply-branch-protection.sh [options] [repo-name...]" >&2
  exit 1
fi

# --- Resolve GitHub user ---
if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
  if [[ -z "$GITHUB_USER" ]]; then
    echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
    exit 1
  fi
fi

echo "GitHub user: $GITHUB_USER"
echo "Dry run:     $DRY_RUN"
echo "Repos:       ${REPOS[*]}"
echo ""

# --- Ruleset JSON ---
# This ruleset enforces:
# 1. No deleting main branch
# 2. No force pushes
# 3. PRs required with 1 approval
# 4. 'validate' CI check must pass
# 5. Repo admin can bypass (for sync scripts)
build_ruleset_json() {
  local repo="$1"

  # Get the repo admin actor ID (repository_roles:admin = role 5)
  cat <<'RULESET_EOF'
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ],
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": true,
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          {
            "context": "validate"
          }
        ]
      }
    }
  ]
}
RULESET_EOF
}

# --- Apply ruleset to a repo ---
apply_to_repo() {
  local repo="$1"
  local full_repo="$GITHUB_USER/$repo"

  echo "--- $repo ---"

  # Check if repo exists
  if ! gh repo view "$full_repo" --json name >/dev/null 2>&1; then
    echo "  SKIP: repo $full_repo not found on GitHub"
    echo ""
    return
  fi

  # Check for existing rulesets
  EXISTING=$(gh api "repos/$full_repo/rulesets" --jq '.[].name' 2>/dev/null || echo "")

  if echo "$EXISTING" | grep -q "main-protection"; then
    echo "  EXISTS: 'main-protection' ruleset already applied"

    if $DRY_RUN; then
      echo "  WOULD: update existing ruleset"
    else
      # Get the existing ruleset ID and update it
      RULESET_ID=$(gh api "repos/$full_repo/rulesets" --jq '.[] | select(.name == "main-protection") | .id' 2>/dev/null)
      if [[ -n "$RULESET_ID" ]]; then
        RULESET_JSON=$(build_ruleset_json "$repo")
        echo "$RULESET_JSON" | gh api "repos/$full_repo/rulesets/$RULESET_ID" \
          --method PUT \
          --input - \
          --jq '.name + " (id: " + (.id | tostring) + ") — updated"' 2>&1 | sed 's/^/  /'
      fi
    fi
  else
    if $DRY_RUN; then
      echo "  WOULD CREATE: 'main-protection' ruleset"
      echo "    - Block branch deletion"
      echo "    - Block force push"
      echo "    - Require PR with 1 approval"
      echo "    - Require 'validate' CI check"
      echo "    - Admin bypass enabled"
    else
      RULESET_JSON=$(build_ruleset_json "$repo")
      echo "$RULESET_JSON" | gh api "repos/$full_repo/rulesets" \
        --method POST \
        --input - \
        --jq '.name + " (id: " + (.id | tostring) + ") — created"' 2>&1 | sed 's/^/  /'
    fi
  fi

  echo ""
}

# --- Apply to each repo ---
SUCCESS=0
SKIPPED=0

for repo in "${REPOS[@]}"; do
  apply_to_repo "$repo"
done

echo "Done."
if $DRY_RUN; then
  echo "(dry run — no changes were made)"
fi
