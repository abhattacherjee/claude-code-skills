# Statusline Item Recipes

Reusable jq snippets and bash fragments for common statusline items. Each recipe is a self-contained block that can be composed into a full statusline script.

## Safety helpers (put these first)

The statusline runs on every prompt, in whatever directory the session is in. Names come from the session JSON and from the repo, so treat them as untrusted:

```bash
# Drop control characters and backslashes, so a name cannot carry terminal escapes
# into echo -e / printf '%b'. Wrap every string field: MODEL=$(clean "$(... jq ...)").
# kept identical by tests/test_helper_parity.py
clean() { printf '%s' "$1" | tr -d '\000-\037\177\\'; }
# Digits only (at most 15), for anything that reaches $(( ... )): bash evaluates a
# variable's text as an expression there, so "a[$(cmd)]" would run cmd.
# kept identical by tests/test_helper_parity.py
num() { local v=${1%%.*}; v=${v//[!0-9]/}; v=${v:0:15}; printf '%s' "${v:-0}"; }
# git without the repo-config hooks (core.fsmonitor) that can run a program.
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
```

Keep values out of printf format strings: `printf '%s\n' "$LINE"`, not `printf "$LINE\n"`.

## Model Display

```bash
# Short: "Opus"
MODEL=$(clean "$(echo "$input" | jq -r '.model.display_name // empty')")
# Full: "claude-opus-4-6"
MODEL_ID=$(clean "$(echo "$input" | jq -r '.model.id // empty')")
# With 1M indicator
CTX_SIZE=$(num "$(echo "$input" | jq -r '.context_window.context_window_size // 200000')")
MODEL_TAG="$MODEL"
[ "$CTX_SIZE" -ge 1000000 ] && MODEL_TAG="${MODEL} (1M)"
```

## Context Bar (progress bar)

```bash
PCT=$(num "$(echo "$input" | jq -r '.context_window.used_percentage // 0')")
[ "$PCT" -gt 100 ] && PCT=100
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
# A float, so not num: jq turns anything that is not a number into 0 here.
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0 | if type == "number" then . else 0 end')
COST_FMT=$(printf '$%.2f' "$COST")
# With color (green <$1, yellow <$5, red $5+)
COST_CENTS=$(echo "$COST" | awk '{printf "%d", $1 * 100}')
if [ "$COST_CENTS" -lt 100 ]; then CC="\033[32m"
elif [ "$COST_CENTS" -lt 500 ]; then CC="\033[33m"
else CC="\033[31m"; fi
```

## Duration

```bash
DURATION_MS=$(num "$(echo "$input" | jq -r '.cost.total_duration_ms // 0')")
MINS=$((DURATION_MS / 60000))
SECS=$(((DURATION_MS % 60000) / 1000))
DURATION_FMT="${MINS}m ${SECS}s"
# API time only (excludes user think time)
API_MS=$(num "$(echo "$input" | jq -r '.cost.total_api_duration_ms // 0')")
API_MINS=$((API_MS / 60000))
API_SECS=$(((API_MS % 60000) / 1000))
```

## Lines Changed

```bash
ADDED=$(num "$(echo "$input" | jq -r '.cost.total_lines_added // 0')")
REMOVED=$(num "$(echo "$input" | jq -r '.cost.total_lines_removed // 0')")
LINES="\033[32m+${ADDED}\033[0m \033[31m-${REMOVED}\033[0m"
```

## Git Branch + Status (with cache)

A private cache dir (not a shared temp file other users could pre-create), one file per working directory, never used through a symlink. The file holds its own timestamp, so no `stat` (whose flags differ between macOS and Linux) is needed. Uses `clean` and `_git` from the safety helpers.

```bash
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"
CACHE_MAX_AGE=5
NOW=$(date +%s)
CACHE_FILE=""
if [ ! -L "$CACHE_DIR" ] && mkdir -p "$CACHE_DIR" 2>/dev/null && [ ! -L "$CACHE_DIR" ] && chmod 700 "$CACHE_DIR"; then
  CACHE_FILE="$CACHE_DIR/v2-git-$(pwd -P | cksum | cut -d' ' -f1)"
  [ -L "$CACHE_FILE" ] && CACHE_FILE=""
fi
FRESH=0
if [ -n "$CACHE_FILE" ] && [ -f "$CACHE_FILE" ]; then
  # One value per line, so a '|' in a branch name cannot shift the fields.
  { read -r TS; read -r BRANCH; read -r STAGED; read -r MODIFIED; read -r AHEAD; read -r BEHIND; } < "$CACHE_FILE"
  # Fresh only if 0-5 s old: a timestamp from the future (clock set back) is not trusted.
  case "$TS" in ''|*[!0-9]*) ;; *) AGE=$(( NOW - TS )); [ "$AGE" -ge 0 ] && [ "$AGE" -le $CACHE_MAX_AGE ] && FRESH=1 ;; esac
fi
if [ "$FRESH" != 1 ]; then
  BRANCH=""; STAGED=""; MODIFIED=""; AHEAD=""; BEHIND=""
  if _git rev-parse --git-dir >/dev/null 2>&1; then
    BRANCH=$(clean "$(_git branch --show-current 2>/dev/null)")
    # Where git diff could run repo-controlled code, skip the counts (see unsafe_repo).
    if ! unsafe_repo; then
      STAGED=$(_git diff --cached --numstat --ignore-submodules=all --no-textconv --no-ext-diff 2>/dev/null | wc -l | tr -d ' ')
      MODIFIED=$(_git diff --numstat --ignore-submodules=all --no-textconv --no-ext-diff 2>/dev/null | wc -l | tr -d ' ')
    fi
    AHEAD=$(_git rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)
    BEHIND=$(_git rev-list --count 'HEAD..@{upstream}' 2>/dev/null || echo 0)
  fi
  if [ -n "$CACHE_FILE" ] && TMP=$(mktemp "$CACHE_DIR/.git.XXXXXX" 2>/dev/null); then
    printf '%s\n' "$NOW" "$BRANCH" "$STAGED" "$MODIFIED" "$AHEAD" "$BEHIND" > "$TMP" &&
      mv -f "$TMP" "$CACHE_FILE" || rm -f "$TMP"
  fi
fi
```

