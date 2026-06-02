#!/usr/bin/env bash
# ensure-gemini.sh — detect Gemini CLI install/auth status and emit KEY=VALUE hints
# Usage: ensure-gemini.sh [--check] [--help]
# Exit codes: 0=always (detection script; reports status, does not fail)
#
# IMPORTANT: This script NEVER installs anything or calls the network.
# It is a pure detection/guidance script. All install/auth actions are
# performed by the orchestrator (adversarial-review SKILL.md Step 0)
# with explicit user consent.

set -eu

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--check] [--help]

Detect Gemini CLI install and auth status. Emits KEY=VALUE lines to stdout.
Never installs or calls the network — detection only.

Options:
  --check   (default) Emit status lines and exit 0
  --help    Show this help and exit 0

Output lines (--check):
  GEMINI_INSTALLED=yes|no
  GEMINI_VERSION=<version>|-
  GEMINI_AUTHED=yes|no|unknown
  INSTALL_HINT=<recommended install command(s)>
  AUTH_HINT=<auth options>

GEMINI_AUTHED values:
  yes      — env GEMINI_API_KEY or GOOGLE_API_KEY is set, OR auth file found
             under ~/.gemini/ (oauth_creds.json, google_accounts.json, or
             settings.json containing an auth token/key)
  no       — gemini is installed but none of the above auth signals found
  unknown  — gemini is not installed; auth state cannot be determined

Exit codes:
  0  Always (this script reports status, it does not fail)
EOF
}

# ---- argument parsing ----
MODE="check"
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --help)  usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $arg" >&2
      usage >&2
      exit 0
      ;;
  esac
done

# ---- detect gemini install ----
GEMINI_INSTALLED="no"
GEMINI_VERSION="-"

if command -v gemini >/dev/null 2>&1; then
  GEMINI_INSTALLED="yes"
  # Try to get the version; many CLIs support --version
  raw_ver="$(gemini --version 2>/dev/null || true)"
  if [ -n "$raw_ver" ]; then
    # Extract the first version-like token (x.y.z)
    ver_token="$(printf '%s' "$raw_ver" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
    if [ -n "$ver_token" ]; then
      GEMINI_VERSION="$ver_token"
    else
      GEMINI_VERSION="$raw_ver"
    fi
  fi
fi

# ---- detect auth ----
# heuristic: yes if any of these signals are present:
#   1. GEMINI_API_KEY env var is set (non-empty)
#   2. GOOGLE_API_KEY env var is set (non-empty)
#   3. Auth/creds file exists under ~/.gemini/
#      Checked files: oauth_creds.json, google_accounts.json
#      settings.json is checked for presence of key/token patterns

GEMINI_AUTHED="unknown"

if [ "$GEMINI_INSTALLED" = "yes" ]; then
  GEMINI_AUTHED="no"

  # Signal 1: API key env vars
  if [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ]; then
    GEMINI_AUTHED="yes"
  fi

  # Signal 2: OAuth / account credentials files
  if [ "$GEMINI_AUTHED" = "no" ]; then
    gemini_dir="${HOME}/.gemini"
    if [ -f "${gemini_dir}/oauth_creds.json" ]; then
      GEMINI_AUTHED="yes"
    elif [ -f "${gemini_dir}/google_accounts.json" ]; then
      GEMINI_AUTHED="yes"
    elif [ -f "${gemini_dir}/settings.json" ]; then
      # Heuristic: settings.json containing an auth token, key, or account info
      if grep -qE '"(api_key|apiKey|token|access_token|refresh_token|account|email)"' \
           "${gemini_dir}/settings.json" 2>/dev/null; then
        GEMINI_AUTHED="yes"
      fi
    fi
  fi
fi

# ---- hints ----
INSTALL_HINT="npm install -g @google/gemini-cli   # primary (requires Node >=18); alt: brew install gemini-cli"
AUTH_HINT="Set GEMINI_API_KEY=<key> (from Google AI Studio at https://aistudio.google.com/apikey), OR run 'gemini' once for interactive Google login, OR set GOOGLE_API_KEY=<key>"

# ---- emit status ----
printf 'GEMINI_INSTALLED=%s\n' "$GEMINI_INSTALLED"
printf 'GEMINI_VERSION=%s\n'   "$GEMINI_VERSION"
printf 'GEMINI_AUTHED=%s\n'    "$GEMINI_AUTHED"
printf 'INSTALL_HINT=%s\n'     "$INSTALL_HINT"
printf 'AUTH_HINT=%s\n'        "$AUTH_HINT"

exit 0
