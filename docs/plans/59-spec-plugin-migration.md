# spec-* Plugin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `spec-creator`, `spec-review`, and `spec-implement` self-contained marketplace plugins whose authoring source lives in this monorepo, so the local `~/.claude/skills/spec-*` copies can be deleted.

**Architecture:** Each skill gains a top-level source directory in the monorepo (`spec-creator/`, `spec-review/`, `spec-implement/`) holding `SKILL.md` + `scripts/` + `references/` + `CHANGELOG.md` + `plugin-manifest.json`. Every hardcoded `~/.claude/skills/<name>/...` path inside those skills is rewritten to a bare-relative path, which the harness resolves against the announced `Base directory for this skill`. `prepare-plugin.sh` then assembles `plugins/<name>/` from the in-repo source (it already excludes `plugin-manifest.json` and `README.md` from the copy, so they do not leak into the plugin).

**Tech Stack:** bash, jq, `scripts/validate-skill.sh`, `scripts/validate-plugin.sh`, `~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh`.

## Global Constraints

- Base branch is `develop`. Never target `main`.
- Run `./scripts/commit-preflight.sh` before every commit.
- Bare-relative script paths only: `scripts/foo.sh`, never `~/.claude/skills/...`, never `${CLAUDE_PLUGIN_ROOT}` (verified unset in Bash tool calls; only populated for `hooks.json`).
- `prepare-plugin.sh` must be invoked from the monorepo root so the relative `source` in each `plugin-manifest.json` resolves.
- Do NOT delete anything under `~/.claude/skills/` in these tasks. Deletion is a destructive step handled by the orchestrator after merge-time verification.
- Final versions: `spec-creator` **2.4.1**, `spec-review` **2.2.1**, `spec-implement` **1.0.0**. (2.4.0/2.2.0 were written into the CHANGELOGs by `69b0d65` but never published — marketplace still served 2.3.0/2.1.0. The patch bump carries the path fix and reconciles every version field at once.)
- Every version must agree across four places: `<skill>/plugin-manifest.json`, `plugins/<name>/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and the CHANGELOG top entry. `SKILL.md`'s `metadata.version` frontmatter is a fifth place and must match too — `validate-skill.sh` errors on a mismatch against the CHANGELOG.
- `validate-skill.sh` errors when a SKILL.md body exceeds **500 lines**, and `commit-preflight.sh` hard-blocks on any validator ERROR. Current bodies: `spec-review` 390, `spec-implement` 264 — both already under the limit, so no restructuring is expected. If a body does exceed it, extract a self-contained section into `references/` and link to it rather than deleting content, and say so in the report.

---

### Task 1: spec-creator — in-repo source + relative script paths

**Files:**
- Create: `spec-creator/SKILL.md`, `spec-creator/scripts/discover-conventions.sh`, `spec-creator/scripts/task-manifest.sh`, `spec-creator/references/spec-template.md`, `spec-creator/CHANGELOG.md`, `spec-creator/plugin-manifest.json`
- Modify: `plugins/spec-creator/skills/spec-creator/SKILL.md`, `plugins/spec-creator/.claude-plugin/plugin.json`, `plugins/spec-creator/CHANGELOG.md`

**Interfaces:**
- Produces: the top-level source-directory convention (`<skill>/plugin-manifest.json` with `"source": "<skill>"`) that Tasks 2 and 3 copy exactly.

- [ ] **Step 1: Write the failing assertion**

```bash
# From repo root. Asserts no local-skill path survives in the source tree.
test -d spec-creator && ! grep -rq '~/\.claude/skills' spec-creator/ \
  && echo PASS || echo FAIL
