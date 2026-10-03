#!/bin/bash
# managed-by: statusline-plugin
# Claude Code statusline - 3-tier adaptive: ultra-narrow / narrow / wide
input=$(cat)
command -v jq >/dev/null 2>&1 || { printf 'statusline: jq not on PATH\n'; exit 0; }
printf '%s' "$input" | jq -e 'type == "object"' >/dev/null 2>&1 || { printf 'statusline: no session data\n'; exit 0; }

# Drop control characters and backslashes from anything the session or the repo controls,
# so a name cannot carry terminal escape sequences into the status bar.
# kept identical by tests/test_helper_parity.py
clean() { printf '%s' "$1" | tr -d '\000-\037\177\\'; }
# git without the repo-config hooks that can run a program on every prompt.
# --no-optional-locks: no index write, so no post-index-change hook; GIT_NO_LAZY_FETCH:
# no transport for missing objects (git 2.44+; unsafe_repo covers older git).
# GIT_ALLOW_PROTOCOL: no transport at all, on any git version; it overrides the repo's own
# protocol.<name>.allow, which beats -c protocol.allow=never (kept to state the intent).
# kept identical by tests/test_helper_parity.py
_git() { GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL=none git --no-pager -c core.fsmonitor=false -c core.untrackedCache=false -c protocol.allow=never --no-optional-locks "$@"; }
# 0 (true) when git status/diff could run code the repo controls, or the config lookup
# fails: a filter driver (filter.<name>.clean runs on status and diff) in any scope other
# than global or system (local, worktree, command, and files they include), or a partial
# clone (diff would lazy-fetch missing blobs through the remote's transport).
# kept identical by tests/test_helper_parity.py
unsafe_repo() {
  local out rc=0
  out=$(_git config --includes --show-scope --get-regexp '^filter\.' 2>/dev/null) || rc=$?
  [ "$rc" -gt 1 ] && return 0          # the config lookup failed: fail closed
  [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qvE '^(global|system)[[:space:]]' && return 0
  rc=0
  _git config --get-regexp '^(extensions\.partialclone|remote\..*\.promisor)$' >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 1 ]                      # 0 = partial clone, >1 = lookup failed; 1 = neither
}

DIR=$(echo "$input" | jq -r '.workspace.current_dir // empty')
DIR="${DIR%/}"; DIR=$(clean "${DIR##*/}")
MODEL=$(clean "$(echo "$input" | jq -r '.model.display_name // empty')")
PCT=$(clean "$(echo "$input" | jq -r '.context_window.used_percentage // 0')")

# Colors (real escape bytes; every printf below uses a constant format)
R=$'\033[0m'
CYAN=$'\033[36m'
MAGENTA=$'\033[35m'
YELLOW=$'\033[33m'
GREEN=$'\033[32m'
RED=$'\033[31m'
BOLD=$'\033[1m'
DIM=$'\033[2m'

# Git branch + changes + upstream sync
BRANCH=""
CHANGES=""
SYNC=""
if [ -d ".git" ] || _git rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(clean "$(_git branch --show-current 2>/dev/null)")
  # Where git status could run repo-controlled code (see unsafe_repo), skip the change
  # count. A global filter (git-lfs) is the user's own, so counts stay there.
  if ! unsafe_repo; then
    CHG=$(_git status --porcelain --ignore-submodules=all 2>/dev/null | wc -l | tr -d ' ')
    [ "$CHG" -gt 0 ] && CHANGES="${YELLOW}~${CHG}${R}"
  fi
  UPSTREAM=$(_git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)
  if [ -n "$UPSTREAM" ]; then
    AHEAD=$(_git rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)
    BEHIND=$(_git rev-list --count 'HEAD..@{upstream}' 2>/dev/null || echo 0)
    if [ "$AHEAD" -gt 0 ] && [ "$BEHIND" -gt 0 ]; then
      SYNC="${RED}⇡${AHEAD}⇣${BEHIND}${R}"
    elif [ "$AHEAD" -gt 0 ]; then
      SYNC="${GREEN}⇡${AHEAD}${R}"
    elif [ "$BEHIND" -gt 0 ]; then
      SYNC="${YELLOW}⇣${BEHIND}${R}"
    else
      SYNC="${CYAN}⇡⇣${R}"
    fi
  else
    SYNC="${DIM}?${R}"
  fi
fi

