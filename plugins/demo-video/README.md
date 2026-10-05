# demo-video

Demo videos in one install: **2** skills and **9** agents. `record` turns a macOS screen recording into a narrated demo. `produce` builds a narrated product video in code with Remotion. Version 1.0.0 | **License:** MIT

```shell
/plugin install demo-video@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/demo-video:record` and `/demo-video:produce`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `record` | `smart-screen-recorder` (4.3.0) | AI-driven screen recording and demo production pipeline for macOS. Records your screen, cursor and window bounds, analyzes the recording with AI vision, writes zoom scripts and voiceover narration, and produces a polished demo video with a narration-first integrated timeline. |
| `produce` | `product-video-creation` (2.0.0) | Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover (OpenAI or macOS) and background music. |

### Use `record` when

- you create product demo videos from screen recordings,
- you record and polish UI walkthroughs,
- you turn raw recordings into narrated presentations,
- you re-process an existing recording with different zoom or voiceover.

### Use `produce` when

- you ask for a product video or demo reel,
- you want an Instagram Reel or YouTube video showcasing your app,
- you have a running web app and want animated marketing content,
- you give brand guidelines to apply to a video project.

If you have a real screen recording, use `record`. If you want animated scenes built from screenshots, use `produce`.

## record

### What it does

Turns any raw screen recording into a professional narrated demo video. The pipeline:

1. **Records** your screen + cursor movements
2. **Extracts** key frames for AI analysis
3. **Brainstorms** narrative themes with a dedicated Storyteller agent
4. **Directs** the demo with AI-crafted zoom scripts and voiceover
5. **Previews** the timeline in an interactive HTML page before rendering
6. **Renders** a polished 4K video with synchronized narration

### Pipeline architecture

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

### Workflow (12 steps with progress tracking)

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

#### Step 3.7: Narrative brainstorming

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

#### Step 7.5: Interactive preview

Before spending 5+ minutes on a full render, review everything in an interactive HTML preview. It is served on 127.0.0.1 only, at a URL with a token made for each run (`http://127.0.0.1:8111/<token>/preview.html`):

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

### Quick start

```shell
/demo-video:record
```

Then tell Claude: "process my recording into a demo video". The skill installs the dependencies and runs the scripts for you. To record, it runs `record.sh` (press Ctrl+C to stop).

### Scripts

The skill runs them through `${CLAUDE_SKILL_DIR}`, so they work from your project directory. You normally do not run them yourself.

| Script | Purpose |
|---|---|
| `record.sh` | Record screen + cursor + window bounds (MKV for crash safety, remux to MP4) |
| `cursor-tracker.py` | Track cursor, clicks and the active window through the Quartz API |
| `extract-frames.py` | Extract key frames as PNGs for AI analysis |
| `apply-zoom-script.py` | Apply a zoom script with trim, bounding boxes and 4K output |
| `generate-tts.py` | Generate OpenAI/macOS TTS audio |
| `build-timeline.py` | Build the integrated PLAY+HOLD timeline |
| `preview-timeline.py` | Generate the interactive HTML preview (127.0.0.1:8111, token in the URL) |
| `render-timeline.py` | Render video from the timeline with zoom effects |
| `mix-audio.py` | Mix TTS segments into the rendered video |
| `smart-zoom.py` | Legacy heuristic zoom modes (focus/click/velocity) |
| `install-deps.sh` | Install ffmpeg, pyobjc, opencv, numpy |

### Dependencies

| Dependency | Install | Purpose |
|---|---|---|
| ffmpeg | `brew install ffmpeg` | Screen capture + video encoding |
| opencv-python | `pip3 install opencv-python` | Frame extraction + processing |
| pyobjc-framework-Quartz | `pip3 install pyobjc-framework-Quartz` | Cursor + window tracking |
| numpy | (with opencv) | Array operations |
| OPENAI_API_KEY (optional) | `export OPENAI_API_KEY=sk-...` | Natural TTS voices (nova recommended) |

macOS only. Requires Screen Recording permission for Terminal. Click tracking requires Accessibility permission.

