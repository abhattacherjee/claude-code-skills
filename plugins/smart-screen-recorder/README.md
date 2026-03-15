# smart-screen-recorder

AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.

## What It Does

AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor + window bounds, then uses AI vision to analyze the recording, create a zoom script targeting specific UI elements, generate voiceover narration, and produce a polished demo video.

**Use when:**
- creating product demo videos, 
- recording and polishing UI walkthroughs, 
- turning raw screen recordings into narrated presentations, 
- re-processing existing recordings with different zoom/voiceover.

## Key Features

- **Pipeline Overview**
- **Step-by-Step Workflow**
- **Agent Definitions**
- **Scripts Reference**
- **Dependencies**
- **Lessons Learned**

## Usage

```bash
# Install dependencies
~/.claude/skills/smart-screen-recorder/scripts/install-deps.sh

# Record (Ctrl+C to stop) — captures screen + cursor + window bounds
~/.claude/skills/smart-screen-recorder/scripts/record.sh

# Then tell Claude: "process my recording into a demo video"
```

## Contents

- **1** skill(s), **0** command(s), **4** agent(s)

### Skills

- `smart-screen-recorder` — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor + window bounds, then uses AI vision to analyze the recording, create a zoom script targeting specific UI elements, generate voiceover narration, and produce a polished demo video.

### Agents

- `demo-director` — Senior Product Demo Director who analyzes screen recording frames to create zoom scripts and voiceover narration. NOT user-invocable — spawned by smart-screen-recorder skill.
- `zoom-qa-verifier` — Verifies and corrects zoom target bounding boxes by extracting full-resolution video frames and measuring actual UI element positions. NOT user-invocable — spawned by smart-screen-recorder skill.
- `voiceover-timing-fixer` — Post-production agent that detects and fixes voiceover timing overlaps by measuring actual TTS audio durations and rebuilding sequential timestamps. NOT user-invocable — spawned by smart-screen-recorder skill.
- `demo-post-production-editor` — Post-production editor who reviews the final demo video output for quality, verifying zoom targets match voiceover, pacing feels natural, and the overall narrative is compelling. Can request re-cuts from other agents. NOT user-invocable — spawned by smart-screen-recorder skill.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install smart-screen-recorder@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/smart-screen-recorder
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/smart-screen-recorder/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall smart-screen-recorder@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/smart-screen-recorder
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
