# skill-authoring

A Claude Code skill for creating and optimizing other Claude Code skills, following Anthropic's official best practices.

## Installation

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/abhattacherjee/skill-authoring.git ~/.claude/skills/skill-authoring

# Windows
git clone https://github.com/abhattacherjee/skill-authoring.git %USERPROFILE%\.claude\skills\skill-authoring
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/abhattacherjee/skill-authoring.git .claude/skills/skill-authoring
```

## Updating

```bash
git -C ~/.claude/skills/skill-authoring pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/skill-authoring
```

## What It Does

This skill guides Claude through the full lifecycle of skill authoring:

- **Creating new skills** from scratch with proper structure and frontmatter
- **Optimizing existing skills** that are too large (>500 lines) or poorly organized
- **Decomposing complex skills** into orchestrator + parallel sub-agent architectures
- **Extracting scripts** for deterministic operations (validation, extraction, fixing)
- **Restructuring directories** into the canonical `SKILL.md + scripts/ + references/` layout
- **Auditing cross-references** for stale or broken links

### Key Topics

| Topic | Description |
|---|---|
| Frontmatter rules | Required fields, naming, description format |
| Directory layout | What goes in SKILL.md vs scripts/ vs references/ |
| Script extraction | When and how to extract deterministic procedures |
| Agent design | Orchestrator pattern, sub-agent specialization, parallelization |
| Skill templates | Simple (script-only) and complex (orchestrator + agents) |
| Quality checklist | Pre-publish verification across frontmatter, content, scripts, and cross-references |
| Anti-patterns | Common mistakes to avoid (sequential agents, monolithic design, verbose prose) |

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
skill-authoring/
├── .gitignore
├── CHANGELOG.md
├── LICENSE
├── README.md
├── SKILL.md
└── references/
    └── quality-checklist.md
```

## License

[MIT](LICENSE)