```

- [ ] **Step 2: Run it to verify it fails**

Run the Step 1 block.
Expected: `FAIL` (the directory does not exist yet).

- [ ] **Step 3: Copy the source into the repo**

```bash
mkdir -p spec-creator
rsync -a --exclude='.DS_Store' ~/.claude/skills/spec-creator/ spec-creator/
```

- [ ] **Step 4: Rewrite the 5 hardcoded script paths**

In `spec-creator/SKILL.md`, replace every occurrence of the literal
`~/.claude/skills/spec-creator/scripts/` with `scripts/`.
Affects lines 20, 21, 29, 30, 80. Line 80 is inside a command substitution:
`CONVENTIONS=$(scripts/discover-conventions.sh "$(git rev-parse --show-toplevel)" --json)`.

```bash
sed -i '' 's|~/\.claude/skills/spec-creator/scripts/|scripts/|g' spec-creator/SKILL.md
```

- [ ] **Step 5: Point the manifest at the in-repo source and set the version**

`spec-creator/plugin-manifest.json` becomes:

```json
{
  "name": "spec-creator",
  "version": "2.4.1",
  "description": "Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).",
  "skills": [
    {
      "name": "spec-creator",
      "source": "spec-creator"
    }
  ],
  "commands": []
}
```

- [ ] **Step 6: Add the CHANGELOG entry**

Prepend to `spec-creator/CHANGELOG.md`, above the existing `## [2.4.0]` entry:

```markdown
## [2.4.1] - 2026-07-25

### Fixed

- Replaced hardcoded `~/.claude/skills/spec-creator/scripts/` invocations with
  bare-relative `scripts/` paths so the skill resolves from the plugin cache
  instead of the maintainer's local skills directory (#59).

### Changed

- Authoring source now lives in the `claude-code-skills` monorepo at
  `spec-creator/`; `plugin-manifest.json` sources from the repo, not `~/.claude/skills`.
```

- [ ] **Step 7: Re-assemble the plugin from the in-repo source**

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/spec-creator spec-creator/plugin-manifest.json
```

- [ ] **Step 8: Verify the assertion now passes, plugin included**

```bash
test -d spec-creator && ! grep -rq '~/\.claude/skills' spec-creator/ && echo PASS || echo FAIL
! grep -rq '~/\.claude/skills' plugins/spec-creator/ && echo PLUGIN-PASS || echo PLUGIN-FAIL
jq -r .version plugins/spec-creator/.claude-plugin/plugin.json   # expect 2.4.1
test -f plugins/spec-creator/skills/spec-creator/scripts/discover-conventions.sh && echo SCRIPTS-OK
test -f plugins/spec-creator/skills/spec-creator/references/spec-template.md && echo REFS-OK
./scripts/validate-skill.sh spec-creator
./scripts/validate-plugin.sh plugins/spec-creator
```

Expected: `PASS`, `PLUGIN-PASS`, `2.4.1`, `SCRIPTS-OK`, `REFS-OK`, and both validators reporting no errors.

- [ ] **Step 9: Commit**

```bash
./scripts/commit-preflight.sh
git add spec-creator plugins/spec-creator
git commit -m "feat(spec-creator): move source in-repo, relative script paths (2.4.1)"
```

---

### Task 2: spec-review — in-repo source + relative script paths

**Files:**
- Create: `spec-review/SKILL.md`, `spec-review/README.md`, `spec-review/scripts/discover-project-architecture.sh`, `spec-review/scripts/extract-spec-sections.sh`, `spec-review/scripts/task-manifest.sh`, `spec-review/references/design-simplification-checklist.md`, `spec-review/CHANGELOG.md`, `spec-review/plugin-manifest.json`
- Modify: `plugins/spec-review/skills/spec-review/SKILL.md`, `plugins/spec-review/.claude-plugin/plugin.json`, `plugins/spec-review/CHANGELOG.md`

**Interfaces:**
- Consumes: the source-directory convention established in Task 1.

- [ ] **Step 1: Write the failing assertion**

The CHANGELOG entry added in Step 6 quotes the old path verbatim as prose
describing the fix, and the generated plugin README carries a
`cp -r … ~/.claude/skills/` manual-install line. Both are legitimate, so the
assertion covers the executable surfaces only.

```bash
test -d spec-review \
  && ! grep -rq '~/\.claude/skills' spec-review/SKILL.md spec-review/README.md spec-review/scripts/ spec-review/references/ \
  && echo PASS || echo FAIL
