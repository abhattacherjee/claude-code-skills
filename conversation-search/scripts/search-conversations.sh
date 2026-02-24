#!/usr/bin/env bash
# search-conversations.sh — Search Claude Code conversation history
# Scans ~/.claude/projects/*/sessions-index.json for indexed conversations and
# discovers orphan JSONL files (no index) by synthesizing metadata on the fly.
# Optionally deep-searches JSONL conversation content for keyword matches.
set -eu

CLAUDE_DIR="${HOME}/.claude"
PROJECTS_DIR="${CLAUDE_DIR}/projects"
DEFAULT_LIMIT=20
DEFAULT_MAX_MESSAGES=200

# Colors (disabled if not a terminal or NO_COLOR is set)
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD='\033[1m' DIM='\033[2m' GREEN='\033[0;32m'
  YELLOW='\033[0;33m' CYAN='\033[0;36m' MAGENTA='\033[0;35m' RESET='\033[0m'
else
  BOLD='' DIM='' GREEN='' YELLOW='' CYAN='' MAGENTA='' RESET=''
fi

usage() {
  cat <<'EOF'
Usage: search-conversations.sh <command> [options]

Commands:
  list                    List recent conversations (all projects)
  search                  Search conversations by criteria
  show <session-id>       Show conversation content
  stats                   Show conversation statistics

Search Options:
  --topic <keyword>       Search in firstPrompt + summary (case-insensitive)
  --after <date>          Created after date (YYYY-MM-DD or ISO 8601)
  --before <date>         Created before date (YYYY-MM-DD or ISO 8601)
  --branch <pattern>      Filter by git branch (substring match)
  --project <pattern>     Filter by project path (substring match)
  --deep                  Also search inside conversation JSONL content (slower)
  --limit <N>             Max results (default: 20)

Show Options:
  --max-messages <N>      Max messages to extract (default: 200)
  --messages-only         Only show user/assistant text (no metadata header)

Global Options:
  --json                  Output as JSON (for agent consumption)
  --no-color              Disable colored output
  -h, --help              Show this help

Examples:
  search-conversations.sh list
  search-conversations.sh list --limit 5 --project "tiny-vacation"
  search-conversations.sh search --topic "catalog" --after 2025-06-01
  search-conversations.sh search --topic "deploy" --deep --branch "main"
  search-conversations.sh show 0be99c26-dc3c-4d3d-a45a-c6ba07978586
  search-conversations.sh show 0be99c26 --max-messages 50 --json
  search-conversations.sh stats
EOF
  exit "${1:-0}"
}

# ── Helpers ──────────────────────────────────────────────────────────────────

