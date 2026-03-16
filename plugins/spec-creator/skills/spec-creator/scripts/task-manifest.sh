#!/usr/bin/env bash
# task-manifest.sh — Emit task definitions for spec-creator workflows
# Usage: ./scripts/task-manifest.sh <workflow-name>
#
# Workflows:
#   single-story   — Create a single story spec (5 tasks)
#   vertical-split  — Create multiple specs as vertical slices (6 tasks)

case "${1:-}" in
  single-story)
    cat <<'JSON'
[
  {"subject":"Parse input and discover conventions","activeForm":"Discovering project conventions","description":"Detect input type (prompt/file/issue/plan), run discover-conventions.sh, read sample spec, determine epic and story number"},
  {"subject":"Research codebase","activeForm":"Researching codebase","description":"Launch parallel agents: Feature Scout (code-explorer) for existing code/paths/signatures, Convention Scanner (haiku) for spec formatting style"},
  {"subject":"Brainstorm approaches with user","activeForm":"Brainstorming approaches","description":"Assess scope, check splitting triggers, present options via AskUserQuestion, get user selection"},
  {"subject":"Generate spec file","activeForm":"Generating spec file","description":"Build spec content from template + research + user selection, run simplification self-check, write to spec directory"},
  {"subject":"Post-creation review","activeForm":"Running post-creation review","description":"Ask user: run /review-spec, /simplify, or done. Invoke selected skill if applicable"}
]
JSON
    ;;
  vertical-split)
    cat <<'JSON'
[
  {"subject":"Parse input and discover conventions","activeForm":"Discovering project conventions","description":"Detect input type (prompt/file/issue/plan), run discover-conventions.sh, read sample spec, determine epic and story number"},
  {"subject":"Research codebase","activeForm":"Researching codebase","description":"Launch parallel agents: Feature Scout (code-explorer) for existing code/paths/signatures, Convention Scanner (haiku) for spec formatting style"},
  {"subject":"Brainstorm approaches with user","activeForm":"Brainstorming approaches","description":"Assess scope, check splitting triggers, present vertical split options via AskUserQuestion, get user selection"},
  {"subject":"Generate spec files for all slices","activeForm":"Generating spec files","description":"Create epic directory, write each slice spec with cross-references and dependency order, run simplification self-check per slice"},
  {"subject":"Update tracking file","activeForm":"Updating tracking file","description":"Add new epic section to tracking file (post-mvp-tracking.md or equivalent), update summary table"},
  {"subject":"Post-creation review","activeForm":"Running post-creation review","description":"Ask user: run /review-spec, /simplify, or done. Invoke selected skill if applicable"}
]
JSON
    ;;
  --list)
    echo "single-story vertical-split"
    ;;
  -h|--help)
    echo "Usage: task-manifest.sh <workflow>"
    echo ""
    echo "Workflows:"
    echo "  single-story    Create a single story spec (5 tasks)"
    echo "  vertical-split  Create multiple specs as vertical slices (6 tasks)"
    echo ""
    echo "Use --list for machine-readable workflow names"
    ;;
  *)
    echo "Error: unknown workflow '${1:-}'. Use --list or --help." >&2
    exit 1
    ;;
esac
