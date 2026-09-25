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

CODEX_LINES="$(bash "$SCRIPT_DIR/ensure-codex.sh" --check)"
GEMINI_LINES="$(bash "$SCRIPT_DIR/ensure-gemini.sh" --check)"
eval "$CODEX_LINES"
eval "$GEMINI_LINES"
printf '%s\n%s\n' "$CODEX_LINES" "$GEMINI_LINES"

if [ "$CODEX_INSTALLED" != "yes" ]; then
  CODEX_WHY="Codex is not installed"; CODEX_FIX="Install it: $CODEX_INSTALL_HINT"
elif [ "$CODEX_AUTHED" != "yes" ]; then
  CODEX_WHY="Codex is not logged in"; CODEX_FIX="$CODEX_AUTH_HINT"
else
  CODEX_WHY=""; CODEX_FIX=""
fi
if [ "$GEMINI_INSTALLED" != "yes" ]; then
  GEMINI_WHY="Gemini is not installed"; GEMINI_FIX="Install it: $INSTALL_HINT"
elif [ "$GEMINI_AUTHED" != "yes" ]; then
  GEMINI_WHY="Gemini has no headless credential"; GEMINI_FIX="$AUTH_HINT"
else
  GEMINI_WHY=""; GEMINI_FIX=""
fi

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
