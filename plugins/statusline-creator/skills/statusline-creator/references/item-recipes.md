# Statusline Item Recipes

Reusable jq snippets and bash fragments for common statusline items. Each recipe is a self-contained block that can be composed into a full statusline script.

## Model Display

```bash
# Short: "Opus"
MODEL=$(echo "$input" | jq -r '.model.display_name')
# Full: "claude-opus-4-6"
MODEL_ID=$(echo "$input" | jq -r '.model.id')
# With 1M indicator
CTX_SIZE=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
MODEL_TAG="$MODEL"
[ "$CTX_SIZE" -ge 1000000 ] && MODEL_TAG="${MODEL} (1M)"
```

## Context Bar (progress bar)

```bash
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
BAR_WIDTH=20
filled=$(( PCT * BAR_WIDTH / 100 ))
[ $filled -gt $BAR_WIDTH ] && filled=$BAR_WIDTH
empty=$(( BAR_WIDTH - filled ))
bar=""
[ $filled -gt 0 ] && bar=$(printf '█%.0s' $(seq 1 $filled))
[ $empty -gt 0 ] && bar+=$(printf '░%.0s' $(seq 1 $empty))

# Color by threshold
if [ "$PCT" -lt 50 ]; then C="\033[32m"    # green
elif [ "$PCT" -lt 80 ]; then C="\033[33m"  # yellow
else C="\033[31m"; fi                       # red
R="\033[0m"
```

## Cost Tracking

```bash
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
COST_FMT=$(printf '$%.2f' "$COST")
# With color (green <$1, yellow <$5, red $5+)
COST_CENTS=$(echo "$COST" | awk '{printf "%d", $1 * 100}')
if [ "$COST_CENTS" -lt 100 ]; then CC="\033[32m"
elif [ "$COST_CENTS" -lt 500 ]; then CC="\033[33m"
else CC="\033[31m"; fi
```

## Duration

```bash
DURATION_MS=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
MINS=$((DURATION_MS / 60000))
SECS=$(((DURATION_MS % 60000) / 1000))
DURATION_FMT="${MINS}m ${SECS}s"
# API time only (excludes user think time)
API_MS=$(echo "$input" | jq -r '.cost.total_api_duration_ms // 0')
API_MINS=$((API_MS / 60000))
API_SECS=$(((API_MS % 60000) / 1000))
```

## Lines Changed

```bash
ADDED=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
REMOVED=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
LINES="\033[32m+${ADDED}\033[0m \033[31m-${REMOVED}\033[0m"
```

## Git Branch + Status (with cache)

```bash
CACHE_FILE="/tmp/statusline-git-cache"
CACHE_MAX_AGE=5
cache_stale() {
  [ ! -f "$CACHE_FILE" ] || \
  [ $(($(date +%s) - $(stat -f %m "$CACHE_FILE" 2>/dev/null || stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0))) -gt $CACHE_MAX_AGE ]
}
if cache_stale; then
  if git rev-parse --git-dir >/dev/null 2>&1; then
    BRANCH=$(git branch --show-current 2>/dev/null)
    STAGED=$(git diff --cached --numstat 2>/dev/null | wc -l | tr -d ' ')
    MODIFIED=$(git diff --numstat 2>/dev/null | wc -l | tr -d ' ')
    AHEAD=$(git rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)
    BEHIND=$(git rev-list --count 'HEAD..@{upstream}' 2>/dev/null || echo 0)
    echo "$BRANCH|$STAGED|$MODIFIED|$AHEAD|$BEHIND" > "$CACHE_FILE"
  else
    echo "||||" > "$CACHE_FILE"
  fi
fi
IFS='|' read -r BRANCH STAGED MODIFIED AHEAD BEHIND < "$CACHE_FILE"
```

## Git Sync Indicator

```bash
# Requires AHEAD/BEHIND from git recipe above
SYNC=""
if [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ] && [ "$BEHIND" -gt 0 ]; then
  SYNC="\033[31m↑${AHEAD}↓${BEHIND}\033[0m"
elif [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ]; then
  SYNC="\033[32m↑${AHEAD}\033[0m"
elif [ -n "$BEHIND" ] && [ "$BEHIND" -gt 0 ]; then
  SYNC="\033[31m↓${BEHIND}\033[0m"
else
  SYNC="\033[2m✓\033[0m"
fi
```

## Directory (short)

```bash
DIR=$(echo "$input" | jq -r '.workspace.current_dir // empty')
DIR_SHORT="${DIR##*/}"  # basename only
```

## Worktree Indicator

```bash
WORKTREE=""
WT_NAME=$(echo "$input" | jq -r '.worktree.name // empty')
if [ -n "$WT_NAME" ]; then
  WORKTREE=" \033[35m⎇ ${WT_NAME}\033[0m"
fi
```

## Vim Mode

```bash
VIM_MODE=$(echo "$input" | jq -r '.vim.mode // empty')
VIM_INDICATOR=""
if [ -n "$VIM_MODE" ]; then
  if [ "$VIM_MODE" = "NORMAL" ]; then
    VIM_INDICATOR="\033[34m[N]\033[0m"
  else
    VIM_INDICATOR="\033[32m[I]\033[0m"
  fi
fi
```

## Agent Name

```bash
AGENT=$(echo "$input" | jq -r '.agent.name // empty')
AGENT_INDICATOR=""
if [ -n "$AGENT" ]; then
  AGENT_INDICATOR=" \033[36m🤖 ${AGENT}\033[0m"
fi
```

## Output Style

```bash
STYLE=$(echo "$input" | jq -r '.output_style.name // "default"')
```

## Session ID (short)

```bash
SID=$(echo "$input" | jq -r '.session_id // ""' | cut -c1-8)
```

## Token Counts (detailed)

```bash
IN_TOKENS=$(echo "$input" | jq -r '.context_window.current_usage.input_tokens // 0')
OUT_TOKENS=$(echo "$input" | jq -r '.context_window.current_usage.output_tokens // 0')
CACHE_CREATE=$(echo "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')
CACHE_READ=$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
# Format as K
IN_K=$(echo "$IN_TOKENS" | awk '{printf "%.0fK", $1/1000}')
OUT_K=$(echo "$OUT_TOKENS" | awk '{printf "%.0fK", $1/1000}')
```

## 200K Warning

```bash
EXCEEDS=$(echo "$input" | jq -r '.exceeds_200k_tokens // false')
WARN=""
[ "$EXCEEDS" = "true" ] && WARN=" \033[31m⚠ >200K\033[0m"
```

## Clickable Repo Link (OSC 8)

```bash
REMOTE=$(git remote get-url origin 2>/dev/null | sed 's/git@github.com:/https:\/\/github.com\//' | sed 's/\.git$//')
if [ -n "$REMOTE" ]; then
  REPO_NAME=$(basename "$REMOTE")
  # OSC 8 link — clickable in iTerm2, Kitty, WezTerm
  printf '%b' "\033]8;;${REMOTE}\a${REPO_NAME}\033]8;;\a"
fi
```
