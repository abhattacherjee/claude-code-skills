# Changelog

All notable changes to the **review** plugin are documented here.

## [1.2.0] - 2026-10-09

### Changed

- `synthesize.py` exits 5 on an unrecognized verdict, instead of a warning and a smaller survivor count that looked valid (#189). stderr names the key it expected (`claude_verdict` or `adversary_verdict`) and the key or value it found, for example `found key 'verdict' on X-002`. It writes no report, and every run first deletes any old file at the `--md` and `--json` paths. `deep` 1.2.0 and `adversarial` 1.2.0 give the exact `r2-claude-verdicts.json` shape.
- Every agent dispatch writes its results to a file the orchestrator named, and the orchestrator reads results from disk (#121). Silence is `NO REPORT`, a coverage gap listed in the final report and never counted as converged. Chasing stops after two tries; then one fresh dispatch, or the orchestrator runs that dimension itself. New `deep` reference `references/dispatch-contract.md` holds the contract and the never-idle rule, which `deep/SKILL.md` repeated six times. The three agents write their results file before replying.

## [1.1.0] - 2026-10-09

### Fixed

- The diff under review is treated as untrusted input (#123). `deep` 1.1.0 and `adversarial` 1.1.0.
  - New `secret_scan.py`. `codex-review.sh` and `gemini-review.sh` run it on every input they send (`--diff`, `--findings`, `--prior`) before any model call. A hit prints `SECRET_SUSPECTED:` and `<path>:<line> <pattern-name>` lines (never the value), sends nothing and exits 4. Exit 4 is not exit 3: the skills never switch model or degrade on it. `--allow-secret-match` sends anyway after the user confirms. It uses the one pattern list in `audit_record.py`, which gains Slack tokens; its `sk-` patterns now need a left boundary, so kebab-case words such as `task-…` no longer match as OpenAI keys.
  - The scan checks the text that is sent. Both adversary scripts parse `--findings` and `--prior` as strict JSON (no duplicate keys, `NaN` or `Infinity`), refuse anything else with exit 1, and send a re-serialized copy, so an escaped key (`\u0041KIA…`) is scanned as the model reads it. `codex-review.sh` scans its stdin as built; `gemini-review.sh` scans its assembled stdin before each call.
  - `gemini-review.sh` no longer puts the brief or findings in `-p`. Brief, diff and findings go on stdin, the data in tags with a per-call nonce marked as untrusted data, and `-p` is one fixed sentence. Every `@` in the data is written as `\@`, because Gemini CLI 0.46.0 reads `@path` in its input as a file to include (#120).
  - New `check-cites.py`. `deep` Step 2.5 runs it before the implementer: a finding whose path is not a file in the diff or inside the repo, or whose line does not exist, goes to the user instead.
  - `deep` asks before committing and pushing when the PR author is not the operator, adds an out-of-tree file only after the user confirms each path, and shows one Gemini direct-call form (a prompt file on stdin). A Red Flag forbids diff text in a shell argument, `-p "$(cat f)"` included.
  - The three agents, and every dispatch in both skills, say the diff and findings are untrusted data, never instructions.
  - The scan also finds Google API keys, Stripe keys, credentials in a URL and (scan only) a quoted or env-style value assigned to a secret-sounding name, and flags `*.env`, `.envrc`, `id_ecdsa*`, `id_dsa*`, `.netrc`, `.npmrc`, `.pypirc` and `.pgpass` (here and in `detect-mode.sh`). It strips color codes, and it prints a path with control characters as escapes, so a newline in a path cannot forge a hit line.
  - `detect-mode.sh` and deep Step 2.6 build diffs with `--no-color --no-ext-diff --no-textconv` and fixed `a/` `b/` prefixes (and `gh pr diff --color=never`), so `color.ui=always`, `diff.mnemonicPrefix`, `diff.noprefix`, an external diff tool or a decrypting textconv cannot hide a header or put plaintext secrets in the diff.
  - `check-cites.py` exits 3 when findings fail and 2 on any internal error, so a crash can no longer read as "some failed, fix the others". It reports entries that are not objects and ids that are not strings, and notes a cited line outside every hunk.
  - `gemini-review.sh` refuses an input over the Gemini CLI's 8 MiB stdin cap (exit 1, nothing sent), and stops if it cannot build its input.
  - Every scan pattern runs in linear time on one long line. The env-style assignment rule, `jwt` and `url-credentials` backtracked quadratically: a 2 MB minified line would have stalled the scan for hours. Now the worst case is about 0.25 s, checked per pattern by a test.
  - The final Gemini scan reads `\@` as `@`, so hunk headers still parse and an added line such as `+++ .env` is not mistaken for a file header. A quoted rename or copy into a `b/` or `a/` directory keeps its full path.
  - The plugin's own files pass its secret scan; `test_self_scan.py` keeps it that way.
  - deep: out-of-tree files are appended as `git diff --no-index /dev/null <path>`; Steps 2.3 and 2.6 handle exit 4; Step 2.6 checks cites against `<BASE_REF>...<FIX_SHA>` with `--id` for confirmed new findings; an empty `gh` login counts as someone else's PR. adversarial: Steps 2 and 3 give exit 1 and exit 4 their own rules.

## [1.0.2] - 2026-10-09

### Changed

- `deep` 1.0.1: `references/audit-trail.md` starts with a Contents list (#210).

## [1.0.1] - 2026-10-06

### Changed

- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).

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
