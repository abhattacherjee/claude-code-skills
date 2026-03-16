# Changelog

## [4.2.0] - 2026-03-16

### Added
- **Demo Storyteller agent** (`demo-storyteller.md`) — analyzes frames and proposes 3 narrative theme options before Demo Director runs
- **Progress tracking** — 12-step task checklist using TaskCreate/TaskUpdate for user visibility
- **Narrative brainstorming step** (Step 3.7) — Storyteller agent + user interactive session to choose demo direction
- **Narrative brief** flows from Storyteller → user choice → Demo Director as creative brief
- **Preview improvements**: numbered audio segments (#N), transcribed text, stacked layout, POST feedback endpoint
- **Server-side feedback** — preview POSTs to `/feedback` endpoint instead of file download
- Higher resolution preview frames (1920px, JPEG quality 92)

### Changed
- Demo Director now accepts `narrative_brief` input (tone, pacing, emphasis from brainstorming)
- Plugin manifest updated with `demo-storyteller` agent
- Preview HTML layout: full-width screenshots on top, audio segments below, feedback at bottom

## [4.1.0] - 2026-03-15

### Added
- User context gathering step (Step 3.5) — asks user to describe their product before AI analysis
- Product context as Demo Director input for accurate narration
- Self-contained pipeline scripts: `generate-tts.py`, `build-timeline.py`, `render-timeline.py`, `mix-audio.py`
- Multi-resolution coordinate reference in Zoom QA Verifier (6016, 3840, 2880)
- Comprehensive README.md
- Plugin manifest for monorepo publishing

### Changed
- Generalized for any product — removed all project-specific references
- SKILL.md examples use generic narration placeholders
- Zoom QA Verifier handles fullscreen apps (no sidebar/dock offsets)
- Version bumped to 4.1.0

## [4.0.0] - 2026-03-15

### Added
- Narration-first integrated timeline architecture (PLAY + HOLD segments)
- Video freezes during narration for perfect audio-visual sync
- Post-Production Editor agent (quality gate with PASS/NEEDS_FIXES/RESHOOT)
- Voiceover Timing Fixer agent (detects and fixes TTS overlaps)
- Hold frames in zoom script for frame-level freeze control
- 1s fade-from-black on final output

### Changed
- Replaced overlay-on-playing-video approach with integrated timeline
- Output video is longer than source (extra time = frozen narration frames)
- TTS timestamps rebuilt sequentially from actual durations (not estimates)

## [3.2.0] - 2026-03-15

### Added
- Zoom QA Verifier agent — corrects bounding boxes against full-res frames
- Demo Director agent — AI vision analysis of recording frames
- Interactive voice selection (OpenAI TTS: nova/fable/alloy/echo/shimmer/onyx + macOS native)
- Bounding-box zoom targeting with aspect ratio preservation

## [2.0.0] - 2026-03-14

### Added
- OpenAI TTS integration (tts-1-hd model)
- AI-driven zoom script with target_box bounding rectangles
- 4K output (3840x2160) for text legibility
- Frame extraction for AI analysis

### Changed
- Replaced heuristic velocity-based zoom with AI vision analysis

## [1.0.0] - 2026-03-14

### Added
- Screen recording with cursor tracking (MKV → MP4)
- Cursor tracker via macOS Quartz API (position, clicks, active window)
- Heuristic smart zoom (velocity, dwell, click modes)
- Key frame extraction at interaction moments
- install-deps.sh for dependency setup
