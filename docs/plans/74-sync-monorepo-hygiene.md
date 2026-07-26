# Plan — #74: sync-monorepo.sh hygiene (build/ pollution + non-skill directories)

Fixes two defects in `sync-monorepo.sh` that compound each other: the plugin auto-build
writes `./build/` into whatever directory the caller happens to be in, and the skill
discovery treats every top-level monorepo directory as a skill — so the `build/` tree the
tool just created is misdetected as a skill on the *next* run.

## Global Constraints

1. **`skill-publishing` is a plugin-only skill with an out-of-repo authoring source.**
   The live source of truth is `~/.claude/skills/skill-publishing/`. The repo carries one
   published copy at `plugins/skill-publishing/skills/skill-publishing/`. The two are
   currently byte-identical and **must stay byte-identical after every task.**
   Edit BOTH directly. Do **not** run `sync-monorepo.sh` to propagate these changes —
   you would be using a half-modified tool to publish itself.

2. **Do not run `sync-monorepo.sh` against the live repo.** Every functional test runs
   against a scratch fixture with `SKILLS_HOME` and the monorepo argument both pointed at
   throwaway directories. `SKILLS_HOME` is overridable (`SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"`,
   line 8), which is what makes this testable at all.

3. **`--add-plugin`'s `./build/<name>` is a user-facing contract and must not change.**
   Its error message literally instructs the user to `Run: prepare-plugin.sh <manifest-file> first`,
   and `prepare-plugin.sh` defaults its output to `./build/<plugin-name>`. Only the
   *internal auto-build* path may be relocated.

4. **Every guard must cover every site.** Two of the three defects in this plan appear at
   more than one location. A fix covering N-1 of N sites reproduces the original bug while
   adding a reassuring log line. Enumerate the sites yourself before declaring a task done —
   do not trust the counts in this plan without re-deriving them.

5. Bash only, `#!/usr/bin/env bash`. Note that on macOS the interactive shell's `grep` is a
   function wrapping ugrep; scripts get real `/usr/bin/grep`. Never test a paraphrase of a
   guard — run the actual script.

6. Never write `… | head -n && …` or `… | head -n || …`. A pipeline's exit status is its
   **last** stage's, so `head` masks the real status. This is the exact defect class of #62.

## Established facts (verified this session — do not re-derive)

- `sync-monorepo.sh` line 8: `SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"` — env-overridable.
- Line 538: `_BUILD_DIR="./build/$_MANIFEST_NAME"` — the internal auto-build path. **This is the polluter.**
- Line 575: `PLUGIN_BUILD="./build/$ADD_PLUGIN"` — the `--add-plugin` contract. **Leave alone.**
- Line 37 usage text: `--add-plugin <name>    Add a plugin from ./build/<name>/ to plugins/` — documents that contract.
- `prepare-plugin.sh` line 117: `OUTPUT_DIR="./build/$PLUGIN_NAME"` when `--output-dir` is not given.
  It already supports `--output-dir DIR` (line 29), so **`prepare-plugin.sh` needs no change**.
- `discover_skills()` contains the exclusion filter `! -name '.git' ! -name '.github' ! -name '.*' ! -name 'plugins' ! -name 'scripts'`
  at **two** separate sites: once in the `--add` branch and once in the main "monorepo exists" branch.
- Against the live repo today, exactly two returned directories are not skills: `build` and `docs`
  (neither contains a `SKILL.md`). Every other returned directory has one.
- `sync-monorepo.sh` line ~1029 embeds a `.gitignore` **template** (`.DS_Store`, `*.swp`, `*~`, `.claude/`)
  written via `write_file` at line 1034, which skips when the file already exists. The repo's real
  `.gitignore` has since diverged and does **not** contain `build/`.
- The repo's only shell regression harness is `scripts/test-discovery-guards.sh`, run
  unconditionally by the `discovery-guards` job in `.github/workflows/validate-skill.yml`.
- `skill-publishing` is at version 4.2.0 in both `plugins/skill-publishing/.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`.

---

## Task 1 — Exclude non-skill directories from `discover_skills()`

**Files:** `~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh` and
`plugins/skill-publishing/skills/skill-publishing/scripts/sync-monorepo.sh` (keep identical).

`discover_skills()` returns every top-level monorepo directory except a small deny-list, so
non-skill directories (`docs`, `build`) enter the sync loop and each produces:

```
  ERROR: no SKILL.md in <SKILLS_HOME>/docs or <MONOREPO_DIR>/docs, skipping
```

Routine `ERROR:` output trains the reader to ignore genuine errors.

**Change:** filter the candidate list to directories that actually contain a `SKILL.md` in
**either** `$SKILLS_HOME/<name>` or `$MONOREPO_DIR/<name>` — i.e. exactly the condition
`skill_source_dir()` already applies. A directory that fails that test is not a skill and
must never have entered the loop.

Apply at **both** sites in the function (the `--add` branch and the main branch). The
`--skills` explicit-list branch is a user-supplied list and must keep its current behaviour:
a name the user typed that turns out not to be a skill should still produce the existing
`ERROR:`, because there it is a genuine problem.

