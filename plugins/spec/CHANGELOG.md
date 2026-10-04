# Changelog

All notable changes to the **spec** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#160). It merges the `spec-creator`, `spec-review` and `spec-implement` plugins. Three skills under short names: `create` (was `spec-creator`), `review` (was `spec-review`) and `implement` (was `spec-implement`). Invoke them as `/spec:create`, `/spec:review` and `/spec:implement`. The old names still match as trigger phrases.
- Smoke tests for every script, in `tests/`, and a CI job (`spec-tests`) that runs them.

### Changed

- Every command in the three `SKILL.md` files runs as written from your project directory. The old text called `./scripts/<name>.sh`, which resolves against your project, not the skill, so no script ran. Commands now use `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. `spec:review` also read `$SPEC_FILE` and `$PROJECT_ROOT` in blocks that never set them; those are now placeholders you fill in.
- Cross-references name the new skills (`/spec:review` after creation, the spec template's "added by /spec:review", the `task-manifest.sh` subject lines).
- `spec:review` says in its description that it reviews a spec, not code or a pull request.

### Deprecated

- The `spec-creator`, `spec-review` and `spec-implement` plugins. They stay published for one more release, marked deprecated in the marketplace. Install `spec`, then uninstall all three, so the old names cannot win a plain-language request.

Per-skill history before the merge is in `skills/create/CHANGELOG.md`, `skills/review/CHANGELOG.md` and `skills/implement/CHANGELOG.md`.
