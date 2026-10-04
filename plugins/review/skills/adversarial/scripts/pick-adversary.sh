#!/usr/bin/env bash
# pick-adversary.sh — choose the opposing model: Codex, then Gemini, then Claude-only.
# Usage: pick-adversary.sh [--adversary auto|codex|gemini] [--help]
# Exit codes: 0=chosen, 2=usage, 3=the forced adversary is not usable (no fallback)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--adversary auto|codex|gemini] [--help]

Pick the adversary. With auto (the default) the order is: Codex when it is
installed and logged in, else Gemini when it has a headless credential, else
claude-only. A forced adversary that is not usable is an error (exit 3), never
a silent fallback.

Prints eval-safe KEY='value' lines: every line from ensure-codex.sh and
ensure-gemini.sh (for their hints), then ADVERSARY and ADVERSARY_REASON.
On exit 3 the ADVERSARY lines are left out and the reason goes to stderr.

If ensure-codex.sh or ensure-gemini.sh itself exits non-zero, or prints
something that doesn't parse as KEY='value' lines, that adversary is treated
as unavailable (a warning goes to stderr) rather than aborting this script.

Exit codes:
  0  an adversary was chosen (claude-only counts)
  2  usage error
  3  the forced adversary is not usable
EOF
}

WANT="auto"
while [ $# -gt 0 ]; do
  case "$1" in
    --adversary)
      if [ $# -lt 2 ]; then
        echo "Error: --adversary requires a value" >&2
        exit 2
      fi
      WANT="$2"
      shift 2
      ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done
case "$WANT" in
  auto|codex|gemini) ;;
  *) echo "Error: --adversary must be auto, codex or gemini, got: $WANT" >&2; exit 2 ;;
esac

# eval-safe: KEY='value' with embedded single quotes escaped. bash 3.2's
# ${var//pattern/replacement} does not collapse a lone backslash before a
# quote in the replacement text, so build the '\'' escape from variables
# instead of a literal \'\\\'\' (which round-trips wrong under bash 3.2).
emit() {
  local q="'" bs='\'
  local v="${2//$q/$q$bs$q$q}"
  printf "%s='%s'\n" "$1" "$v"
}

unusable() {
  echo "ADVERSARY_UNAVAILABLE: --adversary $WANT was asked for, but $1. $2" >&2
  exit 3
}

# Detect Codex. A non-zero exit from ensure-codex.sh, or output that (once
# eval'd) never sets CODEX_INSTALLED, means detection itself failed. That is
# treated as "Codex is unavailable" — never a set -eu abort of this script.
CODEX_INSTALLED=""; CODEX_VERSION="-"; CODEX_AUTHED="unknown"
CODEX_INSTALL_HINT=""; CODEX_AUTH_HINT=""
CODEX_RC=0
CODEX_RAW="$(bash "$SCRIPT_DIR/ensure-codex.sh" --check)" || CODEX_RC=$?
CODEX_DETECTED=0
if [ "$CODEX_RC" -eq 0 ] && eval "$CODEX_RAW" 2>/dev/null && [ -n "$CODEX_INSTALLED" ]; then
  CODEX_DETECTED=1
  printf '%s\n' "$CODEX_RAW"
else
  echo "Warning: ensure-codex.sh --check did not report a usable status (exit $CODEX_RC); treating Codex as unavailable." >&2
  CODEX_INSTALLED="no"; CODEX_VERSION="-"; CODEX_AUTHED="unknown"
  CODEX_INSTALL_HINT="ensure-codex.sh --check failed (exit $CODEX_RC); rerun it directly to see why"
  CODEX_AUTH_HINT="ensure-codex.sh --check failed (exit $CODEX_RC); rerun it directly to see why"
  emit CODEX_INSTALLED "$CODEX_INSTALLED"
  emit CODEX_VERSION "$CODEX_VERSION"
  emit CODEX_AUTHED "$CODEX_AUTHED"
  emit CODEX_INSTALL_HINT "$CODEX_INSTALL_HINT"
  emit CODEX_AUTH_HINT "$CODEX_AUTH_HINT"
