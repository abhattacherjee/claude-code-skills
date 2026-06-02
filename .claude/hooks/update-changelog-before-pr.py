#!/usr/bin/env python3
"""
Pre-PR Hook: Block PR Creation Unless Changelog is Updated

Installed by /harden-repo into target repo's .claude/hooks/

This hook triggers before `gh pr create` commands. It BLOCKS the PR if
CHANGELOG.md has no meaningful entries under [Unreleased], ensuring every
PR includes a changelog update.
"""

import json
import os
import re
import subprocess
import sys


def get_branch_commits():
    """Get commits on current branch not in origin/develop (or origin/main as fallback)."""
    try:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        # Detect base: prefer develop, fall back to main
        for base in ["origin/develop", "origin/main"]:
            check = subprocess.run(
                ["git", "rev-parse", "--verify", base],
                capture_output=True, text=True, cwd=cwd
            )
            if check.returncode == 0:
                result = subprocess.run(
                    ["git", "log", f"{base}..HEAD", "--oneline", "--no-merges"],
                    capture_output=True, text=True, cwd=cwd
                )
                if result.returncode == 0:
                    commits = result.stdout.strip().split('\n')
                    return [c for c in commits if c]
        return []
    except Exception as e:
        print(f"Warning: Failed to get branch commits: {e}", file=sys.stderr)
        return []


def check_changelog_modified_on_branch():
    """Check if CHANGELOG.md was modified on the current branch vs base.

    Returns (was_modified, base_branch_name). Returns (None, reason) if
    the base branch cannot be determined or git comparison fails.
    """
    try:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        # Check against develop first, fall back to main
        for base in ["origin/develop", "origin/main"]:
            check = subprocess.run(
                ["git", "rev-parse", "--verify", base],
                capture_output=True, text=True, cwd=cwd
            )
            if check.returncode == 0:
                result = subprocess.run(
                    ["git", "diff", "--name-only", f"{base}...HEAD", "--", "CHANGELOG.md"],
                    capture_output=True, text=True, cwd=cwd
                )
                if result.returncode == 0:
                    return bool(result.stdout.strip()), base
                # Base exists but diff failed — don't fall through to wrong base
                print(f"Warning: git diff against {base} failed: {result.stderr.strip()}", file=sys.stderr)
                return None, f"git diff against {base} failed"
        return None, "No base branch (origin/develop or origin/main) found"
    except Exception as e:
        print(f"Warning: Failed to check changelog branch modification: {e}", file=sys.stderr)
        return None, f"git comparison failed: {e}"


def _get_current_branch():
    """Return the current git branch, or '' on error."""
    try:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get current branch: {e}", file=sys.stderr)
    return ""


def check_release_version_section(version):
    """Check if CHANGELOG.md has a `## [version]` section with at least one entry.

    Used when the PR is opened from a release/X.Y.Z or hotfix/X.Y.Z branch — the
    release-prep commit moves [Unreleased] entries into [version], so requiring
    [Unreleased] content would block every release PR.
    """
    try:
        changelog_path = os.path.join(
            os.environ.get("CLAUDE_PROJECT_DIR", "."),
            "CHANGELOG.md"
        )
        if not os.path.exists(changelog_path):
            return False, "CHANGELOG.md not found"
        with open(changelog_path, 'r') as f:
            content = f.read()
        pattern = (
            r'## \[v?' + re.escape(version) + r'\][^\n]*\r?\n'
            r'(.*?)(?=\r?\n## \[|\Z)'
        )
        m = re.search(pattern, content, re.DOTALL)
        if not m:
            return False, f"[{version}] section not found in CHANGELOG.md"
        body = m.group(1)
        entries = [line.strip() for line in body.split('\n')
                   if line.strip().startswith('- ')]
        if entries:
            return True, f"{len(entries)} entries found under [{version}]"
        return False, f"[{version}] section has no entries"
    except (PermissionError, OSError) as e:
        return None, f"Cannot read CHANGELOG.md: {e}"
    except Exception as e:
        return None, f"Unexpected error checking changelog: {e}"


def _release_version_from_branch(branch):
    """Extract X.Y.Z version if branch is release/X.Y.Z or hotfix/X.Y.Z, else ''."""
    m = re.match(r'^(?:release|hotfix)/v?(\d+\.\d+\.\d+(?:[-.][\w.]+)?)$', branch)
    return m.group(1) if m else ""


