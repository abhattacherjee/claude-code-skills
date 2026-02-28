#!/usr/bin/env bash
set -eu

# Context Shield — Manifest Manager
# Tracks content sources, batching, and progress across iterations.
# State persists on disk so ralph-loop iterations can resume.

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME <command> [options]

Commands:
  create   --task "description" --output-dir /tmp/dir [sources...]
           Create a new manifest from a list of content sources.
           Sources format: "type:location" where type is figma|url|file|wiki|codebase
           Examples:
             $SCRIPT_NAME create --task "Analyze designs" --output-dir /tmp/cs-123 \\
               "figma:fileKey=abc,nodeId=1:2,label=Homepage" \\
               "url:https://example.com/docs,label=API Docs" \\
               "file:/path/to/large-file.md,label=Spec"

  status   --manifest /path/to/manifest.json
           Show progress: total, done, pending, current batch.

  next-batch --manifest /path/to/manifest.json [--batch-size N]
           Output the next batch of pending items as JSON array.
           Default batch size: 4.

  mark-done --manifest /path/to/manifest.json --index N --summary "text"
           Mark item at index N as done and store its distilled summary.

  reset    --manifest /path/to/manifest.json
           Reset all items to pending (clear summaries). Useful for re-processing.

  summaries --manifest /path/to/manifest.json
           Output all completed summaries as a combined report.

Options:
  -h, --help    Show this help message

Examples:
  # Create manifest for Figma + web research task
  $SCRIPT_NAME create --task "Analyze competitor UIs" --output-dir /tmp/cs-run1 \\
    "url:https://dribbble.com/shots/travel-app,label=Dribbble Travel" \\
    "url:https://behance.net/gallery/booking-ui,label=Behance Booking" \\
    "figma:fileKey=xYz123,nodeId=5:42,label=Current Homepage" \\
    "file:specs/stories/story-10.1.md,label=Story Spec"

  # Check progress
  $SCRIPT_NAME status --manifest /tmp/cs-run1/manifest.json

  # Get next batch for parallel agents
  $SCRIPT_NAME next-batch --manifest /tmp/cs-run1/manifest.json --batch-size 3

  # Mark item done after agent returns
  $SCRIPT_NAME mark-done --manifest /tmp/cs-run1/manifest.json --index 0 \\
    --summary "Travel app uses card-based layout with hero image..."

  # Collect all summaries for synthesis
  $SCRIPT_NAME summaries --manifest /tmp/cs-run1/manifest.json
EOF
  exit 0
}

# --- Helpers ---

die() { echo "ERROR: $1" >&2; exit 1; }

require_jq() {
  command -v jq >/dev/null 2>&1 || die "jq is required but not installed"
}

require_manifest() {
  [[ -n "${MANIFEST:-}" ]] || die "--manifest is required"
  [[ -f "$MANIFEST" ]] || die "Manifest not found: $MANIFEST"
}

parse_source() {
  local raw="$1"
  local src_type="${raw%%:*}"
  local rest="${raw#*:}"

  # Validate type
  case "$src_type" in
    figma|url|file|wiki|codebase) ;;
    *) die "Unknown source type '$src_type'. Valid: figma, url, file, wiki, codebase" ;;
  esac

  # Parse key=value pairs from rest (comma-separated)
  local location="" label="" extra_json="{}"

  # Extract label if present
  if echo "$rest" | grep -q "label="; then
    label=$(echo "$rest" | sed 's/.*label=\([^,]*\).*/\1/')
    rest=$(echo "$rest" | sed 's/,*label=[^,]*//' | sed 's/^,//' | sed 's/,$//')
  fi

  case "$src_type" in
    figma)
      local file_key="" node_id=""
      if echo "$rest" | grep -q "fileKey="; then
        file_key=$(echo "$rest" | sed 's/.*fileKey=\([^,]*\).*/\1/')
      fi
      if echo "$rest" | grep -q "nodeId="; then
        node_id=$(echo "$rest" | sed 's/.*nodeId=\([^,]*\).*/\1/')
      fi
      location="figma://$file_key/$node_id"
      extra_json=$(jq -n --arg fk "$file_key" --arg ni "$node_id" \
        '{fileKey: $fk, nodeId: $ni}')
      ;;
    url|wiki)
      # Rest is the URL (after removing label)
      location="$rest"
      ;;
    file|codebase)
      location="$rest"
      ;;
  esac

  [[ -z "$label" ]] && label="$location"

  jq -n \
    --arg type "$src_type" \
    --arg location "$location" \
    --arg label "$label" \
    --arg status "pending" \
    --argjson extra "$extra_json" \
    '{type: $type, location: $location, label: $label, status: $status, summary: null} + {extra: $extra}'
}

# --- Commands ---

