#!/usr/bin/env bash
# ensure-codex.sh — detect Codex CLI install and login status and emit KEY=VALUE hints
# Usage: ensure-codex.sh [--check] [--help]
# Exit codes: 0=status reported (always, for --check), 2=usage error
#
# Never installs anything and never starts a Codex session. `codex login status`
# only reads the local login.

set -eu

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--check] [--help]

Detect whether the Codex CLI is installed and logged in. Emits eval-safe
KEY='value' lines on stdout. Never installs anything.

Options:
  --check   (default) Emit status lines and exit 0
  --help    Show this help and exit 0

Output lines (--check):
  CODEX_INSTALLED=yes|no
  CODEX_VERSION=<x.y.z>|-
  CODEX_AUTHED=yes|no|unknown     unknown when codex is not installed
  CODEX_INSTALL_HINT=<install command>
  CODEX_AUTH_HINT=<login command>

CODEX_AUTHED comes from the exit code of \`codex login status\`: 0 means logged
in. That command prints to stderr, so its output is never read.

Exit codes:
  0  Status reported
  2  Unknown argument
EOF
}

for arg in "$@"; do
  case "$arg" in
    --check) ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CODEX_INSTALLED="no"
CODEX_VERSION="-"
CODEX_AUTHED="unknown"

if command -v codex >/dev/null 2>&1; then
  CODEX_INSTALLED="yes"
  raw_ver="$(codex --version 2>/dev/null </dev/null || true)"
  ver_token="$(printf '%s' "$raw_ver" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  if [ -n "$ver_token" ]; then
    CODEX_VERSION="$ver_token"
  fi
  if codex login status </dev/null >/dev/null 2>&1; then
    CODEX_AUTHED="yes"
  else
    CODEX_AUTHED="no"
  fi
fi

CODEX_INSTALL_HINT="npm install -g @openai/codex"
CODEX_AUTH_HINT="Run: codex login   (then re-run the review; the skill checks 'codex login status')"

# eval-safe: KEY='value' with embedded single quotes escaped. bash 3.2's
# ${var//pattern/replacement} does not collapse a lone backslash before a
# quote in the replacement text, so build the '\'' escape from variables
# instead of a literal \'\\\'\' (which round-trips wrong under bash 3.2).
emit() {
  local q="'" bs='\'
  local v="${2//$q/$q$bs$q$q}"
  printf "%s='%s'\n" "$1" "$v"
}

emit CODEX_INSTALLED    "$CODEX_INSTALLED"
emit CODEX_VERSION      "$CODEX_VERSION"
emit CODEX_AUTHED       "$CODEX_AUTHED"
emit CODEX_INSTALL_HINT "$CODEX_INSTALL_HINT"
emit CODEX_AUTH_HINT    "$CODEX_AUTH_HINT"

exit 0