def check_changelog_has_unreleased_entries():
    """Check if CHANGELOG.md has meaningful NEW entries under [Unreleased]."""
    try:
        changelog_path = os.path.join(
            os.environ.get("CLAUDE_PROJECT_DIR", "."),
            "CHANGELOG.md"
        )
        if not os.path.exists(changelog_path):
            return False, "CHANGELOG.md not found"

        with open(changelog_path, 'r') as f:
            content = f.read()

        # `[ \t]*\r?\n` tolerates trailing spaces / CRLF after the header but
        # does NOT swallow blank lines — the original `\s*\n` was greedy enough
        # to consume the blank separator before the next release header, which
        # positioned the capture inside the NEXT section and counted its
        # `- ` bullets as Unreleased entries (silent fail-open).
        unreleased_match = re.search(r'## \[Unreleased\][ \t]*\r?\n(.*?)(?=\r?\n## \[|\Z)', content, re.DOTALL)
        if not unreleased_match:
            # Distinguish "header missing" from "header present but malformed"
            # so the error message points at the real problem.
            if re.search(r'## \[Unreleased\]', content):
                return False, "[Unreleased] header found but not followed by a newline (check for trailing whitespace beyond spaces/tabs)"
            return False, "[Unreleased] section not found in CHANGELOG.md"

        unreleased_body = unreleased_match.group(1)

        # Check if there are any list items (actual entries) under [Unreleased]
        # List items start with "- " after optional whitespace
        entries = [line.strip() for line in unreleased_body.split('\n')
                   if line.strip().startswith('- ')]

        if not entries:
            return False, "[Unreleased] section has no entries"

        # Entries exist — but are they new on this branch or stale?
        modified, base_or_reason = check_changelog_modified_on_branch()
        if modified is None:
            # Fail-closed: if we can't verify entries are fresh, block
            return False, (
                f"[Unreleased] has {len(entries)} entries, but could not verify "
                f"they were added on this branch ({base_or_reason}). "
                f"Please ensure CHANGELOG.md is modified on this branch, then retry."
            )
        elif modified:
            return True, f"{len(entries)} entries found under [Unreleased] (modified on this branch)"
        else:
            # Entries exist but CHANGELOG.md wasn't modified on this branch — stale
            return False, (
                f"[Unreleased] has {len(entries)} entries, but CHANGELOG.md was NOT "
                f"modified on this branch (compared to {base_or_reason}). "
                f"These entries were not added on this branch. "
                f"Add a new entry for your changes."
            )
    except (PermissionError, OSError) as e:
        return None, f"Cannot read CHANGELOG.md: {e}"
    except Exception as e:
        return None, f"Unexpected error checking changelog: {e}"


def get_pr_base_branch(command):
    """Extract the --base branch from gh pr create command, default to develop."""
    base_match = re.search(r'--base(?:\s+|=)(\S+)', command)
    if base_match:
        return base_match.group(1)
    return "develop"  # default base for Git Flow


def block(reason):
    """Block the PR creation."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def add_context(message):
    """Add advisory context without blocking."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def _targets_this_project(cmd):
    """Check if the command targets a repo within this project."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return True
    project_dir = os.path.realpath(project_dir)
    cd_match = re.search(r'(?:^|[;&|]\s*)cd\s+("([^"]+)"|\'([^\']+)\'|(\S+))', cmd)
    if cd_match:
        target = cd_match.group(2) or cd_match.group(3) or cd_match.group(4)
        target = os.path.expanduser(target)
        target = os.path.expandvars(target)
        target = os.path.realpath(target)
        return os.path.commonpath([target, project_dir]) == project_dir
    return True


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        block("Changelog hook received invalid input. Blocking PR as a safety measure.")
        return  # block() calls sys.exit(), but guard against refactoring

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only check for gh pr create commands
    if tool_name != "Bash":
        sys.exit(0)

    if "gh pr create" not in command:
        sys.exit(0)

    # Skip if targeting a different repo
    if not _targets_this_project(command):
        sys.exit(0)

    # Release/hotfix PRs: the release-prep commit moves [Unreleased] entries
    # into a versioned section — that IS the changelog update. Accept either
    # [Unreleased] entries OR a populated [X.Y.Z] section matching the branch.
    release_version = _release_version_from_branch(_get_current_branch())
    if release_version:
        has_release, release_reason = check_release_version_section(release_version)
        if has_release is True:
            add_context(f"✅ Changelog check (release branch): {release_reason}")

    # Check if changelog has entries under [Unreleased]
    has_entries, reason = check_changelog_has_unreleased_entries()

    # None means filesystem error — block with the actual error, not changelog instructions
    if has_entries is None:
        block(f"❌ PR BLOCKED: {reason}")
    elif has_entries:
        add_context(f"✅ Changelog check: {reason}")
    else:
        # Get commits for context in the error message
        commits = get_branch_commits()
        commit_count = len(commits)
        commit_summary = '\n'.join(f"  - {c}" for c in commits[:5])
        if commit_count > 5:
            commit_summary += f"\n  ... and {commit_count - 5} more"

        base = get_pr_base_branch(command)

        block(f"""❌ PR BLOCKED: Changelog not updated!

{reason}

This PR targets '{base}' and has {commit_count} commit(s):
{commit_summary}

You MUST add entries under the [Unreleased] section in CHANGELOG.md
before creating this PR.

Example:
  ## [Unreleased]

  ### Added
  - Description of new feature

  ### Fixed
  - Description of bug fix

Update CHANGELOG.md, stage it, amend your commit, then retry.""")


if __name__ == "__main__":
    main()
