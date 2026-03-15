# custom-statusline

4-tier adaptive statusline with icons for folder, git branch, and context usage.

## Preview

**Wide (desktop / iPad) — single line:**
```
Claude Opus 4.6 (1M context) | 📁 my-project | 🌿 develop(ok) | 🧠 ●●●●●●●●●○○○○○○○○○○○○○○○○ 36%
```

**Narrow (phone SSH / small terminal) — two lines:**
```
Claude Opus 4.6 (1M context) | 📁 my-project
🌿 feature/auth(~2|+1) | 🧠 ●●●●●●○○○○○○○○○ 42%
```

**Ultra-narrow (<40 cols):**
```
●●●○○○○○ 38% develop(ok)
```

The layout switches dynamically based on your terminal width — no configuration needed. Works across Mac, iPad, and iPhone via tmux SSH.

## What It Does

Installs an adaptive Claude Code statusline showing:

- 📁 **Project directory** name
- 🌿 **Git branch** with compact sync status: `develop(ok)`, `feat/foo(~2|+1)`, `main(local)`
- 🧠 **Context usage** with color-coded progress bar (green < 50%, yellow < 80%, red 80%+)

## Key Features

- **Dynamic layout** — auto-detects content width and switches between 1-line and 2-line
- **tmux-aware** — reads `#{window_width}` so it adapts when you switch between devices
- **Multi-device SSH** — works on Mac, iPad, and iPhone via tmux sessions

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `install-statusline` — Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install custom-statusline@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/custom-statusline
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/custom-statusline/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall custom-statusline@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/custom-statusline
rm -rf /tmp/ccs
```

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
