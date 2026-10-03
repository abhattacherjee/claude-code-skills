#!/usr/bin/env bash
# Generate a Claude Code statusline script from selected items
# Usage: generate-statusline.sh --items ITEMS [--output PATH] [--lines N] [--install] [--force]
#
# Exit codes: 0 written, 1 failed (a write failed, jq is missing, or settings.json cannot be
# read; a file that was not written is unchanged),
# 2 bad input (flags, items, or settings.json that is not one JSON object), 3 refused: the
# output file exists and was not written by this plugin (re-run with --force).
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../../lib/write-statusline.sh
. "$SCRIPT_DIR/../../../lib/write-statusline.sh"

usage() {
  cat <<'USAGE'
Generate a Claude Code statusline script from selected items.

Usage:
  generate-statusline.sh --items "model,context-bar,git,cost" [OPTIONS]

Options:
  --items ITEMS     Comma-separated list of items to include (see Available Items)
  --output PATH     Output script path (default: ~/.claude/statusline-command.sh, or
                    $CLAUDE_CONFIG_DIR/statusline-command.sh when that is set)
  --lines N         Number of statusline rows: 1, 2, or 3 (default: 2)
  --install         Also update settings.json (same directory) with statusLine config
  --force           Replace an output file this plugin did not write (backed up first)
  --list            List all available items with descriptions
  --help            Show this help

Available Items:
  model             Model display name (e.g., "Opus")
  model-full        Model with 1M context indicator
  dir               Working directory (basename)
  context-bar       Visual progress bar with color thresholds
  context-pct       Context percentage (number only)
  cost              Session cost in USD
  cost-color        Cost with color thresholds ($1/$5)
  duration          Session wall-clock time (Xm Ys)
  api-duration      API response time only
  lines-changed     Lines added/removed (+N -M)
  git               Branch + staged/modified counts (cached)
  git-sync          Upstream ahead/behind indicator
  git-link          Clickable repo link (OSC 8: iTerm2, Kitty, WezTerm)
  worktree          Worktree name indicator
  vim-mode          Vim mode indicator ([N]/[I])
  agent             Agent name indicator
  session-id        Short session ID (8 chars)
  tokens            Detailed token counts (input/output in K)
  warn-200k         Warning when exceeds 200K tokens
  style             Output style name

Examples:
  # Standard 2-line statusline
  generate-statusline.sh --items "model,dir,git,context-bar,cost,duration" --lines 2

  # Minimal 1-line
  generate-statusline.sh --items "model,context-pct,cost" --lines 1

  # Full 3-line with git link
  generate-statusline.sh --items "model-full,dir,git,git-sync,git-link,worktree,context-bar,cost-color,duration,lines-changed" --lines 3

  # Install directly
  generate-statusline.sh --items "model,dir,git,context-bar,cost" --install

Exit codes: 0 written, 1 failed, 2 bad input, 3 refused (use --force).
USAGE
}

list_items() {
  cat <<'LIST'
Available statusline items:

  DISPLAY
  ─────────────────────────────────────────────
  model           Model display name ("Opus")
  model-full      Model + 1M context indicator
  dir             Working directory basename
  session-id      Short session ID (8 chars)
  style           Output style name
  vim-mode        Vim mode ([N]/[I])
  agent           Agent name indicator
  worktree        Worktree name indicator

  CONTEXT
  ─────────────────────────────────────────────
  context-bar     Progress bar ████░░░░ with color
  context-pct     Percentage number only
  tokens          Detailed token counts (K)
  warn-200k       Warning when >200K tokens

  COST & TIME
  ─────────────────────────────────────────────
  cost            Session cost ($X.XX)
  cost-color      Cost with color thresholds
  duration        Wall-clock time (Xm Ys)
  api-duration    API response time only
  lines-changed   Lines +added -removed

  GIT
  ─────────────────────────────────────────────
  git             Branch + staged/modified (cached)
  git-sync        Upstream ahead/behind arrows
  git-link        Clickable OSC 8 repo link
LIST
  exit 0
}

bad_input() {
  echo "Error: $*" >&2
  echo "Run generate-statusline.sh --help for usage." >&2
  exit 2
}

