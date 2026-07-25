# Publishing Tooling + Discovery Guards Implementation Plan

**Issues:** #61 (publishing tooling is blind to in-repo-source skills), #62 (P1 — `spec-*` discovery guards always report true)

**Goal:** Make the `spec-*` discovery scripts report *true* feature detection instead of fabricating every pattern, and teach the publishing tooling (`prepare-plugin.sh`, `sync-monorepo.sh`) to understand the in-repo-source arrangement #59 introduced.

**Architecture:** Two independent tracks that touch disjoint files.

- **#62** is entirely in-repo: two shell scripts under `spec-creator/scripts/` and `spec-review/scripts/`, plus a new regression harness at `scripts/test-discovery-guards.sh`.
- **#61** is mostly **out-of-tree**: `skill-publishing`'s authoring source lives at `~/.claude/skills/skill-publishing/`, and only its *assembled* copy (`plugins/skill-publishing/`) is tracked in this repo. Edits go to the authoring source, then the plugin is re-assembled so the repo carries the fix.

**Tech Stack:** bash, jq, `scripts/validate-skill.sh`, `scripts/validate-plugin.sh`, `~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh`.

## Established facts (verified this session — do not re-derive)

1. **Both #62 bugs reproduce.** Running `spec-review/scripts/discover-project-architecture.sh "$(pwd)" --json` against *this* markdown-only repo returns
   `dataFlow: "HTTP-inter-service,Dev-proxy,Event-messaging,Database,GraphQL,REST-API"`, `i18n: "i18next,vue-i18n,BilingualText"`, `security: "CSRF,Helmet/CSP,RateLimit,CORS"` — 13 patterns, all false.
2. **The mechanism is two compounding faults.** `grep -rlq` — `-q` overrides `-l`, so grep prints nothing and exits on first match — piped into `… | head -1 > /dev/null`, and `&&` tests the exit status of the *last* pipeline element (`head`), which is always `0`.
3. **`set -e` is NOT a hazard here.** Both scripts are `set -eu`. Verified empirically: `bash -c 'set -eu; false && x=1; echo REACHED'` prints `REACHED` and exits `0` — a failing left operand of `&&` is exempt from `set -e`. The rewrite is therefore free to use either form; this plan uses `if/then/fi` for reviewability, not for safety.
4. **`discover-conventions.sh` has TWO broken guards, not one.** Issue #62 names only line 75 (`epic-*`). Line 77 (`elif ls -d "$spec_dir"/[0-9]* … | head -1 > /dev/null`) has the identical defect and is merely *unreachable* today because line 75 always fires. **Fixing only line 75 relocates the bug to line 77.** Both must be fixed in the same edit.
5. **Sibling detectors using the correct idiom already work.** `head -1 | grep -q .` (lines 246, 256, 258, 261, 281, 364) returned empty in the same run. Only the `| head -1 > /dev/null` form is defective. This isolates the blast radius and doubles as the reference idiom.
6. **`resolve_tilde()` is a one-liner no-op for non-`~` paths** (`_lib.sh:166-168`: `echo "${1/#\~/$HOME}"`). `prepare-plugin.sh` calls it at **10 sites** (lines 79, 161, 195, 219, 242, 295, 331, 384, 403, 424).
7. **`skill-publishing` has pre-existing version drift.** `SKILL.md` frontmatter and `CHANGELOG.md` say **4.1.0**; `plugin-manifest.json`, `.claude-plugin/marketplace.json`, and `plugins/skill-publishing/.claude-plugin/plugin.json` all say **4.0.0**. The bump in Task 5 reconciles all five to **4.2.0**.
8. **A stale local `~/.claude/skills/spec-creator/plugin-manifest.json` and `spec-review` one still exist**, declaring `"source": "~/.claude/skills/spec-*"`. #63 deletes them; until then they shadow the in-repo manifests. Task 4's dedupe must therefore be deterministic and logged, never silent.
9. **`SKILLS_HOME` is env-overridable** (`sync-monorepo.sh:8`: `SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"`). This is how Task 4 is verified **without renaming or deleting anything under `~/.claude/skills/`**.
10. **This repo has no test framework.** Verification is shell assertions. Task 1 creates `scripts/test-discovery-guards.sh`; Task 2 extends it.

