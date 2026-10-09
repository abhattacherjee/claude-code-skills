---
name: publish
description: "Was the skill-publishing skill. Publishes Claude Code skills as installable plugins and syncs them to a GitHub monorepo. Plugin-first: every skill with a plugin-manifest.json is auto-assembled and synced as a plugin. Also supports bare skill publishing and individual repos. Use when: (1) user says 'publish', 'share', or 'sync' a skill, (2) a skill needs to be made installable by others, (3) syncing skills/plugins to the monorepo, (4) creating a versioned monorepo release, (5) assembling a plugin from skills + commands, (6) user says 'publish plugin' or 'package plugin'."
metadata:
  version: 1.2.0
---

# Publish Skills & Plugins

> **Paths:** Commands call this skill's scripts as `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. Claude Code fills in this skill's directory before the text reaches you, so the command works from the project directory. Values you only know at run time are `<NAME>` placeholders: write the real value in their place, for example `<MONOREPO_DIR>` (the monorepo checkout), `<SKILL_DIR>`, `<SKILL_NAME>`, `<GITHUB_USER>` and `<MANIFEST_PATH>`.

> **Plugin-only monorepos have their own mode (#190).** A monorepo with `plugins/*/.claude-plugin/plugin.json` and no top-level skill directory (such as `claude-code-skills` itself) is synced by running `validate-plugin.sh` on every plugin (any failure: exit 1, nothing written) and then `scripts/catalogue.py`, which writes the catalogue (and nothing else, except the plugin `--add-plugin` copies): the README plugin table, `marketplace.json` and each plugin README's meta line, all from `plugin.json`. `--dry-run` checks and writes nothing, `--add-plugin` checks the build in a staging copy before it copies it, and `--skills`, `--add` and `--init` are refused. After you change a `plugin.json`, write the catalogue with `"${CLAUDE_SKILL_DIR}/scripts/catalogue.py" "<MONOREPO_DIR>"`, or add `--check` before the directory to report drift without writing (exit 0 clean, 1 drift, 2 cannot run). Modes, `--json` and exit codes: [references/plugin-only-monorepo.md](references/plugin-only-monorepo.md).

**Plugin-first publishing** for Claude Code skills. Every skill with a `plugin-manifest.json`
is automatically assembled and synced as an installable plugin. Bare skills (without manifests)
are synced as standalone directories. Both live in the `claude-code-skills` monorepo.

## Quick Reference

```bash
# --- Monorepo sync (auto-discovers plugins) ---
"${CLAUDE_SKILL_DIR}/scripts/validate-pre-sync.sh" "<MONOREPO_DIR>"        # Pre-sync gate (MANDATORY)
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --dry-run "<MONOREPO_DIR>"   # Preview
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" "<MONOREPO_DIR>"             # Sync (auto-builds plugins)

# --- Monorepo (add a new skill) ---
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --add my-new-skill "<MONOREPO_DIR>"

# --- Monorepo (initialize; there is no default skill set) ---
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --init --skills my-skill "<MONOREPO_DIR>"

# --- Monorepo release (version tag) ---
"${CLAUDE_SKILL_DIR}/scripts/release-monorepo.sh" patch "<MONOREPO_DIR>"   # Bug fixes
"${CLAUDE_SKILL_DIR}/scripts/release-monorepo.sh" minor "<MONOREPO_DIR>"   # New skill/plugin
"${CLAUDE_SKILL_DIR}/scripts/release-monorepo.sh" major "<MONOREPO_DIR>"   # Breaking change

# --- Plugin (manual assemble + validate) ---
"${CLAUDE_SKILL_DIR}/scripts/prepare-plugin.sh" "<MANIFEST_PATH>"      # Build plugin
"${CLAUDE_SKILL_DIR}/scripts/validate-plugin.sh" ./build/<PLUGIN_NAME>                # Validate
"${CLAUDE_SKILL_DIR}/scripts/install-plugin.sh" ./build/<PLUGIN_NAME>                 # Install locally

# --- Individual repo (first-time publish) ---
"${CLAUDE_SKILL_DIR}/scripts/prepare-skill-repo.sh" "<SKILL_DIR>"

# --- Individual repos (sync all published) ---
"${CLAUDE_SKILL_DIR}/scripts/sync-individual-repos.sh" --all --push
```

## Architecture

```
~/.claude/skills/              (SOURCE OF RECORD)
├── my-plugin-skill/           (has plugin-manifest.json → synced as PLUGIN)
│   └── plugin-manifest.json
├── my-skill/                  (no manifest → synced as BARE SKILL)
└── ...

Monorepo that sync writes:     (top-level skills, plus plugins)
└── github.com/USER/<monorepo>
    ├── README.md              (auto-generated: skill table + plugin section)
    ├── my-skill/              (bare skill — flat at root)
    ├── plugins/               (plugins — auto-assembled from manifests)
    │   └── my-plugin-skill/
    │       ├── .claude-plugin/plugin.json
    │       ├── commands/
    │       └── skills/
    └── scripts/
        ├── validate-skill.sh
        ├── validate-plugin.sh
        └── install-plugin.sh
```

**Key principles**:
- `~/.claude/skills/` is the single source of truth
- **Plugin-first**: Skills with `plugin-manifest.json` are auto-assembled into plugins during sync
- Skills without manifests are synced as bare directories (backward compatible)
- `sync-monorepo.sh` handles both automatically — no separate `--add-plugin` needed for known plugins

## Interactive Publishing Flow

When invoked (e.g., "publish this skill", "share skill", "sync skills"), start with target selection.

### Step 1: Detect Current State

For the skill being published, detect which targets it's already published to:

```bash
SKILL_DIR="<SKILL_DIR>"
SKILL_NAME="<name-from-frontmatter>"
GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null)
if [[ -z "$GITHUB_USER" ]]; then echo "Stop: gh is not logged in. Run 'gh auth login' first." >&2; exit 1; fi
MONOREPO_DIR="<MONOREPO_DIR>"

# Has plugin manifest? (determines default target)
HAS_MANIFEST=false
[[ -f "$SKILL_DIR/plugin-manifest.json" ]] && HAS_MANIFEST=true

# Plugin synced?
PLUGIN_SYNCED=false
[[ -d "$MONOREPO_DIR/plugins/$SKILL_NAME" ]] && PLUGIN_SYNCED=true

# Bare skill synced?
MONOREPO_SYNCED=false
[[ -f "$MONOREPO_DIR/$SKILL_NAME/SKILL.md" ]] && MONOREPO_SYNCED=true

# Individual repo?
INDIVIDUAL_PUBLISHED=false
gh repo view "$GITHUB_USER/$SKILL_NAME" --json name >/dev/null 2>&1 && INDIVIDUAL_PUBLISHED=true
```

### Step 2: Present Target Selection (Plugin-First)

Use `AskUserQuestion` with `multiSelect: true`. **Default: Plugin is pre-selected when manifest exists.** If no manifest exists, offer to create one.

**Question**: "Which publishing targets do you want for `<skill-name>`?"

**Options** (ordered by priority — plugin first):

| State | Label | Default | Description |
|-------|-------|---------|-------------|
| Has manifest, not synced | `Plugin (recommended)` | **SELECTED** | "Assemble and sync as installable plugin" |
| Has manifest, synced | `Plugin (synced)` | **SELECTED** | "Keep synced. Deselect to REMOVE" |
| No manifest | `Plugin` | disabled | "Create a plugin-manifest.json first (see below)" |
| Not synced | `Bare skill` | unselected | "Add as bare directory (no plugin format)" |
| Synced | `Bare skill (synced)` | **SELECTED** | "Keep synced. Deselect to REMOVE" |
| Not published | `Individual repo` | unselected | "Create a standalone GitHub repo" |
| Published | `Individual repo (published)` | **SELECTED** | "Keep synced. Deselect to DELETE" |

**When no manifest exists**, prompt:

> This skill doesn't have a `plugin-manifest.json`. Plugins are the recommended format
> for installable skills. Create a minimal manifest now?
>
> A minimal manifest for a single-skill plugin looks like:
> ```json
> {
>   "name": "<skill-name>",
>   "version": "<version-from-SKILL.md>",
>   "description": "<description-from-SKILL.md>",
>   "skills": [{ "name": "<skill-name>", "source": "~/.claude/skills/<skill-name>" }],
>   "commands": []
> }
> ```

**`source` resolution rules** — two supported forms:

- **`~`-prefixed or absolute** — resolves as written (e.g. `~/.claude/skills/skill-name`).
- **Relative** — resolves against the *manifest file's own directory*, not the caller's
  working directory. This is what lets a skill's authoring source live inside the monorepo:
  when the manifest sits inside the skill directory it describes (the
  `<skill>/plugin-manifest.json` layout the `spec-*` plugins use), the correct value is
  `"source": "."` — `"source": "<skill-name>"` resolves to `<skill>/<skill>` and fails.

`sync-monorepo.sh` uses **local-first** precedence when both forms exist for the same skill:
`<SKILLS_HOME>/<name>` (default `~/.claude/skills/<name>`) wins over an in-repo source directory, and the sync log records a
`SKIP (shadowed)` note naming both paths when it dedupes.

**Reversion guard** — local-first is *not* unconditional. A stale local copy left behind after a
skill moved into the monorepo would otherwise overwrite newer in-repo content. When the in-repo
`SKILL.md` version is strictly newer than the local one, that skill is **REFUSED**: the skill
sync, the plugin auto-build, and the plugin resync all skip it (logging `SKIP (reversion guard)`),
its catalog/CHANGELOG metadata is read from the in-repo copy instead, the rest of the sync still
runs, and the script exits **3** — completed, but see below for the full exit-code contract.
Resolve it by deleting the stale local copy so the in-repo copy becomes the source, or re-run
with `--force-local` to let the local copy win deliberately.

If user agrees, create the manifest and proceed with plugin publishing.

### Team Mode: Parallel Skill Publishing

When Agent Teams are enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) and publishing multiple skills, each skill's validation + sync can be assigned to a separate teammate for parallel processing. This is especially useful during monorepo syncs involving 5+ skills — each teammate runs `validate-pre-sync.sh` and prepares its skill independently, then the lead commits and releases.

