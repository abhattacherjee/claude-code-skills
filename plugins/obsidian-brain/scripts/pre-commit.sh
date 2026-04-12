#!/bin/bash
# Secret Detection Script
# Scans staged files for potential secrets before commit.
# Called by commit-preflight.sh as part of the preflight check.
#
# Installed by /harden-repo

set -eo pipefail

echo "🔍 Checking for secrets in staged files..."

# Check for common secret patterns in added lines only (exclude scripts/, docs/, hooks, CI, tests/)
# Scanning only '+' lines avoids blocking commits that remove leaked secrets.
# tests/ is excluded because security tests intentionally contain test patterns.
if git diff --cached -- ':!scripts/*' ':!docs/*' ':!*.md' ':!.claude/hooks/*' ':!.github/workflows/*' ':!tests/*' | grep '^+' | grep -v '^+++' | grep -E "(sk-[a-zA-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|private_key|-----BEGIN.*PRIVATE KEY-----|ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|xox[bsapr]-[a-zA-Z0-9-]+|password\s*[:=]\s*['\"][^'\"]{8,}|Bearer\s+[A-Za-z0-9._-]{20,}|(token|secret|api_key)\s*[:=]\s*[A-Za-z0-9+/=]{40,})" 2>/dev/null; then
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
  echo ""
  echo "⚠️  WARNING: Potentially sensitive files staged:"
  echo "$SECRET_FILES"
  echo ""
  echo "Verify these files do not contain secrets before committing."
  # Warning only — don't block on filenames alone (content scan above catches actual secrets)
fi

echo "✅ No secrets detected"
