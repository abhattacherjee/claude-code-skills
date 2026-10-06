# Changelog

All notable changes to the **demo-video** plugin are documented here.

## [1.0.1] - 2026-10-06

### Changed

- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).

## [1.0.0] - 2026-10-05

### Added

- First release (#162). It takes over the `smart-screen-recorder` plugin (4.3.0) and the `product-video-creation` plugin (2.0.0). Two skills under short names: `record` (was `smart-screen-recorder`) and `produce` (was `product-video-creation`). Invoke them as `/demo-video:record` and `/demo-video:produce`. The old names still match as trigger phrases.
- All nine agents ship with the plugin: `demo-storyteller`, `demo-director`, `zoom-qa-verifier`, `voiceover-timing-fixer` and `demo-post-production-editor` (from `smart-screen-recorder`), and `product-video-storyteller`, `product-video-narrator`, `product-video-music-curator` and `product-video-audio-mixer` (from `product-video-creation`). The names stay as they were, because shortening them would make the two storytellers collide. The plugin prefix scopes them, so the skills start them as `demo-video:<agent>`.
- Smoke tests for the scripts and the wiring, in `tests/run-tests.sh`, and a CI job (`demo-video-tests`, bash 5 and bash 3.2) that runs them. They run each script from a temp project directory with `HOME` on a temp dir and a clean environment, in a plugin copy under a path with a space. `brew`, `pip`, `pip3`, `npm`, `npx`, `curl` and `open` are stubs that only log, and the run fails if any was called, so nothing installs, downloads or calls a TTS service. They need no ffmpeg, opencv, screen or network. All 16 scripts are run. Where a script needs a tool, a fake stands in: a fake opencv module that reads a text "video", fake `ffmpeg`, `ffprobe`, `say`, `python3` (for the recorder's helpers and pip) and Node packages (`openai`, `playwright`, the project's `eslint` and `tsc`), and fake OpenAI and preview servers on 127.0.0.1. The Node checks need `node` and print SKIP without it. They cover `--help` (with opencv and Quartz blocked), every option that needs a value, usage on stderr, exit codes, Ctrl+C during a recording, the preview server's token, Host, Origin, content-type and size checks, the timeline builder on a fixture, the task manifests, the scaffold output, the voice list against the SKILL.md voice table, and the plugin wiring: every `"${CLAUDE_SKILL_DIR}/scripts/..."` path exists and is executable (5 per SKILL.md), no path token in prose, no path into a `~/.claude` skills or agents folder anywhere, each `demo-video:<agent>` named in a SKILL.md has an agent file with that name, all 9 agents are started by a SKILL.md, and the agent docs use the file formats the scripts read. Recording a real screen, rendering a Remotion project, and real screenshot capture are SKIP lines. Rendering a real recording runs one `render-timeline.py` test when opencv and ffmpeg are installed, and is a SKIP line otherwise.

### Changed

- Every command in both skills runs as written from your project directory in a fresh shell. `check-skill-commands.py` found 24 problems in the two old skills and finds none now, and CI runs it on this plugin.
- Every agent is started by plugin agent type, `demo-video:<agent>`. Nothing points at a file in `~/.claude`.
- The scripts name no old install path. See the two skill changelogs for the script fixes: exit codes, missing option values, `install-deps.sh --help` running the installer, Node programs that could not find their packages, Ctrl+C during a recording, unchecked ffmpeg steps, and the agent docs that described other file formats than the scripts read.

### Security

- `record`: the preview server listens on 127.0.0.1 only and needs a per-run token in every URL. It refuses a foreign Host or Origin and any feedback that is not a JSON list (at most 1 MB), and sends no CORS header. Before, any web page could write the `feedback.json` that the agent reads as the user's notes. The skill now tells the agent to treat that file as data, never instructions.
- `record`: `generate-tts.py` no longer puts the OpenAI key on a `curl` command line, where `ps` showed it.
- `produce`: `generate-voiceover.sh` and `capture-screenshots.sh` pass every value to their Node program as data. A quote in `--instructions`, a URL or a selector used to break or change the generated JavaScript.

### Deprecated

- The `smart-screen-recorder` and `product-video-creation` plugins. They stay in the repo until #167. Install `demo-video`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the move is in `skills/record/CHANGELOG.md` and `skills/produce/CHANGELOG.md`.
