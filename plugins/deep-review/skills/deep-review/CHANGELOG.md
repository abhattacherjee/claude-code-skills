# Changelog

## [1.2.0] - 2026-07-30

### Added

- Red Flags now cover the hardcoded-FALSE direction: an "expect nothing" assertion with no positive control cannot distinguish a detector that correctly reports nothing from one stuck OFF. Requires both directions, prefers mutation over inspection, and adds the fixture-reachability check — an assertion whose fixture cannot express the failure is a passing badge on an uncovered path.

## [1.1.1] - 2026-07-25

### Fixed

- Made the `deep-review` skill self-contained: bundled `references/delegated-verification.md` into the plugin and rewrote the Phase 1 Step 3 / Phase 2 Step 2.5 verification steps to reference it by the relative path `references/delegated-verification.md` (was an absolute `~/.claude/skills/ship/...` path that only resolved in the maintainer environment — a dangling pointer for third-party installers).

## [1.1.0] - 2026-07-24

### Changed

- Synced `deep-review` skill from the maintainer's live copy (was drifted since 2026-06-15).
  - Phase 0: exclude generated/derived artifacts from the reviewer diff.
  - Phase 2 R1/R2: corrected Gemini guidance — `scripts/gemini-review.sh` is R2 **judge-only** (no `--mode find`); use a direct `gemini -m gemini-2.5-pro -p` call for R1 discovery; added a fail-open reliability note.

### Added

- Mandatory **delegated-work ground-truth verification** step at Phase 1 Step 3 and Phase 2 Step 2.5 — verify a sub-agent's claims (committed / written / tests-pass) against ground truth before advancing (from claude-code-config Story 1.4). Note: the step references `~/.claude/skills/ship/references/delegated-verification.md`, which resolves in the maintainer environment; bundling it into the plugin is tracked as a follow-up.

## [1.0.0] - 2026-06-06

Initial plugin release.

### Included

- **1 skill(s)**, **0 command(s)**
- Skill: `deep-review`
