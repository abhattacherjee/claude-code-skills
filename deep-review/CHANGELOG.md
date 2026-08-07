# Changelog

## [1.3.0] - 2026-08-06

### Added

- Phase 0 gained a fifth scoping step: record environment/toolchain coverage gaps relevant to the
  diff (e.g. GNU `tar` or `gawk` behaviour that a macOS/BSD review host cannot execute), label them
  explicitly **not executed locally** and **deferred to CI**, and recommend a concrete
  cross-platform check (`gtar`, `gawk`, a Linux container) when feasible.
- Final report now includes a dedicated bullet for portability concerns that were not executable
  locally: the exact CI/toolchain coverage they were deferred to, and any concrete command
  recommended for pre-CI reproduction.
- Red Flags gained "Imply portability coverage from an unavailable toolchain" — a green BSD/macOS
  run does not verify GNU/Linux behaviour (or vice versa); state what was not executed, defer to the
  matching CI job, and recommend a concrete alternate-toolchain check where possible.

This change was originally proposed in PR #98, closed unmerged, which targeted `main` from a docs
branch whose head branch no longer exists; that PR patched the generated plugin copy
(`plugins/deep-review/...`) rather than this authoring source, so a subsequent `prepare-plugin.sh`
rebuild would have silently discarded it. Re-applied here to the source. Original change proposed by
@lntutor in #98.

Motivating case, from this repo: `_lib.sh:44` (shipped in #107) asserts "POSIX awk only, so this
runs on macOS BSD awk and gawk alike" — a portability claim the review host could not execute,
because `gawk` is not installed on it. Step 5 is the rule that would have required labelling it
*not executed locally* up front.

## [1.2.1] - 2026-08-05

### Changed

- Authoring source moved into the `claude-code-skills` monorepo as a top-level `deep-review/`
  directory, and the manifest switched from `"source": "~/.claude/skills/deep-review"` to the
  in-repo form `"source": "."`. The plugin could previously only be assembled on the maintainer's
  machine; it is now rebuildable from a clone, and the local bare skill at
  `~/.claude/skills/deep-review` has been removed so the marketplace plugin is the single
  distribution channel. Same migration `spec-creator`/`spec-review`/`spec-implement` received in
  #59. Also removes this skill's instance of the resolve-by-`source` vs resolve-by-`name` drift
  mismatch tracked in #92 — the detectors no longer depend on `$SKILLS_HOME/deep-review` existing.
  (#101)

### Fixed

- Skill-relative reference links are no longer ambiguous against target-project paths. The two
  `references/delegated-verification.md` links (Phase 1 Step 3, Phase 2 Step 2.5) are now
  `./references/…`, a Path-convention note after the title states the rule, and the Step 2.1 note
  about `scripts/gemini-review.sh` now names the `adversarial-review` plugin that owns it — bare
  `scripts/`/`references/` elsewhere in this skill means the project under review. (#101)

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
