# Catalogue tool and docs drift guard — design (#190)

Date: 2026-10-05. Issue: #190 (closes #2, #84). Follow-up PR: #92, #93, #106.

## Goal

The repo's README catalogue, `marketplace.json` and plugin READMEs drifted from the code over
epic #156, because nothing generates them for a plugin-only monorepo any more: `sync-monorepo.sh`
refuses that layout (#167), so recent edits were made by hand. This design:

1. makes each `plugins/<name>/.claude-plugin/plugin.json` the only source of plugin metadata;
2. adds one tool that writes the catalogue from it, and a `--check` mode that is the drift guard;
3. lets `skill-kit:publish` sync a plugin-only monorepo instead of refusing it;
4. fixes today's doc drift, and runs the guard in CI and `commit-preflight.sh`.

## Split

- **PR 1 (this spec):** sections 1–6. Closes #190, #2 and #84 (#84 was fixed by #167's
  `list_top_level_candidates`; closed with that evidence).
- **PR 2 (own issue, own plan):** the legacy path that copies from `~/.claude/skills` and
  `plugin-manifest.json` — #92 (drift detectors resolve by name, the builder by `source`), #93
  (`--skills` subset shrinks the top-level skill table), #106 (README generator inlines
  `<placeholder>` text), and revisiting `SKILL_KIT_NO_PLUGIN_VALIDATION`. Nothing in PR 1 depends
  on it.

## 1. Source of truth

| Data | Source |
|---|---|
| name, version, description | `plugins/<name>/.claude-plugin/plugin.json` |
| skill / command / agent counts and names | `plugins/<name>/skills/*/SKILL.md`, `commands/*.md`, `agents/*.md` |
| marketplace owner and `metadata` | the existing `marketplace.json` (kept as is) |

Migration: the "Deprecated: …" prefixes now only in `marketplace.json` move into the 13
plugin.json files. Each of those plugins gets a patch bump and a CHANGELOG line.

## 2. `catalogue.py`

`plugins/skill-kit/skills/publish/scripts/catalogue.py`, Python 3 standard library only.

Usage: `catalogue.py [--check] [--json] <repo>`.

Writes (or, with `--check`, compares; it never writes in `--check`):

1. **Root README table** between `<!-- catalogue:start -->` and `<!-- catalogue:end -->`:
   `| Plugin | Version | Skills | Commands | Description |`, one row per plugin, sorted by name,
   link `./plugins/<name>/`. Text outside the markers is never touched.
2. **`marketplace.json`**: `plugins[]` rebuilt with `name`, `version`, `description`,
   `source: ./plugins/<name>`; every other top-level key kept. Written with `json.dump`
   (indent 2, trailing newline), so quoting is always valid.
3. **Plugin README meta line** in each `plugins/<name>/README.md`, between
   `<!-- plugin-meta:start -->` and `<!-- plugin-meta:end -->`:
   `**Version:** X.Y.Z · **N** skills · **M** agents · **K** commands`.

Plugins named in `STANDALONE_PLUGINS` (git-flow, obsidian-brain) are skipped; the list moves to
one place both scripts read.

`--check` also checks the root README's install commands: every `/plugin install X@M` and
`/plugin uninstall X@M` must use the marketplace's `name` as `M`, and `X` must be `PLUGIN_NAME` or
a plugin in the catalogue; every `scripts/install-plugin.sh` path it names must exist.

`--check` also fails when a plugin README does not name each of its skill and agent directory
names (as a whole word), since that cannot be generated without rewriting hand-written prose.

Exit codes: 0 clean (or written); 1 drift found (`--check`), one line per difference
(`README.md: row context: version 1.0.1 != plugin.json 1.0.2`); 2 cannot run, fail closed:
missing or repeated marker, unreadable or invalid JSON, a plugin.json without `name`, `version`
or `description`, a `name` that is not its directory name, or a `plugins/` directory missing.
`--json` prints `{"drift": [...], "errors": [...]}`.

## 3. Doc reference check