## Global Constraints

- Base branch is `develop`. Never target `main`. Never commit directly to `develop` or `main`.
- Run `./scripts/commit-preflight.sh` **as its own command** after `git add` and before `git commit` — the hook rejects it bundled into a compound command.
- **Never `git add -A`.** Stage named paths only. (Sub-agent test runs leave `__pycache__/*.pyc` behind, and the preflight rejects staged build artifacts.)
- **Do NOT delete or rename anything under `~/.claude/skills/`.** Task 4 is verified with a `SKILLS_HOME` override pointing at a scratch directory. Deletion is #63's job, after merge.
- Every version bump must be applied in **five** places: `SKILL.md` frontmatter `metadata.version`, `plugin-manifest.json` `.version`, the CHANGELOG's new top section, `.claude-plugin/marketplace.json`, and the assembled `plugins/<name>/.claude-plugin/plugin.json` (which comes from re-assembly, not a hand edit). `validate-skill.sh` errors when `SKILL.md`'s version ≠ the CHANGELOG's top version.
- `validate-skill.sh` errors when a SKILL.md **body exceeds 500 lines**, and `commit-preflight.sh` hard-blocks on any validator ERROR. If a body would exceed it, extract a self-contained section into `references/` and link to it — never delete content — and say so in the report.
- **Re-assemble `spec-*` plugins by invoking `prepare-plugin.sh` on the in-repo manifest explicitly.** Do NOT use `sync-monorepo.sh` for them: the stale local manifests in fact 8 would win the dedupe and rebuild the plugin from the *old* source.
- **Every new guard needs a positive control.** A detector rewritten to "correctly report nothing" is indistinguishable from one hardcoded to return empty. Each assertion that something is absent must be paired with a fixture where it is genuinely present and must be detected. This is non-negotiable — the last cycle published a false finding because a search that returned nothing was read as "clean" rather than "broken."
- **Prove every new test fails first.** Run it against the pre-fix script (`git show HEAD:<path>` into a temp file) and confirm it FAILS before the fix, PASSES after. A test that passes both ways proves nothing.

---

### Task 1: spec-creator — fix `detect_epic_structure` guards + create the regression harness

**Files:** `spec-creator/scripts/discover-conventions.sh`, `scripts/test-discovery-guards.sh` (new), `spec-creator/SKILL.md`, `spec-creator/plugin-manifest.json`, `spec-creator/CHANGELOG.md`, `plugins/spec-creator/**`

- [ ] **Step 1: Write the fail-first test** — create `scripts/test-discovery-guards.sh` (`#!/usr/bin/env bash`, `set -euo pipefail`, executable). It builds fixtures under a `mktemp -d` trap-cleaned scratch dir and asserts, for `discover-conventions.sh`:

  | Fixture | Assertion | Kind |
  |---|---|---|
  | `specs/` with `story-1.1-alpha.md`, `story-1.2-beta.md`, `story-2.1-gamma.md`, **no** `epic-*` dirs | `epicStructure == "flat"` **and** `epics == [1,2]` | negative |
  | `specs/` with `epic-1/`, `epic-2/` subdirs | `epicStructure == "epic-subdirs"` | **positive control** |
  | `specs/` with `1-foo/`, `2-bar/` numbered subdirs, no `epic-*` | `epicStructure == "numbered-subdirs"` | **positive control** (guards line 77) |
  | empty `specs/` | `epicStructure == "flat"` | negative |

  The positive controls are what prove the fix is a real detector and not a hardcoded empty.

- [ ] **Step 2: Prove it fails first** — extract the current script (`git show HEAD:spec-creator/scripts/discover-conventions.sh > /tmp/pre.sh`), point the harness at it, and confirm the three non-`epic-subdirs` cases FAIL. Record the actual failure output in the report. If any of them *passes* against the pre-fix script, stop and report — the test is not exercising the defect.

