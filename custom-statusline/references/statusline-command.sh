#!/bin/bash
# Claude Code statusline - 3-tier adaptive: ultra-narrow / narrow / wide
input=$(cat)

DIR=$(echo "$input" | jq -r '.workspace.current_dir // empty' | xargs basename 2>/dev/null)
MODEL=$(echo "$input" | jq -r '.model.display_name // empty')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0')

# Colors
R="\033[0m"
CYAN="\033[36m"
MAGENTA="\033[35m"
YELLOW="\033[33m"
GREEN="\033[32m"
RED="\033[31m"
BOLD="\033[1m"
DIM="\033[2m"

# Git branch + changes + upstream sync
BRANCH=""
CHANGES=""
SYNC=""
if [ -d ".git" ] || git rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(git branch --show-current 2>/dev/null)
  CHG=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  [ "$CHG" -gt 0 ] && CHANGES="${YELLOW}~${CHG}${R}"
  UPSTREAM=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)
  if [ -n "$UPSTREAM" ]; then
    AHEAD=$(git rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)
    BEHIND=$(git rev-list --count 'HEAD..@{upstream}' 2>/dev/null || echo 0)
    if [ "$AHEAD" -gt 0 ] && [ "$BEHIND" -gt 0 ]; then
      SYNC="${RED}+${AHEAD}-${BEHIND}${R}"
    elif [ "$AHEAD" -gt 0 ]; then
      SYNC="${GREEN}+${AHEAD}${R}"
    elif [ "$BEHIND" -gt 0 ]; then
      SYNC="${RED}-${BEHIND}${R}"
    else
      SYNC="${DIM}ok${R}"
    fi
  else
    SYNC="${DIM}local${R}"
  fi
fi

# Build compact git info: branch(changes|sync)
# e.g. "develop(ok)" or "feat/foo(~2|+1)"
if [ -n "$BRANCH" ]; then
  GIT_DETAIL=""
  [ -n "$CHANGES" ] && GIT_DETAIL="${CHANGES}"
  if [ -n "$SYNC" ]; then
    [ -n "$GIT_DETAIL" ] && GIT_DETAIL="${GIT_DETAIL}${DIM}|${R}"
    GIT_DETAIL="${GIT_DETAIL}${SYNC}"
  fi
  GIT_INFO="${GREEN}${BRANCH}${R}${DIM}(${R}${GIT_DETAIL}${DIM})${R}"
  GIT_INFO_ICON="🌿 ${GIT_INFO}"
fi

# Context color
ctx_int=${PCT%.*}
ctx_int=${ctx_int:-0}
if [ "$ctx_int" -lt 50 ]; then
  C="${GREEN}"
elif [ "$ctx_int" -lt 80 ]; then
  C="${YELLOW}"
else
  C="${RED}"
fi

# Display model name (full name as-is from Claude Code)
DISPLAY_MODEL="$MODEL"

# Build progress bar helper: build_bar <width>
# Uses ● for filled and ○ for empty
build_bar() {
  local w=$1
  local filled=$(( ctx_int * w / 100 ))
  [ $filled -gt $w ] && filled=$w
  local empty=$(( w - filled ))
  local bar=""
  for (( i=0; i<filled; i++ )); do bar+="●"; done
  for (( i=0; i<empty; i++ )); do bar+="○"; done
  echo "$bar"
}

# Truncate string to N chars
trunc() {
  local str="$1" max="$2"
  if [ ${#str} -gt $max ]; then
    echo "${str:0:$((max-1))}.."
  else
    echo "$str"
  fi
}

# Detect terminal width robustly (even in pipe/SSH contexts)
# $COLUMNS is only set in interactive shells, not in pipe context
# tput/stty fail when stdin is pipe; test if /dev/tty is openable first
HAS_TTY=false
(exec </dev/tty) 2>/dev/null && HAS_TTY=true

COLS="${COLUMNS:-0}"
if [ "$COLS" -eq 0 ] 2>/dev/null && $HAS_TTY; then
  COLS=$(tput cols </dev/tty 2>/dev/null || echo 0)
fi
if [ "$COLS" -eq 0 ] 2>/dev/null && $HAS_TTY; then
  COLS=$(stty size </dev/tty 2>/dev/null | awk '{print $2}')
fi
# Final fallback: assume narrow (safe default for mobile SSH)
COLS="${COLS:-40}"
[ "$COLS" -eq 0 ] 2>/dev/null && COLS=40

if [ "$COLS" -lt 40 ]; then
  # ── ULTRA-NARROW (iPhone portrait ~30-39 cols) ──────────────
  bar=$(build_bar 8)
  printf "${C}${bar}${R} ${C}${BOLD}${ctx_int}%%${R} ${GIT_INFO}\n"

elif [ "$COLS" -lt 60 ]; then
  # ── NARROW (iPhone landscape / small tablet ~40-59 cols) ────
  printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${GIT_INFO}\n"
  bar=$(build_bar 12)
  printf " 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"

elif [ "$COLS" -lt 100 ]; then
  # ── MEDIUM (iPhone SSH / small laptop ~60-99 cols) ──────────
  printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}\n"
  bar=$(build_bar 15)
  printf "${GIT_INFO_ICON} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"

else
  # ── WIDE (desktop / large iPad ~100+ cols) ──────────────────
  printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R} ${DIM}|${R} ${GIT_INFO_ICON}\n"
  bar=$(build_bar 25)
  printf " 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"
fi