`scripts/check-doc-refs.py` (repo-only; it encodes this repo's doc set).

Files: `README.md`, `CONTRIBUTING.md`, `LOCAL-TESTING.md`, `AGENTS.md`, `CLAUDE.md`,
`plugins/*/README.md`. `docs/` holds only dated plans and specs, which are exempt, as are
CHANGELOGs.

Rules, applied outside fenced code blocks:

- **R1 links:** a relative Markdown link target (not `http(s):`, `mailto:` or `#…`) must exist
  relative to the file.
- **R2 repo paths:** an inline-code token that starts with `plugins/`, `scripts/`, `.github/`,
  `.claude-plugin/` or `docs/` must exist relative to the repo root. `<anything>` and `*` in the
  token match one path segment; the token passes if it matches at least one path.
- **R3 namespaced names:** an inline-code token matching `^/?([a-z0-9-]+):([a-z0-9-]+)$` whose
  first part is a plugin in `plugins/` must name a skill, agent or command of that plugin.
  Other prefixes (`git-flow:`, `pr-review-toolkit:`) are not ours and are skipped.

Token alphabet: R2/R3 tokens are taken from single-backtick spans; a token with a space is
skipped. Blind spots, stated in the script header: bare file names (`record.sh`), paths inside
fenced blocks, and paths in a user's own project are not checked.

Exit 0 clean, 1 references broken (one line each, `file:line: token`), 2 cannot run.

## 4. `skill-kit:publish` on a plugin-only monorepo

Replaces the #167 refusal for this layout (detection unchanged: `is_plugin_only_monorepo`).

| Mode | Plugin-only behaviour |
|---|---|
| plain | `validate-plugin.sh` on every plugin (any failure: exit 1, nothing written), then `catalogue.py` writes. Nothing else is written: no CHANGELOG, workflow, CONTRIBUTING, scripts or LICENSE. |
| `--dry-run` | same validation, then `catalogue.py --check`; prints what would change, writes nothing |
| `--add-plugin N` | as today (copy `./build/N/`), then validate, then `catalogue.py` |
| `--skills`, `--add` | refused, exit 1: "plugin-only monorepo has no top-level skills; edit plugins/<group>/skills/ and run sync" |
| `--init` | refused, exit 1: the repo is already initialised |
| `--json` | `{"layout":"plugin-only","validated":N,"catalogue":"written|clean|drift"}` |

`validate-pre-sync.sh` on a plugin-only repo: validates every plugin and runs
`catalogue.py --check`; exit 1 on either failure.

Mixed and top-level layouts keep today's flow, with one change: `marketplace.json` and the
README plugin table are written by `catalogue.py` (the template's plugin table becomes the
marker block), so there is one writer for both files in every layout.

`sync-monorepo.sh` copies `catalogue.py` into a consumer repo's `scripts/` with the other
validators, and `references/workflow-monorepo.yml` gains a `catalogue.py --check` step.

## 5. Guard wiring

- `scripts/check-docs.sh` runs `catalogue.py --check .` then `check-doc-refs.py`; exit is the
  worst of the two.
- CI: a `docs-drift` job in `.github/workflows/validate-skill.yml` runs it on every PR.
- `scripts/commit-preflight.sh` runs it in every mode, including `--docs-only`.

## 6. Tests

- `scripts/test-catalogue.sh`, hermetic fixtures: one seeded drift per class (version, count,
  description, missing row, extra row, marketplace field, meta line, missing skill name in a
  plugin README) each exits 1 and names the difference; each fail-closed case exits 2;
  write-then-check is clean; text outside markers is byte-identical after a write; a
  description with `"` and `\` gives valid JSON.
- `scripts/test-check-doc-refs.sh`: R1–R3 each fail on a seeded broken reference and pass on a
  good one; fenced blocks and other prefixes are skipped.
- `scripts/test-sync-hygiene.sh`: the #167 refusal cases become the plugin-only mode table
  above (plain writes only the catalogue, every other file byte-identical; `--skills`, `--add`,
  `--init` refused with files unchanged; a failing plugin blocks every write).
- Forced failures: `check-docs.sh` on a seeded drift exits 1; with `catalogue.py` missing it
  exits non-zero.

## 7. Docs refresh

Run the guard, then fix every finding by hand or by `catalogue.py`: root README markers, plugin
README meta lines and missing skill/agent names (smart-screen-recorder's five agents, review and
adversarial-review), stale paths and branch names (`LOCAL-TESTING.md`), and the publish
SKILL.md section for plugin-only repos.

## Acceptance criteria (from #190)

1. Every catalogue row, version, skill/agent count and install command in the root README
   matches `marketplace.json` and each plugin.json — `catalogue.py --check` exit 0 (install
   commands by the install rule in section 2).
2. Every plugin README names its skills and agents, with the right version — `--check` meta and
   name rules.
3. No current doc names a path, script, skill or agent that does not exist — `check-doc-refs.py`
   exit 0, blind spots stated.
4. A CI check fails on seeded drift — the tests in section 6 plus a forced-failure run.
5. The check runs in `commit-preflight.sh` — section 5.