# Normalize date to ISO 8601 prefix for lexicographic comparison
normalize_date() {
  local d="$1"
  # If just YYYY-MM-DD, append T00:00:00
  if [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "${d}T00:00:00"
  else
    echo "$d"
  fi
}

# Find all sessions-index.json files (returns empty if none found)
find_index_files() {
  for idx in "${PROJECTS_DIR}"/*/sessions-index.json; do
    [[ -f "$idx" ]] && echo "$idx"
  done
}

# Collect all indexed session IDs (for orphan detection)
collect_indexed_ids() {
  local index_files
  index_files=$(find_index_files)
  if [[ -z "$index_files" ]]; then
    return
  fi
  echo "$index_files" | while IFS= read -r idx; do
    jq -r '.entries[]?.sessionId // empty' "$idx" 2>/dev/null || true
  done | sort -u
}

# Synthesize a metadata entry from a JSONL file not tracked by any index
synthesize_entry() {
  local jsonl_file="$1"
  local sid
  sid=$(basename "$jsonl_file" .jsonl)

  # Read first 50 lines for metadata (fast even on large files)
  local head_lines
  head_lines=$(head -n 50 "$jsonl_file" 2>/dev/null)

  # Extract cwd as project path (most reliable source)
  local project_path
  project_path=$(echo "$head_lines" | jq -r 'select(.cwd != null) | .cwd' 2>/dev/null | head -n 1)
  [[ -z "$project_path" ]] && project_path="unknown"

  # Extract first user message as prompt
  local first_prompt
  first_prompt=$(echo "$head_lines" | jq -c 'select(.type == "user")' 2>/dev/null | head -n 1 | jq -r '
    if (.message.content | type) == "string" then .message.content
    elif (.message.content | type) == "array" then [.message.content[]? | select(.type == "text") | .text] | join(" ")
    else ""
    end
  ' 2>/dev/null | head -c 120)
  [[ -z "$first_prompt" ]] && first_prompt="(no prompt)"

  # Extract first timestamp and branch
  local first_ts branch
  first_ts=$(echo "$head_lines" | jq -r 'select(.timestamp != null) | .timestamp' 2>/dev/null | head -n 1)
  branch=$(echo "$head_lines" | jq -r 'select(.gitBranch != null and .gitBranch != "") | .gitBranch' 2>/dev/null | head -n 1)
  [[ -z "$branch" ]] && branch=""

  # Use file mtime for modified timestamp
  local file_mtime
  if [[ "$(uname)" == "Darwin" ]]; then
    file_mtime=$(stat -f '%Sm' -t '%Y-%m-%dT%H:%M:%S' "$jsonl_file" 2>/dev/null || echo "unknown")
  else
    file_mtime=$(date -r "$jsonl_file" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "unknown")
  fi

  # Approximate message count (fast line count of user/assistant entries)
  local msg_count
  msg_count=$(grep -c -E '"type"\s*:\s*"(user|assistant)"' "$jsonl_file" 2>/dev/null) || true
  # Ensure it's a valid integer
  [[ "$msg_count" =~ ^[0-9]+$ ]] || msg_count=0

  jq -n \
    --arg sid "$sid" \
    --arg path "$project_path" \
    --arg prompt "$first_prompt" \
    --arg branch "$branch" \
    --arg created "${first_ts:-unknown}" \
    --arg modified "$file_mtime" \
    --argjson msgs "$msg_count" \
    '{
      sessionId: $sid,
      projectPath: $path,
      firstPrompt: $prompt,
      summary: "(no index)",
      gitBranch: $branch,
      created: $created,
      modified: $modified,
      messageCount: $msgs,
      isOrphan: true
    }'
}

# Find JSONL files not tracked by any sessions-index.json
gather_orphan_entries() {
  local indexed_ids
  indexed_ids=$(collect_indexed_ids)

  for jsonl in "${PROJECTS_DIR}"/*/*.jsonl; do
    [[ -f "$jsonl" ]] || continue
    local sid
    sid=$(basename "$jsonl" .jsonl)

    # Skip if this session is tracked by an index
    if [[ -n "$indexed_ids" ]] && echo "$indexed_ids" | grep -qF "$sid"; then
      continue
    fi

    synthesize_entry "$jsonl"
  done
}

# Gather all entries from indexes + orphan JSONL files into a single JSON array
gather_entries() {
  {
    # Phase 1: Indexed entries
    local index_files
    index_files=$(find_index_files)
    if [[ -n "$index_files" ]]; then
      echo "$index_files" | while IFS= read -r idx; do
        jq -c '.entries[]?' "$idx" 2>/dev/null || true
      done
    fi

    # Phase 2: Orphan entries (JSONL files not in any index)
    gather_orphan_entries
  } | jq -s 'sort_by(.modified // .created) | reverse'
}

# Build jq filter from search criteria
build_filter() {
  local topic="${1:-}" after="${2:-}" before="${3:-}" branch="${4:-}" project="${5:-}"
  local filters=()

  if [[ -n "$topic" ]]; then
    # Use ascii_downcase + contains for case-insensitive literal substring match
    local lower_topic
    lower_topic=$(printf '%s' "$topic" | tr '[:upper:]' '[:lower:]' | sed 's/"/\\"/g')
    filters+=("((.firstPrompt // \"\" | ascii_downcase | contains(\"${lower_topic}\")) or (.summary // \"\" | ascii_downcase | contains(\"${lower_topic}\")))")
  fi

  if [[ -n "$after" ]]; then
    local norm_after
    norm_after=$(normalize_date "$after")
    filters+=("(.created // .modified // \"\" | . >= \"${norm_after}\")")
  fi

  if [[ -n "$before" ]]; then
    local norm_before
    norm_before=$(normalize_date "$before")
    filters+=("(.created // .modified // \"\" | . <= \"${norm_before}\")")
  fi

  if [[ -n "$branch" ]]; then
    local lower_branch
    lower_branch=$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | sed 's/"/\\"/g')
    filters+=("(.gitBranch // \"\" | ascii_downcase | contains(\"${lower_branch}\"))")
  fi

  if [[ -n "$project" ]]; then
    local lower_project
    lower_project=$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]' | sed 's/"/\\"/g')
    filters+=("(.projectPath // \"\" | ascii_downcase | contains(\"${lower_project}\"))")
  fi

  if [[ ${#filters[@]} -eq 0 ]]; then
    echo "."
  else
    local combined="${filters[0]}"
    local i
    for ((i=1; i<${#filters[@]}; i++)); do
      combined="${combined} and ${filters[i]}"
    done
    echo "[.[] | select(${combined})]"
  fi
}

# Deep search: grep through JSONL files for keyword, return matching session IDs
deep_search_sessions() {
  local topic="$1"
  local matching_ids=()

  for jsonl in "${PROJECTS_DIR}"/*/*.jsonl; do
    [[ -f "$jsonl" ]] || continue
    # Only grep in user/assistant message content, skip huge tool results
    if grep -q -i "$topic" "$jsonl" 2>/dev/null; then
      local sid
      sid=$(basename "$jsonl" .jsonl)
      matching_ids+=("$sid")
    fi
  done

  printf '%s\n' "${matching_ids[@]}"
}

# Find JSONL file for a session ID (supports prefix matching)
find_session_file() {
  local session_id="$1"
  local matches=()

  for jsonl in "${PROJECTS_DIR}"/*/*.jsonl; do
    [[ -f "$jsonl" ]] || continue
    local basename
    basename=$(basename "$jsonl" .jsonl)
    if [[ "$basename" == "$session_id" ]] || [[ "$basename" == "$session_id"* ]]; then
      matches+=("$jsonl")
    fi
  done

  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "No conversation found matching session ID: ${session_id}" >&2
    return 1
  elif [[ ${#matches[@]} -gt 1 ]]; then
    echo "Multiple matches for '${session_id}':" >&2
    printf '  %s\n' "${matches[@]}" >&2
    echo "Please provide a more specific session ID." >&2
    return 1
  fi

  echo "${matches[0]}"
}

# Look up session metadata from index or synthesize from JSONL
lookup_session_metadata() {
  local session_id="$1"

  # Try indexed entries first
  local result
  result=$(gather_entries | jq -c "[.[] | select(.sessionId | startswith(\"${session_id}\"))][0] // empty")

  if [[ -n "$result" ]]; then
    echo "$result"
    return
  fi

  # Fallback: synthesize from JSONL file directly
  local jsonl_file
  jsonl_file=$(find_session_file "$session_id" 2>/dev/null) || return
  synthesize_entry "$jsonl_file"
}

# ── Output Formatters ────────────────────────────────────────────────────────

format_entry_text() {
  local entry="$1"
  local sid first summary branch created modified msgs project

  sid=$(echo "$entry" | jq -r '.sessionId // "unknown"')
  first=$(echo "$entry" | jq -r '.firstPrompt // "(no prompt)"' | head -c 120)
  summary=$(echo "$entry" | jq -r '.summary // "(no summary)"' | head -c 200)
  branch=$(echo "$entry" | jq -r '.gitBranch // "unknown"')
  created=$(echo "$entry" | jq -r '.created // "unknown"' | head -c 19)
  modified=$(echo "$entry" | jq -r '.modified // "unknown"' | head -c 19)
  msgs=$(echo "$entry" | jq -r '.messageCount // 0')
  project=$(echo "$entry" | jq -r '.projectPath // "unknown"' | sed "s|${HOME}|~|")

  printf "${BOLD}${CYAN}%-36s${RESET}  ${DIM}%s${RESET}  ${YELLOW}%s msgs${RESET}\n" "$sid" "$created" "$msgs"
  printf "  ${GREEN}Branch:${RESET}  %s\n" "$branch"
  printf "  ${GREEN}Project:${RESET} %s\n" "$project"
  printf "  ${GREEN}Prompt:${RESET}  %s\n" "$first"
  if [[ "$summary" != "(no summary)" && "$summary" != "null" ]]; then
    printf "  ${GREEN}Summary:${RESET} %s\n" "$summary"
  fi
  echo ""
}

format_entries_text() {
  local entries="$1" limit="$2"
  local count
  count=$(echo "$entries" | jq 'length')

  if [[ "$count" -eq 0 ]]; then
    echo "No conversations found."
    return
  fi

  local shown=$((count < limit ? count : limit))
  printf "${BOLD}Found %d conversations (showing %d):${RESET}\n\n" "$count" "$shown"

  echo "$entries" | jq -c ".[0:${limit}][]" | while IFS= read -r entry; do
    format_entry_text "$entry"
  done
}

# Extract messages from a JSONL conversation file
extract_messages() {
  local jsonl_file="$1" max_messages="${2:-$DEFAULT_MAX_MESSAGES}" output_json="${3:-false}"

  if [[ "$output_json" == "true" ]]; then
    # JSON output: array of {role, timestamp, content} objects
    jq -c "select(.type == \"user\" or .type == \"assistant\")" "$jsonl_file" | \
    head -n "$max_messages" | \
    jq -s '[.[] | {
      role: .type,
      timestamp: .timestamp,
      content: (
        if (.message.content | type) == "string" then
          .message.content
        elif (.message.content | type) == "array" then
          [.message.content[]? | select(.type == "text") | .text] | join("\n")
        else
          ""
        end
      )
    } | select(.content != "")]'
  else
    # Text output: formatted conversation
    jq -c "select(.type == \"user\" or .type == \"assistant\")" "$jsonl_file" | \
    head -n "$max_messages" | \
    jq -r '
      "\n" +
      (if .type == "user" then "━━━ USER" else "━━━ ASSISTANT" end) +
      " [" + (.timestamp // "unknown" | .[0:19]) + "] ━━━\n" +
      (
        if (.message.content | type) == "string" then
          .message.content
        elif (.message.content | type) == "array" then
          [.message.content[]? | select(.type == "text") | .text] | join("\n")
        else
          ""
        end
      )
    '
  fi
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_list() {
  local limit="$DEFAULT_LIMIT" output_json=false topic="" after="" before="" branch="" project=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --json) output_json=true; shift ;;
      --topic) topic="$2"; shift 2 ;;
      --after) after="$2"; shift 2 ;;
      --before) before="$2"; shift 2 ;;
      --branch) branch="$2"; shift 2 ;;
      --project) project="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; usage 2 ;;
    esac
  done

  local entries
  entries=$(gather_entries)

  local filter
  filter=$(build_filter "$topic" "$after" "$before" "$branch" "$project")
  entries=$(echo "$entries" | jq "$filter")

  if [[ "$output_json" == "true" ]]; then
    echo "$entries" | jq ".[0:${limit}]"
  else
    format_entries_text "$entries" "$limit"
  fi
}

cmd_search() {
  local limit="$DEFAULT_LIMIT" output_json=false deep=false
  local topic="" after="" before="" branch="" project=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --topic) topic="$2"; shift 2 ;;
      --after) after="$2"; shift 2 ;;
      --before) before="$2"; shift 2 ;;
      --branch) branch="$2"; shift 2 ;;
      --project) project="$2"; shift 2 ;;
      --deep) deep=true; shift ;;
      --limit) limit="$2"; shift 2 ;;
      --json) output_json=true; shift ;;
      *) echo "Unknown option: $1" >&2; usage 2 ;;
    esac
  done

  if [[ -z "$topic" && -z "$after" && -z "$before" && -z "$branch" && -z "$project" ]]; then
    echo "Error: At least one search criterion required (--topic, --after, --before, --branch, --project)" >&2
    exit 1
  fi

  # Phase 1: Index-based search
  local entries
  entries=$(gather_entries)

  local filter
  filter=$(build_filter "$topic" "$after" "$before" "$branch" "$project")
  entries=$(echo "$entries" | jq "$filter")

  # Phase 2: Deep search (if requested and topic provided)
  if [[ "$deep" == "true" && -n "$topic" ]]; then
    local deep_ids
    deep_ids=$(deep_search_sessions "$topic")

    if [[ -n "$deep_ids" ]]; then
      # Build a jq filter to include sessions found by deep search
      local id_filter=""
      while IFS= read -r sid; do
        [[ -n "$sid" ]] || continue
        if [[ -n "$id_filter" ]]; then
          id_filter="${id_filter} or"
        fi
        id_filter="${id_filter} .sessionId == \"${sid}\""
      done <<< "$deep_ids"

      # Merge deep results with index results
      local all_entries
      all_entries=$(gather_entries)
      local deep_entries
      deep_entries=$(echo "$all_entries" | jq "[.[] | select(${id_filter})]")

      # Apply non-topic filters to deep results too
      local non_topic_filter
      non_topic_filter=$(build_filter "" "$after" "$before" "$branch" "$project")
      deep_entries=$(echo "$deep_entries" | jq "$non_topic_filter")

      # Union (deduplicate by sessionId)
      entries=$(echo "$entries" "$deep_entries" | jq -s '
        .[0] + .[1] | group_by(.sessionId) | map(.[0]) | sort_by(.modified // .created) | reverse
      ')
    fi
  fi

  if [[ "$output_json" == "true" ]]; then
    echo "$entries" | jq ".[0:${limit}]"
  else
    local label="index"
    [[ "$deep" == "true" ]] && label="index + content"
    printf "${DIM}Search mode: %s${RESET}\n\n" "$label"
    format_entries_text "$entries" "$limit"
  fi
}

cmd_show() {
  local session_id="" max_messages="$DEFAULT_MAX_MESSAGES" output_json=false messages_only=false

  if [[ $# -lt 1 ]]; then
    echo "Error: session ID required" >&2
    echo "Usage: search-conversations.sh show <session-id> [options]" >&2
    exit 1
  fi

  session_id="$1"; shift

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --max-messages) max_messages="$2"; shift 2 ;;
      --json) output_json=true; shift ;;
      --messages-only) messages_only=true; shift ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  local jsonl_file
  jsonl_file=$(find_session_file "$session_id") || exit 1

  local actual_sid
  actual_sid=$(basename "$jsonl_file" .jsonl)

  if [[ "$output_json" == "true" ]]; then
    # JSON: metadata + messages
    local metadata
    metadata=$(lookup_session_metadata "$actual_sid")

    local messages
    messages=$(extract_messages "$jsonl_file" "$max_messages" "true")

    if [[ -n "$metadata" && "$metadata" != "null" ]]; then
      jq -n --argjson meta "$metadata" --argjson msgs "$messages" '{
        sessionId: $meta.sessionId,
        metadata: $meta,
        messages: $msgs,
        totalExtracted: ($msgs | length),
        maxMessages: '"$max_messages"'
      }'
    else
      jq -n --argjson msgs "$messages" '{
        sessionId: "'"$actual_sid"'",
        metadata: null,
        messages: $msgs,
        totalExtracted: ($msgs | length),
        maxMessages: '"$max_messages"'
      }'
    fi
  else
    # Text: header + messages
    if [[ "$messages_only" != "true" ]]; then
      local metadata
      metadata=$(lookup_session_metadata "$actual_sid")

      if [[ -n "$metadata" && "$metadata" != "null" ]]; then
        printf "${BOLD}${CYAN}Conversation: %s${RESET}\n" "$actual_sid"
        printf "${GREEN}Created:${RESET}  %s\n" "$(echo "$metadata" | jq -r '.created // "unknown"' | head -c 19)"
        printf "${GREEN}Modified:${RESET} %s\n" "$(echo "$metadata" | jq -r '.modified // "unknown"' | head -c 19)"
        printf "${GREEN}Branch:${RESET}   %s\n" "$(echo "$metadata" | jq -r '.gitBranch // "unknown"')"
        printf "${GREEN}Project:${RESET}  %s\n" "$(echo "$metadata" | jq -r '.projectPath // "unknown"' | sed "s|${HOME}|~|")"
        printf "${GREEN}Messages:${RESET} %s\n" "$(echo "$metadata" | jq -r '.messageCount // "unknown"')"
        printf "${GREEN}Summary:${RESET}  %s\n" "$(echo "$metadata" | jq -r '.summary // "(none)"')"
        printf "\n${BOLD}Showing up to %d messages:${RESET}\n" "$max_messages"
      fi
    fi

    extract_messages "$jsonl_file" "$max_messages" "false"
  fi
}

