---
name: produce
description: "Was the product-video-creation skill (/product-video-creation still works as a phrase). Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, and TTS voiceover (OpenAI or macOS). Use when: (1) user asks to create a product video or demo reel, (2) user wants an Instagram Reel or YouTube video showcasing their app, (3) user has a running web app and wants animated marketing content, (4) user provides brand guidelines to apply to a video project."
metadata:
  version: 1.0.0
---

# Remotion Product Video Generator

## Problem

Creating a compelling product demo video requires storytelling, visual design, voiceover narration, and video editing — typically spread across After Effects, script writers, and voice talent. This skill generates broadcast-quality narrated product videos entirely in code, using AI reasoning for storytelling and TTS for voiceover.

## Architecture

```
Orchestrator (this skill — coordinates all phases)
├── product-video-storyteller (Opus agent — crafts narrative arc + scene scripts)
├── Screenshot capture (Playwright script — deterministic)
├── Scene components (Code generation — brand-aligned Remotion scenes)
├── product-video-narrator (Sonnet agent — generates TTS audio)
└── Composition wiring (Code — timing, audio sync, aspect ratio)
```

Start each agent by its plugin agent type, `demo-video:<agent>` (for example `demo-video:product-video-storyteller`). Never start one by a file path.

## Quick Reference — Skill Scripts

All scripts are in this skill's `scripts/` directory and are standalone. Run each command in a fresh shell from your Remotion project directory (the capture and render commands use paths relative to it):

```bash
# Scaffold a new project (no existing project needed)
"${CLAUDE_SKILL_DIR}/scripts/scaffold-project.sh" <PROJECT_DIR> --aspect 9:16

# Capture screenshots
"${CLAUDE_SKILL_DIR}/scripts/capture-screenshots.sh" ./public/screenshots --url https://myapp.com

# Generate voiceover
"${CLAUDE_SKILL_DIR}/scripts/generate-voiceover.sh" narration.json ./public/audio --provider openai --voice ash

# Render and preview
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh" --contact-sheet

# Task manifest
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" full-video
```

## Progress Tracking (MANDATORY)

Create tasks from the output of this command before starting:

```bash
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" full-video
```

## Phase 0: Project Setup & Voice Selection

### Step 0a: Scaffold project (if no Remotion project exists)

If the user is NOT already in a Remotion project, scaffold one:
```bash
"${CLAUDE_SKILL_DIR}/scripts/scaffold-project.sh" <PROJECT_DIR> --aspect 9:16
cd <PROJECT_DIR>
```

The script creates a complete Remotion + Tailwind + Lucide project with Google Fonts pre-configured. If `<PROJECT_DIR>/remotion.config.ts` already exists, it leaves the files alone and only runs `npm install` (skipped with `--skip-install`), so running it again after a failed install finishes the install.

### Step 0b: Voice Selection Brainstorm (INTERACTIVE)

**Before any work begins**, present the user with voice options. This is a brainstorming conversation.

### Step 1: Check TTS availability

```bash
# Check for OpenAI API key
if [ -n "$(printenv OPENAI_API_KEY)" ]; then echo "OpenAI TTS available"; else echo "No OpenAI key found"; fi
# List voices
"${CLAUDE_SKILL_DIR}/scripts/generate-voiceover.sh" --list-voices --provider openai
"${CLAUDE_SKILL_DIR}/scripts/generate-voiceover.sh" --list-voices --provider macos
```

### Step 2: Present options to the user

Ask the user to choose. Present it like this:

---

**How would you like the voiceover narrated?**

**Option A: OpenAI TTS** (recommended — natural, studio-quality voices with tone control)

| Voice | Character | Best for |
|-------|-----------|----------|
| **coral** | Clear, warm, natural | General product demos |
| **alloy** | Neutral, balanced | Explainers, general use |
| **nova** | Energetic, youthful | Tech/startup products |
| **sage** | Calm, wise | Wellness, premium brands |
| **fable** | Expressive, storytelling | Narrative-heavy videos |
| **onyx** | Deep, authoritative | Enterprise, B2B |
| **ash** | Warm, conversational | Friendly/casual brands |
| **shimmer** | Light, airy | Lifestyle, creative products |
| **echo** | Smooth, confident | Finance, professional |
| **cedar** | Warm, grounded | Nature, sustainability |
| **ballad** | Soft, melodic | Luxury, boutique |
| **verse** | Rich, articulate | Education, culture |
| **marin** | Bright, friendly | Social, community apps |

