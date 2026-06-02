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
  yes      — a headless-capable credential is present: env GEMINI_API_KEY or
             GOOGLE_API_KEY is set (non-empty), OR a non-empty GEMINI_API_KEY=
             line exists in ~/.gemini/.env, OR Vertex is configured
             (GOOGLE_GENAI_USE_VERTEXAI is truthy AND GOOGLE_CLOUD_PROJECT is set).
             Interactive Google OAuth login (google_accounts.json,
             oauth_creds.json) is NOT sufficient for headless use and is
             intentionally not counted here.
  no       — gemini is installed but none of the headless credential signals
             found (OAuth-only credentials do not count)
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
      exit 2
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

# ---- detect auth (headless-only signals) ----
# Reports GEMINI_AUTHED=yes ONLY when a credential that works for headless
# programmatic invocations (gemini -p ... -o json -m <model>) is found.
#
# Interactive Google OAuth login stored in ~/.gemini/google_accounts.json or
# oauth_creds.json is NOT sufficient for headless calls and is intentionally
# excluded — reporting those as "authed" causes the skill to skip the auth
# setup prompt and then fail at runtime with exit code 41.
#
# Headless credential signals (any one → yes):
#   1. GEMINI_API_KEY env var is set (non-empty)
#   2. GOOGLE_API_KEY env var is set (non-empty)
#   3. ~/.gemini/.env file contains a non-empty GEMINI_API_KEY=<value> line
#      (the gemini CLI auto-loads this file for all invocations, including
#      non-login shells and sub-agent/tool contexts — recommended location)
#   4. Vertex AI: GOOGLE_GENAI_USE_VERTEXAI is truthy AND GOOGLE_CLOUD_PROJECT
#      is set (Vertex does not require a personal API key)

GEMINI_AUTHED="unknown"

if [ "$GEMINI_INSTALLED" = "yes" ]; then
  GEMINI_AUTHED="no"

  # Signal 1 & 2: API key env vars
  if [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ]; then
    GEMINI_AUTHED="yes"
  fi

  # Signal 3: GEMINI_API_KEY in ~/.gemini/.env (auto-loaded by the gemini CLI)
  if [ "$GEMINI_AUTHED" = "no" ]; then
    gemini_env_file="${HOME}/.gemini/.env"
    if [ -f "$gemini_env_file" ]; then
      # Match lines of the form GEMINI_API_KEY=<non-empty-value>
      # (allow optional whitespace around =; ignore comment lines)
      if grep -qE '^[[:space:]]*GEMINI_API_KEY[[:space:]]*=[[:space:]]*[^[:space:]#]+' \
           "$gemini_env_file" 2>/dev/null; then
        GEMINI_AUTHED="yes"
      fi
    fi
  fi

  # Signal 4: Vertex AI (no personal API key needed)
  if [ "$GEMINI_AUTHED" = "no" ]; then
    use_vertex="${GOOGLE_GENAI_USE_VERTEXAI:-}"
    cloud_project="${GOOGLE_CLOUD_PROJECT:-}"
    # Treat "1", "true", "TRUE", "yes", "YES" as truthy
    case "$use_vertex" in
      1|true|TRUE|yes|YES)
        if [ -n "$cloud_project" ]; then
          GEMINI_AUTHED="yes"
        fi
        ;;
    esac
  fi
fi

# ---- hints ----
INSTALL_HINT="npm install -g @google/gemini-cli   # primary (requires Node >=18); alt: brew install gemini-cli"
AUTH_HINT="Headless review needs an API key — interactive Google login is NOT enough. Get a key at https://aistudio.google.com/apikey and either: (a) export GEMINI_API_KEY=<key> in your shell, or (b) add GEMINI_API_KEY=<key> to ~/.gemini/.env (recommended — auto-loaded by all shells including sub-agents). Vertex: set GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT=<project>."

# ---- emit status (eval-safe: KEY='value' with embedded single-quotes escaped) ----
emit() { local v="${2//\'/\'\\\'\'}"; printf "%s='%s'\n" "$1" "$v"; }

emit GEMINI_INSTALLED "$GEMINI_INSTALLED"
emit GEMINI_VERSION   "$GEMINI_VERSION"
emit GEMINI_AUTHED    "$GEMINI_AUTHED"
emit INSTALL_HINT     "$INSTALL_HINT"
emit AUTH_HINT        "$AUTH_HINT"

exit 0
