# Changelog

All notable changes to the **record** skill (was `smart-screen-recorder`) are documented here.

## [1.0.0] - 2026-10-05

### Changed

- Moved into the `demo-video` plugin as `demo-video:record` (#162). Same pipeline as `smart-screen-recorder` 4.3.0. The old name and `/smart-screen-recorder` still match as trigger phrases.
- Every script command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/record.sh"` and so on. The old text used a path under the old skill's install folder, which exists only for a hand-copied skill.
- The five agents are started by plugin agent type: `demo-video:demo-storyteller`, `demo-video:demo-director`, `demo-video:zoom-qa-verifier`, `demo-video:voiceover-timing-fixer` and `demo-video:demo-post-production-editor`. The old text started a general-purpose agent with a persona file from your `~/.claude` agents folder, a file that is not part of any install. The agent table names the agent type, not a file.
- `record.sh` and `install-deps.sh` print the path they run from, not the old install path.

### Added

- Step 6b starts the Voiceover Timing Fixer. The agent registry listed it, but no step started it. It runs after TTS and before the timeline is built, and the step says plainly that no script reads its corrected start times (it writes them to `tts-manifest-fixed.json`); its report is for deciding what to change.
- `record.sh --zoom-mode focus|click|velocity`, passed to `smart-zoom.py`. `--dwell` and `--move` only act in velocity mode, which `record.sh` never chose; the help now says so.
- `preview-timeline.py --no-browser`.
- `references/file-formats.md`: `zoom-script.json`, `voiceover-script.json` and `integrated-timeline.json` as the scripts read them.

### Security

- `preview-timeline.py` served on `localhost:8111`, took any `POST /feedback`, sent `Access-Control-Allow-Origin: *`, and wrote the body to `feedback.json`, which the agent reads as the user's notes. It now binds 127.0.0.1, serves everything under a random per-run token (a request without it gets 403), refuses a foreign Host or Origin, takes feedback only as `application/json` holding a JSON list of objects of at most 1 MB, and sends no CORS header. Text from the JSON files is HTML-escaped in the page. SKILL.md tells the agent to treat `feedback.json` as data, never instructions.
- `generate-tts.py` put the OpenAI key in `curl`'s arguments, visible in `ps`. It sends the request itself (urllib), with the key in a header.

### Fixed

- `install-deps.sh --help` (and any other argument) ran the installer, with its Homebrew and pip installs. `-h` and `--help` now print usage and exit 0, and an unknown option exits 2.
- `extract-frames.py`, `preview-timeline.py` and `apply-zoom-script.py --help` exited 1 with "Missing: pip3 install opencv-python" when opencv was not installed, because they imported it before reading their arguments. `--help` works without it now. Running them for real still needs it.
- `record.sh` with an option that needs a value and none given (`record.sh -o`) stopped with `unbound variable` (exit 1). It exits 2 and says which option needs a value.
- `record.sh`: Ctrl+C, the documented way to stop, killed the script inside `wait` (exit 129), so the MKV was never remuxed and no summary printed. It now passes the stop to ffmpeg, waits for it, and goes on. It exits 1 when ffmpeg wrote no video, when (without `--raw-only`) the cursor log has no positions, or when `smart-zoom.py` fails. Usage and missing-dependency messages go to stderr.
- `install-deps.sh` installed with `pip3` but checked with `python3`, and printed "All dependencies installed." without checking. It uses `python3 -m pip`, checks everything again at the end (exit 1, naming what is missing), and explains a PEP 668 "externally-managed-environment" refusal (use a venv or `--user`).
- `generate-tts.py` saved an API error body as an `.mp3`, used a segment id as a file name unchecked, hid errors with a bare `except:`, and exited 0 when segments failed. Only a successful response is saved, ids must be `[A-Za-z0-9_-]` (checked before any request), and it exits 1 with "N of M segments failed".
- `mix-audio.py` ignored every ffmpeg return code in its fallback path and judged success by `demo-final.mp4` existing, so an old output passed as new. It removes the old output first and exits 1 at the first failed step.
- `smart-zoom.py` read the tracker's window lines as cursor positions (the zoom jumped to the window corner every 0.5 s) and zoomed into (0, 0) on a log with no positions. It skips window lines and exits 1 on an empty log. `--help` works without opencv.
- `cursor-tracker.py` swallowed every window-bounds error every 0.5 s. It reports the first one on stderr.
- `render-timeline.py` did not check that the video opened and silently cut short a play segment or dropped a hold when a frame could not be read, which makes the narration drift. It exits 1 on either, naming each segment, and prints holds rendered of planned. `apply-zoom-script.py` fired at most one hold per frame and only within half a frame, so some holds never fired, unreported. It fires every hold due, prints holds fired of planned, and exits 1 for missed holds or a trim end past the video. `build-timeline.py` warns for each speech id the TTS manifest lacks.
- `preview-timeline.py` did not check that the video opened, and never refreshed a copied mp3 after the clip was regenerated. Both fixed.
- `render-timeline.py` read one frame past the end of the video for the last frame of a play segment that runs to the end of the trim, so the new short-read check failed a valid timeline. The end of the source interval is exclusive now, and a frame that is really missing still fails. `record.sh -o -dir`, and `smart-zoom.py` or `apply-zoom-script.py -o=-x.mp4`, handed ffmpeg a path that starts with `-`; they use `./-dir` and `./-x.mp4`.
- `build-timeline.py`, `generate-tts.py`, `mix-audio.py` and `render-timeline.py` print one line, not a traceback, for a missing input file.
- The Demo Director doc described `zoom_events` with other fields, put `hold_frames` in the voiceover script, gave segments no `id`, and called `start_time` an output-timeline value; the Zoom QA Verifier expected `zoom_events`. Both now match the scripts: `events` with `start`, `end`, `transition_in` and `transition_out`, `hold_frames` in `zoom-script.json`, a required `id`, and `start_time` on the trimmed recording (no script places audio by it). The zoom limits agree (at most 3 events, 1.4-1.6x), and `zoom` is noted as unread.
- SKILL.md built the timeline (Step 6) before the TTS clips it needs existed (Step 7). The order is now TTS (6), timing check (6b), timeline (7), preview (7.5), render and mix (7.6). Step 3 no longer offers macOS voices, which no `record` script produces. Team Mode pointed at Step 9 for the preview; it is Step 7.5.

### Known limits

- `generate-tts.py`, `build-timeline.py`, `render-timeline.py` and `mix-audio.py` are tied to one earlier recording. They read and write `voiceover-script.json`, `zoom-script.json`, `tts/` and `integrated-timeline.json` under `~/Desktop/zoom-analysis`. `render-timeline.py` reads the raw video `~/Desktop/screen-recording-20260315-084024-raw.mp4` and writes `~/Desktop/demo-video-only.mp4`, which `mix-audio.py` reads to write `~/Desktop/demo-final.mp4`. `build-timeline.py` has a fixed list of speech segment ids. `build-timeline.py` and `apply-zoom-script.py` read `hold_frames` from `zoom-script.json`, which is where the Demo Director now writes them. The SKILL.md says all this. Making them take arguments needs a decision on how narration segments map to holds, so it is not part of this move.

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
