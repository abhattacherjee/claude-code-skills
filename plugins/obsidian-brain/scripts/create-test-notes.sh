#!/usr/bin/env bash
# create-test-notes.sh — Create unsummarized test session notes for /recall testing.
#
# Creates N notes (default 3) of varying sizes in the vault's sessions folder.
# Reads vault_path and sessions_folder from ~/.claude/obsidian-brain-config.json.
# Can be run from any directory / any project.
#
# Usage:
#   ./scripts/create-test-notes.sh          # 3 notes (small, medium, large)
#   ./scripts/create-test-notes.sh 5        # 5 notes
#   ./scripts/create-test-notes.sh cleanup  # remove all test notes

set -euo pipefail

CONFIG="$HOME/.claude/obsidian-brain-config.json"

if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: Config not found at $CONFIG. Run /obsidian-setup first." >&2
  exit 1
fi

VAULT_PATH=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["vault_path"])' "$CONFIG")
SESS_FOLDER=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("sessions_folder","claude-sessions"))' "$CONFIG")
SESS_DIR="$VAULT_PATH/$SESS_FOLDER"

if [[ ! -d "$SESS_DIR" ]]; then
  echo "ERROR: Sessions dir not found: $SESS_DIR" >&2
  exit 1
fi

# Cleanup mode
if [[ "${1:-}" == "cleanup" ]]; then
  removed=0
  for f in "$SESS_DIR"/*-test-recall-*.md; do
    [[ -f "$f" ]] || continue
    rm -f "$f"
    echo "Removed: $(basename "$f")"
    removed=$((removed + 1))
  done
  echo "Cleaned up $removed test note(s)."
  exit 0
fi

N="${1:-3}"
DATE=$(date +%Y-%m-%d)
PROJECT="test-recall-project"

# Size profiles: lines of fake conversation content
sizes=(small medium large huge giant)
size_lines=(10 40 120 300 600)

created=0
for i in $(seq 1 "$N"); do
  idx=$(( (i - 1) % ${#sizes[@]} ))
  size_name="${sizes[$idx]}"
  num_lines="${size_lines[$idx]}"

  # Generate a unique 4-char hash
  hash=$(echo "${DATE}-${i}-${RANDOM}" | md5sum 2>/dev/null | cut -c1-4 || echo "${DATE}-${i}-${RANDOM}" | md5 | cut -c29-32)

  filename="${DATE}-test-recall-${size_name}-${hash}.md"
  filepath="$SESS_DIR/$filename"

  # Build fake conversation content
  conversation=""
  for line_num in $(seq 1 "$num_lines"); do
    if (( line_num % 2 == 1 )); then
      conversation+="**User:** This is test message $line_num in a $size_name test session note for /recall testing. It contains enough text to simulate real conversation content with various technical terms like Python, subprocess, vault index, and FTS5 search.\n"
    else
      conversation+="**Assistant:** Acknowledged test message $line_num. Working on implementing the requested feature with proper error handling, atomic writes, and post-write verification.\n"
    fi
  done

  cat > "$filepath" <<HEREDOC
---
type: claude-session
date: ${DATE}
session_id: test-${hash}-${size_name}-$(printf '%04d' "$i")
project: obsidian-brain
project_path: "/Users/test/dev/obsidian-brain"
git_branch: "feature/test-branch"
duration_minutes: $((num_lines * 3))
resumed: false
tags:
  - claude/session
  - claude/project/obsidian-brain
  - claude/auto
status: auto-logged
---

# Session: obsidian-brain (feature/test-branch)

## Summary
Session in **obsidian-brain** ($((num_lines * 3)).0 min). AI summary unavailable — raw extraction below.

## Key Decisions
_Not extracted (AI summary unavailable)._

## Changes Made
- /dev/test/file1.py
- /dev/test/file2.md

## Conversation (raw)
$(echo -e "$conversation")

## Session Metadata
- Started: ${DATE}T10:00:00
- Duration: $((num_lines * 3)) minutes
- Branch: feature/test-branch
HEREDOC

  chmod 600 "$filepath"
  echo "Created: $filename ($size_name, ~$num_lines conversation lines)"
  created=$((created + 1))
done

echo ""
echo "Created $created test note(s) in $SESS_DIR"
echo "Run '/recall' in a fresh CC session to test summarization."
echo "Run '$0 cleanup' to remove test notes when done."
