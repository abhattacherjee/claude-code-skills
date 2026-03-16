#!/usr/bin/env bash
# task-manifest.sh — Emit task definitions for each spec-review workflow
# Each workflow returns a JSON array of {subject, activeForm, description} objects.
# Usage: ./scripts/task-manifest.sh <workflow-name>
#        ./scripts/task-manifest.sh --list
#        ./scripts/task-manifest.sh --help

case "${1:-}" in
  full-review)
    cat <<'JSON'
[
  {"subject":"Discover architecture and extract spec","activeForm":"Discovering project architecture","description":"Run discover-project-architecture.sh and extract-spec-sections.sh to gather project context and parse spec structure"},
  {"subject":"Launch 4 parallel analysis agents","activeForm":"Analyzing spec with 4 parallel agents","description":"Launch Codebase Verifier, Architecture Reviewer, Design Simplifier, and Test Plan Extractor agents in a single message"},
  {"subject":"Synthesize findings into enrichments","activeForm":"Synthesizing review findings","description":"Merge agent results into Current Codebase State, Design Simplification Notes, detailed sub-tasks, and test plan sections"},
  {"subject":"Calculate readiness score","activeForm":"Calculating implementation readiness","description":"Score the spec on 5 dimensions (codebase accuracy, architecture alignment, design simplicity, test coverage, sub-task completeness)"},
  {"subject":"Present report and apply enrichments","activeForm":"Presenting review report","description":"Present findings, ask user whether to update spec file, save companion doc, or report only"}
]
JSON
    ;;
  quick-check)
    cat <<'JSON'
[
  {"subject":"Extract and verify spec references","activeForm":"Verifying spec references","description":"Run extraction script, then verify all file paths, function names, and data shapes against actual codebase"},
  {"subject":"Report discrepancies","activeForm":"Reporting discrepancies","description":"List all verified, corrected, and missing references from the spec"}
]
JSON
    ;;
  --list)
    echo "full-review quick-check"
    ;;
  -h|--help)
    echo "Usage: task-manifest.sh <workflow>"
    echo ""
    echo "Workflows:"
    echo "  full-review   5-phase review with 4 parallel agents (3-5 min)"
    echo "  quick-check   Fast codebase verification only (1-2 min)"
    echo ""
    echo "Use --list for machine-readable workflow names"
    ;;
  *)
    echo "Error: unknown workflow '${1:-}'. Use --list or --help." >&2
    exit 1
    ;;
esac