```

- [ ] **Step 2: Run it to verify it fails**

Expected: `FAIL` (directory absent).

- [ ] **Step 3: Copy the source into the repo**

```bash
mkdir -p spec-review
rsync -a --exclude='.DS_Store' ~/.claude/skills/spec-review/ spec-review/
```

- [ ] **Step 4: Rewrite the 7 SKILL.md paths and the README line**

Lines 101, 102, 105, 106, 109, 136, 145 of `spec-review/SKILL.md`; lines 136 and
145 are inside command substitutions and must keep their surrounding syntax.

```bash
sed -i '' 's|~/\.claude/skills/spec-review/scripts/|scripts/|g' spec-review/SKILL.md
```

`spec-review/README.md:122` currently reads
`Copy \`~/.claude/skills/spec-review/\` to your Claude Code skills directory.`
Replace that whole line with:

```markdown
Install via the marketplace: `/plugin install spec-review@claude-code-skills`.
```

- [ ] **Step 5: Point the manifest at the in-repo source and set the version**

`spec-review/plugin-manifest.json`:

```json
{
  "name": "spec-review",
  "version": "2.2.1",
  "description": "Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.",
  "skills": [
    {
      "name": "spec-review",
      "source": "spec-review"
    }
  ],
  "commands": []
}
```

- [ ] **Step 6: Add the CHANGELOG entry**

Prepend to `spec-review/CHANGELOG.md`, above `## [2.2.0]`:

```markdown
## [2.2.1] - 2026-07-25

### Fixed

- Replaced hardcoded `~/.claude/skills/spec-review/scripts/` invocations with
  bare-relative `scripts/` paths so the skill resolves from the plugin cache (#59).
- README install step no longer instructs copying from `~/.claude/skills/`.

### Changed

- Authoring source now lives in the monorepo at `spec-review/`.
```

- [ ] **Step 7: Re-assemble the plugin**

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/spec-review spec-review/plugin-manifest.json
```

- [ ] **Step 8: Verify**

```bash
test -d spec-review \
  && ! grep -rq '~/\.claude/skills' spec-review/SKILL.md spec-review/README.md spec-review/scripts/ spec-review/references/ \
  && echo PASS || echo FAIL
! grep -rq '~/\.claude/skills' plugins/spec-review/skills/spec-review/SKILL.md plugins/spec-review/skills/spec-review/scripts/ \
  && echo PLUGIN-PASS || echo PLUGIN-FAIL
jq -r .version plugins/spec-review/.claude-plugin/plugin.json   # expect 2.2.1
test -f plugins/spec-review/skills/spec-review/scripts/extract-spec-sections.sh && echo SCRIPTS-OK
./scripts/validate-skill.sh spec-review
./scripts/validate-plugin.sh plugins/spec-review
```

Expected: `PASS`, `PLUGIN-PASS`, `2.2.1`, `SCRIPTS-OK`, validators clean.

- [ ] **Step 9: Commit**

```bash
./scripts/commit-preflight.sh
git add spec-review plugins/spec-review
git commit -m "feat(spec-review): move source in-repo, relative script paths (2.2.1)"
```

---

### Task 3: spec-implement — new plugin, self-contained

**Files:**
- Create: `spec-implement/SKILL.md`, `spec-implement/scripts/task-manifest.sh`, `spec-implement/references/delegated-verification.md`, `spec-implement/CHANGELOG.md`, `spec-implement/plugin-manifest.json`, and the whole assembled `plugins/spec-implement/` tree
- Modify: none outside those paths

**Interfaces:**
- Consumes: the source-directory convention from Task 1.
- Produces: `plugins/spec-implement/` with `.claude-plugin/plugin.json` at version `1.0.0`, consumed by Task 4's marketplace entry.

- [ ] **Step 1: Write the failing assertion**

The CHANGELOG entry added in Step 6 quotes the old path verbatim as prose
describing the fix, and the generated plugin README carries a
`cp -r … ~/.claude/skills/` manual-install line. Both are legitimate, so the
assertion covers the executable surfaces only.

```bash
test -d spec-implement \
  && ! grep -rq '~/\.claude/skills' spec-implement/SKILL.md spec-implement/scripts/ spec-implement/references/ \
  && test -f spec-implement/references/delegated-verification.md \
  && echo PASS || echo FAIL
