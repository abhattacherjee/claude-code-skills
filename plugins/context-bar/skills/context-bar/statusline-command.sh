#!/bin/bash
# Claude Code statusline - 3-line display with context bar
input=$(cat)

DIR=$(echo "$input" | jq -r '.workspace.current_dir // empty' | xargs basename 2>/dev/null)
MODEL=$(echo "$input" | jq -r '.model.display_name // empty')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0')

# Git branch + changes
BRANCH=""
CHANGES=""
if [ -d ".git" ] || git rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(git branch --show-current 2>/dev/null)
  CHG=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  [ "$CHG" -gt 0 ] && CHANGES=" ($CHG)"
fi

# Context bar (20 chars)
ctx_int=${PCT%.*}
ctx_int=${ctx_int:-0}
filled=$(( ctx_int * 20 / 100 ))
[ $filled -gt 20 ] && filled=20
empty=$(( 20 - filled ))
bar=""
[ $filled -gt 0 ] && bar=$(printf '█%.0s' $(seq 1 $filled))
[ $empty -gt 0 ] && bar+=$(printf '░%.0s' $(seq 1 $empty))

# Line 1: model + dir + branch
echo "[$MODEL] 📁 $DIR | 🌿 ${BRANCH}${CHANGES}"
# Line 2: context bar with color (green <50%, amber 50-79%, red 80%+)
if [ "$ctx_int" -lt 50 ]; then
  C="\033[32m"   # green
elif [ "$ctx_int" -lt 80 ]; then
  C="\033[33m"   # amber/yellow
else
  C="\033[31m"   # red
fi
R="\033[0m"
printf "ctx:[${C}${bar}${R}] ${C}${PCT}%%${R}\n"
