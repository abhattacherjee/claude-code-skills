# Changelog

All notable changes to the **skill-kit** plugin are documented here.

## [1.2.0] - 2026-10-09

### Changed

- `extract` 1.1.0: Step 1 calls the new `scripts/find-skills.sh` instead of an inline script; removed `resources/skill-template.md` (its frontmatter broke the `author` rules it points to); `resources/research-references.md` is linked and has a Contents list; `find-skills.sh` exits 3 on an `rg` error; cut repeated trigger lists and prompts (#210).
- `publish` 1.2.0: syncs on a branch and opens a PR instead of `git add -A` and a push to `main`; the release step waits for the merge and the user's approval; removed the unused `references/readme-template.md`; body under 500 lines. `release-monorepo.sh` releases only from an up-to-date `main` and takes `--co-author`; `sync-monorepo.sh` prints branch-and-PR next steps (#210).
- `author` 1.0.2: links `references/quality-checklist.md` instead of an inline copy, and cuts repeated principles (#210).

## [1.1.1] - 2026-10-06

### Fixed

- `publish`: `sync-monorepo.sh` finds each plugin skill through its manifest's `source` in the auto-build drift check and the plugin resync, as `prepare-plugin.sh` does. A manifest whose skill name differs from its source directory (`custom-statusline`: skill `install-statusline`) was never rebuilt or resynced, with no output. For a plugin with a manifest the skill is never looked up by name; a skill directory the manifest no longer lists is skipped with a warning. These stop the sync with exit 1 before anything is written, naming the manifest: a manifest that is not a valid JSON object (it used to abort with exit 5 and no message, after skills were written); a `skills[]` value that is not an array, or an entry that is not a name or an object with a string name and source (null, a number, a boolean, an array); and, for a published plugin, a source that does not resolve. The reversion guard now checks every plugin source on every run, before anything is written, including a `--skills` run, which used to rebuild a plugin from a stale local source at exit 0: a source older than the monorepo's copy is refused, under its own name, under another name or through a symlink, and the run exits 3. The resync takes the plugin-root `CHANGELOG.md` from the manifest's first skill, not the first directory by name (#92).
- `publish`: `sync-monorepo.sh --skills <subset>` re-syncs those top-level skills and keeps the full catalogue. The README rows, the skill count and the install-all lines still list every top-level skill, in the order a full sync writes them; plugins are still checked and rebuilt. Before, the catalogue shrank to the named skills. A skill not synced in the run takes its row from its published `SKILL.md`, built by the same function as the main loop's rows (`skill_row`): no version gives 1.0.0 and no description gives an empty one with a warning, as a full sync writes them. When `gh` fails, a row keeps its repo link from the existing README, in both paths. If such a `SKILL.md` cannot be read, the run stops with exit 1 before anything is written. A `--skills` name with no `SKILL.md` gets no install line, and naming no real skill is still refused (#93).
- `publish`: `prepare-plugin.sh` leaves a `SKILL.md` section out of the plugin README when its prose holds a placeholder, and prints `dropped section "<title>": placeholder <x> in prose` on stderr; `sync-monorepo.sh` passes the note on when it publishes that README. A placeholder is `<`, optional spaces, a letter, then letters, digits, `_`, `-`, `.`, `/` or spaces, then `>`, in any case (`<github-user>`, `<GITHUB_USER>`, `<your repo>`, `<owner/repo>`); other styles such as `{{NAME}}` are not caught. Common HTML tags are not placeholders; the allow-list is checked on the whole tag name followed by a space, `/` or `>`, so `<details open>` and `<br/>` pass and `<code-dir>` does not. Placeholders in fenced blocks and in inline code stay; fences and code spans follow CommonMark (at most 3 spaces of indent, or the item's content column plus 3 right after a list item; no backtick in a backtick fence's info string; a code span closes at the next backtick run of the same length). The build stops with exit 1 if a section cannot be read, if a section's code fence is never closed, or if the check itself fails, rather than publish the section unchecked. `extract_section` and `extract_headings` skip `## ` lines inside fenced code blocks, including a fence line saved with CRLF: skill-publishing's `SKILL.md` has a `## See Also` template in a code block, and it became that README's See Also (#106).
- The repo's `scripts/test-sync-hygiene.sh`, which tests these scripts, no longer turns plugin validation off for every case. Its fixtures are valid skills now; only the 9 description-parsing fixtures that must be invalid skip validation, each with a reason (#106).

## [1.1.0] - 2026-10-06

### Added

- `publish`: `scripts/catalogue.py` writes the plugin catalogue from each `plugin.json`: the root README plugin table (between `<!-- catalogue:start -->` and `<!-- catalogue:end -->`), `.claude-plugin/marketplace.json` and one meta line in each plugin README. `--check` writes nothing and reports drift, including any change a write would make (exit 0 clean, 1 drift, 2 cannot run). `--validate-plugins` only loads and checks the plugins, the write targets and `marketplace.json`. A write goes through temp files and renames, so a failed write leaves nothing half done, and it names any file it already replaced. A plugin README names a skill or agent only as `` `name` ``, `<plugin>:name` or `/name`. It also checks that each plugin README names its skills and agents, and that the README's install lines use this marketplace. It fails closed: a missing marker, a bad `plugin.json`, name or version, a name or description holding `<!--` or `-->`, a stray `plugins/` directory, an unreadable `skills/`, `agents/` or `commands/` directory, or a write target that is a symlink is exit 2 (#190).
- `publish`: `scripts/standalone-plugins.txt` lists the standalone plugins (`git-flow`, `obsidian-brain`). `catalogue.py`, `sync-monorepo.sh` and `validate-pre-sync.sh` read it; both parse it the same way (spaces and CR stripped, `#` comments, one plugin name per line, any other line refused), and a missing or unreadable list is an error, never an empty list; it replaces the `STANDALONE_PLUGINS` line in `sync-monorepo.sh` (#190).
- `publish`: `references/plugin-only-monorepo.md` describes the plugin-only mode and the catalogue (#190).

### Changed

- `publish`: `sync-monorepo.sh` syncs a plugin-only monorepo instead of refusing it. A plain sync runs `validate-plugin.sh` on every plugin (any failure: exit 1, nothing written) and then `catalogue.py`, and writes nothing else, except the plugin `--add-plugin` copies. `--dry-run` validates and prints the drift. `--add-plugin` validates the build and every plugin, and runs `catalogue.py --check` on a staging copy with the build in it, before it copies; a build whose `plugin.json` name is not the `--add-plugin` name is refused, and so is any symlink in `plugins/`, in `./build` or the build, so nothing is ever copied through one. A crashing `catalogue.py` counts as "cannot run", never drift. A refusal before the plugin-only mode starts still prints the JSON object, with `"catalogue": "not-run"`. `--skills`, `--add` and `--init` are refused. The new `--json` prints `{"layout", "validated", "catalogue"}` (#190).
- `publish`: `validate-pre-sync.sh` on a plugin-only monorepo validates every plugin and runs `catalogue.py --check`; exit 1 if either fails. `--json` keeps its shape and adds `layout`, `catalogue` and `catalogue_lines` (#190).
- `publish`: in every other layout, `catalogue.py` writes the README plugin table and `marketplace.json`, so one tool writes them. The old `marketplace.json` was built as a string and broke on a description with a quote or a backslash. `marketplace.json` keeps its `owner` and `metadata`; a sync no longer rewrites `metadata.version` with the date. The sync runs `catalogue.py --validate-plugins` before its first write and again before the README. A REFUSED skill (exit 3) is no longer hidden by catalogue drift, and `--init` does not initialise while the catalogue needs a hand edit. `catalogue.py` and `standalone-plugins.txt` are copied into the monorepo's `scripts/`, and the `workflow-monorepo.yml` template runs `catalogue.py --check` when the monorepo has `plugins/` (#190).
- `publish`: `SKILL.md` describes the plugin-only mode in place of the #167 refusal (#190).
- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).

## [1.0.2] - 2026-10-05

### Fixed

- `publish`: `sync-monorepo.sh` and `validate-pre-sync.sh` refuse a plugin-only monorepo in every mode (discovery, `--skills`, `--add`, `--add-plugin`, `--init`, `--dry-run`, `--json`): one that has `plugins/*/.claude-plugin/plugin.json` and no top-level skill directory, like this repo since #167. They exit 1 with one message before writing anything; `validate-pre-sync.sh --json` also prints a JSON error object. Before, an `--add-plugin` run on a copy of this repo rewrote its README, CHANGELOG, marketplace catalogue and CI workflow at exit 0. Any other monorepo is handled as before. Sync for plugin-only monorepos is being redesigned in #190. A top-level symlink to a skill directory does not count as a top-level skill, because discovery skips symlinks; the refusal test and discovery now read one shared candidate list (`list_top_level_candidates` in `_lib.sh`). Before, such a symlink let a sync of an otherwise plugin-only monorepo through, and it rewrote README.md, CHANGELOG.md, validate-skill.yml and marketplace.json.
- `publish`: `--init`, or a monorepo directory that does not exist, with no skill named exits 1. The old default set (`conversation-search`, `skill-authoring`, `skill-publishing`) named top-level skills that #167 deleted (#167).
- `publish`: `release-monorepo.sh` counts and lists skills in both layouts, top-level `<name>/SKILL.md` and `plugins/<plugin>/skills/<name>/SKILL.md`, and lists a plugin skill as `<plugin>:<name>`. With no skill in either layout it exits 1 without writing anything. It counted only top-level files and released "Skills: 0" once those were deleted (#167).
- `publish`: the `workflow-monorepo.yml` template detects changed skills both under `plugins/<group>/skills/<name>/` and in top-level `<name>/` directories (sync still writes those). A failing `git diff origin/main...HEAD` fails the job instead of reading as "no skill changed". A removed skill or plugin directory is skipped with a note; a skill directory still there without `SKILL.md` fails (#167).
- `publish`: `validate-plugin.sh` takes the skill validator's own exit code (it used to take `sed`'s, so a failing skill passed). A `skills/` directory with no skill in it is a FAIL, and so is a skill when `validate-skill.sh` is missing or not executable (it passed as "SKILL.md exists") (#167).
- `publish`: `prepare-plugin.sh` exits 1 when the plugin it assembled fails `validate-plugin.sh`, or when the validator is missing. It used to run it with `|| true`, print "Plugin assembled" and let sync publish the plugin. `SKILL_KIT_NO_PLUGIN_VALIDATION=1` skips the step and says so; only the sync-hygiene test harness sets it (#167).
- `publish`: the CONTRIBUTING text that `sync-monorepo.sh` writes says to add a skill at the repo root, and where a skill that ships inside a plugin goes (#167).
- `publish`: `SKILL.md` states the plugin-only refusal and when sync still applies, tells that refusal apart from a CHANGELOG failure at the pre-sync gate, and drops deleted skills from the architecture diagram and `--init` examples (#167).
- The bundled `validate-skill.sh` (in `author`, `extract` and `publish`) changed in comments and help text only: the usage example no longer names the deleted `changelog-keeper/` directory, and the NOTE names the skills that ship a copy and the frozen exception. `author` and `extract` are at 1.0.1 (#167).

## [1.0.1] - 2026-10-05

### Fixed

- `publish`: the `--add-plugin` usage example named `obsidian-brain`, a plugin this repo no longer carries (#166). It now shows `<plugin-name>`.
- `publish`: `sync-monorepo.sh` skips `obsidian-brain` as a standalone plugin, as it already did `git-flow`. `--add-plugin` refuses any standalone plugin (exit 1, nothing written). It takes a bare lowercase name only, and it also reads the `name` in the built `plugin.json`, so `obsidian-brain/`, `Obsidian-Brain` or a differently named build dir is refused too. The names live in one variable, `STANDALONE_PLUGINS`.
- `publish`: a regenerated root README builds the install note for each standalone plugin (`git-flow`, `obsidian-brain`) from `STANDALONE_PLUGINS`, one line each.

## [1.0.0] - 2026-10-04

### Added

- First release (#161). It merges the `skill-authoring` plugin, the `skill-publishing` plugin and the bare `claudeception` skill. Three skills under short names: `author` (was `skill-authoring`), `publish` (was `skill-publishing`) and `extract` (was `claudeception`). Invoke them as `/skill-kit:author`, `/skill-kit:publish` and `/skill-kit:extract`. The old names still match as trigger phrases.
- `plugins/skill-kit/skills/publish/` is the source of truth for the publishing scripts. The deprecated `plugins/skill-publishing/` copy is frozen until #167 and is not tested. The old loose `~/.claude/skills/skill-publishing` clone is removed at the post-merge cut-over. `scripts/test-sync-hygiene.sh` tests the shipped files and no longer compares them with a copy outside the repo (#105).
- Smoke tests for the scripts, in `tests/`, and a CI job (`skill-kit-tests`) that runs them. They also check that `author` and `extract` show the `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` tokens only inside fenced code blocks.
- `skills/extract/LICENSE`: the MIT license and "Copyright (c) 2024 Claude Code" notice of [blader/Claudeception](https://github.com/blader/Claudeception), which `extract` is a fork of. The README's License section points to it.

### Changed

- Every script command in the three `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`; each skill was also run once through headless Claude): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<NAME>` placeholders for values known only at run time. The old `publish` text used `$SCRIPTS`, `$MONOREPO_DIR` and `~/.claude/skills/skill-publishing/scripts/`, which only worked from a loose copy.
- Each skill's `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`. The `skill-authoring` and `claudeception` copies were older.
- `claudeception-activator.sh` tells Claude to use `Skill(skill-kit:extract)`. It is still opt-in: the plugin does not register it as a hook.

### Deprecated

- The `skill-authoring` and `skill-publishing` plugins, and the bare `claudeception` and `skill-authoring` skills. They stay in the repo until #167. Install `skill-kit`, then remove the old ones, so the old names cannot win a plain-language request.

### Fixed

- `publish`: `sync-individual-repos.sh` counted with `((ERRORS++))`, `((SKIPPED++))` and `((SYNCED++))` under `set -eu`. On a zero counter that returns status 1, so bash 4.1+ (Linux CI) stopped after the first skill. It now uses `n=$((n + 1))`. The frozen `plugins/skill-publishing/` copy still has the bug (#167).
- `author`: Claude Code replaces `${CLAUDE_SKILL_DIR}` everywhere in a SKILL.md, prose included, so the advice on what to write in a new skill showed the author skill's own absolute path. See `skills/author/CHANGELOG.md`.
- `extract`: Step 1 searched all of `~/.claude/plugins/cache` and `~/.claude/plugins/marketplaces`, old versions and plugins that are not installed included. See `skills/extract/CHANGELOG.md`.

### History

Per-skill history before the merge is in `skills/author/CHANGELOG.md`, `skills/publish/CHANGELOG.md` and `skills/extract/CHANGELOG.md`.
