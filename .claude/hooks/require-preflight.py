#!/usr/bin/env python3
"""
Blocking Pre-Commit Hook: Requires Preflight Verification

Installed by /harden-repo into target repo's .claude/hooks/

This hook BLOCKS git commit commands unless a valid preflight token exists.
Claude must run `./scripts/commit-preflight.sh` before committing.

The token is:
- Created by commit-preflight.sh after checks pass
- Valid for 5 minutes
- One-time use for regular commits (consumed after validation); reusable for --amend
"""

import hashlib
import json
import os
import re
import sys
import time


def _get_token_path():
    """Get project-specific token path using a hash of the project directory."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    project_dir = os.path.realpath(project_dir)
    project_hash = hashlib.md5(project_dir.encode()).hexdigest()[:8]
    return f"/tmp/.preflight-token-{project_hash}"

TOKEN_FILE = _get_token_path()


def _targets_this_project(cmd: str) -> bool:
    """Check if the command targets a repo within this project.

    Hooks run in their own process (cwd = project dir), so git commands in
    the hook inspect the wrong repo when Claude does 'cd /other/repo && git commit'.
    Parse the cd target from the command to determine the effective repo.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return True  # Can't determine scope, be safe

    project_dir = os.path.realpath(project_dir)

    # Extract the first "cd /path" from the command (handles "cd X && git commit")
    cd_match = re.search(r'(?:^|[;&|]\s*)cd\s+("([^"]+)"|\'([^\']+)\'|(\S+))', cmd)
    if cd_match:
        target = cd_match.group(2) or cd_match.group(3) or cd_match.group(4)
        target = os.path.expanduser(target)
        target = os.path.expandvars(target)
        target = os.path.realpath(target)
        return os.path.commonpath([target, project_dir]) == project_dir

    # No cd in command — assume it targets the project repo
    return True


def block(reason: str) -> None:
    """Output a blocking decision."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def allow() -> None:
    """Allow the command to proceed."""
    sys.exit(0)


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Security gate must fail closed, not open
        block("Preflight hook received invalid input. Blocking commit as a safety measure.")
        return  # block() calls sys.exit(), but guard against refactoring

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only validate git commit commands
    if tool_name != "Bash":
        allow()
        return

    # Check if this is a git commit command
    is_commit = "git commit" in command
    is_amend = "--amend" in command

    if not is_commit:
        allow()
        return

    # Skip this hook if the command targets a repo outside this project
    if not _targets_this_project(command):
        allow()
        return

    # Check for skip flag (for emergencies - user must explicitly approve)
    if "SKIP_PREFLIGHT=1" in command:
        allow()
        return

    # Check if token file exists
    if not os.path.exists(TOKEN_FILE):
        block(f"""❌ COMMIT BLOCKED: Preflight verification required!

You must run the preflight check before committing:

    ./scripts/commit-preflight.sh

This ensures:
  ✓ Secret scanning passes
  ✓ Lint passes (if configured)
  ✓ Tests pass (if configured)

The preflight creates a one-time token that allows the next commit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why this exists:
  Claude previously ignored hook warnings and committed without
  running tests. This mechanism ENFORCES the verification step.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run: ./scripts/commit-preflight.sh
Then retry your commit.""")

    # Read and validate token
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        # Token file corrupted - require new preflight
        try:
            os.remove(TOKEN_FILE)
        except OSError as e:
            print(f"Warning: Failed to remove corrupted token: {e}", file=sys.stderr)
        block(f"""❌ COMMIT BLOCKED: Invalid preflight token!

The token file is corrupted. Please run preflight again:

    ./scripts/commit-preflight.sh

Then retry your commit.""")

    # Check token expiry
    expires = token_data.get("expires", 0)
    current_time = int(time.time())

    if current_time > expires:
        try:
            os.remove(TOKEN_FILE)
        except OSError as e:
            print(f"Warning: Failed to remove expired token: {e}", file=sys.stderr)
        time_ago = current_time - expires
        block(f"""❌ COMMIT BLOCKED: Preflight token expired!

Token expired {time_ago} seconds ago.

Please run preflight again to refresh:

    ./scripts/commit-preflight.sh

Then retry your commit.""")

    # Token is valid — consume for regular commits, preserve for amends
    checks_run = token_data.get("checks_run", "none")
    staged_count = token_data.get("staged_files", 0)

    # For amend, we're more lenient — don't consume the token
    if not is_amend:
        try:
            os.remove(TOKEN_FILE)
        except OSError as e:
            print(f"Warning: Failed to consume preflight token: {e}", file=sys.stderr)

    # Token valid - allow commit
    # Output verification status for audit trail
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": f"✅ Preflight verified: {checks_run} | {staged_count} files"
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