# Defaults. Claude Code reads its settings from $CLAUDE_CONFIG_DIR when that is set.
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CFG="${CFG%/}"
ITEMS=""
DEFAULT_OUTPUT="$CFG/statusline-command.sh"
OUTPUT="$DEFAULT_OUTPUT"
LINES=2
INSTALL=false
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --items|--output|--lines)
      [ $# -ge 2 ] || bad_input "$1 needs a value"
      case "$1" in
        --items) ITEMS="$2" ;;
        --output) OUTPUT="$2" ;;
        --lines) LINES="$2" ;;
      esac
      shift 2 ;;
    --install) INSTALL=true; shift ;;
    --force) FORCE=1; shift ;;
    --list) list_items ;;
    --help|-h) usage; exit 0 ;;
    *) bad_input "unknown option: $1" ;;
  esac
done

[ -n "$ITEMS" ] || bad_input "--items is required. Use --list to see available items."
case "$LINES" in 1|2|3) ;; *) bad_input "--lines must be 1, 2 or 3 (got: $LINES)" ;; esac
[ -n "$OUTPUT" ] || bad_input "--output needs a value"
case "$OUTPUT" in /*) ;; *) OUTPUT="$PWD/$OUTPUT" ;; esac

# Parse items into array, dropping spaces ("model, dir" works)
ITEMS=$(printf '%s' "$ITEMS" | tr -d ' ')
IFS=',' read -ra ITEM_LIST <<< "$ITEMS"
[ "${#ITEM_LIST[@]}" -gt 0 ] || bad_input "--items lists no items"
for item in "${ITEM_LIST[@]}"; do
  case "$item" in
    model|model-full|dir|context-bar|context-pct|cost|cost-color|duration|api-duration|\
    lines-changed|git|git-sync|git-link|worktree|vim-mode|agent|session-id|tokens|\
    warn-200k|style) ;;
    *) bad_input "unknown item '$item'. Use --list to see available items." ;;
  esac
done

command -v python3 >/dev/null 2>&1 || {
  echo "Error: python3 is required to generate the statusline. Nothing was written." >&2
  exit 1
}

# The command settings.json runs. ~/.claude/statusline-command.sh keeps the literal ~ form;
# any other path is single-quoted when it holds characters the shell would split or expand.
if [ "$OUTPUT" = "$HOME/.claude/statusline-command.sh" ]; then
  COMMAND='bash ~/.claude/statusline-command.sh'
else
  COMMAND="bash $(sl_shell_quote "$OUTPUT")"
fi

# Check settings.json before writing anything, so a bad file never leaves a half install.
if $INSTALL; then
  SETTINGS="$CFG/settings.json"
  rc=0; check_settings "$SETTINGS" || rc=$?
  [ $rc -eq 0 ] || exit $rc
fi

# Build the script in a temp file; write_statusline moves it into place.
GEN=$(mktemp "${TMPDIR:-/tmp}/statusline-gen.XXXXXX")
trap 'rm -f "$GEN"' EXIT

# git and git-sync both read the git data block; it is emitted once, before any item.
needs_git_data=false
for item in "${ITEM_LIST[@]}"; do
  case "$item" in git|git-sync) needs_git_data=true ;; esac
done

# Generate script
cat > "$GEN" <<'HEADER'
#!/bin/bash
# managed-by: statusline-plugin
# Claude Code statusline — generated by the statusline plugin (/statusline:create)
input=$(cat)
command -v jq >/dev/null 2>&1 || { printf 'statusline: jq not on PATH\n'; exit 0; }
printf '%s' "$input" | jq -e 'type == "object"' >/dev/null 2>&1 || { printf 'statusline: no session data\n'; exit 0; }

# Drop control characters and backslashes from anything the session or the repo controls,
# so a name cannot carry terminal escape sequences into the status bar.
clean() { printf '%s' "$1" | tr -d '\000-\037\177\\'; }
# Digits only (at most 15, so arithmetic cannot overflow), for values that reach shell
# arithmetic.
num() { local v=${1%%.*}; v=${v//[!0-9]/}; v=${v:0:15}; printf '%s' "${v:-0}"; }
# git without the repo-config hooks that can run a program on every prompt.
_git() { git -c core.fsmonitor=false -c core.untrackedCache=false --no-optional-locks "$@"; }
# 0 (true) when the repo controls a filter driver, or git config fails: filter.<name>.clean
# runs on status and diff. Every filter.* key is read with includes, and any scope other
# than global or system (local, worktree, command, and files they include) counts.
repo_filter() {
  local out rc=0
  out=$(_git config --includes --show-scope --get-regexp '^filter\.' 2>/dev/null) || rc=$?
  [ "$rc" -eq 1 ] && return 1          # no filter.* key at all
  [ "$rc" -ne 0 ] && return 0          # the config lookup failed: fail closed
  printf '%s\n' "$out" | grep -qvE '^(global|system)[[:space:]]'
}

# ─── Colors ───
R="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
MAGENTA="\033[35m"
CYAN="\033[36m"

HEADER

if $needs_git_data; then
  cat >> "$GEN" <<'BLOCK'
# ─── Git data (cached 5s per working directory, in a private cache dir) ───
# The cache lives in ${XDG_CACHE_HOME:-~/.cache}/claude-statusline (mode 700), never in a
# shared temp dir, and a cache path that is a symlink is never read or written. One value
# per line, so a '|' in a branch name cannot shift the fields.
GIT_MAX_AGE=5
_now=$(date +%s)
_gc_dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"
GIT_CACHE=""
if [ ! -L "$_gc_dir" ] && mkdir -p "$_gc_dir" 2>/dev/null && [ ! -L "$_gc_dir" ] && chmod 700 "$_gc_dir" 2>/dev/null; then
  # "v2": one value per line. The older one-line "git-" files are never read.
  GIT_CACHE="$_gc_dir/v2-git-$(pwd -P | cksum | cut -d' ' -f1)"
  [ -L "$GIT_CACHE" ] && GIT_CACHE=""
fi
_fresh=0
if [ -n "$GIT_CACHE" ] && [ -f "$GIT_CACHE" ]; then
  { read -r _ts; read -r BRANCH; read -r STAGED; read -r MODIFIED; read -r GIT_AHEAD; read -r GIT_BEHIND; } < "$GIT_CACHE"
  # Fresh only if 0-5 s old: a timestamp from the future (clock set back) is not trusted.
  case "$_ts" in ''|*[!0-9]*) ;; *) _age=$(( _now - _ts )); [ "$_age" -ge 0 ] && [ "$_age" -le $GIT_MAX_AGE ] && _fresh=1 ;; esac
fi
if [ "$_fresh" != 1 ]; then
  BRANCH=""; STAGED=""; MODIFIED=""; GIT_AHEAD=""; GIT_BEHIND=""
  if _git rev-parse --git-dir >/dev/null 2>&1; then
    BRANCH=$(clean "$(_git branch --show-current 2>/dev/null)")
    # In a repo that controls a filter driver, skip the counts (git diff would run it).
    # A global filter (git-lfs) is the user's own, so counts stay there.
    if ! repo_filter; then
      STAGED=$(_git diff --cached --numstat 2>/dev/null | wc -l | tr -d ' ')
      MODIFIED=$(_git diff --numstat 2>/dev/null | wc -l | tr -d ' ')
    fi
    GIT_AHEAD=$(_git rev-list --count '@{upstream}..HEAD' 2>/dev/null || echo 0)
    GIT_BEHIND=$(_git rev-list --count 'HEAD..@{upstream}' 2>/dev/null || echo 0)
  fi
  if [ -n "$GIT_CACHE" ] && _tmp=$(mktemp "$_gc_dir/.git.XXXXXX" 2>/dev/null); then
    printf '%s\n' "$_now" "$BRANCH" "$STAGED" "$MODIFIED" "$GIT_AHEAD" "$GIT_BEHIND" > "$_tmp" &&
      mv -f "$_tmp" "$GIT_CACHE" 2>/dev/null || rm -f "$_tmp"
  fi
fi
BLOCK
fi

# Add extraction blocks based on items needed
for item in "${ITEM_LIST[@]}"; do
  case "$item" in
    model)
      cat >> "$GEN" <<'BLOCK'
# ─── Model ───
MODEL=$(clean "$(echo "$input" | jq -r '.model.display_name // empty')")
BLOCK
      ;;
    model-full)
      cat >> "$GEN" <<'BLOCK'
# ─── Model (with 1M indicator) ───
MODEL=$(clean "$(echo "$input" | jq -r '.model.display_name // empty')")
CTX_SIZE=$(num "$(echo "$input" | jq -r '.context_window.context_window_size // 200000')")
[ "$CTX_SIZE" -ge 1000000 ] && MODEL="${MODEL} (1M)"
BLOCK
      ;;
    dir)
      cat >> "$GEN" <<'BLOCK'
# ─── Directory ───
DIR=$(echo "$input" | jq -r '.workspace.current_dir // empty')
DIR_SHORT=$(clean "${DIR##*/}")
BLOCK
      ;;
    context-bar)
      cat >> "$GEN" <<'BLOCK'