### Step 3: Dispatch

**For each SELECTED target:**

| Target | Already Published? | Action |
|--------|--------------------|--------|
| Plugin | No | Auto-handled by `sync-monorepo.sh` if manifest exists (or manual **Workflow E**) |
| Plugin | Yes | Auto-rebuilt on next sync if source drifted (or manual **Workflow E**) |
| Bare skill | No | Run `"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --add <name> "<MONOREPO_DIR>"` then **Workflow B** |
| Bare skill | Yes | Run **Workflow B** (sync monorepo) |
| Individual repo | No | Run **Workflow A** (prepare + push) |
| Individual repo | Yes | Run **Workflow C** (sync individual repo) |

**For each DESELECTED target that was previously published (removal):**

| Target | Removal Action |
|--------|---------------|
| Plugin | `rm -rf "<MONOREPO_DIR>/plugins/<SKILL_NAME>/"` then re-sync README + commit + push |
| Bare skill | `rm -rf "<MONOREPO_DIR>/<SKILL_NAME>/"` then re-sync README + commit + push |
| Individual repo | `gh repo delete <GITHUB_USER>/<SKILL_NAME> --yes` (confirm with user first!) |

**Always confirm destructive removals** with the user before executing.

### Step 4: Pre-Sync Validation (MANDATORY GATE)