cmd_create() {
  local task="" output_dir="" batch_size=4
  local sources=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task) task="$2"; shift 2 ;;
      --output-dir) output_dir="$2"; shift 2 ;;
      --batch-size) batch_size="$2"; shift 2 ;;
      -*) die "Unknown option: $1" ;;
      *) sources+=("$1"); shift ;;
    esac
  done

  [[ -n "$task" ]] || die "--task is required"
  [[ -n "$output_dir" ]] || die "--output-dir is required"
  [[ ${#sources[@]} -gt 0 ]] || die "At least one source is required"

  mkdir -p "$output_dir"

  # Build sources JSON array
  local items_json="[]"
  local idx=0
  for src in "${sources[@]}"; do
    local item_json
    item_json=$(parse_source "$src")
    items_json=$(echo "$items_json" | jq --argjson item "$item_json" --argjson idx "$idx" \
      '. + [$item + {index: $idx}]')
    idx=$((idx + 1))
  done

  # Create manifest
  local manifest_path="$output_dir/manifest.json"
  jq -n \
    --arg task "$task" \
    --arg outputDir "$output_dir" \
    --argjson batchSize "$batch_size" \
    --argjson sources "$items_json" \
    --arg createdAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      task: $task,
      outputDir: $outputDir,
      batchSize: $batchSize,
      currentBatch: 0,
      iteration: 1,
      createdAt: $createdAt,
      sources: $sources
    }' > "$manifest_path"

  echo "Manifest created: $manifest_path"
  echo "  Task:    $task"
  echo "  Sources: ${#sources[@]}"
  echo "  Batches: $(( (${#sources[@]} + batch_size - 1) / batch_size )) (batch size: $batch_size)"
  echo "  Output:  $output_dir"
}

cmd_status() {
  require_manifest

  local total pending done failed
  total=$(jq '.sources | length' "$MANIFEST")
  done=$(jq '[.sources[] | select(.status == "done")] | length' "$MANIFEST")
  pending=$(jq '[.sources[] | select(.status == "pending")] | length' "$MANIFEST")
  failed=$(jq '[.sources[] | select(.status == "failed")] | length' "$MANIFEST")
  local batch_size current_batch iteration task
  batch_size=$(jq -r '.batchSize' "$MANIFEST")
  current_batch=$(jq -r '.currentBatch' "$MANIFEST")
  iteration=$(jq -r '.iteration' "$MANIFEST")
  task=$(jq -r '.task' "$MANIFEST")
  local total_batches=$(( (total + batch_size - 1) / batch_size ))

  echo "Task:       $task"
  echo "Progress:   $done/$total done ($pending pending, $failed failed)"
  echo "Batch:      $((current_batch + 1))/$total_batches (size: $batch_size)"
  echo "Iteration:  $iteration"
  echo ""

  if [[ "$pending" -eq 0 && "$failed" -eq 0 ]]; then
    echo "STATUS: COMPLETE — all sources processed"
  elif [[ "$pending" -eq 0 && "$failed" -gt 0 ]]; then
    echo "STATUS: BLOCKED — $failed failed items need retry"
  else
    echo "STATUS: IN PROGRESS — $pending items remaining"
  fi
}

cmd_next_batch() {
  require_manifest

  local batch_size
  batch_size=$(jq -r '.batchSize' "$MANIFEST")

  # Override from CLI if provided
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --batch-size) batch_size="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  # Get next N pending items
  jq --argjson n "$batch_size" \
    '[.sources[] | select(.status == "pending")] | .[:$n]' "$MANIFEST"
}

cmd_mark_done() {
  require_manifest

  local index="" summary=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --index) index="$2"; shift 2 ;;
      --summary) summary="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  [[ -n "$index" ]] || die "--index is required"
  [[ -n "$summary" ]] || die "--summary is required"

  # Update manifest in place (via temp file for atomicity)
  local tmp_file
  tmp_file=$(mktemp)
  jq --argjson idx "$index" --arg summary "$summary" \
    '.sources[$idx].status = "done" | .sources[$idx].summary = $summary' \
    "$MANIFEST" > "$tmp_file"
  mv "$tmp_file" "$MANIFEST"

  local label
  label=$(jq -r --argjson idx "$index" '.sources[$idx].label' "$MANIFEST")
  echo "Marked done: [$index] $label"
}

cmd_reset() {
  require_manifest

  local tmp_file
  tmp_file=$(mktemp)
  jq '.sources[].status = "pending" | .sources[].summary = null | .currentBatch = 0 | .iteration = 1' \
    "$MANIFEST" > "$tmp_file"
  mv "$tmp_file" "$MANIFEST"
  echo "Reset all items to pending"
}

cmd_summaries() {
  require_manifest

  local task
  task=$(jq -r '.task' "$MANIFEST")
  echo "# Distilled Summaries: $task"
  echo ""

  jq -r '.sources[] | select(.status == "done") |
    "## [\(.index)] \(.label) (\(.type))\n\(.summary)\n"' "$MANIFEST"

  local pending
  pending=$(jq '[.sources[] | select(.status == "pending")] | length' "$MANIFEST")
  if [[ "$pending" -gt 0 ]]; then
    echo "---"
    echo "*$pending items still pending*"
  fi
}

# --- Main ---

[[ $# -eq 0 ]] && usage

COMMAND="$1"; shift

case "$COMMAND" in
  -h|--help) usage ;;
  create)
    require_jq
    cmd_create "$@"
    ;;
  status)
    require_jq
    MANIFEST=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    require_manifest
    cmd_status
    ;;
  next-batch)
    require_jq
    MANIFEST=""
    local_args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        *) local_args+=("$1"); shift ;;
      esac
    done
    require_manifest
    cmd_next_batch ${local_args[@]+"${local_args[@]}"}
    ;;
  mark-done)
    require_jq
    MANIFEST=""
    local_args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        *) local_args+=("$1"); shift ;;
      esac
    done
    require_manifest
    cmd_mark_done ${local_args[@]+"${local_args[@]}"}
    ;;
  reset)
    require_jq
    MANIFEST=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    require_manifest
    cmd_reset
    ;;
  summaries)
    require_jq
    MANIFEST=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    require_manifest
    cmd_summaries
    ;;
  *)
    die "Unknown command: $COMMAND. Run '$SCRIPT_NAME --help' for usage."
    ;;
esac
