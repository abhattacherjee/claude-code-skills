# Remotion Product Video Generator

An AI-powered Claude Code skill that creates polished, narrated product demo videos from a running web app — complete with animated phone mockups, brand-aligned styling, AI voiceover, and background music.

## What It Does

Given a web app URL and a product description, this skill:

1. **Crafts a compelling narrative** using Claude Opus 4.6 — not templates, but reasoned storytelling with an emotional arc (yearning → discovery → ease → delight → invitation)
2. **Captures mobile screenshots** of your app using Playwright (hero, multi-step flows, full-page results)
3. **Generates AI voiceover** via OpenAI TTS (13 voice options with per-scene tone control) or macOS native voices
4. **Finds royalty-free background music** from Pixabay/Mixkit matching your brand's mood
5. **Builds a Remotion video** with animated scenes, iPhone 17 phone mockups, scrolling page effects, and crossfade transitions
6. **Renders to MP4** ready for Instagram Reels, YouTube, or any platform

## Example Output

A 68-second Instagram Reel (1080×1920) with:
- 7 animated scenes (hook → intro → app demo → features → how it works → results → CTA)
- Soft voiceover narrated by OpenAI's `ash` voice
- Gentle acoustic background music
- Real app screenshots in Dynamic Island phone frames
- Brand colors, fonts, and tone from your guidelines

## Architecture

```
Orchestrator (SKILL.md — coordinates all phases)
│
├── product-video-storyteller    [Opus]   Crafts narrative arc + voiceover scripts
├── product-video-music-curator  [Sonnet] Searches royalty-free music libraries
├── product-video-narrator       [Sonnet] Generates TTS audio (OpenAI or macOS)
├── product-video-audio-mixer    [Sonnet] Mixes voiceover + music with ducking
│
├── scripts/scaffold-project.sh          Scaffolds fresh Remotion project
├── scripts/capture-screenshots.sh       Playwright mobile screenshot capture
├── scripts/generate-voiceover.sh        TTS generation (OpenAI / macOS)
├── scripts/render-and-preview.sh        Render MP4 + contact sheet + preview
└── scripts/task-manifest.sh             Progress tracking for 5 workflows
```

## Workflow (9 Phases)

| Phase | What Happens | Interactive? |
|-------|-------------|:---:|
| **0a** | Scaffold Remotion project (if needed) | No |
| **0b** | Voice selection brainstorm — present 13 OpenAI voices + macOS options | Yes |
| **1** | Opus storyteller crafts narrative arc + scene scripts | Yes (approval) |
| **2** | Capture mobile screenshots via Playwright | No |
| **3** | Generate per-scene voiceover with OpenAI TTS | No |
| **4** | Create 7 animated Remotion scene components | No |
| **5** | Apply brand guidelines (colors, fonts, tone) | No |
| **6** | Music curator finds royalty-free background track | Yes (selection) |
| **7** | Mix audio + wire composition with timing sync | No |
| **8** | Render to MP4, generate contact sheet, open preview | No |

## Scripts

All scripts are standalone — invoke from any directory:

```bash
SKILL=~/.claude/skills/product-video-creation

# Scaffold a new video project
$SKILL/scripts/scaffold-project.sh ~/dev/my-video --aspect 9:16

# Capture screenshots from a running app
$SKILL/scripts/capture-screenshots.sh ./public/screenshots \
  --url https://myapp.com \
  --shared-url https://myapp.com/results/abc \
  --hide-selectors ".fixed,.cookie-banner" \
  --fullpage

# List available TTS voices
$SKILL/scripts/generate-voiceover.sh --list-voices --provider openai

# Generate voiceover from a narration script
$SKILL/scripts/generate-voiceover.sh narration.json ./public/audio \
  --provider openai --voice ash \
  --speed 0.9

# Render and preview
$SKILL/scripts/render-and-preview.sh --contact-sheet --output out/reel.mp4

# View task manifest for a workflow
$SKILL/scripts/task-manifest.sh full-video
```

