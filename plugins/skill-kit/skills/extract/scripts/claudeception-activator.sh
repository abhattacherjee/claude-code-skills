#!/usr/bin/env bash

# skill-kit:extract Auto-Activation Hook (was the claudeception hook)
# This hook ensures the skill-kit:extract skill evaluates every interaction
# for extractable knowledge worth preserving.
#
# Installation:
#   1. Copy this script from the installed skill-kit plugin (skills/extract/scripts/)
#      to ~/.claude/hooks/
#   2. Make it executable: chmod +x ~/.claude/hooks/claudeception-activator.sh
#   3. Add to ~/.claude/settings.json (see README for details)

case "${1:-}" in
  -h|--help)
    echo "Usage: claudeception-activator.sh"
    echo "UserPromptSubmit hook: prints a reminder to evaluate the session with Skill(skill-kit:extract)."
    exit 0
    ;;
esac

cat << 'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 MANDATORY SKILL EVALUATION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL: After completing this user request, you MUST evaluate whether
it produced extractable knowledge using the skill-kit:extract skill.

EVALUATION PROTOCOL (NON-NEGOTIABLE):

1. COMPLETE the user's request first
2. EVALUATE: Ask yourself:
   - Did this require non-obvious investigation or debugging?
   - Was the solution something that would help in future similar situations?
   - Did I discover something not immediately obvious from documentation?

3. IF YES to any question above:
   ACTIVATE: Use Skill(skill-kit:extract) NOW to extract the knowledge

4. IF NO to all questions:
   SKIP: No skill extraction needed

This is NOT optional. Failing to evaluate means valuable knowledge is lost.
The skill-kit:extract skill will decide whether to actually create a new
skill based on its quality criteria.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
