# Changelog

All notable changes to the **produce** skill (was `product-video-creation`) are documented here.

## [1.0.0] - 2026-10-05

### Changed

- Moved into the `demo-video` plugin as `demo-video:produce` (#162). Same workflow as `product-video-creation` 2.0.0. The old name and `/product-video-creation` still match as trigger phrases.
- Every script command is written to work from your Remotion project directory in a fresh shell (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/<name>"`. The old text set `SKILL_DIR=` in one block and read it in others, and called `./scripts/...` and bare `scripts/...`.
- The four agents are started by plugin agent type: `demo-video:product-video-storyteller`, `demo-video:product-video-narrator`, `demo-video:product-video-music-curator` and `demo-video:product-video-audio-mixer`. The old text named them with no type. `task-manifest.sh` task descriptions say the same.
- The OpenAI key check in Step 1 now works. The old `echo "${OPENAI_API_KEY:+...}" || echo "No OpenAI key found"` could never print the second line, because `echo` always succeeds. It is an `if` on `printenv OPENAI_API_KEY` now, and an empty key counts as not set.
- `references/scene-architecture.md`: the entry-animation tip had a JavaScript template literal in an inline code span, which the command checker read as a shell variable. It is plain words now.

### Added

- Phase 3 names the `product-video-narrator` agent and how to start it. It was in the architecture tree and the agent table but nothing started it.
- `alloy` in the voice table. The script and the changelog count 13 OpenAI voices; the table had 12.

### Fixed

- `generate-voiceover.sh`, `scaffold-project.sh` and `capture-screenshots.sh` printed "Error: ... is required" and then exited 0, so a missing argument looked like success. They exit 2.
- `task-manifest.sh` with no workflow printed the usage and exited 0. It exits 2. Its help said `full-video` has 9 tasks; it has 10.
- `generate-voiceover.sh --list-voices --provider <unknown>` printed nothing and exited 0. An unknown provider exits 2 with a message, before anything else runs.
- An option that needs a value, given none (`scaffold-project.sh --name`), stopped with `unbound variable` (exit 1). The four scripts that take options (`scaffold-project.sh`, `generate-voiceover.sh`, `capture-screenshots.sh` and `render-and-preview.sh`) exit 2 and name the option.
- `scaffold-project.sh --name` with a quote or backslash in the name wrote an invalid `package.json`. The name is escaped now. The generated `description` no longer names the old skill.

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
