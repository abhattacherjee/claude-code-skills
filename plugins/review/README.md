# review

Two review skills in one install. `deep` converges a changeset to zero actionable issues in two phases. `adversarial` is the single-pass version: Claude and an opposing model (Codex, else Gemini) find issues independently, cross-examine each other, and only findings both confirm are reported.

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

Use `adversarial` for a high-precision look before merge. Use `deep` when the change is high-stakes and you want it ironclad. `deep` runs the same scripts as `adversarial`, from the same plugin.

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

- A Claude finding (C-NNN) survives only if the adversary confirmed it in R2.
- An adversary finding (X-NNN for Codex, G-NNN for Gemini) survives only if Claude confirmed it in R2.
- All other findings go to the `UNCONFIRMED (single-model)` bucket, shown below the survivors and never dropped.
- Rejected findings are kept with the model that refuted them and its reason.
- `synthesize.py` applies the rule mechanically, with no further adjudication.

### Modes

- **PR mode** (a PR exists for the current branch): reviews `gh pr diff`, then saves the exchange on the PR. There is one thread per finding, the opposing model's verdict is a reply, refuted threads are resolved, and one summary review is posted. `--no-post` skips posting.
- **Local mode** (no PR found): reviews `git diff <base>...HEAD` against the working tree, prints a terminal report and writes a gitignored `<branch>.adversarial-review.md` file.

### Degradation

If the adversary is not logged in, errors, times out, or returns unparseable JSON after one retry, the skill falls back to a Claude-only review and prints a loud `ADVERSARY UNAVAILABLE — single-model review only` banner. The second opinion is never skipped silently.

## How `deep` works

- **Phase 1** dispatches the `pr-review-toolkit` reviewers (code, tests, silent failures, types, comments) in fix and re-review rounds. It stops when every dimension returns CONVERGED in the same round, after the latest fix. If that plugin is missing, it falls back to `feature-dev:code-reviewer`, `Explore` or a `general-purpose` reviewer.
- **Phase 2** runs the `adversarial` engine with extra rounds. R3 sends each refuted finding back to its originator to concede or defend, and direct source evidence settles factual disputes. With Codex, step 2.6 has Codex re-check each fix, so fixed threads close. Genuine judgment calls go to you.
- Flags: `--phase1-only`, `--phase2-only`, `--max-rounds N`, `--no-post`, `--adversary codex|gemini`, and a PR number or `local`.
- Every round of both phases is saved on the PR with `pr-audit.py`. See `skills/deep/references/audit-trail.md`.

## Prerequisites

The skills pick **Codex** first when `codex login status` says you are logged in (run `codex login` once), then Gemini, then Claude-only. `--adversary codex|gemini` forces one, and a forced adversary that is not usable stops the run. Codex runs in a locked-down `codex exec`; see the `adversarial` skill's "Codex sandbox" section for what that does and does not stop.

The Gemini notes below apply when Gemini is the adversary. The skill detects and guides setup at the start of every run through `ensure-gemini.sh` and Step 0:

- **Not installed:** the skill tells you what is missing, shows the install command (`npm install -g @google/gemini-cli`) and asks whether to run it. If you decline or the install fails, it goes on Claude-only with a loud banner.
- **Installed but not authenticated:** the skill asks for a headless-capable credential. Interactive `gemini` Google login is not enough, because the headless calls (`gemini -p ... -o json`) need a `GEMINI_API_KEY` or Vertex AI credentials. Recommended: add `GEMINI_API_KEY=<key>` to `~/.gemini/.env`, which every shell loads, sub-agents included. Get a key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey). `export GEMINI_API_KEY=<key>` also works for the current session. If you decline, it goes on Claude-only.
- **Auth state unknown** (installed, no detectable headless credential): the skill goes on and relies on the runtime guard in `gemini-review.sh` (exit 3) to catch a failure.
- **Installed and authenticated:** no questions.

The `gemini` binary at version 0.38.2 or later supports `gemini -p "<prompt>" -o json` for headless use.

## Contents

- **2** skills, **0** commands, **3** agents

### Scripts (in `skills/adversarial/scripts/`)

- `ensure-gemini.sh`: Step 0 detection. Prints `KEY=VALUE` status lines (installed, version, authed, install hint, auth hint). It never installs anything and never calls the network.
- `ensure-codex.sh`: Codex install and login detection (the exit code of `codex login status`). It never installs anything.
- `pick-adversary.sh`: picks Codex, then Gemini, then Claude-only. `--adversary` forces one.
- `codex-review.sh`: Codex's find, judge and counter passes, and re-checks, in a locked-down `codex exec`.
- `gemini-review.sh`: `--mode find` is Gemini's independent R1 pass. `--mode judge` is its R2 cross-examination of Claude's findings. It extracts JSON from the CLI envelope and retries once on a parse failure.
- `detect-mode.sh`: resolves PR or local mode and writes the shared diff that both models read.
- `synthesize.py`: applies the survivor rule to the four symmetric inputs (Claude findings, adversary findings, adversary verdicts, Claude verdicts) and sorts findings into SURVIVORS, UNCONFIRMED and REJECTED.
- `sink.sh`: delivers the report. It posts the PR audit trail in PR mode, and prints the terminal report and writes the markdown file in local mode.
- `pr-audit.py`: the PR audit trail. Both skills use it, and `deep` uses it for every round.
- `run-tests.sh` and the `test_*.py` files: the test suite. `test_skill_paths.py` checks that every command in the skills spells out its script path.

## Installation

### Via Claude Code (recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install review@claude-code-skills
```

### Via script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/review
rm -rf /tmp/ccs
```

There is no manual copy of the skills alone: `deep` runs the scripts in `skills/adversarial/scripts/` through `${CLAUDE_PLUGIN_ROOT}`, so the skills and agents must be installed together as the plugin.

## Uninstall

```bash
# Via Claude Code
/plugin uninstall review@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/review
rm -rf /tmp/ccs
```

## Moving from the old plugins

The old `deep-review` and `adversarial-review` plugins are deprecated and stay published for one more release. Install `review`, then uninstall both old plugins, so the old names cannot win a plain-language request. Old PR comments carry the skill values `deep-review` and `adversarial-review`; the scripts still read them.

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