fi

# Detect Gemini, same treatment.
GEMINI_INSTALLED=""; GEMINI_VERSION="-"; GEMINI_AUTHED="unknown"
INSTALL_HINT=""; AUTH_HINT=""
GEMINI_RC=0
GEMINI_RAW="$(bash "$SCRIPT_DIR/ensure-gemini.sh" --check)" || GEMINI_RC=$?
GEMINI_DETECTED=0
if [ "$GEMINI_RC" -eq 0 ] && eval "$GEMINI_RAW" 2>/dev/null && [ -n "$GEMINI_INSTALLED" ]; then
  GEMINI_DETECTED=1
  printf '%s\n' "$GEMINI_RAW"
else
  echo "Warning: ensure-gemini.sh --check did not report a usable status (exit $GEMINI_RC); treating Gemini as unavailable." >&2
  GEMINI_INSTALLED="no"; GEMINI_VERSION="-"; GEMINI_AUTHED="unknown"
  INSTALL_HINT="ensure-gemini.sh --check failed (exit $GEMINI_RC); rerun it directly to see why"
  AUTH_HINT="ensure-gemini.sh --check failed (exit $GEMINI_RC); rerun it directly to see why"
  emit GEMINI_INSTALLED "$GEMINI_INSTALLED"
  emit GEMINI_VERSION "$GEMINI_VERSION"
  emit GEMINI_AUTHED "$GEMINI_AUTHED"
  emit INSTALL_HINT "$INSTALL_HINT"
  emit AUTH_HINT "$AUTH_HINT"
fi

if [ "$CODEX_DETECTED" -eq 0 ]; then
  CODEX_WHY="Codex detection failed"
  CODEX_FIX="ensure-codex.sh --check did not report a usable status (exit $CODEX_RC); rerun it directly to see why"
elif [ "$CODEX_INSTALLED" != "yes" ]; then
  CODEX_WHY="Codex is not installed"; CODEX_FIX="Install it: $CODEX_INSTALL_HINT"
elif [ "$CODEX_AUTHED" != "yes" ]; then
  CODEX_WHY="Codex is not logged in"; CODEX_FIX="$CODEX_AUTH_HINT"
else
  CODEX_WHY=""; CODEX_FIX=""
fi
if [ "$GEMINI_DETECTED" -eq 0 ]; then
  GEMINI_WHY="Gemini detection failed"
  GEMINI_FIX="ensure-gemini.sh --check did not report a usable status (exit $GEMINI_RC); rerun it directly to see why"
elif [ "$GEMINI_INSTALLED" != "yes" ]; then
  GEMINI_WHY="Gemini is not installed"; GEMINI_FIX="Install it: $INSTALL_HINT"
elif [ "$GEMINI_AUTHED" != "yes" ]; then
  GEMINI_WHY="Gemini has no headless credential"; GEMINI_FIX="$AUTH_HINT"
else
  GEMINI_WHY=""; GEMINI_FIX=""
fi

case "$WANT" in
  codex)
    if [ -n "$CODEX_WHY" ]; then unusable "$CODEX_WHY" "$CODEX_FIX"; fi
    ADVERSARY="codex"
    REASON="forced with --adversary codex; Codex $CODEX_VERSION is logged in"
    ;;
  gemini)
    if [ -n "$GEMINI_WHY" ]; then unusable "$GEMINI_WHY" "$GEMINI_FIX"; fi
    ADVERSARY="gemini"
    REASON="forced with --adversary gemini"
    ;;
  auto)
    if [ -z "$CODEX_WHY" ]; then
      ADVERSARY="codex"
      REASON="Codex $CODEX_VERSION is installed and logged in"
    elif [ -z "$GEMINI_WHY" ]; then
      ADVERSARY="gemini"
      REASON="$CODEX_WHY; using Gemini, which has a headless credential"
    else
      ADVERSARY="claude-only"
      REASON="$CODEX_WHY and $GEMINI_WHY"
    fi
    ;;
esac

emit ADVERSARY "$ADVERSARY"
emit ADVERSARY_REASON "$REASON"
exit 0
