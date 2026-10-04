# Changelog

All notable changes to the **spec** plugin are documented here.

## [1.0.2] - 2026-10-04

### Changed

- The See Also lines in the README and in `spec:review` name `context:shield` (was `context-shield`), after `context-shield` moved into the `context` plugin (#163). `spec:review` is at 1.0.1.

## [1.0.1] - 2026-10-04

### Changed

- The See Also lines in the README and in `spec:create` name `skill-kit:author` (was `skill-authoring`), after the skill-authoring skill moved into the `skill-kit` plugin (#161). `spec:create` is at 1.0.1.

## [1.0.0] - 2026-10-04

### Added

- First release (#160). It merges the `spec-creator`, `spec-review` and `spec-implement` plugins. Three skills under short names: `create` (was `spec-creator`), `review` (was `spec-review`) and `implement` (was `spec-implement`). Invoke them as `/spec:create`, `/spec:review` and `/spec:implement`. The old names still match as trigger phrases.
- Smoke tests for every script, in `tests/`, and a CI job (`spec-tests`) that runs them. They also run every script command written in the three `SKILL.md` files.
- `discover-conventions.sh --json` has a `skippedEpics` list: the epic directories it ignored because their names are not all digits.

### Changed

- Every script command in the three `SKILL.md` files now calls `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. The old text called `./scripts/<name>.sh`, which resolves against your project, not the skill, so the commands did not run as written.
- `spec:review` read `$SPEC_FILE` in a block that never set it. That is now a `<SPEC_FILE>` placeholder. `PROJECT_ROOT` was set in its own block, and the unused `PROJECT_ROOT=`, `ARCH=` and `SPEC_DATA=` captures are gone.
- Cross-references name the new skills (`/spec:review` after creation, the spec template's "added by /spec:review", the `task-manifest.sh` task descriptions).
- `spec:review` says in its description that it reviews a spec, not code or a pull request.
- `extract-spec-sections.sh` looks for a relative spec path in the current directory first, then in the repo root. It used to try only the repo root, so a path typed from a subdirectory was not found, or matched a different file of the same name at the repo root.
- `extract-spec-sections.sh` counts distinct referenced endpoints. `POST /api/login` and `/api/login` were counted twice.

### Fixed

- The two review scripts escaped only backslash, quote, newline and tab in their JSON. A CR or another control character in a title or directory name gave invalid JSON. `discover-conventions.sh` escaped only backslash and quote, and not epic names or tracking paths. All three scripts now escape every control character.
- `discover-conventions.sh` takes only all-digit epic names and checks a story number before doing arithmetic on it. It sorts under `LC_ALL=C`, so one invalid byte no longer empties `commonSections`. It finds the sample spec with `find -exec ls -t {} +` instead of `xargs`.
- `discover-project-architecture.sh` read `find` output word by word and printed it with `printf '%b'`, so a directory name with a space or a backslash sequence was split or cut. It now reads whole lines and prints them as they are.
- `extract-spec-sections.sh` text mode dropped endpoints: the first grep that found nothing ended the group under `set -e`. Text and `--json` now agree.
- The three discovery and extract scripts read files as bytes (`LC_ALL=C`). In a UTF-8 locale on Linux, GNU grep calls a file with one invalid byte "binary" and prints no lines, so headings, criteria and endpoints silently vanished. macOS grep does not do this.
- `spec:review` quotes its `"<SPEC_FILE>"` placeholder, so a spec path with a space works.
- `extract-spec-sections.sh` and `discover-conventions.sh` stop with an error on an unreadable spec or epic directory, instead of reporting false gaps or `nextStory: 1`.

### Deprecated

- The `spec-creator`, `spec-review` and `spec-implement` plugins. They stay published for one more release, marked deprecated in the marketplace. Install `spec`, then uninstall all three, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/create/CHANGELOG.md`, `skills/review/CHANGELOG.md` and `skills/implement/CHANGELOG.md`.