```

- [ ] **Step 2: Run it to verify it fails**

Expected: `FAIL` (directory absent).

- [ ] **Step 3: Copy the source and bundle the cross-skill reference**

`SKILL.md:114` points at `~/.claude/skills/ship/references/delegated-verification.md`
— a dangling pointer for anyone but the maintainer. Bundle it, exactly as #58 did
for deep-review.

```bash
mkdir -p spec-implement
rsync -a --exclude='.DS_Store' ~/.claude/skills/spec-implement/ spec-implement/
mkdir -p spec-implement/references
cp ~/.claude/skills/ship/references/delegated-verification.md \
   spec-implement/references/delegated-verification.md
```

- [ ] **Step 4: Rewrite all three path references**

```bash
sed -i '' 's|~/\.claude/skills/spec-implement/scripts/|scripts/|g' spec-implement/SKILL.md
sed -i '' 's|~/\.claude/skills/ship/references/delegated-verification\.md|references/delegated-verification.md|g' spec-implement/SKILL.md
```

Lines 24-25 become `scripts/task-manifest.sh standard` / `scripts/task-manifest.sh ui-heavy`;
line 114's pointer becomes `references/delegated-verification.md`.

- [ ] **Step 5: Create the manifest**

`spec-implement/plugin-manifest.json`:

```json
{
  "name": "spec-implement",
  "version": "1.0.0",
  "description": "Implements a previously created and reviewed story spec end-to-end: feature branch, sub-task implementation with progress tracking, acceptance-criteria validation, and PR creation.",
  "skills": [
    {
      "name": "spec-implement",
      "source": "spec-implement"
    }
  ],
  "commands": []
}
```

- [ ] **Step 6: Create the CHANGELOG**

`spec-implement/CHANGELOG.md`:

```markdown
# Changelog

## [1.0.0] - 2026-07-25

Initial plugin release.

### Added