## Git Sync Indicator

```bash
# Requires BRANCH/AHEAD/BEHIND from the git recipe above; outside a repo it shows nothing
SYNC=""
if [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ] && [ "$BEHIND" -gt 0 ]; then
  SYNC="\033[31m↑${AHEAD}↓${BEHIND}\033[0m"
elif [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ]; then
  SYNC="\033[32m↑${AHEAD}\033[0m"
elif [ -n "$BEHIND" ] && [ "$BEHIND" -gt 0 ]; then
  SYNC="\033[31m↓${BEHIND}\033[0m"
elif [ -n "$BRANCH" ]; then
  SYNC="\033[2m✓\033[0m"
fi
```

## Directory (short)

```bash
DIR=$(clean "$(echo "$input" | jq -r '.workspace.current_dir // empty')")
DIR_SHORT="${DIR##*/}"  # basename only (DIR is already clean)
```

## Worktree Indicator

```bash
WORKTREE=""
WT_NAME=$(clean "$(echo "$input" | jq -r '.worktree.name // empty')")
if [ -n "$WT_NAME" ]; then
  WORKTREE=" \033[35m⎇ ${WT_NAME}\033[0m"
fi
```

## Vim Mode

```bash
VIM_MODE=$(clean "$(echo "$input" | jq -r '.vim.mode // empty')")
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
AGENT=$(clean "$(echo "$input" | jq -r '.agent.name // empty')")
AGENT_INDICATOR=""
if [ -n "$AGENT" ]; then
  AGENT_INDICATOR=" \033[36m🤖 ${AGENT}\033[0m"
fi
```

## Output Style

```bash
STYLE=$(clean "$(echo "$input" | jq -r '.output_style.name // "default"')")
```

## Session ID (short)

```bash
SID=$(clean "$(echo "$input" | jq -r '.session_id // ""')" | cut -c1-8)
```

## Token Counts (detailed)

```bash
IN_TOKENS=$(num "$(echo "$input" | jq -r '.context_window.current_usage.input_tokens // 0')")
OUT_TOKENS=$(num "$(echo "$input" | jq -r '.context_window.current_usage.output_tokens // 0')")
CACHE_CREATE=$(num "$(echo "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')")
CACHE_READ=$(num "$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')")
# Format as K (floored), as the generator does
IN_K=$(echo "$input" | jq -r '(.context_window.current_usage.input_tokens // 0) / 1000 | floor | tostring + "K"')
OUT_K=$(echo "$input" | jq -r '(.context_window.current_usage.output_tokens // 0) / 1000 | floor | tostring + "K"')
```

## 200K Warning

```bash
EXCEEDS=$(echo "$input" | jq -r '.exceeds_200k_tokens // false')
WARN=""
[ "$EXCEEDS" = "true" ] && WARN=" \033[31m⚠ >200K\033[0m"
```

## Clickable Repo Link (OSC 8)

Only http(s) remotes become links; anything else prints as plain text. Uses `clean` and `_git` from the safety helpers.

```bash
REMOTE=$(clean "$(_git remote get-url origin 2>/dev/null | sed 's/git@github.com:/https:\/\/github.com\//' | sed 's/\.git$//' |
  sed -E 's#^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@#\1#')")  # drop user:token@ so no secret is shown
if [ -n "$REMOTE" ]; then
  REPO_NAME=$(basename "$REMOTE")
  case "$REMOTE" in
    # OSC 8 link — clickable in iTerm2, Kitty, WezTerm
    http://*|https://*) printf '\033]8;;%s\a%s\033]8;;\a' "$REMOTE" "$REPO_NAME" ;;
    *) printf '%s' "$REPO_NAME" ;;
  esac
fi
```