## produce

### What it does

Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, and TTS voiceover (OpenAI or macOS).

Phases:

- **Phase 0:** project setup and voice selection
- **Phase 1:** story and narrative (AI-driven)
- **Phase 2:** screenshot capture (script)
- **Phase 3:** voiceover generation
- **Phase 4:** scene components (AI-generated code)
- **Phase 5:** brand application
- **Phase 6:** background music (AI-curated)
- **Phase 7:** audio mixing and composition
- **Phase 8:** render and preview

The skill also covers the problem it solves, the architecture, a quick reference for its scripts, and mandatory progress tracking.

### Quick start

```shell
/demo-video:produce make a 9:16 product reel for my app
```

### Scripts

The skill runs them through `${CLAUDE_SKILL_DIR}`, so they work from your project directory.

| Script | Purpose |
|---|---|
| `scaffold-project.sh` | Scaffold a new Remotion + Tailwind + Lucide project with Google Fonts (no existing project needed) |
| `capture-screenshots.sh` | Capture screenshots of the running app (Playwright) |
| `generate-voiceover.sh` | Generate TTS voiceover (OpenAI or macOS) from a narration JSON |
| `render-and-preview.sh` | Lint, render to MP4, print specs, optionally make a contact sheet and open the player |
| `task-manifest.sh` | Emit the task manifest (JSON array) used for progress tracking |

Scene templates, animation patterns and phone mockups are in `skills/produce/references/scene-architecture.md`.

## Agents

Started by the skills and not meant to be invoked by hand. Claude Code adds the plugin prefix, so the agent types are `demo-video:<agent>`.

| Agent | Was | Started by | Model | Purpose |
|---|---|---|---|---|
| `demo-storyteller` | `demo-storyteller` (in `smart-screen-recorder`) | `record` | sonnet | Analyzes frames, proposes 3 narrative themes for user brainstorming |
| `demo-director` | `demo-director` (in `smart-screen-recorder`) | `record` | opus | Creates zoom-script.json + voiceover-script.json from frames + narrative brief |
| `zoom-qa-verifier` | `zoom-qa-verifier` (in `smart-screen-recorder`) | `record` | opus | Extracts full-res frames at zoom timestamps, corrects bounding boxes |
| `voiceover-timing-fixer` | `voiceover-timing-fixer` (in `smart-screen-recorder`) | `record` | sonnet | Detects TTS audio overlaps, rebuilds sequential timestamps |
| `demo-post-production-editor` | `demo-post-production-editor` (in `smart-screen-recorder`) | `record` | opus | Reviews final output for quality, can request re-cuts |
| `product-video-storyteller` | `product-video-storyteller` (in `product-video-creation`) | `produce` | opus | Crafts compelling product video narratives with scene-by-scene scripts |
| `product-video-narrator` | `product-video-narrator` (in `product-video-creation`) | `produce` | sonnet | Generates TTS voiceover audio using OpenAI or macOS voices |
| `product-video-music-curator` | `product-video-music-curator` (in `product-video-creation`) | `produce` | sonnet | Finds royalty-free background music matching the narrative arc and brand tone |
| `product-video-audio-mixer` | `product-video-audio-mixer` (in `product-video-creation`) | `produce` | sonnet | Mixes voiceover with background music using ffmpeg, with ducking, fades and volume balancing |

The agent names did not change. Shortening them would make `demo-storyteller` and `product-video-storyteller` collide.

## See also

- `remotion-best-practices`: general Remotion coding patterns (used by `produce`)

## Install and uninstall

Install the plugin; do not copy the skills by hand. A loose copy breaks the `${CLAUDE_SKILL_DIR}` paths and shadows the plugin.

```shell
/plugin marketplace add abhattacherjee/claude-code-skills
/plugin install demo-video@claude-code-skills
/plugin uninstall demo-video@claude-code-skills
```

If you used the old names, install `demo-video` first. Then remove the old `smart-screen-recorder` and `product-video-creation` skills and plugins, and any loose copies of these agents in your `~/.claude` agents folder, so they cannot win a plain-language request.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