- [ ] **Step 3: Fix both guards** in `detect_epic_structure` (lines ~75 and ~77). Replace the `ls -d … | head -1 > /dev/null` form with a direct glob test that preserves the existing match semantics:

```bash
if compgen -G "$spec_dir/epic-*" > /dev/null; then
    echo "epic-subdirs"
elif compgen -G "$spec_dir/[0-9]*" > /dev/null; then
    echo "numbered-subdirs"
else
    echo "flat"
fi
```

  `compgen` is a bash builtin and the shebang is `#!/usr/bin/env bash`, so this is safe. It matches the same set the glob would — including non-directory entries, exactly as `ls -d` did — so nothing but the truth of the guard changes.

- [ ] **Step 4: Audit every remaining guard in this file** (AC #3 of #62). `grep -n 'head -1' spec-creator/scripts/discover-conventions.sh` currently reports lines 75, 77, 149. Line 149 (`xargs ls -t … | head -1`) is a value assignment, not a guard, and is correct. State this explicitly in the report — an audit that says nothing is indistinguishable from an audit that was not run.

- [ ] **Step 5: Confirm the test now passes**, and that `find_epics` reaches its flat-layout branch (epics `[1,2]` for the story-only fixture — this is the behaviour that was silently unreachable).

- [ ] **Step 6: Bump to 2.4.2** in `spec-creator/SKILL.md` (`metadata.version`) and `spec-creator/plugin-manifest.json`, and add a CHANGELOG section:

```markdown
## [2.4.2] - 2026-07-25

### Fixed

- `discover-conventions.sh`: `detect_epic_structure` used `ls -d … | head -1 > /dev/null`
  as its test, which evaluates `head`'s exit status and is therefore always true. Every
  project with a spec directory — including an empty one — was reported as `epic-subdirs`,
  which made `find_epics`' flat-layout branch unreachable and silently dropped every epic
  in a `story-X.Y-name.md` project. Both the `epic-*` and the `numbered-subdirs` guard are
  now direct glob tests. (#62)
```

- [ ] **Step 7: Re-assemble the plugin**

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/spec-creator spec-creator/plugin-manifest.json
```

- [ ] **Step 8: Verify** — `scripts/validate-skill.sh spec-creator` and `scripts/validate-plugin.sh plugins/spec-creator` both pass; `jq -r .version plugins/spec-creator/.claude-plugin/plugin.json` is `2.4.2`; `diff -q spec-creator/scripts/discover-conventions.sh plugins/spec-creator/skills/spec-creator/scripts/discover-conventions.sh` reports identical.

---

### Task 2: spec-review — fix the 13 always-true detector guards

**Files:** `spec-review/scripts/discover-project-architecture.sh`, `scripts/test-discovery-guards.sh` (extend), `spec-review/SKILL.md`, `spec-review/plugin-manifest.json`, `spec-review/CHANGELOG.md`, `plugins/spec-review/**`

- [ ] **Step 1: Extend the harness** with `discover-project-architecture.sh` cases:

  | Fixture | Assertion | Kind |
  |---|---|---|
  | this repo (markdown-only, no `package.json`) | `dataFlow`, `i18n`, `security` all empty | negative |
  | scratch project with `package.json` containing `i18next` and `graphql`, and a `src/server.ts` with `helmet` + `csurf` | `i18n` contains `i18next`; `dataFlow` contains `GraphQL`; `security` contains `CSRF` and `Helmet/CSP` | **positive control** |
  | scratch project with a `node_modules/` copy of the same markers and nothing else | those patterns are **absent** | **negative control** — proves the `node_modules` filter still works |

  The third row matters: the naive fix `grep -rl … \| grep -qv node_modules` must still exclude vendored matches, and only a fixture where the *sole* match is inside `node_modules` can prove it.

- [ ] **Step 2: Prove it fails first** against `git show HEAD:spec-review/scripts/discover-project-architecture.sh`. The two negative rows must FAIL pre-fix. Record the output.

- [ ] **Step 3: Fix all 13 guards.** Lines ~308-341 (`detect_data_flow`, 6 guards), ~349-361 (`detect_i18n`, 3 guards), ~371-382 (`detect_security_patterns`, 4 guards). Two shapes:

```bash
# with the node_modules filter (12 of the 13)
if grep -rl "PATTERN" . --include="*.ts" --include="*.js" 2>/dev/null \
     | grep -qv node_modules; then
    patterns="${patterns}NAME,"
fi

# without it — the Dev-proxy guard at ~line 314 has no node_modules stage
if grep -rl "PATTERN" . --include="vite.config.*" 2>/dev/null | grep -q .; then
    patterns="${patterns}Dev-proxy,"
fi
```

  Drop `-q` from every `grep -rlq` (that is the first of the two faults) and test the pipeline's real result. Do **not** touch the six sibling detectors that already use `head -1 | grep -q .` (lines 246, 256, 258, 261, 281, 364) — they are correct, and they are the control that isolated this bug.

- [ ] **Step 4: Audit every remaining `head -1` in this file** (AC #3). Classify each of the 21 occurrences as guard-defective, guard-correct, or value-assignment, and report the classification. Lines 251, 269, 409 are assignments (`head -10`, `head -1` into a variable); 246/256/258/261/281/364 are the correct guard idiom.

- [ ] **Step 5: Confirm the harness passes**, including the `node_modules`-only negative control.

- [ ] **Step 6: Bump to 2.2.2** across `SKILL.md`, `plugin-manifest.json`, CHANGELOG:

```markdown
## [2.2.2] - 2026-07-25

### Fixed

- `discover-project-architecture.sh`: 13 detectors in `detect_data_flow`, `detect_i18n`,
  and `detect_security_patterns` combined `grep -rlq` (where `-q` suppresses the `-l`
  output) with a `| head -1 > /dev/null &&` guard that tests `head`'s exit status — always
  zero. Every data-flow, i18n and security pattern was reported as present for every
  project. This repository, which is markdown-only, reported `i18next, vue-i18n, CSRF,
  Helmet/CSP, GraphQL, REST-API` among others. The fabricated JSON is pasted verbatim into
  the Architecture Reviewer's prompt, so reviewers were being fed invented architecture on
  every run. (#62)
```

- [ ] **Step 7: Re-assemble**

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/spec-review spec-review/plugin-manifest.json
```

  `spec-review/README.md` is hand-authored rather than generated — if the assembly overwrites it, restore it.

- [ ] **Step 8: Verify** — both validators pass; assembled `plugin.json` is `2.2.2`; the script is byte-identical between source and plugin; and re-running the reproduction from the issue against this repo now yields three empty fields.

---

### Task 3: prepare-plugin.sh — resolve a relative manifest `source` against the manifest's directory

**Files (OUT OF REPO):** `~/.claude/skills/skill-publishing/scripts/_lib.sh`, `~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh`

- [ ] **Step 1: Fail-first** — from a directory that is not the monorepo root, confirm the current failure:

```bash
(cd /tmp && ~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh --dry-run \
   /Users/abhishek/dev/claude_workspace/claude-code-skills/spec-creator/plugin-manifest.json)
# expect: ERROR: skill source not found: spec-creator
```

- [ ] **Step 2: Add `resolve_source_path()` to `_lib.sh`.** Leave `resolve_tilde()` untouched — `sync-monorepo.sh` and others depend on it.

```bash
# Resolve a manifest-declared source path.
#   $1 = the raw source string from the manifest
#   $2 = the directory containing the manifest
# A leading ~ expands to $HOME. An absolute path is returned unchanged. A
# relative path resolves against the MANIFEST's directory, not the caller's
# cwd, so in-repo-source manifests work from anywhere.
resolve_source_path() {
  local raw="$1" manifest_dir="$2" expanded
  expanded="$(resolve_tilde "$raw")"
  case "$expanded" in
    /*) echo "$expanded" ;;
    *)  echo "${manifest_dir%/}/$expanded" ;;
  esac
}
```

- [ ] **Step 3: Compute `MANIFEST_DIR` in `prepare-plugin.sh`** immediately after the manifest-existence check (~line 83):

```bash
MANIFEST_DIR="$(cd "$(dirname "$MANIFEST_FILE")" && pwd)"
```

- [ ] **Step 4: Switch the nine source-resolution sites** — lines ~161 (`SKILL_SRC`), ~195 (`CMD_SRC`), ~219 (`AGENT_SRC`), ~242 (`HOOKS_SRC`), ~295 (`FIRST_SKILL_SOURCE`), ~331 (`PRIMARY_SKILL_SRC`), ~384 (`SSRC`), ~403 (`CSRC`), ~424 (`ASRC`) — from `resolve_tilde "$X"` to `resolve_source_path "$X" "$MANIFEST_DIR"`.

  **Line 79 (`MANIFEST_FILE` itself) must keep `resolve_tilde`.** That path is a command-line argument typed by the user and is correctly interpreted relative to their cwd. Changing it would be a regression, not a fix. Verify no other `resolve_tilde` call in this file resolves a *manifest-declared* path before leaving it alone.

- [ ] **Step 5: Verify the fix and prove backward compatibility.**

```bash
# (a) the fail-first case now succeeds
(cd /tmp && ~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh --dry-run \
   /Users/abhishek/dev/claude_workspace/claude-code-skills/spec-creator/plugin-manifest.json)

# (b) from three different cwds the dry-run output is IDENTICAL
# (c) an existing ~-form manifest is unaffected — assemble deep-review to a
#     temp dir and diff it against plugins/deep-review; expect no differences
```

  (c) is the load-bearing one: every other manifest in the repo uses the `~/.claude/skills/<name>` form, which `resolve_source_path` returns unchanged. Prove that with a real assembly diff, not by reasoning about the code.

---

### Task 4: sync-monorepo.sh — fall back to an in-repo source directory

**Files (OUT OF REPO):** `~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh`

- [ ] **Step 1: Fail-first** — with `SKILLS_HOME` pointed at an empty scratch dir, confirm today's behaviour is the silent-staleness the issue describes:

```bash
EMPTY=$(mktemp -d)
SKILLS_HOME="$EMPTY" ~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh \
  --dry-run /Users/abhishek/dev/claude_workspace/claude-code-skills 2>&1 | grep -i 'spec-'
# expect: "SKILL.md not found, skipping" for spec-creator/spec-review/spec-implement,
# and NO auto-build entry for any of them
```

  This is the exact post-#63 world, reproduced without touching `~/.claude/skills/`.

- [ ] **Step 2: Add a `skill_source_dir()` helper** near the top of the script:

```bash
# Resolve a skill's authoring source: the local skills home if present,
# else an in-repo top-level directory (the arrangement #59 introduced).
skill_source_dir() {
  local name="$1"
  if [[ -f "$SKILLS_HOME/$name/SKILL.md" ]]; then
    echo "$SKILLS_HOME/$name"
  elif [[ -f "$MONOREPO_DIR/$name/SKILL.md" ]]; then
    echo "$MONOREPO_DIR/$name"
  fi
}
```

  Local-first precedence deliberately preserves today's behaviour exactly while both copies exist (fact 8), and hands over automatically once #63 deletes the local ones.

- [ ] **Step 3: Extend the auto-build manifest scan** (~line 331) to also iterate `"$MONOREPO_DIR"/*/plugin-manifest.json`, deduplicating by resolved plugin name with **local-first precedence**. When a monorepo manifest is skipped because a local one shadows it, `echo` a one-line note naming both paths. A silent skip here is what makes the failure mode invisible; the note is the fix's whole point.

- [ ] **Step 4: Route the source-path reads through the helper.** Replace `$SKILLS_HOME/$_FIRST_SKILL/SKILL.md` (~line 360) and the drift-resync block's reads (~lines 478, 489, 514, 529, 586 — SKILL.md, `scripts/`, `CHANGELOG.md`, and the whole-dir copy) with `skill_source_dir` results. Where the helper returns empty (no source anywhere), keep the existing skip-with-error behaviour.

- [ ] **Step 5: Guard against self-copy.** The bare-skill sync loop (~line 155) sets `SKILL_SRC="$SKILLS_HOME/$SKILL_NAME"` and `SKILL_DST="$MONOREPO_DIR/$SKILL_NAME"`. For an in-repo source these are **the same directory**, and a copy of a directory onto itself risks destroying it. Before any copy, compare the two resolved paths and, when equal, skip with an explicit `in-repo source — already in place, nothing to copy` message. Verify this branch is actually taken for `spec-creator` under the `SKILLS_HOME` override, and verify afterwards that `spec-creator/` still contains its `SKILL.md`, `scripts/`, `references/`, and `CHANGELOG.md`.

- [ ] **Step 6: Verify with the override** — repeat Step 1's command. `spec-creator`, `spec-review` and `spec-implement` must now be discovered from the repo, report drift correctly, and appear as auto-build candidates rather than `SKILL.md not found`.

- [ ] **Step 7: Prove the normal path is unchanged.** Run `sync-monorepo.sh --dry-run` against the real repo with the real `SKILLS_HOME` and diff the output against the same command's output from `git stash`-ed / pre-fix script. Any difference beyond the new dedupe notes is a regression and must be reported, not explained away.

- [ ] **Step 8: `--dry-run` must remain side-effect free.** Confirm `git status --porcelain` is empty after every dry-run in this task.

---

### Task 5: skill-publishing — document the in-repo-source variant, bump to 4.2.0, re-assemble

**Files:** `~/.claude/skills/skill-publishing/SKILL.md` (out of repo), `~/.claude/skills/skill-publishing/plugin-manifest.json` (out of repo), `~/.claude/skills/skill-publishing/CHANGELOG.md` (out of repo), `plugins/skill-publishing/**` (in repo)

- [ ] **Step 1: Document the in-repo-source form** in the manifest-schema section of `SKILL.md` (the block around line 137 showing `"source": "~/.claude/skills/skill-name"`). Add the second supported form and state the resolution rule plainly: a `~`-prefixed or absolute `source` resolves as written; a **relative** `source` resolves against the manifest file's own directory, which is what lets a skill's authoring source live inside the monorepo. Note that `sync-monorepo.sh` prefers `$SKILLS_HOME/<name>` when both exist. This is AC #4 of #61 — a maintainer reading the publishing tool's own docs must learn the variant exists.

- [ ] **Step 2: Reconcile the version drift and bump to 4.2.0.** Per fact 7, `SKILL.md`/CHANGELOG are at 4.1.0 while the manifest and marketplace are at 4.0.0. Set **4.2.0** in `SKILL.md` `metadata.version` and `plugin-manifest.json`; add the CHANGELOG section below. (`marketplace.json` is Task 6.)

```markdown
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

### Added

- Manifest-schema documentation for the in-repo `source` form and its resolution rule. (#61)
```

- [ ] **Step 3: Re-assemble the plugin** so the repo carries the out-of-tree fixes from Tasks 3-5:

```bash
~/.claude/skills/skill-publishing/scripts/prepare-plugin.sh \
  --output-dir plugins/skill-publishing ~/.claude/skills/skill-publishing/plugin-manifest.json
```

- [ ] **Step 4: Verify the assembled copy actually carries all three changes.** This is the step that makes the out-of-tree work visible in the PR:

```bash
for f in _lib.sh prepare-plugin.sh sync-monorepo.sh; do
  diff -q ~/.claude/skills/skill-publishing/scripts/$f \
          plugins/skill-publishing/skills/skill-publishing/scripts/$f \
    && echo "$f: SYNCED" || echo "$f: DRIFT"
done
grep -q 'resolve_source_path' plugins/skill-publishing/skills/skill-publishing/scripts/_lib.sh && echo LIB-OK
grep -q 'skill_source_dir'   plugins/skill-publishing/skills/skill-publishing/scripts/sync-monorepo.sh && echo SYNC-OK
jq -r .version plugins/skill-publishing/.claude-plugin/plugin.json   # expect 4.2.0
```

  If any file reports DRIFT, the re-assembly did not take — report it as a failure, do not hand-copy the file.

- [ ] **Step 5: Validators** — `scripts/validate-skill.sh` on the assembled skill dir and `scripts/validate-plugin.sh plugins/skill-publishing` both pass. If the SKILL.md body crosses 500 lines after Step 1, extract to `references/` per the global constraint.

---

### Task 6: Repo wiring — marketplace versions, root CHANGELOG, final sweep

**Files:** `.claude-plugin/marketplace.json`, `CHANGELOG.md`, `README.md` (only if it carries versioned plugin rows)

- [ ] **Step 1: Update `.claude-plugin/marketplace.json`** — `spec-creator` → `2.4.2`, `spec-review` → `2.2.2`, `skill-publishing` → `4.2.0`. Leave `spec-implement` at `1.0.0` (untouched by this change).

- [ ] **Step 2: Add a root `CHANGELOG.md` `[Unreleased]` section** covering both issues, in the style of the existing entries.

- [ ] **Step 3: Check `README.md`** for a plugin table carrying versions; update the three rows if present. If the README has no version column, say so rather than editing nothing silently.

- [ ] **Step 4: Version-agreement sweep** — every plugin's marketplace version must equal its assembled `plugin.json` version:

```bash
python3 - <<'PY'
import json, pathlib
mk = json.load(open('.claude-plugin/marketplace.json'))
bad = []
for p in mk['plugins']:
    pj = pathlib.Path(p['source'].lstrip('./')) / '.claude-plugin' / 'plugin.json'
    if pj.exists():
        v = json.load(open(pj))['version']
        if v != p['version']:
            bad.append((p['name'], p['version'], v))
print('MISMATCH:', bad) if bad else print('ALL VERSIONS AGREE')
PY
```

- [ ] **Step 5: Regression harness green** — `scripts/test-discovery-guards.sh` passes end to end, including every positive and negative control.

- [ ] **Step 6: Full validation** — `scripts/validate-skill.sh` on `spec-creator` and `spec-review`; `scripts/validate-plugin.sh` on `plugins/spec-creator`, `plugins/spec-review`, `plugins/skill-publishing`. All must pass.

- [ ] **Step 7: Re-run the issues' own reproductions** and paste the actual output into the report — #62's architecture-discovery JSON against this repo (expect three empty fields) and #61's `cd /tmp` `prepare-plugin.sh` invocation (expect success).

- [ ] **Step 8: Confirm nothing under `~/.claude/skills/` was deleted or renamed.** `ls ~/.claude/skills/ | wc -l` and confirm `spec-creator`, `spec-review`, `spec-implement` and `skill-publishing` are all still present. #63 owns that deletion, not this change.

## Out of scope for this plan

- **#63** — verifying the `spec-*` plugins from a real marketplace install and deleting the local `~/.claude/skills/spec-*` copies. This plan must leave those copies intact.
- **#64** — `validate-plugin.sh`'s blindness to namespaced `subagent_type` / `Skill(plugin:name)` references.
- **#37** — the `prepare-plugin.sh` README generator's `>-` folded-scalar leak. If a re-assembly in this plan emits a literal `>-` into a generated README, hand-correct that line and note it; do not fix the generator here.
- Wiring `scripts/test-discovery-guards.sh` into the CI workflow. The harness lands and must pass locally; the CI job's changed-directory detection only triggers on skill dirs, so adding a test job is a separate change.
