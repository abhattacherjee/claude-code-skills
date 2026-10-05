# Changelog

All notable changes to the **record** skill (was `smart-screen-recorder`) are documented here.

## [1.0.0] - 2026-10-05

### Changed

- Moved into the `demo-video` plugin as `demo-video:record` (#162). Same pipeline as `smart-screen-recorder` 4.3.0. The old name and `/smart-screen-recorder` still match as trigger phrases.
- Every script command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/record.sh"` and so on. The old text used a path under the old skill's install folder, which exists only for a hand-copied skill.
- The five agents are started by plugin agent type: `demo-video:demo-storyteller`, `demo-video:demo-director`, `demo-video:zoom-qa-verifier`, `demo-video:voiceover-timing-fixer` and `demo-video:demo-post-production-editor`. The old text started a general-purpose agent with a persona file from your `~/.claude` agents folder, a file that is not part of any install. The agent table names the agent type, not a file.
- `record.sh` and `install-deps.sh` print the path they run from, not the old install path.

### Added

- Step 7b starts the Voiceover Timing Fixer. The agent registry listed it, but no step started it.

### Fixed

- `install-deps.sh --help` (and any other argument) ran the installer, with its Homebrew and pip installs. `-h` and `--help` now print usage and exit 0, and an unknown option exits 2.
- `extract-frames.py`, `preview-timeline.py` and `apply-zoom-script.py --help` exited 1 with "Missing: pip3 install opencv-python" when opencv was not installed, because they imported it before reading their arguments. `--help` works without it now. Running them for real still needs it.
- `record.sh` with an option that needs a value and none given (`record.sh -o`) stopped with `unbound variable` (exit 1). It exits 2 and says which option needs a value.

### Known limits

- `generate-tts.py`, `build-timeline.py`, `render-timeline.py` and `mix-audio.py` are tied to one earlier recording. They read and write fixed paths under `~/Desktop/zoom-analysis`. `build-timeline.py` has a fixed list of speech segment ids and reads `hold_frames` from `zoom-script.json`, while the Demo Director agent writes `hold_frames` into the voiceover script. `render-timeline.py` has a fixed raw video name. The SKILL.md now says so. Making them take arguments needs a decision on how narration segments map to holds, so it is not part of this move.

## History before 1.0.0 (as `smart-screen-recorder`)

### smart-screen-recorder 4.3.0 - 2026-03-17

#### Added

- **Team Mode section** — optional persistent team structure (`demo-production`) where Storyteller, Director, and QA Verifier teammates persist across phases, enabling cross-phase communication and parallel iteration during preview-feedback cycles
- **When to use guidance** — decision table for teams vs sub-agents based on scenario complexity

### smart-screen-recorder 4.2.0 - 2026-03-16

#### Added
- **Demo Storyteller agent** (`demo-storyteller.md`) — analyzes frames and proposes 3 narrative theme options before Demo Director runs
- **Progress tracking** — 12-step task checklist using TaskCreate/TaskUpdate for user visibility
- **Narrative brainstorming step** (Step 3.7) — Storyteller agent + user interactive session to choose demo direction
- **Narrative brief** flows from Storyteller → user choice → Demo Director as creative brief
- **Preview improvements**: numbered audio segments (#N), transcribed text, stacked layout, POST feedback endpoint
- **Server-side feedback** — preview POSTs to `/feedback` endpoint instead of file download
- Higher resolution preview frames (1920px, JPEG quality 92)

#### Changed
- Demo Director now accepts `narrative_brief` input (tone, pacing, emphasis from brainstorming)
- Plugin manifest updated with `demo-storyteller` agent
- Preview HTML layout: full-width screenshots on top, audio segments below, feedback at bottom

### smart-screen-recorder 4.1.0 - 2026-03-15

#### Added
- User context gathering step (Step 3.5) — asks user to describe their product before AI analysis
- Product context as Demo Director input for accurate narration
- Self-contained pipeline scripts: `generate-tts.py`, `build-timeline.py`, `render-timeline.py`, `mix-audio.py`
- Multi-resolution coordinate reference in Zoom QA Verifier (6016, 3840, 2880)
- Comprehensive README.md
- Plugin manifest for monorepo publishing

#### Changed
- Generalized for any product — removed all project-specific references
- SKILL.md examples use generic narration placeholders
- Zoom QA Verifier handles fullscreen apps (no sidebar/dock offsets)
- Version bumped to 4.1.0

### smart-screen-recorder 4.0.0 - 2026-03-15

#### Added
- Narration-first integrated timeline architecture (PLAY + HOLD segments)
- Video freezes during narration for perfect audio-visual sync
- Post-Production Editor agent (quality gate with PASS/NEEDS_FIXES/RESHOOT)
- Voiceover Timing Fixer agent (detects and fixes TTS overlaps)
- Hold frames in zoom script for frame-level freeze control
- 1s fade-from-black on final output

#### Changed
- Replaced overlay-on-playing-video approach with integrated timeline
- Output video is longer than source (extra time = frozen narration frames)
- TTS timestamps rebuilt sequentially from actual durations (not estimates)

### smart-screen-recorder 3.2.0 - 2026-03-15

#### Added
- Zoom QA Verifier agent — corrects bounding boxes against full-res frames
- Demo Director agent — AI vision analysis of recording frames
- Interactive voice selection (OpenAI TTS: nova/fable/alloy/echo/shimmer/onyx + macOS native)
- Bounding-box zoom targeting with aspect ratio preservation

### smart-screen-recorder 2.0.0 - 2026-03-14

#### Added
- OpenAI TTS integration (tts-1-hd model)
- AI-driven zoom script with target_box bounding rectangles
- 4K output (3840x2160) for text legibility
- Frame extraction for AI analysis

#### Changed
- Replaced heuristic velocity-based zoom with AI vision analysis

### smart-screen-recorder 1.0.0 - 2026-03-14

#### Added
- Screen recording with cursor tracking (MKV → MP4)
- Cursor tracker via macOS Quartz API (position, clicks, active window)
- Heuristic smart zoom (velocity, dwell, click modes)
- Key frame extraction at interaction moments
- install-deps.sh for dependency setup
