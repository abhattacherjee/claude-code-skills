#!/usr/bin/env bash
# generate-task-manifest.sh — Scaffold a task-manifest.sh for a skill's workflows
# Exit codes: 0 = success, 1 = error, 2 = usage error
set -eu

# --- Usage ---
usage() {
  cat <<'EOF'
Usage: generate-task-manifest.sh --skill-dir <dir> --workflows "<name:count>[,...]"

Generates scripts/task-manifest.sh in the target skill directory with
placeholder tasks for each specified workflow.

Options:
  --skill-dir <dir>    Target skill directory (must exist)
  --workflows <spec>   Comma-separated workflow specs: "name:task_count,name2:count2"
  -h, --help           Show this help

Examples:
  generate-task-manifest.sh --skill-dir ~/.claude/skills/my-skill \
    --workflows "full-audit:5,quick-check:2"

  generate-task-manifest.sh --skill-dir ./catalog-maintenance \
    --workflows "all:6,experiences:3,embeddings:2"

Output: Creates <skill-dir>/scripts/task-manifest.sh with:
  - One case branch per workflow emitting a JSON task array
  - --list flag for machine-readable workflow names
  - --help flag for human-readable usage
  - Placeholder subject/activeForm/description for each task

EOF
  exit 0
}

# --- Parse arguments ---
SKILL_DIR=""
WORKFLOWS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --skill-dir) SKILL_DIR="$2"; shift 2 ;;
    --workflows) WORKFLOWS="$2"; shift 2 ;;
    *) echo "Error: Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SKILL_DIR" ]] || [[ -z "$WORKFLOWS" ]]; then
  echo "Error: --skill-dir and --workflows are required" >&2
  echo "Run with --help for usage" >&2
  exit 2
fi

if [[ ! -d "$SKILL_DIR" ]]; then
  echo "Error: skill directory not found: $SKILL_DIR" >&2
  exit 1
fi

# Ensure scripts/ directory exists
mkdir -p "$SKILL_DIR/scripts"

OUTPUT="$SKILL_DIR/scripts/task-manifest.sh"

if [[ -f "$OUTPUT" ]]; then
  echo "Warning: $OUTPUT already exists. Overwrite? [y/N] "
  read -r CONFIRM
  if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# --- Parse workflow specs ---
IFS=',' read -ra WORKFLOW_SPECS <<< "$WORKFLOWS"
WORKFLOW_NAMES=()

for spec in "${WORKFLOW_SPECS[@]}"; do
  IFS=':' read -r name count <<< "$spec"
  if [[ -z "$name" ]] || [[ -z "$count" ]]; then
    echo "Error: Invalid workflow spec '$spec'. Expected format: name:count" >&2
    exit 2
  fi
  if ! [[ "$count" =~ ^[0-9]+$ ]] || [[ "$count" -lt 1 ]]; then
    echo "Error: Task count must be a positive integer (got: $count for $name)" >&2
    exit 2
  fi
  WORKFLOW_NAMES+=("$name")
done

# --- Generate script ---
{
  cat <<'HEADER'
#!/usr/bin/env bash
# task-manifest.sh — Emit task definitions for each workflow
# Each workflow returns a JSON array of {subject, activeForm, description} objects.
# Usage: ./scripts/task-manifest.sh <workflow-name>
#        ./scripts/task-manifest.sh --list
#        ./scripts/task-manifest.sh --help

case "${1:-}" in
HEADER

  # Generate one case branch per workflow
  for spec in "${WORKFLOW_SPECS[@]}"; do
    IFS=':' read -r name count <<< "$spec"

    echo "  $name)"
    echo "    cat <<'JSON'"
    echo "["

    for ((i = 1; i <= count; i++)); do
      COMMA=""
      if [[ $i -lt $count ]]; then
        COMMA=","
      fi
      echo "  {\"subject\":\"Phase $i: TODO\",\"activeForm\":\"Running phase $i\",\"description\":\"TODO: describe what phase $i does\"}$COMMA"
    done

    echo "]"
    echo "JSON"
    echo "    ;;"
  done

  # --list flag
  NAMES_STR="${WORKFLOW_NAMES[*]}"
  cat <<FOOTER
  --list)
    echo "$NAMES_STR"
    ;;
  -h|--help)
    echo "Usage: task-manifest.sh <workflow>"
    echo "Workflows: $NAMES_STR"
    echo "Use --list for machine-readable workflow names"
    ;;
  *)
    echo "Error: unknown workflow '\${1:-}'. Use --list or --help." >&2
    exit 1
    ;;
esac
FOOTER
} > "$OUTPUT"

chmod +x "$OUTPUT"

echo "Generated: $OUTPUT"
echo "Workflows: ${WORKFLOW_NAMES[*]}"
echo ""
echo "Next steps:"
echo "  1. Edit $OUTPUT to replace TODO placeholders with real task descriptions"
echo "  2. Add a 'Progress Tracking (MANDATORY)' section to SKILL.md"
echo "  3. Reference the manifest: ./scripts/task-manifest.sh <workflow>"