- `spec-implement` skill published as a marketplace plugin (#59).
- Bundled `references/delegated-verification.md` so the delegated-work
  verification step resolves without the `ship` skill installed.

### Fixed

- Script invocations use bare-relative `scripts/` paths rather than
  `~/.claude/skills/spec-implement/scripts/`.
```

- [ ] **Step 7: Assemble the plugin**

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/spec-implement spec-implement/plugin-manifest.json
```

If the generated `plugins/spec-implement/README.md` contains a literal `>-`
(issue #37, folded-YAML description leak), hand-correct that line — do not
leave the artifact in the committed README.

- [ ] **Step 8: Verify**

```bash
test -d spec-implement \
  && ! grep -rq '~/\.claude/skills' spec-implement/SKILL.md spec-implement/scripts/ spec-implement/references/ \
  && echo PASS || echo FAIL
! grep -rq '~/\.claude/skills' plugins/spec-implement/skills/spec-implement/ \
  && echo PLUGIN-PASS || echo PLUGIN-FAIL
jq -r .version plugins/spec-implement/.claude-plugin/plugin.json   # expect 1.0.0
test -f plugins/spec-implement/skills/spec-implement/scripts/task-manifest.sh && echo SCRIPTS-OK
test -f plugins/spec-implement/skills/spec-implement/references/delegated-verification.md && echo REFS-OK
grep -c '>-' plugins/spec-implement/README.md   # expect 0
./scripts/validate-skill.sh spec-implement
./scripts/validate-plugin.sh plugins/spec-implement
```

Expected: `PASS`, `PLUGIN-PASS`, `1.0.0`, `SCRIPTS-OK`, `REFS-OK`, `0`, validators clean.

- [ ] **Step 9: Commit**

```bash
./scripts/commit-preflight.sh
git add spec-implement plugins/spec-implement
git commit -m "feat(spec-implement): publish as plugin, self-contained refs (1.0.0)"
```

---

### Task 4: Repo wiring — marketplace, README, root CHANGELOG

**Files:**
- Modify: `.claude-plugin/marketplace.json`, `README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: plugin versions produced by Tasks 1-3 (`2.4.1`, `2.2.1`, `1.0.0`).

- [ ] **Step 1: Write the failing assertion**

```bash
jq -e '.plugins[]|select(.name=="spec-implement")' .claude-plugin/marketplace.json >/dev/null \
  && [ "$(jq -r '.plugins[]|select(.name=="spec-creator")|.version' .claude-plugin/marketplace.json)" = "2.4.1" ] \
  && [ "$(jq -r '.plugins[]|select(.name=="spec-review")|.version' .claude-plugin/marketplace.json)" = "2.2.1" ] \
  && echo PASS || echo FAIL
```

- [ ] **Step 2: Run it to verify it fails**

Expected: `FAIL` (no `spec-implement` entry; versions still 2.3.0 / 2.1.0).

- [ ] **Step 3: Update `.claude-plugin/marketplace.json`**

Bump `spec-creator` to `2.4.1` and `spec-review` to `2.2.1`. Add a `spec-implement`
entry matching the shape of its siblings exactly (same key order, `"source": "./plugins/spec-implement"`),
keeping the plugin list in its existing alphabetical position.

- [ ] **Step 4: Add the plugin row to the root README**

Add `spec-implement` to the plugin catalog table, matching the existing row
format and alphabetical placement, and correct the `spec-creator` / `spec-review`
version cells to `2.4.1` / `2.2.1`.

- [ ] **Step 5: Add the root CHANGELOG entry**

Under the `Unreleased` heading (create it if absent, matching the file's existing
heading style):

```markdown
### Added

- `spec-implement` published as a marketplace plugin (#59).

### Fixed

- `spec-creator`, `spec-review`, and `spec-implement` no longer reference
  `~/.claude/skills/` paths; all three resolve their scripts and references
  relative to the skill directory, making them installable by third parties (#59).

### Changed

- Authoring source for the `spec-*` family moved into the monorepo.
```

- [ ] **Step 6: Verify**

```bash
# Re-run the Step 1 assertion — expect PASS
jq -e '.plugins[]|select(.name=="spec-implement")' .claude-plugin/marketplace.json >/dev/null \
  && [ "$(jq -r '.plugins[]|select(.name=="spec-creator")|.version' .claude-plugin/marketplace.json)" = "2.4.1" ] \
  && [ "$(jq -r '.plugins[]|select(.name=="spec-review")|.version' .claude-plugin/marketplace.json)" = "2.2.1" ] \
  && echo PASS || echo FAIL

# marketplace version must equal each plugin.json version
for p in spec-creator spec-review spec-implement; do
  m=$(jq -r --arg n "$p" '.plugins[]|select(.name==$n)|.version' .claude-plugin/marketplace.json)
  j=$(jq -r .version plugins/$p/.claude-plugin/plugin.json)
  [ "$m" = "$j" ] && echo "$p OK $m" || echo "$p MISMATCH marketplace=$m plugin=$j"
done

# whole-repo sweep over EXECUTABLE surfaces only: no spec-* path may point at
# the local skills dir. CHANGELOG prose quotes the old path when describing the
# fix, and generated plugin READMEs carry a `cp -r … ~/.claude/skills/`
# manual-install line — both legitimate, both excluded.
grep -rn '~/\.claude/skills/spec-' \
  spec-creator/SKILL.md spec-review/SKILL.md spec-implement/SKILL.md \
  spec-creator/scripts/ spec-review/scripts/ spec-implement/scripts/ \
  spec-creator/references/ spec-review/references/ spec-implement/references/ \
  spec-review/README.md \
  plugins/spec-creator/skills/ plugins/spec-review/skills/ plugins/spec-implement/skills/ \
  && echo SWEEP-FAIL || echo SWEEP-PASS
```

Expected: `PASS`, three `OK` lines, `SWEEP-PASS`.

- [ ] **Step 7: Commit**

```bash
./scripts/commit-preflight.sh
git add .claude-plugin/marketplace.json README.md CHANGELOG.md
git commit -m "chore: wire spec-* plugins into marketplace, README, changelog (#59)"
```

---

## Out of scope for this plan

- **Deleting `~/.claude/skills/spec-{creator,review,implement}`.** Destructive and
  outside the repo; the orchestrator performs it after installing the plugins from
  the branch and exercising each skill with the local copies renamed away.
- **Publishing the marketplace release.** Requires a release branch merged to `main`,
  which is a separate deliberate step.
- **Teaching `sync-monorepo.sh` about in-repo-source skills.** It syncs from
  `$HOME/.claude/skills/<name>` and will now skip `spec-*` with a non-fatal
  "SKILL.md not found" error. Track as a follow-up issue.
