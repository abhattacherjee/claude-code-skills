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
- `scaffold-project.sh` printed "Project scaffolded" and exited 0 when `npm install` failed, because the install output went through a pipe to `tail`. It exits 1 and shows the end of the npm output.
- An option that needs a value, given none (`scaffold-project.sh --name`), stopped with `unbound variable` (exit 1). The four scripts that take options (`scaffold-project.sh`, `generate-voiceover.sh`, `capture-screenshots.sh` and `render-and-preview.sh`) exit 2 and name the option.
- `scaffold-project.sh --name` with a quote, backslash, tab or other control character wrote an invalid `package.json`. The name is written with `JSON.stringify` now. The generated `description` no longer names the old skill.
- `scaffold-project.sh --name --version` (or a name that starts with `-`, such as `--import=...`, or a project directory named `./-x`) passed the name to `node` as an option: it wrote `"name": v22.23.1,` (invalid JSON), ran the `--import` code, or aborted with `bad option`. The name now follows `--`. `render-and-preview.sh --output -x.mp4` was read as an option by `dirname`, `ffprobe` and `ffmpeg`; it is used as `./-x.mp4`.
- `generate-voiceover.sh` and `capture-screenshots.sh` wrote their JavaScript to `/tmp/...XXXXXX.mjs`. ESM looks for `openai` and `playwright` next to that file, so the import failed (`ERR_MODULE_NOT_FOUND`) even after the script's own `npm install`, and BSD `mktemp` left the X's in the name, so runs collided. The program now runs with `node --input-type=module -e` from the project directory, with no temp file, and gets every value through environment variables, so a quote in `--instructions`, a URL or a selector cannot break it. A failed `npm install` exits 1 with its output.
- `generate-voiceover.sh` checks the scene list before making audio: not a JSON array, or a scene with no `text` (which the macOS path spoke as "undefined"), exits 1. The macOS path exited 0 after a crash; it now runs `say` and `ffmpeg` from Node and exits 1 on any failure. An unknown macOS `--voice` exits 2, and a `--speed` that is not a number exits 2. Scene names become safe file names.
- `capture-screenshots.sh` exited 0 when the capture failed. It exits 1 and closes the browser. A bad `--viewport` or `--dpr` exits 2.
- `scaffold-project.sh` decided a project existed by `remotion.config.ts`, which is written before `npm install`, so a rerun after a failed install skipped it and exited 0. An existing project keeps its files and still runs `npm install` (unless `--skip-install`). SKILL.md said it checks the current directory; it checks `<PROJECT_DIR>`.
- `render-and-preview.sh` reported a missing or crashing eslint or tsc as "errors found" (it ran them through `npx` with stderr hidden). It runs the project's own `node_modules/.bin/eslint` and `tsc` with their output, says when one is not installed, and reports eslint exit 2 as "could not run". A failed contact sheet exits 1 with the ffmpeg output. With several compositions in `src/Root.tsx` and no ID it took the first; it exits 1 and lists them.
- Phase 6 downloaded the music to `bg-music.mp3` and then faded `bg-music-raw.mp3`. The download is `bg-music-raw.mp3`, the faded file `bg-music.mp3`, and the music curator agent agrees.

### Removed

- `capture-screenshots.sh --flow-script`. It was in the help and parsed, but never used. Write your own Playwright script for a custom flow.

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