## OpenAI TTS Voices

The skill supports all 13 OpenAI `gpt-4o-mini-tts` voices with per-scene tone instructions:

| Voice | Character | Best For |
|-------|-----------|----------|
| **coral** | Clear, warm, natural | General product demos |
| **ash** | Warm, conversational | Friendly/casual brands |
| **sage** | Calm, wise | Wellness, premium |
| **ballad** | Soft, melodic | Luxury, boutique |
| **cedar** | Warm, grounded | Nature, sustainability |
| **fable** | Expressive, storytelling | Narrative-heavy |
| **nova** | Energetic, youthful | Tech/startup |
| **onyx** | Deep, authoritative | Enterprise, B2B |
| **shimmer** | Light, airy | Lifestyle, creative |
| **echo** | Smooth, confident | Finance, professional |
| **verse** | Rich, articulate | Education, culture |
| **marin** | Bright, friendly | Social, community |

Falls back to **macOS native voices** (Samantha, Daniel, Karen, etc.) if no OpenAI API key is set.

## Phone Mockup Styles

All phone frames use the **iPhone 17 Dynamic Island** (pill-shaped cutout):

- **PhoneMockup** — static screenshot in a phone frame
- **AnimatedPhone** — crossfades between multiple screenshots with step indicator dots
- **ScrollingPhone** — tall full-page screenshot with eased vertical scroll animation

## Supported Aspect Ratios

| Format | Dimensions | Use Case |
|--------|-----------|----------|
| **9:16** | 1080×1920 | Instagram Reels, TikTok, YouTube Shorts |
| **16:9** | 1920×1080 | YouTube, website embeds |
| **1:1** | 1080×1080 | Instagram posts, LinkedIn |

## Prerequisites

- **Node.js** 18+
- **ffmpeg** (`brew install ffmpeg`) — for audio processing and video analysis
- **Playwright** (auto-installed by capture script)
- **OpenAI API key** (optional, for TTS voiceover — set `OPENAI_API_KEY`)

## Brand Guidelines Integration

If you provide a brand guidelines document (PDF, doc, or verbal description), the skill extracts:

- **Color palette** → mapped to background, accent, secondary, text, muted
- **Typography** → heading font (display), accent font (sans-serif), body font (serif) via Google Fonts
- **Tone of voice** → shapes both visual copy and TTS delivery instructions

## Background Music

The music curator agent searches royalty-free libraries:

- [Pixabay Music](https://pixabay.com/music/) — free commercial use, no attribution
- [Mixkit](https://mixkit.co/free-stock-music/) — free, no attribution
- [Free Music Archive](https://freemusicarchive.org/) — CC-licensed

Music is processed with ffmpeg (fade-in/out, trimmed to video length) and mixed at ~10% volume under the voiceover using Remotion's native `<Audio>` component.

## Key Technical Details

- **No CSS transitions** — all animations derive from `useCurrentFrame()` (Remotion requirement)
- **Remotion `<Img>`** for images, `staticFile()` for public assets
- **Scene durations** are derived from audio file lengths (not arbitrary frame counts)
- **Crossfade transitions** via 10-15 frame Sequence overlaps with per-scene opacity interpolation
- **Scroll animations** use quadratic ease-in-out for natural feel
- **Spring physics** (`spring()`) for element entries — different damping/mass per element type

## Workflows

The skill supports 5 task manifests:

| Workflow | Tasks | Description |
|----------|:-----:|-------------|
| `full-video` | 10 | Complete narrated video with music |
| `visual-only` | 7 | Video without voiceover |
| `screenshots` | 3 | Screenshot capture only |
| `brand-update` | 3 | Restyle existing video with new brand guidelines |
| `voiceover-only` | 3 | Add/change voiceover on existing video |

## License

Skill: Unlicensed (private)
Background music: Per-track license (Pixabay Content License / Mixkit Free License)
OpenAI TTS: Subject to OpenAI usage policies (must disclose AI-generated voice)
