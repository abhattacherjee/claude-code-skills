---
allowed-tools: Bash(git:*), Read
description: Display comprehensive Git Flow status including branch type, sync status, changes, and merge targets
---

# Git Flow Status

Display comprehensive Git Flow repository status.

## Task

Run the `git-flow` skill's diagnostic script and present the results:

```bash
~/.claude/skills/git-flow/scripts/git-flow-status.sh
```

For programmatic consumption (e.g., when deciding next actions):

```bash
~/.claude/skills/git-flow/scripts/git-flow-status.sh --json
```

### Supplement with Branch-Specific Guidance

After running the script, provide context-aware guidance based on the current branch type:

**Feature branches:** Remind about `/finish` when clean and synced.
**Release/Hotfix branches:** Remind about `/finalize-release` or `/finish`.
**Develop:** Suggest `/feature <name>` for new work, `/release <version>` if many commits ahead of main.
**Main:** Warn about direct commits, suggest branching commands.

## Related Commands

- `/feature <name>` — Create feature branch
- `/release <version>` — Create release branch
- `/hotfix` — Create hotfix branch from main
- `/finish` — Complete current branch
- `/finalize-release` — Ship release/hotfix with parallel artifact generation (project-specific)
- `git-flow` skill — Branching model reference, conventions, and diagnostic script