**Before syncing, validate that every skill's CHANGELOG matches its version.** This catches the common failure where SKILL.md version is bumped but CHANGELOG.md is not updated.

```bash
# GATE: Validate all skill CHANGELOGs match their SKILL.md versions
"${CLAUDE_SKILL_DIR}/scripts/validate-pre-sync.sh" "<MONOREPO_DIR>"
```

**On a plugin-only monorepo** it checks plugins, not CHANGELOGs: every plugin must pass `validate-plugin.sh` and `catalogue.py` with `--check` must find no drift (see [references/plugin-only-monorepo.md](references/plugin-only-monorepo.md)). Fix what it lists, or run `catalogue.py` to write the catalogue.

**On any other monorepo, if validation fails (exit code 1):** STOP. Do not proceed to sync. Fix each failing skill:
1. Open the skill's `CHANGELOG.md`
2. Add a `## [X.Y.Z] - YYYY-MM-DD` entry describing what changed
3. Re-run validation until it passes

**This gate is non-negotiable.** The monorepo must never receive a skill whose CHANGELOG is behind its version.

### Step 5: Auto-Sync to Monorepo

**When any Monorepo or Plugin target is selected, automatically sync and push.** Do NOT leave this as a manual step — the user expects publishing to be end-to-end. On a plugin-only monorepo the sync writes only the catalogue (and the plugin `--add-plugin` copies): see the plugin-only note at the top.

`sync-monorepo.sh` automatically handles both bare skills and plugins:
- Skills **with** `plugin-manifest.json` → auto-assembled via `prepare-plugin.sh` and synced to `plugins/`
- Skills **without** manifest → synced as bare directories at monorepo root

