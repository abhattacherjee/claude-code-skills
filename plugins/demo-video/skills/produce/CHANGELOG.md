# Changelog

All notable changes to the **produce** skill (was `product-video-creation`) are documented here.

## [1.0.0] - 2026-10-05

### Changed

- Moved into the `demo-video` plugin as `demo-video:produce` (#162). Same workflow as `product-video-creation` 2.0.0. The old name and `/product-video-creation` still match as trigger phrases.

## History before 1.0.0 (as `product-video-creation`)

### product-video-creation 2.0.0 - 2026-03-15

#### Added
- AI-driven storytelling via Opus 4.6 agent (product-video-storyteller) — crafts narrative arcs, not template fills
- OpenAI TTS voiceover with 13 voice options (gpt-4o-mini-tts) with per-scene tone instructions
- macOS native voice fallback (Samantha, Daniel, Karen, etc.)
- Background music curation agent (product-video-music-curator) — searches Pixabay/Mixkit for royalty-free tracks
- Audio mixing agent (product-video-audio-mixer) — handles ducking, fades, volume balancing
- Interactive voice selection brainstorm (Phase 0)
- User narrative approval gate before code generation
- `scaffold-project.sh` — scaffolds fresh Remotion projects from any directory
- `generate-voiceover.sh` — TTS generation script (OpenAI + macOS)
- `render-and-preview.sh` — render to MP4, generate contact sheet, open preview
- iPhone 17 Dynamic Island phone frames
- Scrolling full-page screenshot animation (ScrollingPhone component)
- Animated phone crossfade with step indicator dots (AnimatedPhone component)
- 5 workflow manifests: full-video, visual-only, screenshots, brand-update, voiceover-only
- Plugin manifest for monorepo publishing

#### Changed
- Renamed from `remotion-product-video` to `product-video-creation`
- All project-specific references removed — fully generalized for any product
- Scaffold uses neutral defaults (Inter, #111827) instead of brand-specific values

### product-video-creation 1.0.0 - 2026-03-15

#### Added
- Initial skill with 7-scene product video structure
- Playwright screenshot capture script
- Brand guidelines integration (PDF extraction)
- 9:16, 16:9, 1:1 aspect ratio support
- Scene architecture reference document
- Task manifest for progress tracking