Emit one line per filtered directory so the skip is visible rather than silent, at a
non-error severity, e.g.:

```
  SKIP (not a skill: no SKILL.md)  docs
```

Silence here would trade a false error for a real blind spot; the goal is to move the
message out of the `ERROR:` namespace, not to remove it.

**Verify:** against a fixture monorepo containing `docs/`, `build/` and at least two real
skill directories, the printed "Skills to sync" list contains the skills and neither
`docs` nor `build`, and the run prints no `ERROR:` line mentioning either.

---

## Task 2 — Auto-build into a temp directory instead of the caller's cwd

**Files:** the same two `sync-monorepo.sh` copies (keep identical).

Line 538's `_BUILD_DIR="./build/$_MANIFEST_NAME"` is relative to the caller's working
directory, and `prepare-plugin.sh` (invoked one line above with no `--output-dir`) defaults
to the same cwd-relative path. Running the sync from the monorepo root therefore leaves an
untracked `build/` tree in the repo, which a routine `git add -A` would commit.

**Change:** create one temp directory for the whole auto-build stage (`mktemp -d`), pass
`--output-dir "<tmp>/<plugin-name>"` explicitly to `prepare-plugin.sh`, and read
`_BUILD_DIR` from that same path. Remove the temp tree on exit via a `trap` so a failure
part-way through does not leak it. If a `trap … EXIT` already exists in this script, extend
it rather than replacing it — clobbering an existing EXIT trap would silently disable
whatever cleanup it performs.

**Do not touch** the `--add-plugin` block (line ~575) or the line 37 usage text: that path
consumes a build directory the *user* produced with their own `prepare-plugin.sh` run, and
relocating it would break the documented workflow.

`prepare-plugin.sh` itself needs no change — it already accepts `--output-dir`.

**Verify:** run the sync against a scratch fixture from a scratch working directory, and
assert `build/` does **not** exist in that working directory afterwards, while
`plugins/<name>/` in the fixture monorepo is still correctly assembled. Confirm the
temp directory is gone after the run. Then separately confirm the `--add-plugin` path still
finds `./build/<name>` when the user created it.

---

## Task 3 — `.gitignore` (both sites), regression harness, CI job, version bump

**Files:** `.gitignore`; both `sync-monorepo.sh` copies; `scripts/test-sync-hygiene.sh` (new);
`.github/workflows/validate-skill.yml`; `plugins/skill-publishing/.claude-plugin/plugin.json`;
`.claude-plugin/marketplace.json`; `plugins/skill-publishing/CHANGELOG.md`; root `CHANGELOG.md`.

1. **`.gitignore` — two sites.** Add `build/` to the repo's real `.gitignore`, **and** to the
   embedded template inside `sync-monorepo.sh` (line ~1029) so a freshly `--init`-ed monorepo
   gets it too. Fixing only the repo file leaves every new monorepo carrying the defect.
   Note the repo currently has an untracked `build/` tree; after this change it must no longer
   appear in `git status`.

2. **Regression harness** `scripts/test-sync-hygiene.sh`, `set -euo pipefail`, executable,
   modelled on `scripts/test-discovery-guards.sh` (same assertion-helper style and output
   format). It must build its own throwaway `SKILLS_HOME` and monorepo fixtures, run the real
   `sync-monorepo.sh`, and assert at minimum:
   - no `build/` directory is left in the working directory the sync was run from;
   - `docs` and `build` do not appear in the "Skills to sync" list;
   - no `ERROR:` line mentions `docs` or `build`;
   - a real skill in the fixture *is* still synced (guards against a filter that excludes everything);
   - `build/` is matched by the repo's `.gitignore` (`git check-ignore -q build`).

   Point it at the **repo's** copy of the script by default, with an env override
   (e.g. `SYNC_SCRIPT`) so the live copy can be exercised too — mirroring the
   `DISCOVER_CONVENTIONS_SCRIPT` pattern already used in `test-discovery-guards.sh`.

   **Prove each assertion fails first.** Revert each fix in a scratch copy of the script and
   confirm the corresponding assertion FAILS. An assertion that passes against the unfixed
   script is vacuous and worse than none. Report the fail-first evidence explicitly.

3. **CI**: add a job that runs `./scripts/test-sync-hygiene.sh` unconditionally, alongside the
   existing `discovery-guards` job. Do **not** put it behind a changed-paths filter — the
   existing skill/plugin path filters do not match `scripts/**`, which is why the discovery
   harness had to be wired unconditionally.

4. **Version + changelog**: bump `skill-publishing` 4.2.0 → **4.2.1** in
   `plugins/skill-publishing/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
   Add a `## [4.2.1]` entry to the plugin CHANGELOG and a matching root CHANGELOG entry, both
   referencing #74.

**Verify:** `./scripts/test-sync-hygiene.sh` passes; every assertion has recorded fail-first
evidence; `git status` no longer shows `build/`; the two `sync-monorepo.sh` copies are
byte-identical (`diff -q`); `scripts/validate-plugin.sh` passes for `skill-publishing`.
