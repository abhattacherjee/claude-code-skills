#!/bin/bash
# Quick context usage bar — estimates from JSONL file size
# ~8 bytes per token heuristic (JSON overhead inflates raw char count)

PROJ_DIR="$HOME/.claude/projects/-Users-abhishek-dev-claude-workspace-tiny-vacation-agent"
LATEST=$(ls -t "$PROJ_DIR"/*.jsonl 2>/dev/null | head -1)

[ -z "$LATEST" ] && { echo "No conversation found"; exit 0; }

BYTES=$(wc -c < "$LATEST" | tr -d ' ')
TOKENS=$(( BYTES / 8 + 50000 ))  # +50K system overhead
WINDOW=1000000
PCT=$(( TOKENS * 100 / WINDOW ))
[ $PCT -gt 100 ] && PCT=100

W=30
F=$(( PCT * W / 100 )); [ $F -gt $W ] && F=$W; E=$(( W - F ))
BAR=""; [ $F -gt 0 ] && BAR=$(printf '█%.0s' $(seq 1 $F))
[ $E -gt 0 ] && BAR+=$(printf '░%.0s' $(seq 1 $E))

[ $PCT -lt 50 ] && C="\033[32m" || { [ $PCT -lt 75 ] && C="\033[33m" || C="\033[31m"; }
printf "${C}[${BAR}] ${PCT}%%\033[0m (~$((TOKENS/1000))K/$((WINDOW/1000))K tokens)\n"