# ─── Context Bar ───
PCT=$(num "$(echo "$input" | jq -r '.context_window.used_percentage // 0')")
[ "$PCT" -gt 100 ] && PCT=100
BAR_W=20; filled=$(( PCT * BAR_W / 100 ))
[ $filled -gt $BAR_W ] && filled=$BAR_W
empty=$(( BAR_W - filled ))
bar=""
[ $filled -gt 0 ] && bar=$(printf '█%.0s' $(seq 1 $filled))
[ $empty -gt 0 ] && bar+=$(printf '░%.0s' $(seq 1 $empty))
if [ "$PCT" -lt 50 ]; then CTX_C="$GREEN"
elif [ "$PCT" -lt 80 ]; then CTX_C="$YELLOW"
else CTX_C="$RED"; fi
BLOCK
      ;;
    context-pct)
      cat >> "$GEN" <<'BLOCK'
# ─── Context Percentage ───
PCT=$(num "$(echo "$input" | jq -r '.context_window.used_percentage // 0')")
BLOCK
      ;;
    cost)
      cat >> "$GEN" <<'BLOCK'
# ─── Cost ───
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
COST_FMT=$(printf '$%.2f' "$COST")
BLOCK
      ;;
    cost-color)
      cat >> "$GEN" <<'BLOCK'
