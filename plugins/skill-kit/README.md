# skill-kit

<!-- plugin-meta:start -->
**Version:** 1.0.2 · **3** skills · **0** agents · **0** commands
<!-- plugin-meta:end -->

Three skills for the life of a Claude Code skill, in one install. `author` writes and optimizes it, `publish` packages it as a plugin and syncs it to a GitHub monorepo, and `extract` turns what a work session taught you into a new or updated skill.

```shell
/plugin install skill-kit@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/skill-kit:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `author` | `skill-authoring` | Creates and optimizes Claude Code skills following Anthropic's official best practices, with emphasis on agent parallelization and script-first determinism. |
| `publish` | `skill-publishing` | Publishes skills as installable plugins and syncs them to a GitHub monorepo. Plugin-first: every skill with a `plugin-manifest.json` is auto-assembled and synced as a plugin. Also supports bare skills and individual repos. |
| `extract` | `claudeception` | Extracts reusable knowledge from work sessions and codifies it into Claude Code skills. It is a customized fork of [blader/Claudeception](https://github.com/blader/Claudeception). |

The usual order is `extract` (or you) finds something worth keeping, `author` shapes the skill, and `publish` ships it.

## `author`

Your guide to writing high-quality skills. When you invoke it (or when Claude sees you creating a skill), it provides:

- **Structured authoring workflow**: from checking for existing skills to validation.
- **Frontmatter rules**: exactly which fields to use (`name`, `description`, `metadata.version`) and which to avoid.
- **Directory layout conventions**: where to put `SKILL.md`, `scripts/`, `references/` and agent definitions.
- **Script-first methodology**: when to extract deterministic logic into bash scripts and when to keep it in `SKILL.md` prose.
- **Agent decomposition patterns**: how to split complex skills into parallel sub-agents with an orchestrator.
- **Quality checklist**: verify your skill meets all requirements before publishing.
- **Anti-patterns**: common mistakes like sequential agents, monolithic prompts and verbose explanations.

### Decomposition framework

It evaluates whether your skill should use parallel agents:

| Signal | Approach |
|--------|----------|
| 2+ independent subtasks | Parallel sub-agents |
| Web search or AI judgement needed | Dedicated agent per domain |
| N items of the same type | Fan-out: one agent per item |
| Single deterministic check | Script only, no agent |

### Script extraction

It decides when to extract bash scripts from `SKILL.md`:

- The skill checks, validates or detects something: extract.
- The same code block appears in multiple skills: extract.
- Users may run it standalone: extract.

Scripts follow conventions: `--help`, `--fix`, `--dry-run`, meaningful exit codes, `#!/usr/bin/env bash`.

### Templates

Two ready-to-use templates:

1. **Simple skill**: script-only, no agents (for validation and detection tasks).
2. **Complex skill**: orchestrator + parallel agents + scripts (for multi-phase workflows).

Ask in plain words:

```
"Create a skill for validating catalog URLs"
"Optimize my deployment skill, it's over 600 lines"
"Following skill-kit:author best practices, write a SKILL.md for..."
```

## `publish`

Use it when you say "publish", "share" or "sync" a skill, need a skill installable by others, sync skills or plugins to the monorepo, cut a versioned monorepo release, assemble a plugin from skills and commands, or "publish plugin" / "package plugin".

It covers five workflows:

- **A**: publish a new skill (individual repo).
- **B**: sync to the monorepo.
- **C**: sync individual repos.
- **D**: monorepo release (version tag).
- **E**: publish a plugin (manual fallback).

The architecture, the interactive publishing flow and the design trade-offs are in the skill's `SKILL.md`.

## `extract`

Every time you use an AI coding agent, it starts from zero. You spend an hour debugging an obscure error, the agent figures it out, the session ends. Next time you hit the same issue, it is another hour. This skill persists discoveries as reusable skills.

### Changes from upstream

This fork customizes the original Claudeception:

1. **Skill-authoring integration**: delegates skill creation to `skill-kit:author` for consistent structure, frontmatter conventions and quality checks.
2. **Existing skills check (Step 1)**: before creating a new skill, searches project and user-level skill directories to decide: create new, update existing, or add cross-references.
3. **Project artifact updates (Step 5)**: after saving a skill, updates `CHANGELOG.md` and uses the right commit prefix (`docs(skills):` or `fix(skills):`).
4. **Streamlined frontmatter**: uses `metadata.version` instead of top-level `version`, and drops `author`, `date`, `tags` and `allowed-tools` per Anthropic best practices.
5. **Concise research section**: a one-line strategy instead of verbose search instructions.
6. **See Also cross-references**: links to `skill-kit:author` and Anthropic's official docs.

The original's core concepts (trigger conditions, quality gates, automatic and explicit modes, retrospective) are unchanged.

### Automatic mode

The skill activates when Claude Code:

