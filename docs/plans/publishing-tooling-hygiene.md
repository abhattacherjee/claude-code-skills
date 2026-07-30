# Plan — publishing-tooling hygiene (#73, #77, #78, #79, #80, #81)

Six defects in the `skill-publishing` scripts, all surfaced by dogfooding #74 (PR #76). Five of
the six share one shape: **a write path that reports success while not doing its job.** The sixth
(#79) publishes a wrong-but-plausible value. They are batched because they overlap on the same
three files and stacked feature PRs are blocked in this repo.

| # | File(s) | One-line defect |
|---|---|---|
| #77 | `prepare-plugin.sh` | a declared `hooks.source` that does not exist is silently skipped, then `rsync --delete` removes hooks from the published plugin |
| #79 | `sync-monorepo.sh` | auto-build does not forward `--github-user`, so one run can advertise two accounts |
| #73 | `prepare-plugin.sh`, `sync-monorepo.sh` | legacy string-array `skills[]` aborts `jq`; sync only warns, so the plugin never rebuilds |
| #78 | `validate-pre-sync.sh`, `_lib.sh` | skips every in-repo-source skill, then reports "Safe to sync" |
| #80 | `sync-monorepo.sh` | `--skills` resolving to zero names republishes an empty catalog, silently |
| #81 | `sync-monorepo.sh` | unquoted `for` IFS-splits skill names containing spaces, then reports a false synced count |

---

## Global Constraints

1. **`skill-publishing` is a plugin-only skill with an out-of-repo authoring source.** The live
   source of truth is `~/.claude/skills/skill-publishing/`; the repo carries one published copy at
   `plugins/skill-publishing/skills/skill-publishing/`. **All 11 scripts are byte-identical today
   (verified this session) and must stay byte-identical after every task.** Edit BOTH copies
   directly. Do **not** run `sync-monorepo.sh` to propagate these changes — you would be using a
   half-modified tool to publish itself.

2. **Do not run `sync-monorepo.sh` (or `validate-pre-sync.sh`) against the live repo.** Every
   functional test runs against throwaway fixtures with `SKILLS_HOME` and the monorepo argument
   both pointed at scratch directories. `SKILLS_HOME` is env-overridable in both scripts, which is
   what makes this testable.

3. **Every guard must cover every site, and you must re-derive the sites yourself.** Do not trust
   the line numbers or counts in this plan — they were correct when written and the file shifts
   under each task. A fix covering N-1 of N sites reproduces the original bug while adding a
   reassuring log line. This plan's predecessor named 2 version-bump sites where there were 5.

4. **Every new assertion needs BOTH directions.** A negative fixture catches a guard stuck ON;
   only a positive fixture catches one stuck OFF. Prove each new assertion fails against the
   unfixed code (revert the fix in a scratch copy), *and* prove the positive control fails if the
   guard is patched to no-op (`if false && …`). An assertion that passes against unfixed code is
   vacuous and worse than none. This is issue #69, shipping in parallel.

5. **Fixtures must be able to reach the condition under test.** Payloads past whatever threshold
   the code cares about (the CHANGELOG fixture must stay >64 KiB — a broken-pipe defect firing on
   every real run once hid behind a few-hundred-byte fixture and 14/14 passing assertions);
   identifiers unique per run wherever concurrency is possible; at least one instance of every
   branch a predicate can resolve through.

6. Bash only, `#!/usr/bin/env bash`. On macOS the interactive shell's `grep` is a function wrapping
   ugrep; scripts get real `/usr/bin/grep`. **Never test a paraphrase of a guard — run the actual
   script.**

7. Never write `… | head -n && …` or `… | head -n || …`; a pipeline's status is its **last**
   stage's. Prefer here-strings (`<<<`) over `printf | grep` in assertion helpers: on a large
   haystack the pipe form returns non-zero under `pipefail` *while grep matched*, silently
   inverting the assertion. Both traps have already shipped bugs in this repo (#62, PR #76).

8. `git check-ignore -q` returns **0=ignored, 1=not-ignored, 128=error**. Never write it as
   `check-ignore … && …`, which collapses 128 into the expected value.

---

## Established facts (verified this session — do not re-derive, but do re-locate)

**Parity**
- All 11 files under `scripts/` are byte-identical between the live skill and the in-repo copy.

**#77 — hooks**
- `prepare-plugin.sh` §5 "Copy hooks (optional)" (~line 237-252): `if [[ -d "$HOOKS_SRC" ]]; then …
  fi` with **no `else`**.
- The three sibling loops **do** error and `exit 1` on a missing source: skills (~164-166),
  commands (~198-200), agents (~222-224). Match their message shape exactly.
- **No manifest anywhere on this machine currently declares `hooks.source`** (all 14 audited
  manifests report `-` or `null`). This fix is therefore a **latent guardrail** for this repo — it
  bites other repos that use this tooling and do have hooks (e.g. `obsidian-brain`). Say so in the
  CHANGELOG; do not claim it fixes an active breakage here.

**#79 — github-user**
- `sync-monorepo.sh` ~line 618: `"$PREPARE_SCRIPT" --output-dir "$_BUILD_DIR" "$_MANIFEST"` — no
  `--github-user`.
- `GITHUB_USER` is resolved by `resolve_github_user` (~line 138) well before the auto-build stage,
  so it is guaranteed non-empty at the call site.
- `prepare-plugin.sh` ~line 111-112 falls back to `gh api user … || echo "USERNAME"` — hence the
  literal string `USERNAME` in an unauthenticated CI.

**#73 — legacy manifest shape**
- `prepare-plugin.sh` reads `.skills[$i].name` / `.skills[$i].source` at ~160-162, ~314, ~383-384,
  and `.skills[0].source` at ~295-296 and ~331-332. `sync-monorepo.sh` reads
  `.skills[]?.name // empty` at ~567 and `.skills[0].name` at ~587.
- **Exactly one** legacy manifest exists: `~/.claude/skills/github-release-board-promote/plugin-manifest.json`,
  with `"skills": ["github-release-board-promote"]`. Its `agents` and `commands` are `[]`.
- A legacy bare string means "the skill lives in this manifest's own directory", so
  `{"name": <string>, "source": "."}` is the correct normalisation — `resolve_source_path "."
  "$MANIFEST_DIR"` yields the manifest's directory.
- `sync-monorepo.sh` ~644-652 currently only warns; the comment there explicitly says the exit-0
  behaviour is "deliberate here and tracked separately (#73)". **This task is what retires that
  comment** — delete it along with the behaviour, do not leave it claiming a defect is intentional.
- **`github-release-board-promote` has no `plugins/` directory and no `marketplace.json` entry.**
  The consequence of #73 was not drift — that plugin was **never published at all**. Fixing the
  tooling therefore means the *next* real sync run will create a new published plugin and a new
  marketplace entry. This PR must **not** do that (Constraint 2); it is a separate deliberate act.

**#78 — validate-pre-sync**
- `validate-pre-sync.sh` ~71-74 discovers with the pre-#74 deny-list (no `SKILL.md` filter), then
  ~83-90 hardcodes `SKILL_SRC="$SKILLS_HOME/$SKILL_NAME"` and `continue`s when the local `SKILL.md`
  is absent — counting that skill as neither total nor fail, i.e. as a pass.
- Eleven repo top-level directories have an in-repo `SKILL.md`: `changelog-keeper`, `claudeception`,
  `context-shield`, `conversation-search`, `figma-ui-designer`, `github-board-move`,
  `skill-authoring`, `spec-creator`, `spec-implement`, `spec-review`, `worktree`. **Re-derive this
  list yourself** — #63 changed it two days ago and it will change again.
- `skill_source_dir()` is defined in `sync-monorepo.sh` ~95-102, i.e. *after* it sources `_lib.sh`
  at ~13. Hoisting the definition into `_lib.sh` and deleting the local one is therefore
  behaviour-preserving for `sync-monorepo.sh`.

**#80 — --skills**
- `discover_skills()`'s `--skills` branch (~221-224) is `printf '%s\n' "$SKILLS_LIST" | tr ',' '\n'
  | sort` — no blank-line filter and no zero-result guard. The `--add` branch immediately above
  (~210-217) received exactly those two things in PR #76; mirror it.
- `exit 1` inside `$(discover_skills)` terminates the subshell and `set -e` catches the
  assignment's status in the parent. The `--add` branch already relies on this — it is proven, not
  speculative.
- `SKILLS_TO_SYNC=$(discover_skills)` at ~251; `SKILL_COUNT` branches on emptiness at ~258-262.
  Neither refuses to continue.

**#81 — IFS splitting**
- Unquoted iteration over a newline-delimited list occurs at **at least five** sites:
  `sync-monorepo.sh` ~275 (main sync loop), ~950 (install-all commands), ~1057 (skill inventory),
  ~911 (`$PLUGINS_TO_LIST`), ~567 (`$(jq -r '.skills[]?.name …')`); plus
  `validate-pre-sync.sh` ~83 (`$SKILLS`). **Re-derive the full set — this list is a floor, not a
  ceiling.**
- The ~275 loop assigns `CATALOG_ROWS` and `REFUSED_SKILLS`, and ~1057 reads `skill_refused`, so
  those loops must stay in the **current shell**: use `while IFS= read -r … done <<< "$LIST"`, never
  a pipe.
- A here-string on an empty variable yields one empty line, so every converted loop needs
  `[[ -z "$NAME" ]] && continue`.

**Versions**
- `skill-publishing` is at **4.2.1** at five sites: `plugins/skill-publishing/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `~/.claude/skills/skill-publishing/plugin-manifest.json`, and
  `metadata.version` in **both** `SKILL.md` copies. `README.md:35` carries it in the catalogue
  table. Three CHANGELOG copies must stay byte-identical: root `CHANGELOG.md`,
  `plugins/skill-publishing/CHANGELOG.md`, `plugins/skill-publishing/skills/skill-publishing/CHANGELOG.md`.
- Target: **4.3.0** (minor, not patch — this batch introduces new *refusals*, so runs that
  previously exited 0 will now exit 1).

**Harness**
- `scripts/test-sync-hygiene.sh` exists with 59 assertions; `scripts/test-discovery-guards.sh`
  alongside it. Both run unconditionally in `.github/workflows/validate-skill.yml` (jobs
  `sync-hygiene`, `discovery-guards`) because the repo's changed-path filters do not match
  `scripts/**`.

---

## Task 1 — #77 (hooks source) + #79 (forward --github-user)

**Files:** both copies of `prepare-plugin.sh`; both copies of `sync-monorepo.sh`;
`scripts/test-sync-hygiene.sh`.

Two small independent fixes in the same auto-build path, batched to avoid two passes over the same
region.

**#77.** Give the `hooks.source` existence check an `else` that prints an error to stderr and
`exit 1`, matching the skills/commands/agents siblings verbatim in shape. A declared source that
does not exist is a manifest error, not an optional extra. Do **not** add defence-in-depth at the
sync layer (refusing `--delete` on a shrinking build) — that is more machinery than it is worth
once the child errors properly.

Note the distinction the fix must preserve: `hooks` **absent** from the manifest, and
`hooks.source` **null/empty**, both remain legal no-ops. Only a *declared, non-empty* source that
does not resolve to a directory is an error. Get all three cases into the tests.

**#79.** Pass `--github-user "$GITHUB_USER"` to `prepare-plugin.sh` in the auto-build invocation.
Side benefit: one fewer `gh` call per sync run, which makes the CI job less network-dependent.

**Tests (fail-first, both directions):**
- A fixture plugin whose manifest declares `hooks.source` pointing at a directory that exists →
  build succeeds and `hooks/` is present in the output (**positive control**: without this, a fix
  that rejects *all* hooks would pass).
- Same fixture with the hooks directory deleted → `prepare-plugin.sh` exits non-zero and says so;
  and the already-published `plugins/<name>/hooks/` still exists afterwards (i.e. sync did not
  `--delete` it).
- Manifest with no `hooks` key, and manifest with `hooks.source: null` → both still exit 0.
- Run sync with `--github-user probe` against a fixture and assert **every** generated README
  (monorepo root *and* each `plugins/*/README.md`) says `probe` — not just the root one. Assert the
  string `USERNAME` appears in none of them.

---

## Task 2 — #73 (legacy manifest shape + hard failure)

**Files:** both copies of `prepare-plugin.sh`; both copies of `sync-monorepo.sh`;
`~/.claude/skills/github-release-board-promote/plugin-manifest.json` (out-of-repo, live);
`scripts/test-sync-hygiene.sh`.

**Normalise the manifest in one place, not at every read site.** There are six-plus `jq` reads of
`.skills[…]`; patching each is how you get an N-1-of-N fix. Instead, once the manifest has been
validated, write a normalised copy to a temp file and point the existing reads at that:

```bash
jq '(.skills // []) |= map(if type == "string" then {name: ., source: "."} else . end)' \
   "$MANIFEST_FILE" > "$NORMALIZED_MANIFEST"
```

**The load-bearing subtlety:** `MANIFEST_DIR` must keep pointing at the **original** manifest's
directory, because `resolve_source_path` resolves relative sources against it. If `MANIFEST_DIR`
follows the temp file, every relative source in every manifest breaks — that is a far worse
regression than the bug being fixed. Add a test that a manifest using a *relative* source still
builds correctly after this change.

Clean the temp file up with a `trap … EXIT`. If an EXIT trap already exists in the script, **extend
it, do not replace it** — clobbering it silently disables whatever it was cleaning up. (`rm -rf`,
not `rm -r`: the `-f` is load-bearing, because under `set -e` a trap body that returns non-zero
rewrites the script's exit status.)

A bare string in `commands[]` or `agents[]` is **not** normalisable — their sources are files, not
directories, so `"."` is meaningless. Reject those loudly with the same error shape as a missing
source rather than guessing.

**Make the sync-layer failure hard.** Replace the `Warning: prepare-plugin.sh failed …` path with
an error and `exit 1`, keeping the captured child log (that is the only actionable output). Delete
the comment claiming the exit-0 behaviour is deliberate. Note the trade-off explicitly in your
report: failing fast here leaves the monorepo with skills synced but README/CHANGELOG not
regenerated. That is inconsistent-but-loud and fully git-recoverable, and is preferable to
publishing a catalogue that describes a plugin the run failed to build. If you conclude otherwise
after reading the surrounding code, say so in your report rather than silently choosing the other
design.

**Migrate the live legacy manifest** to the object form
(`[{"name": "github-release-board-promote", "source": "."}]`). Do **not** bump its version — the
shape is not user-visible content, and a version change would trigger a drift rebuild. The fixture
test is the permanent canary for the legacy shape once this migration removes the only real
instance.

**Tests (fail-first, both directions):**
- Fixture manifest with legacy `"skills": ["name"]` → `prepare-plugin.sh` exits 0 and assembles the
  skill (currently: `jq: error … Cannot index string with string "name"`).
- Fixture manifest with object-form skills **and a relative `source`** → still assembles correctly
  (guards the `MANIFEST_DIR` regression).
- Fixture manifest with a bare string in `commands[]` → exits non-zero with a clear message.
- A sync run where one manifest cannot be built → exits **non-zero**, and the failing manifest's
  name appears on stderr along with the child's own diagnosis.
- **Positive control:** a sync run where all manifests build cleanly still exits 0. Without this, a
  fix that makes every run fail would pass the assertion above.

---

## Task 3 — #78 (validate-pre-sync must see in-repo-source skills)

**Files:** both copies of `_lib.sh`; both copies of `validate-pre-sync.sh`; both copies of
`sync-monorepo.sh`; `scripts/test-sync-hygiene.sh`.

Hoist `skill_source_dir()` from `sync-monorepo.sh` into `_lib.sh` verbatim, delete the local
definition, and have `validate-pre-sync.sh` resolve each skill through it instead of hardcoding
`$SKILLS_HOME/<name>`. After this there is **one** definition of "where does this skill's source
live", which is the whole premise of #74: discovery must never disagree with sourcing.

In `_lib.sh` the function must tolerate an unset `MONOREPO_DIR` (`${MONOREPO_DIR:-}`) — `_lib.sh`
is sourced by scripts that never set it, and `set -u` would abort them the moment the function is
called. Verify every script that sources `_lib.sh` still runs (`--help` at minimum).

While in `validate-pre-sync.sh`: filter its discovery to actual skills (same condition), so `docs/`
and `build/` stop entering the loop; and convert its `for SKILL_NAME in $SKILLS` to the line-wise
form (this is #81's shape in this file — fixing it here avoids two tasks editing the same loop).

Behaviour to preserve: a skill with **no** source anywhere must still be skipped, not counted as a
failure. The point is to stop counting *unexamined* skills as passes, not to start failing on
directories that are not skills.

**Tests (fail-first, both directions):**
- Fixture monorepo with an **in-repo-source-only** skill whose `SKILL.md` version has **no**
  matching CHANGELOG entry → `validate-pre-sync.sh` exits **1** and names it. Currently it exits 0
  saying "Safe to sync". This is the core assertion.
- **Positive control:** the same skill *with* a matching CHANGELOG entry → exits 0 and the skill
  appears in the PASS list with the right version. Without this, a rework that fails everything
  would pass the assertion above.
- A local-source skill still validates exactly as before (no regression on the existing path).
- `docs/` and `build/` in the fixture appear in neither the pass nor the fail counts.
- The reported `Total:` equals the number of real skills in the fixture — assert the **number**,
  since "it examined them" is exactly what the old code got wrong while printing a green summary.

---

## Task 4 — #80 (`--skills` must refuse rather than publish an empty catalog)

**Files:** both copies of `sync-monorepo.sh`; `scripts/test-sync-hygiene.sh`.

Two entry points, differing only in how quiet they are:

1. `--skills ,` (any separator-only value) → resolves to zero names, **completely silent**, exit 0,
   and the monorepo README is regenerated with an empty catalogue table plus a CHANGELOG entry
   claiming "Synced 0 skills".
2. `--skills nosuchskill` → one `ERROR: no SKILL.md …` line, then the same destructive rewrite.

Fix (1) in `discover_skills()`, mirroring what PR #76 did for `--add`: filter blank lines, capture
the result, and if it is empty print `Error: --skills produced no skill names from: '<value>'` to
stderr and `exit 1` before anything is written.

Fix (2) with a second guard: when `--skills` was **explicitly supplied** and the sync loop
synced **zero** skills, error out before regenerating the README/CHANGELOG. Site it after the main
sync loop and before the first catalogue write — re-derive where that boundary actually is. Do not
apply this guard to the discovery path (a monorepo that genuinely contains no skills yet is a
legitimate zero, not a user error).

**Tests (fail-first, both directions):**
- Fixture monorepo with a populated catalogue; run `--skills ,` → exits non-zero, stderr names the
  argument, and the README **still has its original catalogue rows** (count them before and after).
- Same fixture, `--skills nosuchskill` → exits non-zero and the catalogue rows survive.
- **Positive control:** `--skills <a real skill in the fixture>` → exits 0 and that skill is synced
  and appears in the catalogue. Without this, a guard that refuses every `--skills` invocation
  would pass both assertions above.
- A plain discovery run against a monorepo with zero skills still exits 0 (the legitimate zero).

---

## Task 5 — #81 (line-wise iteration at every site)

**Files:** both copies of `sync-monorepo.sh`; `scripts/test-sync-hygiene.sh`.

`filter_skill_candidates` correctly *accepts* a skill directory whose name contains a space — it
has a valid `SKILL.md` — prints it as one entry, and counts it as one. The unquoted `for` loop then
splits it into fragments, each of which fails to resolve. The result is two loud `ERROR:` lines and
a closing summary that still claims the full count was synced, with `rc=0`.

Convert **every** unquoted iteration over a newline-delimited list to:

```bash
while IFS= read -r SKILL_NAME; do
    [[ -z "$SKILL_NAME" ]] && continue
    …
done <<< "$SKILLS_TO_SYNC"
```

A here-string, not a pipe: the main loop assigns `CATALOG_ROWS` / `REFUSED_SKILLS` and must stay in
the current shell. Re-derive the full set of sites (the facts section lists five as a floor, one of
which — `validate-pre-sync.sh` — Task 3 already converted). Include the `$PLUGINS_TO_LIST` loop and
the `$(jq …)` skill-name loop: same class, same consequence.

Also make the closing summary honest: it must report the number of skills **actually** synced, not
the discovered count. A count that disagrees with what happened is the reassuring-log-line failure
this whole batch is about.

**Tests (fail-first, both directions):**
- Fixture monorepo with a skill directory named `my skill` plus a normal one → both are synced,
  both appear as catalogue rows, `Sync complete.` reports **2**, and no `ERROR:` line is printed.
- The space-named skill's own directory contents are actually copied (not just counted).
- **Positive control:** the all-normal-names fixture still syncs and reports the correct count —
  the conversion must not break the ordinary path.
- Assert on the *summary number* specifically. Under the current code that line reads 2 while one
  skill was dropped, so an assertion that only checks "no ERROR lines" would not catch a
  half-conversion.

---

## Task 6 — Harness audit, version bump, changelogs, CI

**Files:** `scripts/test-sync-hygiene.sh`; `.github/workflows/validate-skill.yml`;
`plugins/skill-publishing/.claude-plugin/plugin.json`; `.claude-plugin/marketplace.json`;
`~/.claude/skills/skill-publishing/plugin-manifest.json`; both `SKILL.md` copies; `README.md`;
the three CHANGELOG copies.

1. **Mutation-audit the whole harness, not just the new assertions.** For each of the six fixes,
   patch the fixed code to a no-op (`if false && …`, or revert the hunk) in a scratch copy and
   confirm the suite goes **red**, naming which assertion caught it. Report the matrix
   (fix → assertion that dies). Any fix with no assertion that dies is unguarded — say so
   explicitly rather than quietly leaving it.

2. **Re-derive and bump every version site.** The facts section names five plus `README.md` — count
   them yourself; `plugin.json` is *generated from* the live `plugin-manifest.json`, so bumping only
   the obvious sites silently reverts on the next sync. 4.2.1 → **4.3.0**.

3. **Three CHANGELOG copies, byte-identical.** One `## [4.3.0]` entry covering all six issues.
   State plainly that #77 is a latent guardrail (no manifest here declares `hooks.source`) and that
   #73's fix means `github-release-board-promote` will be published by the next sync run.

4. **CI**: the `sync-hygiene` job already runs `test-sync-hygiene.sh` unconditionally — confirm it
   still does and that no changed-paths filter crept in. Add nothing new unless the harness grew a
   second entry point.

5. **Final parity + validation gate:** `diff -q` every file under `scripts/` between the live skill
   and the in-repo copy (all 11 must be identical), `scripts/validate-plugin.sh skill-publishing`
   passes, `scripts/validate-skill.sh` passes, both harnesses green, and `git status` shows no
   stray `build/` tree.

**Verify:** report the mutation matrix, the enumerated version sites with their before/after
values, and the parity diff output — as evidence, not as a claim.