Sync on a branch and open a PR; never commit or push to `main`. **Which branch:** if the skill change is already committed on a feature branch of the monorepo (skills edited in place, as in `claude-code-skills`), stay on it and skip the `fetch` and `switch` lines. Otherwise branch from a fresh `origin/<BASE_BRANCH>`, as below. `<BASE_BRANCH>` is the branch the monorepo's own rules (its CLAUDE.md or CONTRIBUTING.md) send feature PRs to: `develop` for `claude-code-skills`, which uses Git Flow. Stage the paths the sync wrote by name: staging everything would also sweep in `./build/` output and stray files.

```bash
git -C "<MONOREPO_DIR>" fetch origin "<BASE_BRANCH>"
git -C "<MONOREPO_DIR>" switch -c "feature/sync-skills-<YYYY-MM-DD>" "origin/<BASE_BRANCH>"
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" "<MONOREPO_DIR>"   # sync all skills + auto-build plugins
git -C "<MONOREPO_DIR>" status --short                            # the paths the sync wrote
git -C "<MONOREPO_DIR>" add -- <PATH>...                          # each path from that list, by name
git -C "<MONOREPO_DIR>" commit -m "Sync skills (<YYYY-MM-DD>)"
git -C "<MONOREPO_DIR>" push -u origin HEAD
(cd "<MONOREPO_DIR>" && gh pr create --base "<BASE_BRANCH>" --fill)
```

If `status` lists nothing, there is nothing to commit: delete the branch and skip the PR.

### Step 6: Monorepo Release (MANDATORY)

**After every sync that changes skill content, ALWAYS create a monorepo release** once the sync PR has merged. `release-monorepo.sh` commits the CHANGELOG on `main` and pushes `origin main --tags` itself, so run it only when the user has approved that push. It refuses (exit 1, before any commit or tag) when HEAD is not `main` or `main` is behind `origin/main`. Pass the commit attribution line your session gives you with `--co-author`; with none, leave the flag out (no trailer). A Git Flow monorepo such as `claude-code-skills` releases through its own release flow (`git-flow:release`) instead of this script.

```bash
# Determine bump level from what changed:
#   - patch: typo fixes, sync-only updates, no SKILL.md changes
#   - minor: skill version bumps, new features, new scripts
#   - major: new skill added, skill removed, breaking structure changes
git -C "<MONOREPO_DIR>" switch main
git -C "<MONOREPO_DIR>" pull --ff-only
"${CLAUDE_SKILL_DIR}/scripts/release-monorepo.sh" --co-author "<ATTRIBUTION_LINE>" <patch|minor|major> "<MONOREPO_DIR>"
```

**Bump level decision:**
| What Changed | Bump |
|---|---|
| Skill version bumped (e.g., v2.3.0 → v2.4.0) | `minor` |
| New skill added to monorepo | `minor` |
| Plugin added or restructured | `minor` |
| Typo/wording fixes only, no version changes | `patch` |
| Skill removed or breaking layout change | `major` |

### Step 7: Post-Publish

After all targets are processed:
1. Clean up build artifacts from a manual Workflow E run: `rm -rf ./build/<plugin-name>` (`prepare-plugin.sh` writes there, relative to where you ran it; the auto-build inside `sync-monorepo.sh` uses a temp dir)
2. Report summary of what was published/synced/released

**Summary must include:**
- Skills synced (with version numbers)
- Monorepo release version created
- Individual repos updated (if any)
- Any validation failures that were fixed

---

## Workflow A: Publish a New Skill (Individual Repo)

### Step 1: Run the Preparation Script

```bash
"${CLAUDE_SKILL_DIR}/scripts/prepare-skill-repo.sh" "<SKILL_DIR>"
```

The script:
- Reads `SKILL.md` frontmatter to extract `name`, `description`, `version`
- Creates `.gitignore` (with `.claude/` exclusion for local settings)
- Creates `LICENSE` (MIT)
- Creates `CHANGELOG.md` from the extracted metadata
- Generates a `README.md` with individual + monorepo install instructions
- Reports what files already exist (skips them) vs what was created

### Step 2: Review and Customize

After the script runs, review the generated files. Common customizations:
- **README.md**: Add a Prerequisites section if the skill has dependencies (e.g., `jq`, `perl`)
- **README.md**: Add usage examples specific to the skill
- **CHANGELOG.md**: Expand the "Included" section with more detail
- **SKILL.md**: Add a See Also section linking to the GitHub repo

### Step 3: Add See Also to SKILL.md

Append to the end of `SKILL.md`:

