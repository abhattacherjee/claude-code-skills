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

# Display model name as-is from Claude Code
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

# Detect terminal width robustly
# Priority: tmux (most accurate when attached) > parent TTY > /dev/tty > fallback
COLS="${COLUMNS:-0}"

if [ "$COLS" -eq 0 ] 2>/dev/null && [ -n "$TMUX" ]; then
  # Inside tmux: get the actual pane/window width (adapts to current client)
  COLS=$(tmux display-message -p '#{window_width}' 2>/dev/null || echo 0)
fi

if [ "$COLS" -eq 0 ] 2>/dev/null; then
  # Try parent process's TTY (works in Claude Code outside tmux)
  PARENT_TTY=$(ps -o tty= -p $PPID 2>/dev/null | tr -d ' ')
  if [ -n "$PARENT_TTY" ] && [ "$PARENT_TTY" != "??" ] && [ -e "/dev/$PARENT_TTY" ]; then
    COLS=$(stty size < "/dev/$PARENT_TTY" 2>/dev/null | awk '{print $2}')
  fi
fi

if [ "$COLS" -eq 0 ] 2>/dev/null; then
  # Fallback: try /dev/tty directly (works in direct SSH)
  (exec </dev/tty) 2>/dev/null && COLS=$(tput cols </dev/tty 2>/dev/null || echo 0)
fi

# Final fallback: assume narrow (safe for mobile SSH)
COLS="${COLS:-40}"
[ "$COLS" -eq 0 ] 2>/dev/null && COLS=40

if [ "$COLS" -lt 40 ]; then
  # ── ULTRA-NARROW (iPhone portrait ~30-39 cols) ──────────────
  bar=$(build_bar 8)
  printf "${C}${bar}${R} ${C}${BOLD}${ctx_int}%%${R} ${GIT_INFO}\n"

elif [ "$COLS" -lt 60 ]; then
  # ── NARROW (iPhone landscape / small tablet ~40-59 cols) ────
  printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}\n"
  bar=$(build_bar 10)
  printf "${GIT_INFO_ICON} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"

else
  # ── 60+ cols: auto-detect single vs two lines ───────────────
  # Measure visible width: count chars of each plain-text segment
  # MODEL " | " 📁(2) " " DIR " | " 🌿(2) " " BRANCH "(" detail ")" " | " 🧠(2) " " bar " " PCT "%"
  # detail = CHANGES + "|" + SYNC (worst case ~8 chars: "~99|+99")
  min_bar=8
  detail_len=6
  fixed_len=$(( ${#DISPLAY_MODEL} + 3 + 2 + 1 + ${#DIR} + 3 + 2 + 1 + ${#BRANCH} + 1 + detail_len + 1 + 3 + 2 + 1 + min_bar + 1 + ${#PCT} + 1 ))

  if [ "$COLS" -ge "$fixed_len" ]; then
    # Single line — use remaining space for the bar
    bar_width=$(( COLS - fixed_len + min_bar ))
    [ $bar_width -gt 25 ] && bar_width=25
    [ $bar_width -lt 8 ] && bar_width=8
    bar=$(build_bar $bar_width)
    printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R} ${DIM}|${R} ${GIT_INFO_ICON} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"
  else
    # Two lines
    printf "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}\n"
    bar=$(build_bar 15)
    printf "${GIT_INFO_ICON} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%%${R}\n"
  fi
fi
