#!/usr/bin/env bash
set -eu

# Task manifest for spec-implement skill
# Usage: task-manifest.sh <workflow>
# Workflows: standard, ui-heavy

show_help() {
  cat <<'HELP'
Usage: task-manifest.sh <workflow> [--list] [--help]

Workflows:
  standard    — Default implementation workflow (7 tasks)
  ui-heavy    — UI-heavy spec with design system work (9 tasks)

Options:
  --list      List available workflows
  --help      Show this help
HELP
}

case "${1:-}" in
  --help|-h) show_help; exit 0 ;;
  --list) echo "standard"; echo "ui-heavy"; exit 0 ;;
  standard)
    cat <<'JSON'
[
  {"subject": "Read spec and discover project conventions", "activeForm": "Reading spec and project conventions", "description": "Parse the spec file, read CLAUDE.md files, understand branching strategy and project structure"},
  {"subject": "Create feature branch", "activeForm": "Creating feature branch", "description": "Create a Git Flow feature branch from develop for this story"},
  {"subject": "Implement sub-tasks", "activeForm": "Implementing sub-tasks", "description": "Implement each sub-task from the spec, checking off acceptance criteria"},
  {"subject": "Validate build and lint", "activeForm": "Validating build and lint", "description": "Run npm run build and npm run lint to ensure no regressions"},
  {"subject": "Verify acceptance criteria", "activeForm": "Verifying acceptance criteria", "description": "Walk through every acceptance criterion in the spec and confirm it is met"},
  {"subject": "Update tracking and changelog", "activeForm": "Updating tracking files", "description": "Update mvp-ux-tracking.md status and CHANGELOG.md"},
  {"subject": "Create PR", "activeForm": "Creating pull request", "description": "Commit, push, and create a PR with spec-linked description"}
]
JSON
    ;;
  ui-heavy)
    cat <<'JSON'
[
  {"subject": "Read spec and discover project conventions", "activeForm": "Reading spec and project conventions", "description": "Parse the spec file, read CLAUDE.md files, understand branching strategy and project structure"},
  {"subject": "Create feature branch", "activeForm": "Creating feature branch", "description": "Create a Git Flow feature branch from develop for this story"},
  {"subject": "Assess complexity and invoke design skills", "activeForm": "Assessing complexity", "description": "Determine if brainstorming, frontend-design, or ui-from-requirements skills should be invoked"},
  {"subject": "Implement sub-tasks", "activeForm": "Implementing sub-tasks", "description": "Implement each sub-task from the spec, checking off acceptance criteria"},
  {"subject": "Update ComponentShowcase if needed", "activeForm": "Updating ComponentShowcase", "description": "Add showcase entries for any new DS components"},
  {"subject": "Validate build and lint", "activeForm": "Validating build and lint", "description": "Run npm run build and npm run lint to ensure no regressions"},
  {"subject": "Verify acceptance criteria", "activeForm": "Verifying acceptance criteria", "description": "Walk through every acceptance criterion in the spec and confirm it is met"},
  {"subject": "Update tracking and changelog", "activeForm": "Updating tracking files", "description": "Update mvp-ux-tracking.md status and CHANGELOG.md"},
  {"subject": "Create PR", "activeForm": "Creating pull request", "description": "Commit, push, and create a PR with spec-linked description"}
]
JSON
    ;;
  *)
    echo "Unknown workflow: ${1:-<none>}" >&2
    echo "Run with --list or --help" >&2
    exit 2
    ;;
esac
