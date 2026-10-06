# context-shield

<!-- plugin-meta:start -->
**Version:** 1.3.3 · **1** skill · **1** agent · **0** commands
<!-- plugin-meta:end -->

Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.

## What It Does

Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count.

**Use when:**
- reading 3+ large external sources (URLs, Figma frames, wiki pages), 
- large documentation/API reference sites decomposed into section URLs, 
- monorepo code audits across many directories, 
- dependency upgrade research across 5+ packages, 
- large PR reviews with 15+ changed files, 
- competitive feature matrix analysis, 
- security advisory triage for dependency updates.

## Key Features

- **When to Use**
- **Visualization**
- **Workflow**
- **Architecture**
- **Content Source Format**
- **Agent Definition**
- **Common Patterns**

## Usage

```bash
SCRIPTS=~/.claude/skills/context-shield/scripts

# Create manifest from sources
$SCRIPTS/manage-manifest.sh create --task "Analyze competitor UIs" --output-dir /tmp/cs-run \
  "url:https://dribbble.com/shots/travel-app,label=Dribbble Travel" \
  "figma:fileKey=xYz,nodeId=5:42,label=Current Homepage"

# Check progress
$SCRIPTS/manage-manifest.sh status --manifest /tmp/cs-run/manifest.json

# Get next batch
$SCRIPTS/manage-manifest.sh next-batch --manifest /tmp/cs-run/manifest.json

# Collect all summaries
$SCRIPTS/manage-manifest.sh summaries --manifest /tmp/cs-run/manifest.json

# Visualize workflow (full animated demo)
$SCRIPTS/visualize.sh full-demo
```

## Contents

- **1** skill(s), **0** command(s), **1** agent(s)

### Skills

- `context-shield` — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count.

### Agents

- `content-distiller` — Reads a single content source (URL, Figma node, file, wiki page, codebase section) in an isolated context and returns a distilled summary. Absorbs token-heavy content so the parent context stays lean. NOT user-invocable — spawned by context-shield skill.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install context-shield@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/context-shield
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/context-shield/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall context-shield@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/context-shield
rm -rf /tmp/ccs
```

## See Also

- `figma-ui-designer` — use context-shield when analyzing 10+ Figma frames or 5+ competitor designs
- `spec:review` — use context-shield when a spec references many external docs or code directories
- `project-code-review` — use context-shield for large PRs with 15+ changed files
- `npm-dependency-management` — use context-shield to research 5+ package changelogs before upgrades
- `ci-security-issue-creator` — use context-shield to triage many CVE/GHSA advisory pages
- `conversation-search` — use context-shield when summarizing multiple large conversations at once
- `ralph-loop` plugin — provides the iteration mechanism for multi-batch processing
- `content-distiller` agent (`~/.claude/agents/content-distiller.md`) — the isolated reader

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