*Requires `OPENAI_API_KEY`. If not set, guide user:*
```bash
export OPENAI_API_KEY=sk-...  # From https://platform.openai.com/api-keys
```

**Option B: macOS Native Voice** (free, no API key, works offline)
- **Samantha** (en_US) — clear, standard
- **Daniel** (en_GB) — British accent
- **Karen** (en_AU) — Australian accent
- **Tara** (en_IN) — Indian English

**Option C: No voiceover** — visual-only video with on-screen text

---

Wait for user selection before proceeding.

## Phase 1: Story & Narrative (AI-Driven)

**This is NOT a heuristic template fill.** Launch the `product-video-storyteller` agent (Opus model) with `subagent_type: "demo-video:product-video-storyteller"` to craft the narrative.

### What the Storyteller agent receives:
- Product description and copy from the user
- Brand guidelines (if provided — colors, tone, target audience)
- App screenshots (described, not raw images)
- Target duration and aspect ratio
- Voice selection from Phase 0

### What the Storyteller agent returns:
A complete narrative with:
- **Emotional arc**: curiosity → discovery → desire → action
- **Scene-by-scene headlines, copy, and voiceover scripts**
- **Pacing guidance**: which scenes need silence, which need energy
- **Full concatenated narration** for TTS generation

**Present the narrative to the user for approval before proceeding.**
Allow them to revise tone, adjust copy, or change the story arc.

## Phase 2: Screenshot Capture (Script)

```bash
"${CLAUDE_SKILL_DIR}/scripts/capture-screenshots.sh" ./public/screenshots \
  --url http://localhost:5173 \
  --shared-url https://app.example.com/shared/abc \
  --hide-selectors ".fixed,.theme-toggle" \
  --fullpage
```

Or write a custom Playwright capture script for the specific app flow.

## Phase 3: Voiceover Generation

Save the storyteller's per-scene narration as JSON:
```json
[
  { "scene": "hook", "text": "What if the hardest part was already done?", "instructions": "Speak with gentle curiosity, like asking a friend." },
  { "scene": "intro", "text": "A smarter way to get started.", "instructions": "Warmer now, confident but not pushy." }
]
```

Run the script below, or hand the job to the `product-video-narrator` agent with `subagent_type: "demo-video:product-video-narrator"` (pass it the narration JSON, the voice, the provider and the output directory).

Generate audio:
```bash
"${CLAUDE_SKILL_DIR}/scripts/generate-voiceover.sh" narration.json ./public/audio \
  --provider openai --voice coral \
  --instructions "Speak warmly and calmly, like a thoughtful host."
```

### Audio Integration in Remotion

Add `<Audio>` components in the Composition, synced to scene `<Sequence>` timing:
```tsx
import { Audio, staticFile } from "remotion";

<Sequence from={0} durationInFrames={150}>
  <Audio src={staticFile("audio/01-hook.mp3")} />
  <HookScene />
</Sequence>
```

Adjust scene `durationInFrames` to match audio duration:
```ts
const audioDurationFrames = Math.ceil((audioDurationMs / 1000) * fps);
```

## Phase 4: Scene Components (AI-Generated Code)

Create scenes using the storyteller's output — **not hardcoded templates**. Each scene's headlines, copy, bullet points, and step descriptions come from the narrative.

See **[references/scene-architecture.md](references/scene-architecture.md)** for:
- Phone mockup components (PhoneMockup, AnimatedPhone, ScrollingPhone)
- Animation patterns (spring entries, crossfades, scroll easing)
- Aspect ratio layout rules

### Key components to create:
- `src/scenes/HookScene.tsx` — dramatic text reveal
- `src/scenes/IntroScene.tsx` — product name + value prop
- `src/scenes/AppShowcaseScene.tsx` + `AnimatedPhone.tsx` — cycling screenshots
- `src/scenes/VibesScene.tsx` — Lucide icon feature cards
- `src/scenes/HowItWorksScene.tsx` — numbered step process
- `src/scenes/ResultsScene.tsx` + `ScrollingPhone.tsx` — scrolling results
- `src/scenes/CtaScene.tsx` — closing headline + CTA

