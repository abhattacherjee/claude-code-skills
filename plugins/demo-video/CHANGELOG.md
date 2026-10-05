# Changelog

All notable changes to the **demo-video** plugin are documented here.

## [1.0.0] - 2026-10-05

### Added

- First release (#162). It takes over the `smart-screen-recorder` plugin (4.3.0) and the `product-video-creation` plugin (2.0.0). Two skills under short names: `record` (was `smart-screen-recorder`) and `produce` (was `product-video-creation`). Invoke them as `/demo-video:record` and `/demo-video:produce`. The old names still match as trigger phrases.
- All nine agents ship with the plugin: `demo-storyteller`, `demo-director`, `zoom-qa-verifier`, `voiceover-timing-fixer` and `demo-post-production-editor` (from `smart-screen-recorder`), and `product-video-storyteller`, `product-video-narrator`, `product-video-music-curator` and `product-video-audio-mixer` (from `product-video-creation`). The names stay as they were, because shortening them would make the two storytellers collide. The plugin prefix scopes them, so the skills start them as `demo-video:<agent>`.
- Smoke tests for the scripts and the wiring, in `tests/run-tests.sh`, and a CI job (`demo-video-tests`, bash 5 and bash 3.2) that runs them. They run each script from a temp project directory with `HOME` on a temp dir and a clean environment, in a plugin copy under a path with a space. `brew`, `pip`, `pip3`, `npm`, `npx`, `curl` and `open` are stubs that only log, and the run fails if any was called, so nothing installs, downloads or calls a TTS service. They need no ffmpeg, opencv or screen. They cover `--help`, bad input and exit codes for every script that can run offline, the timeline builder on a fixture, the task manifests, the scaffold output, the voice list against the SKILL.md voice table, and the plugin wiring: every `"${CLAUDE_SKILL_DIR}/scripts/..."` path exists and is executable, no path token in prose, no path into a `~/.claude` skills or agents folder anywhere, each `demo-video:<agent>` named in a SKILL.md has an agent file with that name, and all 9 agents are started by a SKILL.md. Recording, rendering and screenshot capture are SKIP lines.

### Changed

- Every command in both skills runs as written from your project directory in a fresh shell. `check-skill-commands.py` found 24 problems in the two old skills and finds none now, and CI runs it on this plugin.
- Every agent is started by plugin agent type, `demo-video:<agent>`. Nothing points at a file in `~/.claude`.
- The scripts name no old install path. See the two skill changelogs for the script fixes (exit codes, missing option values, `install-deps.sh --help` running the installer).

### Deprecated

- The `smart-screen-recorder` and `product-video-creation` plugins. They stay in the repo until #167. Install `demo-video`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the move is in `skills/record/CHANGELOG.md` and `skills/produce/CHANGELOG.md`.
