# Changelog

All notable changes to this project will be documented in this file.

## [4.2.1] - 2026-07-26

### Fixed

- `sync-monorepo.sh` treated every top-level directory in the monorepo as a skill, so
  directories that exist for other reasons — `docs/`, `build/` — entered the sync loop and
  produced a spurious `ERROR: no SKILL.md ...` line on every run. Both directory-scan sites
  in `discover_skills()` now filter through `filter_skill_candidates()` — the plain scan,
  and the `--add` branch's `existing=` scan, which runs only when `--add` is passed — each
  applying the same test `skill_source_dir()` does and announcing what it dropped on stderr
  instead of discarding it silently. The filter emits through `printf` rather than `echo`,
  so a directory named `-n`/`-e`/`-E` cannot be eaten by `echo`'s option parsing and vanish
  without even a SKIP line. (#74)
- The plugin auto-build stage assembled each plugin into `./build/<name>` in the *caller's*
  working directory, so a sync run from the monorepo root left an untracked `build/` tree
  behind — which the script's own "Next steps: `git add -A`" banner would then commit.
  Builds now go into a `mktemp -d` stage removed by an EXIT trap, passed through to
  `prepare-plugin.sh` via `--output-dir`. (#74)
- The `.gitignore` template written into a freshly `--init`-ed monorepo did not list
  `build/`, so every newly generated monorepo shipped with the same defect. The pattern is
  written root-anchored as `/build/`: unanchored, it matches at every depth, so a plugin
  that legitimately ships a `build/` subdirectory would be silently excluded from the very
  `git add -A` the ignore rule exists to protect. (#74)
- The CHANGELOG-parsing step read its first line via `echo "$ALL_ENTRIES" | head -1`.
  `head` exits after one line, so `echo` races it and takes EPIPE once the entry text is
  well past the 64 KiB pipe buffer. With the auto-build EXIT trap now registered, bash no
  longer leaves SIGPIPE at its default disposition in the command-substitution subshell —
  the trap does not itself run there — so `echo`'s failed write is reported rather than
  silently killing it: `echo: write error: Broken pipe` on stderr. It is a write/reader
  race, not a hard threshold: measured 0/50 reproductions below 64 KiB, ~53% at 84 KiB and
  10/10 at 154 KiB, so it reproduces reliably well past the buffer. Replaced with a
  parameter expansion; generated output is byte-identical. (#74)
- `Skills to sync (N)` counted an empty list as 1 and printed a bare `  - ` bullet,
  because `echo ""` emits a newline for `wc -l` to count. Newly reachable now that
  discovery filters non-skill directories: a monorepo holding only `docs/` and `build/`
  yields an empty list. (#74)
- The two remaining `echo` sites in `discover_skills()` ate a skill whose name begins
  `-n`/`-e`/`-E`, the same class the filter fix above closed. `--skills -n` printed
  `Skills to sync (0):`, synced nothing and still exited 0 — a silent no-op; `--add -n`
  into a monorepo with no skills yet (the only case where the comma-join leaves the bare
  name as the whole argument) produced no output at all, so the trailing `grep -v '^$'`
  exited 1 and aborted the run under `set -e` with nothing on stderr to explain it. Both
  now emit through `printf`. (#74)

## [4.2.0] - 2026-07-25

### Fixed

- `prepare-plugin.sh` resolved a relative manifest `source` against the caller's working
  directory, so a manifest whose source lives beside it — the in-repo arrangement #59
  introduced — only assembled when invoked from exactly the right cwd. Relative sources now
  resolve against the manifest file's own directory. `~`-prefixed and absolute sources are
  unchanged. (#61)
- `sync-monorepo.sh` looked for every skill's source under `$SKILLS_HOME` only. Once a
  skill's local copy is removed in favour of an in-repo source directory, drift went
  undetected and the plugin quietly served stale content while the source looked updated.
  Discovery, auto-build and drift-resync now fall back to `$MONOREPO_DIR/<name>`, and a
  same-directory source is skipped rather than copied onto itself. (#61)
- `copy_file` now returns early when source and destination are the same file (device +
  inode comparison, so symlink/hardlink aliases count too). Previously `cp a a` failed and,
  under `set -e`, aborted the entire sync mid-run — reachable for an in-repo skill whose
  manifest declares agents, since the agents-copy block runs for in-place sources. (#61)
- `resolve_source_path` no longer resolves an empty `"source": ""` to the manifest's own
  directory; it returns empty so callers report "source not found" as they did before the
  relative-source change. (#61)

### Added

- Manifest-schema documentation for the in-repo `source` form and its resolution rule. (#61)
- Reversion guard in `sync-monorepo.sh`: source resolution is local-first, so a stale local
  copy left behind after a skill moved into the monorepo silently overwrote newer in-repo
  content with older content — and then rebuilt the plugin from the reverted source, exiting
  0. A skill whose in-repo `SKILL.md` version is strictly newer than the local one (semver
  comparison via `sort -V`) is now REFUSED with both paths and both versions named, skipped
  in both the main sync loop and the plugin auto-build, and reported in a closing summary
  with exit status 3. Equal versions with differing content still sync forward (with a
  note); an unknown or unparseable version never refuses. `--force-local` overrides. (#61)
- Reversion guard now covers the plugin auto-resync stage as well, closing the path that
  mattered most: the resync resolved its own sources through the same local-first lookup and
  copied `SKILL.md`, `scripts/`, `references/`, the skill `CHANGELOG.md` and the plugin-root
  `CHANGELOG.md` of a refused skill straight into `plugins/<name>/` — the copy installers
  actually receive — so a run announced its refusal and then reverted the shipped plugin
  anyway, leaving `marketplace.json` advertising a version the artifact no longer was. Its
  drift detection is guarded too, so a refused skill alone no longer opens a resync at all,
  and the root-CHANGELOG skill inventory is now read from the in-repo copy rather than
  recording a version the monorepo never received. Refused skills are skipped individually,
  so a plugin whose other skills legitimately drifted still resyncs those. (#61)

### Changed

- `sync-monorepo.sh` skips the `git-flow` manifest during plugin discovery: that plugin is
  distributed via its own standalone marketplace (`abhattacherjee/git-flow`), not this
  monorepo. Previously shipped but undocumented.

## [4.1.0] - 2026-03-17

### Added

- **Team mode note** — when Agent Teams are enabled and publishing multiple skills, each skill's validation + sync can be assigned to a separate teammate for parallel processing

## [4.0.0] - 2026-03-13

### Changed (BREAKING)

- **Plugin-first publishing** — plugins are now the default distribution format. Every skill with a `plugin-manifest.json` is auto-assembled and synced as a plugin during `sync-monorepo.sh`. Bare skills (without manifests) remain supported as a secondary path.
- **`sync-monorepo.sh` auto-discovers plugins** — scans `$SKILLS_HOME/*/plugin-manifest.json` during regular sync, runs `prepare-plugin.sh` automatically, and syncs built plugins to `plugins/`. The `--add-plugin` flag is now a manual override, no longer required for known plugins.
- **SKILL.md rewritten for plugin-first** — frontmatter, architecture, interactive publishing flow, and key decisions table all updated to reflect plugins as primary, bare skills as secondary, individual repos as optional.
- **Target selection defaults to Plugin** when a `plugin-manifest.json` exists (previously defaulted to Bare Skill)
- **Quick Reference reordered** — monorepo sync (auto-discovers plugins) listed first, manual plugin commands second, individual repo last

### Added

- **Auto-build on drift** — `sync-monorepo.sh` detects when plugin source skills have changed and rebuilds the plugin automatically, with README preservation
- **Manifest creation prompt** — when publishing a skill without a `plugin-manifest.json`, the flow now suggests creating a minimal manifest with a JSON template

## [3.6.0] - 2026-03-06

### Added

- **`scripts/validate-pre-sync.sh`** — mandatory pre-sync gate that verifies each skill's CHANGELOG.md has an entry matching its SKILL.md version. Exits non-zero on mismatch, blocking sync until fixed. Supports `--fix` (remediation guidance) and `--json` (machine-readable) modes.
- **Step 4: Pre-Sync Validation (MANDATORY GATE)** — new step in the Interactive Publishing Flow. Runs `validate-pre-sync.sh` before `sync-monorepo.sh` and blocks if any skill's CHANGELOG is behind its version.
- **Step 6: Monorepo Release (MANDATORY)** — after every sync that changes skill content, ALWAYS create a monorepo release. No longer optional/ask-the-user. Includes bump level decision table.

### Changed

- **Interactive Publishing Flow** — renumbered from 5 steps to 7 steps: added Step 4 (pre-sync validation) and Step 6 (mandatory release). Previous "Post-Publish" is now Step 7.
- **Quick Reference** — added `validate-pre-sync.sh` commands

### Fixed

- **Changelog drift on publish** — previously, syncing a skill with a bumped SKILL.md version but stale CHANGELOG.md went undetected. The new validation gate makes this impossible.
- **Optional monorepo releases** — previously, the post-publish step "asked whether to create a release", making it easy to skip. Releases are now mandatory after content changes.

## [3.5.1] - 2026-03-05

### Fixed

- **Plugin CHANGELOG sync** — `sync-monorepo.sh` now syncs CHANGELOGs from source skills to plugin copies during auto-resync. Previously, plugin CHANGELOGs were preserved (stale) while bare-skill CHANGELOGs were updated, causing version history drift.
- **CHANGELOG drift detection** — Added CHANGELOG diff check to the plugin drift detection phase, so CHANGELOG-only changes trigger a resync
- **`--add-plugin` path** — No longer preserves stale plugin CHANGELOGs; only README is preserved (CHANGELOGs come from source skill)

## [3.5.0] - 2026-02-28

### Added

- **Auto GitHub releases** — `release-monorepo.sh` now creates a GitHub release (via `gh release create`) after pushing the tag, with categorized commit summary and skill/plugin inventory. Falls back gracefully if `gh` CLI fails.
- **Auto plugin resync** — `sync-monorepo.sh` now detects when plugin copies of SKILL.md, scripts/, references/, or agents/ have drifted from their source skills and patches them automatically during sync. Eliminates the silent plugin-content-drift problem.

### Changed

- **SKILL.md** — version bumped to 3.5.0
- **plugin-manifest.json** — version bumped to 3.5.0

## [3.4.0] - 2026-02-28

### Added

- **Agent auto-discovery in bare skill sync** — `sync-monorepo.sh` now detects agent files referenced in SKILL.md (via `agents/*.md` path patterns) and copies them from `~/.claude/agents/` into the monorepo alongside their skills
- **Plugin CHANGELOG preservation** — `sync-monorepo.sh` preserves both README.md and CHANGELOG.md in plugin destinations during `--add-plugin` rsync, preventing overwrite of hand-written content

### Fixed

- **Bare-bones CHANGELOG enrichment** — when a plugin's CHANGELOG only has a template entry, it's replaced with the source skill's CHANGELOG content during sync

## [3.3.0] - 2026-02-28

### Added

- **Rich plugin README generation** — `prepare-plugin.sh` now extracts What It Does, Key Features, Usage, See Also, Prerequisites, and agent/command descriptions from SKILL.md frontmatter and headings. Plugin READMEs are now informative without hand-editing.

### Changed

- **Contents section enhanced** — skills, commands, and agents now include short descriptions extracted from their YAML frontmatter
- **`_lib.sh`** — added `extract_section()` and `extract_headings()` helpers for markdown section extraction

## [3.2.3] - 2026-02-28

### Added

- **Agent cross-reference validation** — `validate-plugin.sh` now scans SKILL.md files for agent path references (e.g., `agents/figma-ux-expert.md`) and warns if the referenced agent is not included in the plugin's `agents/` directory. Prevents silent omission of associated agents during plugin assembly.

## [3.2.2] - 2026-02-27

### Fixed

- **Plugin CHANGELOG preservation** — `sync-monorepo.sh --add-plugin` now preserves both README.md and CHANGELOG.md (previously only README was preserved)
- **Bash 3.2 compatibility** — replaced `declare -A` associative array with temp files for macOS default bash

## [3.2.1] - 2026-02-27

### Fixed

- **Plugin README preservation** — `sync-monorepo.sh --add-plugin` now preserves hand-written README.md files instead of overwriting them with the auto-generated template

## [3.2.0] - 2026-02-27

### Added

- **Auto-sync on publish** — when Monorepo or Plugin targets are selected in the Interactive Publishing Flow, the skill now automatically runs `sync-monorepo.sh`, commits, and pushes instead of leaving it as a manual step
- **Build artifact cleanup** — Post-Publish step now cleans up `build/` directories after publishing
- **Push-blocked fallback** — documents workaround when `prevent-direct-push` hook blocks monorepo pushes

### Changed

- **Interactive Publishing Flow** — Step 4 renamed from "Post-Publish" to "Auto-Sync to Monorepo", Step 5 is now "Post-Publish"
- **SKILL.md** — version bumped to 3.2.0

## [3.1.0] - 2026-02-27

### Added

- **Interactive Publishing Flow** — when invoked, detects current publishing state and presents a multiSelect prompt for target selection (individual repo, monorepo, plugin)
  - Dynamic labels show current state (e.g., "Monorepo (synced)", "Individual repo (published)")
  - Deselecting a published target triggers removal with confirmation
  - Post-publish step offers versioned release if monorepo was modified

### Changed

- **SKILL.md** — added "Interactive Publishing Flow" section before individual workflows
  - Version bumped to 3.1.0

## [3.0.0] - 2026-02-27

### Added

- **Plugin distribution support** — assemble, validate, and publish Claude Code plugins
- **scripts/prepare-plugin.sh** — assembles plugin from a JSON build manifest (`plugin-manifest.json`)
- **scripts/validate-plugin.sh** — validates assembled plugin structure (plugin.json, commands, skills)
- **scripts/install-plugin.sh** — consumer-facing installer/uninstaller for plugins
- **scripts/_lib.sh** — shared library extracted from all scripts (extract_field, extract_version, write_file, etc.)
- **Workflow E** in SKILL.md — full plugin publishing workflow (manifest → assemble → validate → sync → install)
- **Monorepo marketplace support** — auto-generates `.claude-plugin/marketplace.json` during sync
- **`/plugin` install instructions** — README shows `/plugin marketplace add` as recommended install method
- **Plugin section in monorepo README** — auto-generated table with plugin inventory
- **Plugin inventory in releases** — release script includes plugin count and inventory in CHANGELOG, tag, and summary
- **CI validation for plugins** — `validate-plugins` job in GitHub Actions workflow
- **PR template plugin checkboxes** — plugin.json validation, bundled skills, command frontmatter checks

### Changed

- **scripts/sync-monorepo.sh** — added `--add-plugin` flag, plugin discovery, README plugin section, marketplace.json generation
- **scripts/release-monorepo.sh** — includes plugin inventory in CHANGELOG entry, commit message, tag annotation
- **All existing scripts** — refactored to source `_lib.sh` shared library, removed duplicated helpers
- **SKILL.md** — version bumped to 3.0.0, description updated for plugin triggers

## [2.1.0] - 2026-02-24

### Added

- **scripts/release-monorepo.sh** — creates versioned releases of the monorepo with semver tags
  - `patch`, `minor`, `major` bump levels
  - `--dry-run` to preview without changes
  - `--github-user` override (auto-detects via `gh api`)
  - Reads current version from latest `v*` tag, calculates next version
  - Updates CHANGELOG top entry from "Monorepo sync" to versioned section
  - Creates annotated tag with skill inventory
  - Pushes branch + tag to origin

### Changed

- **SKILL.md** — added Workflow D (monorepo release) with bump level table
  - Updated Quick Reference with release commands
  - Updated description to mention versioned releases
  - Version bumped to 2.1.0

### Fixed

- **scripts/sync-monorepo.sh** — CHANGELOG generation now produces audit-style entries instead of duplicating per-skill changelogs
- **scripts/release-monorepo.sh** — version detection uses `git tag -l 'v[0-9]*'` instead of `git describe --tags` to avoid non-semver tags

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option

## [1.0.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — workflow for converting any skill directory into a GitHub repo
  - Step-by-step guide: prepare files, review, init git, create repo, push
  - Key decisions table (why `.claude/` is gitignored, why MIT, etc.)
  - Known gotchas (`gh repo create` remote conflict, username discovery)
- **scripts/prepare-skill-repo.sh** — generates `.gitignore`, `LICENSE`, `CHANGELOG.md`, `README.md` from `SKILL.md` frontmatter
  - Dry-run mode, skip-existing safety, `--github-user` flag
- **references/readme-template.md** — template with install/update/uninstall/compatibility sections
