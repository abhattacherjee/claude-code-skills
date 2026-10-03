#!/usr/bin/env bash
# Quick context usage bar for the current Claude Code session, estimated from the size of
# its transcript: ~8 bytes per token (JSON overhead inflates the raw character count),
# plus 50K tokens of system overhead, against a 1M-token window.
#
# The transcript lives in ${CLAUDE_CONFIG_DIR:-~/.claude}/projects/<slug>/, where <slug> is
# the session's working directory with every character that is not an ASCII letter or digit
# replaced by '-' (counted in UTF-16 code units, as Claude Code's JavaScript does). A slug
# longer than 200 characters is cut to 200 and gets '-<hash>' appended, so that case is
# matched by prefix. The logical $PWD is tried first, then the physical path.
# In that directory, $CLAUDE_CODE_SESSION_ID.jsonl is used when it exists, else the newest
# *.jsonl.
#
# Exit codes: 0 bar printed, 1 no transcript found (no bar is printed), 2 bad argument.

usage() {
  cat <<'USAGE'
Usage: context-bar.sh

Prints a color-coded bar of how much of the context window the current Claude Code
session has used (green <50%, amber 50-79%, red 80%+). Run it from the session's
working directory.

Exit codes: 0 bar printed, 1 no transcript found, 2 bad argument.
USAGE
}

case "${1:-}" in
  "") ;;
  --help|-h) usage; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

PROJECTS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"

slug() {
  python3 -c '
import sys
p = sys.argv[1]
print("".join(c if (c.isascii() and c.isalnum())
              else "-" * (len(c.encode("utf-16-le", "surrogatepass")) // 2) for c in p))
' "$1"
}

# Print the project dir for working directory $1, if it exists.
project_dir() {
  local s d
  s=$(slug "$1") || return 1
  if [ "${#s}" -le 200 ]; then
    [ -d "$PROJECTS/$s" ] && printf '%s\n' "$PROJECTS/$s"
  else
    for d in "$PROJECTS/${s:0:200}-"*; do
      [ -d "$d" ] && { printf '%s\n' "$d"; return 0; }
    done
  fi
  return 0
}

LOGICAL="${PWD:-$(pwd)}"
PHYSICAL="$(pwd -P)"
PROJ_DIR=$(project_dir "$LOGICAL")
[ -z "$PROJ_DIR" ] && [ "$PHYSICAL" != "$LOGICAL" ] && PROJ_DIR=$(project_dir "$PHYSICAL")
if [ -z "$PROJ_DIR" ]; then
  echo "No Claude Code transcript directory for $LOGICAL" >&2
  echo "(looked for $PROJECTS/$(slug "$LOGICAL")). Run this from the session's working directory." >&2
  exit 1
fi

LATEST=""
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] && [ -f "$PROJ_DIR/$CLAUDE_CODE_SESSION_ID.jsonl" ]; then
  LATEST="$PROJ_DIR/$CLAUDE_CODE_SESSION_ID.jsonl"
else
  [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] &&
    echo "No $CLAUDE_CODE_SESSION_ID.jsonl in $PROJ_DIR; using the newest transcript there." >&2
  LATEST=$(ls -t "$PROJ_DIR"/*.jsonl 2>/dev/null | head -1)
fi
if [ -z "$LATEST" ]; then
  echo "No transcript (*.jsonl) in $PROJ_DIR" >&2
  exit 1
fi

BYTES=$(wc -c < "$LATEST" | tr -d ' ')
TOKENS=$(( BYTES / 8 + 50000 ))  # +50K system overhead
WINDOW=1000000
PCT=$(( TOKENS * 100 / WINDOW ))
[ $PCT -gt 100 ] && PCT=100

W=30
F=$(( PCT * W / 100 )); [ $F -gt $W ] && F=$W; E=$(( W - F ))
BAR=""
i=0; while [ $i -lt $F ]; do BAR="${BAR}█"; i=$((i + 1)); done
i=0; while [ $i -lt $E ]; do BAR="${BAR}░"; i=$((i + 1)); done

if [ $PCT -lt 50 ]; then C="\033[32m"
elif [ $PCT -lt 80 ]; then C="\033[33m"
else C="\033[31m"; fi
printf '%b[%s] %s%%\033[0m (~%sK/%sK tokens)\n' "$C" "$BAR" "$PCT" "$((TOKENS / 1000))" "$((WINDOW / 1000))"
