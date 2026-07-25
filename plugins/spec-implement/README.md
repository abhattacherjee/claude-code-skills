# spec-implement

Implements a previously created and reviewed story spec end-to-end: feature branch, sub-task implementation with progress tracking, acceptance-criteria validation, and PR creation.

## What It Does

Implements a previously created and reviewed story spec end-to-end: reads the spec, creates a feature branch, implements all sub-tasks with progress tracking, validates acceptance criteria, updates tracking files, and creates a PR. Delegates to brainstorming/frontend-design/ui-from-requirements for complex UI work.

**Use when:**
- user says /spec-implement or 'implement this spec', 
- a story spec has been created and reviewed and is ready for implementation, 
- user provides a spec file path to implement.

## Key Features

- **Usage**
- **Progress Tracking (MANDATORY)**
- **Workflow**
- **Skill Delegation Matrix**
- **Error Recovery**

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `spec-implement` — Implements a previously created and reviewed story spec end-to-end: reads the spec, creates a feature branch, implements all sub-tasks with progress tracking, validates acceptance criteria, updates tracking files, and creates a PR. Delegates to brainstorming/frontend-design/ui-from-requirements for complex UI work.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install spec-implement@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/spec-implement
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/spec-implement/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall spec-implement@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/spec-implement
rm -rf /tmp/ccs
```

## See Also

- `spec-creator` — creates the specs this skill implements
- `spec-review` — reviews specs for accuracy before implementation
- `finish` — merges the feature branch after PR approval
- `ui-pr-review` — reviews the PR for design system compliance
- `ui-from-requirements` — full UI build pipeline for complex specs

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
