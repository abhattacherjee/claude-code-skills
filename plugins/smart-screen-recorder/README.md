# Smart Screen Recorder

AI-driven screen recording and demo production pipeline for macOS. Records your screen, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos with a narration-first integrated timeline.

**Version:** 4.2.0 | **1** skill, **6** agents | **License:** MIT

## What It Does

Turn any raw screen recording into a professional narrated demo video. The pipeline:

1. **Records** your screen + cursor movements
2. **Extracts** key frames for AI analysis
3. **Brainstorms** narrative themes with a dedicated Storyteller agent
4. **Directs** the demo with AI-crafted zoom scripts and voiceover
5. **Previews** the timeline in an interactive HTML page before rendering
6. **Renders** a polished 4K video with synchronized narration

**Use when:**
- Creating product demo videos from screen recordings
- Recording and polishing UI walkthroughs
- Turning raw recordings into narrated presentations
- Re-processing existing recordings with different zoom/voiceover

## Pipeline Architecture

```
Record ──> Extract ──> Voice  ──> Storyteller ──> Demo Director ──> TTS ──> Preview ──> Render
  |          Frames     Select     (brainstorm     (AI agent)       |       HTML        4K
  MKV +      as PNGs    (user)      3 themes)      Zoom script +   OpenAI  Review      Video
  cursor     + manifest             User picks      voiceover       nova    Iterate     + Audio
```

**Key architecture (v4.0+): Narration-first integrated timeline.**

The video and narration are built TOGETHER, not separately:
- Each narration segment is paired with a specific source frame to freeze on
- The renderer alternates between PLAY (advance source) and HOLD (freeze + narrate)
- Output is longer than source — extra time is frozen frames where the narrator describes what's on screen

## Workflow (12 Steps with Progress Tracking)

The skill tracks progress with a live task checklist so you always know where you are:

```
 1. [x] Record screen              - Capture raw video + cursor data
 2. [x] Extract frames             - Pull key frames as PNGs for AI analysis
 3. [x] Voice & context            - Select TTS voice + gather product description
 4. [x] Brainstorm narrative       - Storyteller proposes 3 themes, you pick one
 5. [x] Demo Director              - AI creates zoom + voiceover scripts
 6. [x] Verify zoom targets        - QA agent corrects bounding boxes at full resolution
 7. [x] Generate TTS               - Create audio segments from voiceover script
 8. [x] Build timeline             - Construct integrated PLAY + HOLD sequence
 9. [ ] Preview & feedback          - Interactive HTML review with per-section feedback
10. [ ] Render video               - Full 4K render from approved timeline
11. [ ] Mix audio                  - Place TTS at precise output timestamps
12. [ ] Post-production            - Quality gate: PASS / NEEDS_FIXES / RESHOOT
```

### Step 3.7: Narrative Brainstorming

Before the Demo Director runs autonomously, the **Demo Storyteller** agent analyzes your recording frames and proposes 3 distinct narrative themes:

```
Based on your recording, I identified these key moments:
- Landing page with hero image and CTA
- Multi-step onboarding flow with user selections
- Processing/loading screen with progress indicators
- Results dashboard with personalized recommendations

Here are 3 narrative directions:

A) The Journey — "Meet [Product]. Your personal guide to [domain]."
   Tone: warm, personal, storytelling
   Best for: social media, landing pages

B) Two Minutes Flat — "Two minutes. That's all it takes."
   Tone: punchy, energetic, feature-focused
   Best for: Product Hunt, investor pitches

C) Behind the Curtain — "Powered by AI. Built on real data."
   Tone: authoritative, detailed, trust-building
   Best for: blog posts, comparison pages

Which direction resonates? You can also mix elements.
```

Your choice becomes the **narrative brief** that guides the Demo Director's tone, pacing, and emphasis.

### Step 7.5: Interactive Preview

Before spending 5+ minutes on a full render, review everything in an interactive HTML preview at `http://localhost:8111`:

```
+---------------------------------------------------------------+
| Demo Preview — Timeline Review                                |
| Total: 2:59 | Segments: 29 | Holds: 14 | TTS: 28 clips      |
| [Play All (Sequential)]                                       |
+---------------------------------------------------------------+
|                                                                |
| HOLD — 4.7s at source t=82.5s              0:54 -> 0:59       |
| Results dashboard — personalized recommendations              |
| +----------------------------------------------------------+  |
| |                                                          |  |
| |              [Full-width screenshot of the               |  |
| |               frame frozen during this hold]             |  |
| |                                                          |  |
| +----------------------------------------------------------+  |
|                                                                |
| #9  [Play] And here it is. Your personalized        4.7s      |
|            dashboard. Everything in one place,                 |
|            built just for you.                                 |
|     [==========>                         ] progress            |
|                                                                |
| [Feedback for this section...                              ]   |
|                                                                |
+---------------------------------------------------------------+
| PLAY — 1.5s (source 83.0s -> 87.5s)                           |
| Carousel advances to show more days                            |
+---------------------------------------------------------------+
|                                                                |
| HOLD — 5.4s at source t=87.5s              0:59 -> 1:05       |
| ...                                                            |
+---------------------------------------------------------------+
```

**Preview features:**
- **Full-width screenshot** for each HOLD and PLAY segment
- **Numbered audio segments** (#1, #2, ...) with transcribed narration text and play/pause buttons
- **Progress bars** on each audio clip during playback
- **Per-section feedback** text boxes that auto-save to localStorage
- **Play All** button for sequential narration review (spacebar to pause)
- **Server-side feedback** — "Save Feedback" POSTs directly to the server so Claude reads it without file downloads

Reference specific clips by number in your feedback: *"Audio #14 doesn't match the screenshot"* or *"#9 sounds too fast, regenerate slower."*

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| **Demo Storyteller** | sonnet | Analyzes frames, proposes 3 narrative themes for user brainstorming |
| **Demo Director** | opus | Creates zoom-script.json + voiceover-script.json from frames + narrative brief |
| **Zoom QA Verifier** | opus | Extracts full-res frames at zoom timestamps, corrects bounding boxes |
| **Voiceover Timing Fixer** | sonnet | Detects TTS audio overlaps, rebuilds sequential timestamps |
| **Post-Production Editor** | opus | Reviews final output for quality, can request re-cuts |

## Quick Start

```bash
# Install dependencies
~/.claude/skills/smart-screen-recorder/scripts/install-deps.sh

# Record (Ctrl+C to stop)
~/.claude/skills/smart-screen-recorder/scripts/record.sh

# Then tell Claude:
# "process my recording into a demo video"
```

Or invoke the skill directly:
```
/smart-screen-recorder
```

## Scripts

| Script | Purpose |
|--------|---------|
| `record.sh` | Record screen + cursor (MKV for crash safety, remux to MP4) |
| `extract-frames.py` | Extract key frames as PNGs for AI analysis |
| `generate-tts.py` | Generate OpenAI/macOS TTS audio |
| `build-timeline.py` | Build integrated PLAY+HOLD timeline |
| `preview-timeline.py` | Generate interactive HTML preview (localhost:8111) |
| `render-timeline.py` | Render video from timeline with zoom effects |
| `mix-audio.py` | Mix TTS segments into rendered video |
| `install-deps.sh` | Install ffmpeg, pyobjc, opencv, numpy |

## Dependencies

| Dependency | Install | Purpose |
|------------|---------|---------|
| ffmpeg | `brew install ffmpeg` | Screen capture + video encoding |
| opencv-python | `pip3 install opencv-python` | Frame extraction + processing |
| pyobjc-framework-Quartz | `pip3 install pyobjc-framework-Quartz` | Cursor + window tracking |
| OPENAI_API_KEY (optional) | `export OPENAI_API_KEY=sk-...` | Natural TTS voices (nova recommended) |

macOS only. Requires Screen Recording + Accessibility permissions.

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
cp -r plugins/smart-screen-recorder/skills/* ~/.claude/skills/
cp plugins/smart-screen-recorder/agents/* ~/.claude/agents/
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
