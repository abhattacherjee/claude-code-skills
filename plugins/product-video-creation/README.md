# product-video-creation

Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.

## What It Does

Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, and TTS voiceover (OpenAI or macOS).

**Use when:**
- user asks to create a product video or demo reel, 
- user wants an Instagram Reel or YouTube video showcasing their app, 
- user has a running web app and wants animated marketing content, 
- user provides brand guidelines to apply to a video project.

## Key Features

- **Problem**
- **Architecture**
- **Quick Reference — Skill Scripts**
- **Progress Tracking (MANDATORY)**
- **Phase 0: Project Setup & Voice Selection**
- **Phase 1: Story & Narrative (AI-Driven)**
- **Phase 2: Screenshot Capture (Script)**
- **Phase 3: Voiceover Generation**
- **Phase 4: Scene Components (AI-Generated Code)**
- **Phase 5: Brand Application**
- **Phase 6: Background Music (AI-Curated)**
- **Phase 7: Audio Mixing & Composition**

## Contents

- **1** skill(s), **0** command(s), **4** agent(s)

### Skills

- `product-video-creation` — Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, and TTS voiceover (OpenAI or macOS).

### Agents

- `product-video-storyteller` — Crafts compelling product video narratives with scene-by-scene scripts. NOT user-invocable — spawned by product-video-creation skill.
- `product-video-narrator` — Generates TTS voiceover audio for product videos using OpenAI or macOS voices. NOT user-invocable — spawned by product-video-creation skill.
- `product-video-music-curator` — Finds royalty-free background music matching a product video's narrative arc and brand tone. NOT user-invocable — spawned by product-video-creation skill.
- `product-video-audio-mixer` — Mixes voiceover narration with background music using ffmpeg, applying ducking, fades, and volume balancing. NOT user-invocable — spawned by product-video-creation skill.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install product-video-creation@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/product-video-creation
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/product-video-creation/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall product-video-creation@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/product-video-creation
rm -rf /tmp/ccs
```

## See Also

- `remotion-best-practices` — general Remotion coding patterns
- `smart-screen-recorder` — alternative: record real screen + AI post-processing
- **[references/scene-architecture.md](references/scene-architecture.md)** — scene templates, animation patterns, phone mockups

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