```markdown
## See Also

- **GitHub**: https://github.com/<github-user>/<skill-name> — install instructions, changelog, license
```

### Step 4: Initialize Git and Push

```bash
cd "<SKILL_DIR>"
git init
git add .gitignore LICENSE CHANGELOG.md README.md SKILL.md scripts/ references/
git commit -m "Initial public release: <skill-name> v<version>"
gh repo create <skill-name> --public --description "<short-description>" --source . --push
git tag v<version>
git push origin v<version>
```

**Known gotcha**: If `git remote add origin` was already run before `gh repo create --source .`,
the latter fails with "Unable to add remote" — but the repo IS created. Fix with
`git remote set-url origin <url>` then push manually.

**Username discovery**: `gh repo create` reveals the actual GitHub username (e.g., `abhattacherjee`
not `abhishek`). After repo creation, update any references in README.md and SKILL.md with the
correct username.

### Step 5: Verify

After pushing:
1. Clone to a temp dir: `git clone <url> /tmp/test-skill`
2. Confirm `SKILL.md` is at root with correct frontmatter
3. Confirm `scripts/` and `references/` are present (if applicable)
4. Check that `.claude/` was NOT committed

## Workflow B: Sync to Monorepo

### First Time: Initialize the Monorepo

```bash
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --init --skills my-skill,other-skill "<MONOREPO_DIR>"
```

This creates the directory, syncs the skills you name with `--skills` (or `--add`), generates the root README with a catalog table, and creates + pushes the GitHub repo. There is no default skill set: the old one named top-level skills that #167 deleted, so `--init` with no skill named exits 1 before creating anything.

### Ongoing: Sync Changes

```bash
# Preview changes
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --dry-run "<MONOREPO_DIR>"
# Sync
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" "<MONOREPO_DIR>"
```

Then commit on a branch and open a PR, as in Step 5.

### Adding a New Skill to the Monorepo

```bash
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --add my-new-skill "<MONOREPO_DIR>"
```

`--skills a,b` replaces the synced set; `--add` appends. **They are mutually exclusive** — passing both is rejected at parse time with exit 1, rather than one silently winning. Both de-duplicate repeats, but they refuse on **different thresholds**: `--add` refuses if *any* name it contributes is unresolvable; `--skills` refuses only if *all* of them are — so a typo in a `--skills` list still publishes the rest. `--skills` re-syncs only the named top-level skills. Plugins are still checked and rebuilt, and a plugin whose source is older than the monorepo's copy is refused (exit 3) as in a full sync; the README catalogue, its skill count and the install-all lines still list every top-level skill (#93). The CHANGELOG's sync entry covers only the skills synced in that run.