- completed debugging with a non-obvious solution,
- found a workaround through investigation or trial and error,
- resolved an error where the root cause was not immediately apparent,
- learned project-specific patterns through investigation.

### Explicit mode

```
/skill-kit:extract
```

Or: `Save what we just learned as a skill`. The old `/claudeception` still matches as a trigger phrase.

### What gets extracted

Not every task produces a skill. It extracts only knowledge that took real discovery (not just reading docs), will help with future tasks, has clear trigger conditions and has been verified to work.

### Activation hook (optional)

The skill activates by semantic matching. A hook makes Claude check every session for extractable knowledge. The plugin does not register it; you opt in.

1. Copy `skills/extract/scripts/claudeception-activator.sh` from the installed plugin:

```bash
mkdir -p ~/.claude/hooks
cp <PLUGIN_DIR>/skills/extract/scripts/claudeception-activator.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/claudeception-activator.sh
```

`<PLUGIN_DIR>` is the installed skill-kit directory under `~/.claude/plugins/`.

2. Add the hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/claudeception-activator.sh"
          }
        ]
      }
    ]
  }
}
```

The hook tells Claude to use `Skill(skill-kit:extract)`.

### Examples

`skills/extract/examples/` has sample skills:

- `nextjs-server-side-error-debugging/`: errors that do not show in the browser console.
- `prisma-connection-pool-exhaustion/`: the "too many connections" serverless problem.
- `typescript-circular-dependency/`: detecting and fixing import cycles.

### Research

The idea comes from academic work on skill libraries for AI agents. [Voyager](https://arxiv.org/abs/2305.16291) (Wang et al., 2023) showed that game-playing agents can build up libraries of reusable skills over time. [CASCADE](https://arxiv.org/abs/2512.23880) (2024) introduced "meta-skills" (skills for acquiring skills), which is what this is. [SEAgent](https://arxiv.org/abs/2508.04700) (2025) showed agents can learn new software environments through trial and error. [Reflexion](https://arxiv.org/abs/2303.11366) (Shinn et al., 2023) showed that self-reflection helps. More on the skills architecture [here](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills).

## Scripts

Each skill's commands run its own scripts through `${CLAUDE_SKILL_DIR}`, so they work from your project directory. You normally do not run them yourself.

| Skill | Script | Purpose |
|---|---|---|
| `author` | `validate-skill.sh <skill-dir>` | Checks frontmatter fields, description format, body length and script conventions. |
| `author` | `generate-task-manifest.sh --skill-dir <dir> --workflows "name:count,..."` | Scaffolds a `task-manifest.sh` with placeholder tasks in the skill's `scripts/` directory. |
| `publish` | `validate-pre-sync.sh <monorepo-dir>` | Pre-sync gate (mandatory before a sync). |
| `publish` | `sync-monorepo.sh [--dry-run] [--init] [--add <skill>] <monorepo-dir>` | Syncs skills and plugins into the monorepo; auto-builds plugins. |
| `publish` | `release-monorepo.sh patch\|minor\|major <monorepo-dir>` | Version tag and release for the monorepo. |
| `publish` | `prepare-plugin.sh <plugin-manifest.json>` | Assembles a plugin from a manifest. |
| `publish` | `validate-plugin.sh <plugin-dir>` | Validates an assembled plugin. |
| `publish` | `install-plugin.sh <plugin-dir>` | Installs a plugin locally. |
| `publish` | `prepare-skill-repo.sh <skill-dir>` | First-time publish of a skill as its own repo. |
| `publish` | `sync-individual-repos.sh [--all] [--push]` | Syncs published individual repos. |
| `publish` | `apply-branch-protection.sh [--all] [--dry-run] [repo-name...]` | Applies branch protection rulesets to the published repos. |
| `publish` | `validate-skill.sh <skill-dir>` | Same validator as `author`. |
| `extract` | `claudeception-activator.sh` | Optional hook text (see above). |
| `extract` | `validate-skill.sh <skill-dir>` | Same validator as `author`. |

## Install and uninstall

Install the plugin; do not copy the skills by hand. A loose copy breaks the `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` paths and shadows the plugin.

```shell
/plugin marketplace add abhattacherjee/claude-code-skills
/plugin install skill-kit@claude-code-skills
/plugin uninstall skill-kit@claude-code-skills
```

If you used the old names, install `skill-kit` first, then remove the old `skill-authoring`, `skill-publishing` and `claudeception` copies so they cannot win a plain-language request.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Acknowledgments

`extract` is based on the original concept and implementation by [blader](https://github.com/blader/Claudeception).

## License

[MIT](LICENSE). The `extract` skill is a fork of [blader/Claudeception](https://github.com/blader/Claudeception), MIT, "Copyright (c) 2024 Claude Code". Its original license and copyright notice are kept in [`skills/extract/LICENSE`](skills/extract/LICENSE).
