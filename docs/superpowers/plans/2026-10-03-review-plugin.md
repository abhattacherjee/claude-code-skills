# review plugin Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Merge the `deep-review` and `adversarial-review` plugins into one `review` plugin (1.0.0) with skills `deep` and `adversarial` and agents `bug-hunter`, `convention-reviewer`, `cross-examiner`.

**Issue:** #159 (epic #156). **Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`.

## Name map

| Old | New |
|---|---|
| plugin `deep-review`, skill `deep-review` (`/deep-review`, `deep-review:deep-review`) | plugin `review`, skill `deep` (`/review:deep`) |
| plugin `adversarial-review`, skill `adversarial-review` | skill `adversarial` (`/review:adversarial`) |
| agent `adversarial-review:adversarial-bug-hunter` | `review:bug-hunter` |
| agent `adversarial-review:adversarial-convention-reviewer` | `review:convention-reviewer` |
| agent `adversarial-review:adversarial-cross-examiner` | `review:cross-examiner` |
| `plugins/adversarial-review/skills/adversarial-review/scripts/` | `plugins/review/skills/adversarial/scripts/` |

## Global constraints

- Plugin `review`, version `1.0.0`. Each SKILL.md `description` names the old skill so plain-language and old-name requests still match ("…(was deep-review)").
- **The Bash tool keeps no shell variables between calls.** Today `adversarial-review` sets `SCRIPTS="$(dirname "$0")/scripts"` in one block and uses `$SCRIPTS` in 8 others (and `$0` is the shell, not the skill, so even the first block is wrong). `deep-review` does the same with `AR_SCRIPTS`, `ADV_REVIEW` and `AUDIT`. Every command must spell its script path in full:
  - inside `skills/adversarial/`: `"${CLAUDE_SKILL_DIR}/scripts/<script>"`
  - inside `skills/deep/` (SKILL.md and references): `"${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts/<script>"`
  - `ADV_REVIEW` becomes the literal script name the text picks (codex-review.sh or gemini-review.sh), written out in each command; say "use `gemini-review.sh` in place of `codex-review.sh` when the adversary is Gemini".
  - Run-scoped values created at run time (`RUN_DIR`, `RUN_ID`, round counter, `ADVERSARY`) are printed once; the text tells the model to write the printed value literally into later commands. No later block may read them as shell variables.
