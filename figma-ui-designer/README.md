# figma-ui-designer

Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code.

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/figma-ui-designer ~/.claude/skills/figma-ui-designer
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set figma-ui-designer
cp -r figma-ui-designer ~/.claude/skills/figma-ui-designer
rm -rf /tmp/ccs
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r figma-ui-designer ~/.claude/skills/figma-ui-designer

# If installed from individual repo
git -C ~/.claude/skills/figma-ui-designer pull
```

## What It Does

Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