# ─── Cost (color-coded) ───
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
COST_FMT=$(printf '$%.2f' "$COST")
COST_CENTS=$(echo "$COST" | awk '{printf "%d", $1 * 100}')
if [ "$COST_CENTS" -lt 100 ]; then COST_C="$GREEN"
elif [ "$COST_CENTS" -lt 500 ]; then COST_C="$YELLOW"
else COST_C="$RED"; fi
BLOCK
      ;;
    duration)
      cat >> "$GEN" <<'BLOCK'
# ─── Duration ───
DUR_MS=$(num "$(echo "$input" | jq -r '.cost.total_duration_ms // 0')")
DUR_M=$((DUR_MS / 60000)); DUR_S=$(((DUR_MS % 60000) / 1000))
BLOCK
      ;;
    api-duration)
      cat >> "$GEN" <<'BLOCK'
# ─── API Duration ───
API_MS=$(num "$(echo "$input" | jq -r '.cost.total_api_duration_ms // 0')")
API_M=$((API_MS / 60000)); API_S=$(((API_MS % 60000) / 1000))
BLOCK
      ;;
    lines-changed)
      cat >> "$GEN" <<'BLOCK'
# ─── Lines Changed ───
ADDED=$(num "$(echo "$input" | jq -r '.cost.total_lines_added // 0')")
REMOVED=$(num "$(echo "$input" | jq -r '.cost.total_lines_removed // 0')")
BLOCK
      ;;
    git)
      cat >> "$GEN" <<'BLOCK'
# ─── Git ───
GIT_CHANGES=""
[ -n "$STAGED" ] && [ "$STAGED" -gt 0 ] && GIT_CHANGES="${GREEN}+${STAGED}${R}"
[ -n "$MODIFIED" ] && [ "$MODIFIED" -gt 0 ] && GIT_CHANGES="${GIT_CHANGES}${YELLOW}~${MODIFIED}${R}"
BLOCK
      ;;
    git-sync)
      cat >> "$GEN" <<'BLOCK'
# ─── Git Sync ───
SYNC=""
if [ -n "${GIT_AHEAD:-}" ] && [ "${GIT_AHEAD:-0}" -gt 0 ] && [ "${GIT_BEHIND:-0}" -gt 0 ]; then
  SYNC="${RED}↑${GIT_AHEAD}↓${GIT_BEHIND}${R}"
elif [ -n "${GIT_AHEAD:-}" ] && [ "${GIT_AHEAD:-0}" -gt 0 ]; then
  SYNC="${GREEN}↑${GIT_AHEAD}${R}"
elif [ -n "${GIT_BEHIND:-}" ] && [ "${GIT_BEHIND:-0}" -gt 0 ]; then
  SYNC="${RED}↓${GIT_BEHIND}${R}"