## Phase 5: Brand Application

If brand guidelines provided, extract and apply:
1. **Colors** → background, accent, secondary, text, muted
2. **Typography** → heading font, accent font, body font (via Google Fonts)
3. **Tone** → inform both visual style and voiceover `instructions`

## Phase 6: Background Music (AI-Curated)

Launch the `product-video-music-curator` agent with `subagent_type: "demo-video:product-video-music-curator"` to find royalty-free background music.

**What the curator receives:** narrative arc, brand tone, video duration, voiceover characteristics
**What it returns:** 3-5 track recommendations from Pixabay/Mixkit/FMA with download URLs

After user selects a track:
1. Download to `public/audio/bg-music.mp3`
2. Process with ffmpeg for fade-in/fade-out:
```bash
ffmpeg -i public/audio/bg-music-raw.mp3 \
  -af "afade=t=in:st=0:d=3,afade=t=out:st=<end-3>:d=3" \
  public/audio/bg-music.mp3
```

## Phase 7: Audio Mixing & Composition

Launch the `product-video-audio-mixer` agent with `subagent_type: "demo-video:product-video-audio-mixer"` OR use Remotion-native mixing (recommended).

### Remotion-Native Approach (simpler)
Add background music as a separate `<Audio>` spanning the full video:
```tsx
<Audio src={staticFile("audio/bg-music.mp3")} volume={0.10} startFrom={0} />
```

Volume guidelines:
- Background music during voiceover: **0.08–0.12** (~-18dB)
- Music during scene transitions (no voice): **0.20–0.30** (~-12dB)
- Use Remotion's `volume` callback for dynamic ducking

Wire scene `<Sequence>` timing from audio durations. Overlap by 10-15 frames for crossfades.

## Phase 8: Render & Preview

Use the `render-and-preview.sh` script for the full render → verify → preview pipeline:

```bash
# Render, show specs, and open in video player
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh"

# Render with contact sheet for visual verification
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh" --contact-sheet

# Custom output path
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh" --output out/reel-v2.mp4

# Render without opening player (CI/headless)
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh" --no-open --contact-sheet

# See all options
"${CLAUDE_SKILL_DIR}/scripts/render-and-preview.sh" --help
```

The script:
1. Runs eslint + tsc (fails fast on errors)
2. Auto-detects the composition ID from `Root.tsx`
3. Renders to MP4 via `npx remotion render`
4. Prints video specs (resolution, duration, size, codec)
5. Optionally generates a 7-frame contact sheet for visual verification
6. Opens the rendered video in the system player

### Contact Sheet Preview (for inline review)

After rendering with `--contact-sheet`, use the Read tool to display the contact sheet image to the user:
```
Read: out/video-contact-sheet.png
```

### Remotion Studio (for live iteration)

For frame-by-frame scrubbing during development:
```bash
npx remotion studio  # Opens at http://localhost:3000
```

## Agent Definitions

| Agent type | Model | Role |
|-------|-------|------|
| `demo-video:product-video-storyteller` | **Opus** | Crafts narrative arc, scene copy, voiceover scripts. Uses deep reasoning — not templates. |
| `demo-video:product-video-narrator` | Sonnet | Generates TTS audio files via OpenAI API or macOS `say` command. |
| `demo-video:product-video-music-curator` | Sonnet | Searches royalty-free music libraries, recommends tracks matching brand tone and narrative arc. |
| `demo-video:product-video-audio-mixer` | Sonnet | Mixes voiceover + background music with ducking, fades, and volume balancing. |

## Critical Rules

- **Never use CSS transitions** in Remotion — causes flickering. All animations from `useCurrentFrame()`
- **Use `<Img>` from remotion**, not `<img>`; use `staticFile()` for public/ assets
- **Audio must sync** — scene durations derived from audio file lengths, not arbitrary frame counts
- **Phone frames use Dynamic Island** (pill-shaped), not old-style wide notch
- **Present story to user** for approval before generating code or audio
- **Disclose AI voice** — OpenAI requires disclosure that TTS is AI-generated

## See Also

- `remotion-best-practices` — general Remotion coding patterns
- `demo-video:record` — alternative: record real screen + AI post-processing
- **[references/scene-architecture.md](references/scene-architecture.md)** — scene templates, animation patterns, phone mockups
