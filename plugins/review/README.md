# review

<!-- plugin-meta:start -->
**Version:** 1.3.1 · **2** skills · **3** agents · **0** commands
<!-- plugin-meta:end -->

Two review skills in one install. `deep` converges a changeset to zero actionable issues in two phases. `adversarial` is the single-pass version: Claude and an opposing model (Codex, else Gemini) find issues independently, cross-examine each other, and only findings the other side confirms are reported.

```shell
/plugin install review@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/review:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `deep` | `deep-review` | Two phases. Phase 1: specialised reviewers in fix and re-review rounds until a full round finds nothing actionable. Phase 2: a multi-round cross-examination with the opposing model (it finds, Claude judges, it counters, it re-checks each fix). Every confirmed finding is fixed and verified. |
| `adversarial` | `adversarial-review` | One pass of the cross-examination: independent discovery (R1), then each side judges the other's findings (R2). The opposing model is Codex, else Gemini. Only findings it confirms survive. |

Use `adversarial` for a high-precision look before merge, or when Copilot is unavailable and you want a non-Claude second opinion. Use `deep` when the change is high-stakes and you want it ironclad. `deep` runs the same scripts as `adversarial`, from the same plugin.

## Agents

Dispatched by both skills as `review:<agent>`. They are not user-invocable.

| Agent | Was | Model | Role |
|---|---|---|---|
| `bug-hunter` | `adversarial-bug-hunter` | Opus | R1 bug hunt over the diff, grounded in the actual source. |
| `convention-reviewer` | `adversarial-convention-reviewer` | Sonnet | R1 convention, CLAUDE.md and maintainability scan. |
| `cross-examiner` | `adversarial-cross-examiner` | Opus | R2 cross-examiner. Reads the adversary's (Codex or Gemini) R1 findings against the source and returns confirm or refute verdicts. |

## How `adversarial` works

```
detect-mode → R1 parallel independent discovery → R2 parallel symmetric cross-examination → synthesize → sink
```

1. **R1, independent discovery (parallel, blind).** Two Claude sub-agents (`bug-hunter` on Opus, `convention-reviewer` on Sonnet) review the diff grounded in the source. Their findings become `r1-claude.json`. At the same time the adversary's script (`codex-review.sh` or `gemini-review.sh`) runs its own pass, and its findings become `r1-codex.json` or `r1-gemini.json`. Neither side sees the other's output.
2. **R2, symmetric cross-examination (parallel).** `cross-examiner` reads the adversary's R1 findings against the source and returns verdicts (`r2-claude-verdicts.json`). At the same time the adversary judges Claude's R1 findings (`r2-<adversary>-verdicts.json`).

### Survivor rule

- A finding survives only when the other side confirms it.
  - A Claude finding (C-NNN) needs the adversary's confirmation in R2.
  - An adversary finding (X-NNN for Codex, G-NNN for Gemini) needs Claude's confirmation in R2.
- Findings the other side did not judge go to the `UNCONFIRMED (single-model)` bucket, shown below the survivors and never dropped.
- Rejected findings are kept with the model that refuted them and its reason.
- `synthesize.py` applies the rule mechanically, with no further adjudication.

### Modes

- **PR mode** (a PR exists for the current branch): reviews `gh pr diff`, then saves the exchange on the PR. There is one thread per finding, the opposing model's verdict is a reply, refuted threads are resolved, and one summary review is posted. `--no-post` skips posting.
- **Local mode** (no PR found): reviews the working tree against the merge base with the base branch: committed, staged and unstaged changes to tracked files. Your index is not touched. The base is `--base <branch>` if you pass it, else a guess from the branch prefix (`feature/*` to `develop`, `release/*` and `hotfix/*` to `main`, else the repo default). A guessed base that does not exist falls back to the repo default branch with a note on stderr; if no base exists the run stops. Untracked files are left out and listed on stderr (paths only), because the diff is sent to the adversary model (Codex or Gemini) and an untracked file may hold a secret. `--include-untracked` adds them, but files named like secrets (`.env`, `.env.*`, `*.env`, `.envrc`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `id_dsa*`, `*credentials*`, `*.p12`, `*.pfx`, `.netrc`, `.npmrc`, `.pypirc`, `.pgpass`) are never sent. It prints a terminal report and writes a gitignored `<branch>.adversarial-review.md` file.

### Degradation

If the adversary is not logged in, errors, times out, or returns unparseable JSON after one retry, the skill falls back to a Claude-only review and prints a loud `ADVERSARY UNAVAILABLE — single-model review only` banner. The second opinion is never skipped silently.

## How `deep` works

- **Phase 1** dispatches the `pr-review-toolkit` reviewers (code, tests, silent failures, types, comments) in fix and re-review rounds. It stops when every dimension returns CONVERGED in the same round, after the latest fix. If that plugin is missing, it falls back to `feature-dev:code-reviewer`, `Explore` or a `general-purpose` reviewer.
- **Targets:** the open PR's diff if the branch has one, else the working tree.
- **Phase 2** runs the `adversarial` engine with extra rounds. R3 sends each refuted finding back to its originator to concede or defend, and direct source evidence settles factual disputes. With Codex, step 2.6 has Codex re-check each fix, so fixed threads close. Genuine judgment calls go to you.
- **No usable adversary:** `deep` asks you to set one up or go on Claude-only. In Claude-only mode a second independent Claude agent judges the first's findings, with a loud banner that cross-model confirmation was skipped.
- **Tiered lane (opt-in, `--lane tiered`).** A cheaper flow for the same job. Round 1 runs two Claude reviewers on Sonnet (`bug-hunter` and `convention-reviewer`, which now carry the code, test, silent-failure, comment and type checks) next to a Codex find pass. The Opus `cross-examiner` only judges Codex's findings and breaks ties. One Sonnet fix wave follows, then Codex re-checks the fix range, and a clean re-check is the sign-off. When Codex is unavailable, Gemini does those jobs, sign-off included. A Claude-only run says "Not signed off" on its first line. A diff of only lockfiles or docs takes a light path: green CI plus one adversary pass. Manifests such as `package.json` can carry scripts, so they take the full path. Steps T0–T6 are in `skills/deep/references/tiered-lane.md`. The default stays `--lane legacy` (today's flow) until a replay on past PRs passes.
- Flags: `--phase1-only`, `--phase2-only`, `--max-rounds N`, `--no-post`, `--adversary codex|gemini`, `--lane tiered|legacy`, and a PR number or `local`.
- Every round of both phases is saved on the PR with `pr-audit.py`. See `skills/deep/references/audit-trail.md`.

## Prerequisites

The skills pick **Codex** first when `codex login status` says you are logged in (run `codex login` once), then Gemini, then Claude-only. `--adversary codex|gemini` forces one, and a forced adversary that is not usable stops the run. Codex runs in a locked-down `codex exec`; see the `adversarial` skill's "Codex sandbox" section for what that does and does not stop.

The Gemini notes below apply when Gemini is the adversary. The skill detects and guides setup at the start of every run through `ensure-gemini.sh` and Step 0:

- **Not installed:** the skill tells you what is missing, shows the install command (`npm install -g @google/gemini-cli`) and asks whether to run it. If you decline or the install fails, it goes on Claude-only with a loud banner.
- **Installed but not authenticated:** the skill asks for a headless-capable credential. Interactive `gemini` Google login is not enough, because the headless calls (`gemini-review.sh` runs `gemini -o json` with all input on stdin) need a `GEMINI_API_KEY` or Vertex AI credentials. Recommended: add `GEMINI_API_KEY=<key>` to `~/.gemini/.env`, which the gemini CLI loads in every shell, sub-agents included. Get a key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey). `export GEMINI_API_KEY=<key>` also works for the current session. If you decline, it goes on Claude-only.
- **Auth state unknown** (installed, no detectable headless credential): the skill goes on and relies on the runtime guard in `gemini-review.sh` (exit 3) to catch a failure.
- **Installed and authenticated:** no questions.

No manual pre-flight is needed; the check runs at the start of every run.

The `gemini` binary at version 0.38.2 or later supports headless use. `gemini-review.sh` runs `gemini -o json` with all input on stdin and a fixed `-p` sentence.

## Contents

- **2** skills, **0** commands, **3** agents

### Scripts (in `skills/adversarial/scripts/`)

- `ensure-gemini.sh`: Step 0 detection. Prints `KEY=VALUE` status lines (installed, version, authed, install hint, auth hint). It never installs anything and never calls the network.
- `ensure-codex.sh`: Codex install and login detection (the exit code of `codex login status`). It never installs anything. `CODEX_STALE=yes|no|unknown` compares `codex --version` with `client_version` in `${CODEX_HOME:-~/.codex}/models_cache.json` and with the codex bundled in the ChatGPT app. An app binary that exists but gives no version makes it `unknown`, never `no`. `CODEX_STALE_HINT` gives the fix. It is an `ln -sfn` command only when `codex` is a symlink into the standalone installer's `${CODEX_HOME:-~/.codex}/packages/` or to the app binary, and the app is the newest source. npm and Homebrew also install `codex` as a symlink, so any other `codex` gets "update that install, or reorder `PATH`", and a cache newer than the app gets the version to update to. When Codex rejects a model as "not supported when using Codex with a ChatGPT account", `codex-review.sh` exits 3 and says the CLI looks stale.
- `pick-adversary.sh`: picks Codex, then Gemini, then Claude-only. `--adversary` forces one.
- `codex-review.sh`: Codex's find, judge and counter passes, and re-checks, in a locked-down `codex exec`. Exit 4 (`SECRET_SUSPECTED`) means the secret scan hit an input and nothing was sent; `--allow-secret-match` sends anyway after the user confirms. A content refusal by Codex is still exit 3, with the stderr prefix `ADVERSARY_REFUSED:` in place of `ADVERSARY_UNAVAILABLE:`; `deep` then falls back to a Gemini sweep at a re-check, in auto mode when Gemini is set up.
- `gemini-review.sh`: `--mode find` is Gemini's independent R1 pass. `--mode judge` is its R2 cross-examination of Claude's findings. It extracts JSON from the CLI envelope and retries once on a parse failure. The diff and findings go on stdin only, in nonce-tagged blocks marked as untrusted data, with every `@` written as `\@` so the Gemini CLI does not read it as a file include. Exit 4 works as for `codex-review.sh`. Each `gemini` call has a time limit (`--timeout`, else `GEMINI_REVIEW_TIMEOUT`, else 540 s); a call past it is killed with its process group, and the script exits 3 without a retry. In find mode the script numbers the findings `G-001`, ... itself; `--id-start <n>` starts at `G-<n>`. `--prior <round.json>` (find mode only) re-checks an earlier round against a fix range and returns `prior_status` for each Gemini and Claude finding.
- `run_bounded.py`: runs one command in its own process group with a time limit and kills the whole group when it runs over. `gemini-review.sh` runs `gemini` through it, because macOS has no `timeout` or `setsid`.
- `secret_scan.py`: scans files for secret formats and secret-looking file names in diff headers. Prints `<path>:<line> <pattern-name>`, never the value. Exit 0 clean, 4 hit, 2 unreadable. Both adversary scripts run it on their inputs before any model call.
- `check-cites.py`: checks that each finding's path is a file in the diff, inside the repo, and that its line exists. `deep` runs it before an implementer acts on the survivors. Exit codes: 0 all passed, 3 some failed, 2 unreadable input or an internal error. A cited line outside every hunk passes with a `note:` on stderr.
- `detect-mode.sh`: resolves PR or local mode and writes the shared diff that both models read. `--base <branch>` sets the local base; `--include-untracked` adds untracked files, minus secret-looking names.
- `synthesize.py`: applies the survivor rule to the four symmetric inputs (Claude findings, adversary findings, adversary verdicts, Claude verdicts) and sorts findings into SURVIVORS, UNCONFIRMED and REJECTED. `--match` labels findings both sides raised (same path and category, lines within 3) with `raised_by_both` and `matched_with`. The label never changes a status: every finding is still judged.
- `lane_scope.py`: the tiered lane's size gate. `--files <list>` prints `light` only when every changed path is a lockfile or a doc (under `docs/`, only doc and image files count). `requirements*.txt` (it can install from a URL), dependency manifests, and anything in a dot directory, `prompts/` or `rules/` are full, as are agent instruction files (`SKILL.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, anything under `agents/`, `skills/` or `commands/`). Anything else prints `full`.
- `sink.sh`: delivers the report. It posts the PR audit trail in PR mode, and prints the terminal report and writes the markdown file in local mode.
- `pr-audit.py`: the PR audit trail. Both skills use it, and `deep` uses it for every round. `recheck --gemini-sweep` records a Gemini sweep after Codex refused a re-check, and closes no Codex thread. `recheck --adversary gemini` records the tiered lane's Gemini re-check: it closes resolved Gemini and Claude findings, never Codex's.
- `run-tests.sh` and the `test_*.py` files: the test suite. `test_skill_paths.py` checks that every command in the skills spells out its script path.

## Installation

### Via Claude Code (recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install review@claude-code-skills
```

### Via the command line

```bash
claude plugin install review@claude-code-skills
```

Install only through `/plugin` or `claude plugin install`. There is no script or manual copy install for this plugin: the repo's install script and a hand copy put skills and agents loose into `~/.claude`, which breaks the `review:*` agent names, and `deep` runs the scripts in `skills/adversarial/scripts/` through `${CLAUDE_PLUGIN_ROOT}`, so the skills and agents must be installed together as the plugin.

## Uninstall

```bash
# Via Claude Code
/plugin uninstall review@claude-code-skills

# Via the command line
claude plugin uninstall review@claude-code-skills
```

## Moving from the old plugins

The old `deep-review` and `adversarial-review` plugins were removed in v4.0.0. Install `review`, then uninstall both old plugins if you still have them, so the old names cannot win a plain-language request. Round-record files written by the old skills (for example a `round-N.json` reused with `recheck --prior`, or a Step 5 rerun) carry the skill values `deep-review` and `adversarial-review`; the scripts still read them.

## See also

- `code-review` skill: the built-in all-Claude breadth review (no adversary; use it for full coverage rather than precision).
- `pr-review-toolkit:review-pr`: the per-dimension reviewers that `deep` Phase 1 drives.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
