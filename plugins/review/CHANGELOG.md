# Changelog

All notable changes to the **review** plugin are documented here.

## [1.0.0] - 2026-10-03

### Added

- First release (#159). It merges the `deep-review` and `adversarial-review` plugins. Two skills under short names: `deep` (was `deep-review`) and `adversarial` (was `adversarial-review`). Invoke them as `/review:deep` and `/review:adversarial`. The old names still match as trigger phrases.
- Three agents, dispatched as `review:bug-hunter`, `review:convention-reviewer` and `review:cross-examiner` (were `adversarial-bug-hunter`, `adversarial-convention-reviewer` and `adversarial-cross-examiner`). Both skills use them.
- One copy of the adversary scripts, in `skills/adversarial/scripts/`. `deep` runs them from the same plugin, so it no longer depends on the `adversarial-review` plugin. `pr-review-toolkit` is still a soft dependency of Phase 1.

### Changed

- `detect-mode.sh` local mode: a guessed base that does not exist (for example `feature/*` with no `develop`) falls back to the repo default branch with a note on stderr, and a missing base now exits 1 instead of writing an empty diff. New `--base <branch>` picks the base (an unknown one exits 2). The local diff is now the working tree against the merge base: committed, staged and unstaged changes to tracked files. Untracked files are left out and listed on stderr (paths only), because the diff is sent to the adversary model; `--include-untracked` adds them, but files named like secrets (`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `*credentials*`, `*.p12`, `*.pfx`) are never sent. Your index is not changed. File names from the working tree are passed to git as literal paths (`GIT_LITERAL_PATHSPECS=1`), so an untracked file named `[.]env` or `*` cannot pull a secret into the diff, and a final check refuses to write any diff that holds an untracked path that was not chosen. A repo with no commits now says so instead of "Not inside a git repository". PR mode is unchanged.
- Every command in both skills and in the `deep` references spells out its script path. The Bash tool keeps no shell variables between calls, so the old `$SCRIPTS`, `$AR_SCRIPTS`, `$ADV_REVIEW`, `$AUDIT` and `$RUN_DIR` reads were empty. A test (`skills/adversarial/scripts/test_skill_paths.py`) now fails when a fenced block reads a variable it did not set.
- `audit_record.py` accepts the skill values `adversarial` and `deep`, and still accepts `adversarial-review` and `deep-review`, because round-record files written by the old skills (for example a `round-N.json` reused with `recheck --prior`, or a Step 5 rerun) carry them. New runs write the new values.
- The local report file is still `<branch>.adversarial-review.md`, so existing `.gitignore` entries still match.

### Deprecated

- The `deep-review` and `adversarial-review` plugins. They stay published for one more release, marked deprecated in the marketplace. Install `review`, then uninstall both, so the old names cannot win a plain-language request.

Per-skill history before the merge is in `skills/deep/CHANGELOG.md` and `skills/adversarial/CHANGELOG.md`.