elif [ -n "${BRANCH:-}" ]; then
  SYNC="${DIM}✓${R}"
fi
BLOCK
      ;;
    git-link)
      cat >> "$GEN" <<'BLOCK'
# ─── Git Link (OSC 8, http(s) remotes only) ───
REMOTE=$(clean "$(_git remote get-url origin 2>/dev/null | sed 's/git@github.com:/https:\/\/github.com\//' | sed 's/\.git$//')")
GIT_LINK=""
if [ -n "$REMOTE" ]; then
  REPO_NAME=$(basename "$REMOTE")
  case "$REMOTE" in
    http://*|https://*)
      GIT_LINK="$(printf '\033]8;;')${REMOTE}$(printf '\a')${REPO_NAME}$(printf '\033]8;;\a')" ;;
    *) GIT_LINK="$REPO_NAME" ;;
  esac
fi
BLOCK
      ;;
    worktree)
      cat >> "$GEN" <<'BLOCK'
# ─── Worktree ───
WT_NAME=$(clean "$(echo "$input" | jq -r '.worktree.name // empty')")
WORKTREE=""
[ -n "$WT_NAME" ] && WORKTREE=" ${MAGENTA}⎇ ${WT_NAME}${R}"
BLOCK
      ;;
    vim-mode)
      cat >> "$GEN" <<'BLOCK'
# ─── Vim Mode ───
VIM_MODE=$(clean "$(echo "$input" | jq -r '.vim.mode // empty')")
VIM=""
if [ -n "$VIM_MODE" ]; then
  [ "$VIM_MODE" = "NORMAL" ] && VIM="${BLUE}[N]${R}" || VIM="${GREEN}[I]${R}"
fi
BLOCK
      ;;
    agent)
      cat >> "$GEN" <<'BLOCK'
# ─── Agent ───
AGENT_NAME=$(clean "$(echo "$input" | jq -r '.agent.name // empty')")
AGENT=""
[ -n "$AGENT_NAME" ] && AGENT=" ${CYAN}🤖 ${AGENT_NAME}${R}"
BLOCK
      ;;
    session-id)
      cat >> "$GEN" <<'BLOCK'
# ─── Session ID ───
SID=$(clean "$(echo "$input" | jq -r '.session_id // ""')" | cut -c1-8)
BLOCK
      ;;
    tokens)
      cat >> "$GEN" <<'BLOCK'
# ─── Token Counts ───
IN_K=$(echo "$input" | jq -r '(.context_window.current_usage.input_tokens // 0) / 1000 | floor | tostring + "K"')
OUT_K=$(echo "$input" | jq -r '(.context_window.current_usage.output_tokens // 0) / 1000 | floor | tostring + "K"')
BLOCK
      ;;
    warn-200k)
      cat >> "$GEN" <<'BLOCK'
# ─── 200K Warning ───
EXCEEDS=$(echo "$input" | jq -r '.exceeds_200k_tokens // false')
WARN=""
[ "$EXCEEDS" = "true" ] && WARN=" ${RED}⚠ >200K${R}"
BLOCK
      ;;
    style)
      cat >> "$GEN" <<'BLOCK'
# ─── Output Style ───
STYLE=$(clean "$(echo "$input" | jq -r '.output_style.name // "default"')")
BLOCK
      ;;
  esac
done

# Add output section
echo "" >> "$GEN"
echo '# ─── Output ───' >> "$GEN"
python3 "$SCRIPT_DIR/generate-output.py" "$ITEMS" "$LINES" >> "$GEN"

rc=0; write_statusline "$GEN" "$OUTPUT" "$FORCE" || rc=$?
[ $rc -eq 0 ] || exit $rc

if $INSTALL; then
  rc=0; update_settings "$SETTINGS" "$COMMAND" || rc=$?
  if [ $rc -ne 0 ]; then
    echo "Result: statusline script written; settings.json unchanged. Fix the error above and re-run." >&2
    exit $rc
  fi
fi

echo ""
echo "Test with:"
echo "  echo '{\"model\":{\"display_name\":\"Opus\"},\"workspace\":{\"current_dir\":\"/tmp/test\"},\"context_window\":{\"used_percentage\":42,\"context_window_size\":200000},\"cost\":{\"total_cost_usd\":0.05,\"total_duration_ms\":120000,\"total_api_duration_ms\":5000,\"total_lines_added\":50,\"total_lines_removed\":10}}' | $COMMAND"