- The three old plugin directories and the bare top-level `deep-review/` stay unchanged in this PR. Only their marketplace entries change. (`deep-review/` goes with the other bare dirs in #167.)
- Python 3.9+, standard library only. bash runs on macOS bash 3.2 and Linux bash 5.
- No personal values in published files (a home-directory path, private repo names).

## Review focus

1. No fenced bash block reads a variable that only an earlier block set. A test enforces it for both skills and the deep references.
2. Every script path written in a SKILL.md or reference resolves to a file that exists in the plugin.
3. Every agent dispatch names a `review:` agent that exists in `plugins/review/agents/`.
4. The moved test suites pass at the new paths, and CI runs them.

---

### Task 1: Scaffold the plugin and move the content

**Files:** create `plugins/review/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `skills/deep/`, `skills/adversarial/`, `agents/`, `docs/`.

- `git mv` is wrong here (the old dirs stay). Copy:
  - `plugins/deep-review/skills/deep-review/` → `skills/deep/`
  - `plugins/adversarial-review/skills/adversarial-review/` → `skills/adversarial/` (scripts, fixtures, tests)
  - `plugins/adversarial-review/agents/adversarial-<x>.md` → `agents/<x>.md`, with `name:` set to `<x>`
  - `plugins/adversarial-review/docs/` → `docs/`
- Set each SKILL.md `name:` (`deep`, `adversarial`) and version metadata to 1.0.0 in the plugin's own terms. Skill CHANGELOGs start a fresh 1.0.0 entry that says where they came from (deep-review 1.4.0, adversarial-review 0.2.0).
- Replace every old skill, agent and plugin name in the moved text with the new one, except deliberate "was …" notes. `deep` dispatches `review:bug-hunter`, `review:convention-reviewer`, `review:cross-examiner`.
- README: one page for both skills, with a "Was" column like `plugins/github-board/README.md`. Merge the two plugin READMEs; keep every fact (Codex sandbox, adversary choice, audit trail, degradation).
- Run `scripts/validate-plugin.sh plugins/review` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Spell every path; enforce it with a test

**Files:** `skills/adversarial/SKILL.md`, `skills/deep/SKILL.md`, `skills/deep/references/*.md`, new `skills/adversarial/scripts/test_skill_paths.py` (or extend `test_skill_docs.py`).

- Apply the path rules from Global constraints to every fenced block.
- Test (fails on today's text, passes after):
  1. For each fenced `bash`/`sh` block in both SKILL.md files and `skills/deep/references/*.md`: every `$NAME` / `${NAME}` read must be assigned in the same block, be a loop/`read` variable of that block, or be in a short allow-list (`HOME`, `CLAUDE_SKILL_DIR`, `CLAUDE_PLUGIN_ROOT`, `GH_HOST`, `PATH`, `TMPDIR`, positional `$1`… inside functions, `$?`, `$$`). Report block and line.
  2. No block uses `$(dirname "$0")`.
  3. Every `${CLAUDE_SKILL_DIR}/…` and `${CLAUDE_PLUGIN_ROOT}/…` path resolves to an existing file under `plugins/review/`.
  4. Every `review:<agent>` named in the skills exists as `plugins/review/agents/<agent>.md` with matching `name:`.
- Prove the test fails first: run it against the copied-but-unfixed text (commit order or a scratch copy), record the failures, then fix.
- Commit.

### Task 3: Tests and CI

**Files:** `skills/adversarial/scripts/run-tests.sh` and the `test_*.py` files (fix any path or name they assert), `.github/workflows/validate-skill.yml`.

- Run `bash plugins/review/skills/adversarial/scripts/run-tests.sh` and `python3 -m pytest plugins/review/skills/adversarial/scripts -q -p no:cacheprovider` until green. `test_skill_docs.py` asserts on SKILL.md text; update its expected names to the new ones.
- CI: add a `review-tests` job modelled on `adversarial-review-tests`, running the new suite and the new path test. Keep the old job while the old plugin is still published.
- Commit.

### Task 4: Marketplace, catalogue, changelogs, in-repo callers

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, `plugins/review/CHANGELOG.md`, plus every in-repo LIVE-CALLER from the inventory (listed below by the orchestrator).

- Add a `review` entry (source `./plugins/review`, version 1.0.0).
- Prefix the two old entries' descriptions with `Deprecated: use the review plugin (review:deep / review:adversarial).` Keep their sources; they go in the next release.
- README catalogue: add the `review` row; mark the two old rows deprecated.
- CHANGELOG entries under `[Unreleased]`, inside the existing block.
- In-repo callers: see the list appended below.
- Run `scripts/validate-plugin.sh` over all plugins, `ls scripts/test-*.sh` suites, and `./scripts/commit-preflight.sh`.
- Commit.

### Task 5 (orchestrator, after merge): live cut-over

Not part of the implementation pass. After the PR merges:
1. `claude plugin install review@claude-code-skills`.
2. Move the out-of-repo callers (one PR per repo: claude-code-config for `/ship`, others per the inventory).
3. Uninstall `deep-review@claude-code-skills` and `adversarial-review@claude-code-skills`, so the old names cannot win a plain-language request.
4. Dogfood each skill through a plain-language `claude -p` request.

## Rulings from the caller inventory (2026-10-03)

- **Report file suffix `*.adversarial-review.md` stays.** It is a file-name convention that `.gitignore` files in this repo, openclaw and cc-token-router already match. Renaming it would leave reports untracked-but-visible in those repos.
- **Audit-record `skill` field:** `audit_record.py` accepts the old values (`adversarial-review`, `deep-review`) and the new ones (`adversarial`, `deep`), because old PR comments already carry the old ones. The new skills write `deep` / `adversarial`. The rendered label follows the value. Tests cover both old and new values.
- **`test_skill_docs.py` in the new plugin** checks only `plugins/review/`. It must not reach into the bare `deep-review/` or the old plugin dirs; those keep their own copy of the test.
- **Agent file references** (`run-tests.sh` reading `agents/adversarial-cross-examiner.md`) point at `plugins/review/agents/cross-examiner.md`.
- **The `if the adversarial-review skill is installed` fallback in deep** goes: the scripts now ship in the same plugin. Keep the manual fallback only for a missing adversary model, not a missing plugin.

## In-repo callers for Task 4

- `.github/workflows/validate-skill.yml`: add `review-tests`; keep `adversarial-review-tests`.
- `.claude-plugin/marketplace.json`: new entry + two deprecations.
- `README.md` rows 26 and 30 (both plugins): mark deprecated, add `review`.
- `LOCAL-TESTING.md:24,32,46`: install command and example paths → the review plugin.

Out-of-repo callers (claude-code-config, codex-config, ~/.claude, ~/.agents, ~/.codex) move after merge in Task 5, one PR per repo.