**Exit codes**: `0` success; `3` completed, but a stale local source was refused (a top-level skill, or a plugin's source, on every run including `--skills`); `1` usage/setup error (bad names) or a manifest that could not be published, and `1` beats `3`. These `1`s stop the run before anything is written: a `plugin-manifest.json` that is not a valid JSON object; a `skills[]` value that is not an array, or an entry that is not a name or an object with a string name and source; a published plugin whose skill source does not resolve; and, with `--skills`, another top-level skill whose `SKILL.md` cannot be read. These stop it after the skills are written: a build that failed, and a bare-string `agents[]` entry. `--dry-run` predicts `3` and every `1` except a build failure.

## Workflow C: Sync Individual Repos

When you update a skill locally and want to push changes to its individual GitHub repo:

```bash
# Preview changes to all published repos
"${CLAUDE_SKILL_DIR}/scripts/sync-individual-repos.sh" --dry-run --all

# Sync all and auto-push
"${CLAUDE_SKILL_DIR}/scripts/sync-individual-repos.sh" --all --push

# Sync a specific skill
"${CLAUDE_SKILL_DIR}/scripts/sync-individual-repos.sh" conversation-search
```

## Workflow D: Monorepo Release (Version Tag)

After syncing skills to the monorepo and committing, create a versioned release:

After the sync PR from Step 5 has merged, with the user's approval to push to `main`, run the Step 6 commands.

`release-monorepo.sh` counts top-level `<name>/SKILL.md` and `plugins/<plugin>/skills/<name>/SKILL.md` skills, lists a plugin skill as `<plugin>:<name>`, and exits 1 without writing anything when it finds no skill in either layout.

Bump levels: the Step 6 table.

The script:
- Reads current version from the latest `v*` semver tag
- Calculates the next version based on bump level
- Updates the CHANGELOG top entry from "Monorepo sync" to a versioned section
- Commits the changelog update
- Creates an annotated tag with skill inventory
- Pushes to `origin main --tags`

Use `--dry-run` to preview without making changes.

**Prerequisite**: All changes must be committed before running. The script rejects uncommitted changes.

**CHANGELOG gotchas** (both scripts write the monorepo CHANGELOG): `sync-monorepo.sh` writes a `## [<date>] — Monorepo sync` entry and `release-monorepo.sh` turns it into `## [X.Y.Z] - <date>`. Each must recognise the other's heading before it writes: replace a sync entry, keep a versioned one, else prepend. When you change either script, add blank lines at the point where strings are joined: `$(...)` strips trailing newlines, even from `printf '%s\n\n'`, and two entries then run together.

## Workflow E: Publish a Plugin (Manual Fallback)

> **Note:** For skills that already have a `plugin-manifest.json`, `sync-monorepo.sh`
> auto-builds and syncs the plugin. Use this manual workflow only for first-time setup,
> debugging, or when you need to control the build/validate cycle explicitly.

A plugin bundles skills + commands + optional agents/hooks into a single installable package.

### Plugin Format

```
plugin-name/
├── .claude-plugin/plugin.json   # Required manifest: {name, version, description}
├── commands/                    # Slash commands (.md files)
├── skills/skill-name/           # Skills (SKILL.md + scripts/ + references/)
├── agents/                      # Subagents (.md files, optional)
└── hooks/                       # hooks.json + scripts (optional — see note below)
```

### Step 1: Create Build Manifest

Create `plugin-manifest.json` in the skill directory that anchors the plugin:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Short description",
  "skills": [{ "name": "my-skill", "source": "~/.claude/skills/my-skill" }],
  "commands": [{ "name": "cmd-name", "source": "~/.claude/commands/cmd-name.md" }]
}
```

`skills[]` also accepts a legacy bare string (normalised to `source: "."`); bare strings in `commands[]`/`agents[]` are hard errors instead. A declared `hooks.source` that doesn't resolve is fatal too (absent/`null` remain no-ops).

### Step 2: Assemble

```bash
"${CLAUDE_SKILL_DIR}/scripts/prepare-plugin.sh" "<MANIFEST_PATH>"
```

This creates `./build/<plugin-name>/` with the official plugin format, scaffolding, and auto-runs validation.

### Step 3: Validate

```bash
"${CLAUDE_SKILL_DIR}/scripts/validate-plugin.sh" ./build/<plugin-name>
```

### Step 4: Sync to Monorepo

```bash
"${CLAUDE_SKILL_DIR}/scripts/sync-monorepo.sh" --add-plugin <plugin-name> "<MONOREPO_DIR>"
```

Then commit `plugins/<plugin-name>/` and the catalogue files the sync lists on a branch, and open a PR, as in Step 5.

### Step 5: Install (Consumer)

```bash
git clone https://github.com/USER/claude-code-skills.git /tmp/ccs
"${CLAUDE_SKILL_DIR}/scripts/install-plugin.sh" /tmp/ccs/plugins/<plugin-name>
rm -rf /tmp/ccs
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Plugin-first default** | Manifest → plugin | Plugins are the installable unit; bare skills are for simple cases without commands/agents |
| **Auto-assemble on sync** | `sync-monorepo.sh` builds plugins | Eliminates manual `prepare-plugin.sh` + `--add-plugin` for known plugins |
| `.claude/` in `.gitignore` | Always | Contains `settings.local.json` with user-specific permissions |
| License | MIT default | Most permissive, standard for open-source tools |
| Version from frontmatter | Use as-is | Avoids version mismatch between SKILL.md and tag |
| Flat copy, not subtree | By design | Simpler mental model; local dir is single source of truth |
| Monorepo README | Plugin table generated | The plugin table between the catalogue markers comes from each plugin.json via catalogue.py; never hand-edit inside the markers. In a plugin-only monorepo the rest is hand-written. |
| Plugins in `plugins/` subfolder | By design | Different structure than bare skills; separates concerns |
| Plugin build manifest (JSON) | `jq` dependency | Plugins bundle multiple sources; CLI-only would be unwieldy |
| `install-plugin.sh` in monorepo | Consumer-facing | Users need it to install plugins; not just an author tool |

## See Also

- `skill-kit:author` — how to structure and write skills (the content)
- This skill handles the distribution packaging (the container)
- **GitHub**: https://github.com/abhattacherjee/claude-code-skills/tree/main/plugins/skill-kit — install instructions, changelog, license