cmd_stats() {
  local output_json=false
  [[ "${1:-}" == "--json" ]] && output_json=true

  local entries
  entries=$(gather_entries)

  local total_conversations total_messages projects_count
  total_conversations=$(echo "$entries" | jq 'length')
  total_messages=$(echo "$entries" | jq '[.[].messageCount // 0] | add // 0')
  projects_count=$(echo "$entries" | jq '[.[].projectPath // "unknown"] | unique | length')

  local earliest latest
  earliest=$(echo "$entries" | jq -r 'last | .created // .modified // "unknown"' | head -c 10)
  latest=$(echo "$entries" | jq -r 'first | .created // .modified // "unknown"' | head -c 10)

  local avg_messages
  if [[ "$total_conversations" -gt 0 ]]; then
    avg_messages=$((total_messages / total_conversations))
  else
    avg_messages=0
  fi

  # Top branches
  local top_branches
  top_branches=$(echo "$entries" | jq -r '[.[].gitBranch // "unknown"] | group_by(.) | map({branch: .[0], count: length}) | sort_by(-.count) | .[0:5]')

  if [[ "$output_json" == "true" ]]; then
    jq -n \
      --argjson total "$total_conversations" \
      --argjson msgs "$total_messages" \
      --argjson projects "$projects_count" \
      --argjson avg "$avg_messages" \
      --arg earliest "$earliest" \
      --arg latest "$latest" \
      --argjson branches "$top_branches" \
      '{
        totalConversations: $total,
        totalMessages: $msgs,
        projectsTracked: $projects,
        avgMessagesPerConversation: $avg,
        dateRange: {earliest: $earliest, latest: $latest},
        topBranches: $branches
      }'
  else
    printf "${BOLD}Claude Code Conversation Statistics${RESET}\n"
    printf "═══════════════════════════════════════\n"
    printf "${GREEN}Total conversations:${RESET}  %d\n" "$total_conversations"
    printf "${GREEN}Total messages:${RESET}       %d\n" "$total_messages"
    printf "${GREEN}Projects tracked:${RESET}     %d\n" "$projects_count"
    printf "${GREEN}Avg msgs/conversation:${RESET} %d\n" "$avg_messages"
    printf "${GREEN}Date range:${RESET}           %s to %s\n" "$earliest" "$latest"
    printf "\n${BOLD}Top branches:${RESET}\n"
    echo "$top_branches" | jq -r '.[] | "  \(.branch): \(.count) conversations"'
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  if [[ $# -eq 0 ]]; then
    usage 0
  fi

  # Process global flags and strip them from args
  local args=()
  for arg in "$@"; do
    case "$arg" in
      -h|--help) usage 0 ;;
      --no-color) NO_COLOR=1; BOLD='' DIM='' GREEN='' YELLOW='' CYAN='' MAGENTA='' RESET='' ;;
      *) args+=("$arg") ;;
    esac
  done
  set -- "${args[@]}"

  if [[ $# -eq 0 ]]; then
    usage 0
  fi

  local cmd="$1"; shift

  case "$cmd" in
    list)   cmd_list "$@" ;;
    search) cmd_search "$@" ;;
    show)   cmd_show "$@" ;;
    stats)  cmd_stats "$@" ;;
    *) echo "Unknown command: $cmd" >&2; usage 2 ;;
  esac
}

main "$@"