# Build compact git info: branch(changes|sync)
# e.g. "develop(⇡⇣)" or "feat/foo(~2|⇡1)"
# $1 = max chars for branch name (0 = no limit)
build_git_info() {
  local max_branch="${1:-0}"
  if [ -n "$BRANCH" ]; then
    local display_branch="$BRANCH"
    if [ "$max_branch" -gt 0 ] && [ ${#BRANCH} -gt "$max_branch" ]; then
      display_branch="${BRANCH:0:$((max_branch-2))}.."
    fi
    local gd=""
    [ -n "$CHANGES" ] && gd="${CHANGES}"
    if [ -n "$SYNC" ]; then
      [ -n "$gd" ] && gd="${gd}${DIM}|${R}"
      gd="${gd}${SYNC}"
    fi
    echo "${GREEN}${display_branch}${R}${DIM}(${R}${gd}${DIM})${R}"
  fi
}

if [ -n "$BRANCH" ]; then
  GIT_INFO=$(build_git_info 0)
  GIT_INFO_ICON="🌿 ${GIT_INFO}"
fi

# Context color
ctx_int=${PCT%.*}
ctx_int=${ctx_int//[!0-9]/}   # digits only, 0-100: it reaches shell arithmetic
ctx_int=${ctx_int:-0}
[ ${#ctx_int} -gt 3 ] && ctx_int=100
[ "$ctx_int" -gt 100 ] && ctx_int=100
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

# Helper: check if branch + context bar fit on one line
# Args: $1=overhead (icons, separators, pct), $2=bar_width
# Returns 0 if branch fits alongside bar, 1 if needs separate lines
branch_fits_with_bar() {
  local overhead=$1 bar_w=$2
  local avail=$(( COLS - overhead - bar_w ))
  # Need at least 12 chars AND must show at least 2/3 of the branch name
  local min_to_show=$(( ${#BRANCH} * 2 / 3 ))
  [ "$min_to_show" -lt 12 ] && min_to_show=12
  [ "$avail" -ge "$min_to_show" ]
}

if [ "$COLS" -lt 40 ]; then
  # ── ULTRA-NARROW (iPhone portrait ~30-39 cols) ──────────────
  # Always 3 lines: model, branch, context bar
  printf '%s\n' "${BOLD}${MAGENTA}$(trunc "$DISPLAY_MODEL" $((COLS-2)))${R}"
  max_b=$(( COLS - 3 ))  # "🌿 " prefix
  [ $max_b -lt 6 ] && max_b=6
  git_trunc=$(build_git_info $max_b)
  printf '%s\n' "🌿 ${git_trunc}"
  bar=$(build_bar 8)
  printf '%s\n' "🧠 ${C}${bar}${R} ${C}${BOLD}${ctx_int}%${R}"

elif [ "$COLS" -lt 60 ]; then
  # ── NARROW (iPhone landscape / small tablet ~40-59 cols) ────
  # Line 1: model | dir (always)
  printf '%s\n' "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}"
  # Check if branch + bar fit on one line
  # overhead: "🌿 "(3) + "(detail)"(~8) + " | "(3) + "🧠 "(3) + " PCT%"(~5) = ~22
  if branch_fits_with_bar 22 10; then
    # 2 lines total: branch + bar together
    max_b=$(( COLS - 22 - 10 ))
    [ $max_b -lt 8 ] && max_b=8
    git_trunc=$(build_git_info $max_b)
    bar=$(build_bar 10)
    printf '%s\n' "🌿 ${git_trunc} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%${R}"
  else
    # 3 lines: branch alone, then bar alone
    max_b=$(( COLS - 3 ))
    [ $max_b -lt 8 ] && max_b=8
    git_trunc=$(build_git_info $max_b)
    printf '%s\n' "🌿 ${git_trunc}"
    bar_w=$(( COLS - 8 ))  # "🧠 "(3) + " PCT%"(~5)
    [ $bar_w -gt 20 ] && bar_w=20
    [ $bar_w -lt 8 ] && bar_w=8
    bar=$(build_bar $bar_w)
    printf '%s\n' "🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%${R}"
  fi

else
  # ── 60+ cols: auto-detect 1, 2, or 3 lines ─────────────────
  min_bar=8
  detail_len=6
  # Check if everything fits on 1 line
  fixed_len=$(( ${#DISPLAY_MODEL} + 3 + 2 + 1 + ${#DIR} + 3 + 2 + 1 + ${#BRANCH} + 1 + detail_len + 1 + 3 + 2 + 1 + min_bar + 1 + ${#PCT} + 1 ))

  if [ "$COLS" -ge "$fixed_len" ]; then
    # Single line
    bar_width=$(( COLS - fixed_len + min_bar ))
    [ $bar_width -gt 25 ] && bar_width=25
    [ $bar_width -lt 8 ] && bar_width=8
    bar=$(build_bar $bar_width)
    printf '%s\n' "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R} ${DIM}|${R} ${GIT_INFO_ICON} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%${R}"
  else
    # 2-line attempt: line1=model|dir, line2=branch+bar
    # overhead for line2: "🌿 "(3) + "(detail)"(~8) + " | "(3) + "🧠 "(3) + " PCT%"(~5) = ~22
    pct_len=${#PCT}
    line2_overhead=$(( 3 + 1 + detail_len + 1 + 3 + 3 + 1 + pct_len + 1 ))
    line2_bar=15
    line2_branch_budget=$(( COLS - line2_overhead - line2_bar ))

    if [ "$line2_branch_budget" -ge 12 ]; then
      # 2 lines: branch fits with bar
      git_trunc=$(build_git_info $line2_branch_budget)
      printf '%s\n' "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}"
      bar=$(build_bar $line2_bar)
      printf '%s\n' "🌿 ${git_trunc} ${DIM}|${R} 🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%${R}"
    else
      # 3 lines: branch and bar each get their own line
      printf '%s\n' "${BOLD}${MAGENTA}${DISPLAY_MODEL}${R} ${DIM}|${R} 📁 ${CYAN}${DIR}${R}"
      max_b=$(( COLS - 3 ))
      [ $max_b -lt 10 ] && max_b=10
      git_trunc=$(build_git_info $max_b)
      printf '%s\n' "🌿 ${git_trunc}"
      bar_w=$(( COLS - 8 ))
      [ $bar_w -gt 25 ] && bar_w=25
      [ $bar_w -lt 8 ] && bar_w=8
      bar=$(build_bar $bar_w)
      printf '%s\n' "🧠 ${C}${bar}${R} ${C}${BOLD}${PCT}%${R}"
    fi
  fi
fi
