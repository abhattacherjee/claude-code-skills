# review: treat the diff as untrusted input — Implementation Plan

> **For agentic workers:** one implementation pass, TDD task by task, one commit per task. Review happens once on the whole branch.

**Goal:** the diff under review is third-party text. It must not reach a shell argument, it must be marked as data for every model that reads it, nothing that looks like a secret leaves the machine without the user's say-so, and no finding reaches the committing implementer unless its `file:line` checks out.

**Issue:** #123 (written against the old `deep-review` layout). Related: #120 (Gemini CLI `@` file includes).

**Layout now:** one skill copy, `plugins/review/skills/deep/SKILL.md`. Scripts in `plugins/review/skills/adversarial/scripts/`, agents in `plugins/review/agents/`. The "both copies of SKILL.md" criterion has one copy to update.

## Global Constraints
- Fake secrets in tests are built by string concatenation (`"AKIA" + "EXAMPLE..."`), as `test_audit_record.py` does, so `scripts/pre-commit.sh` does not flag the test files. No literal `private_key`, no `.pem`/`.key` fixture names.
- Tests never call a real `gemini` or `codex`; both are stubbed.
- `deep/SKILL.md` body stays under 500 lines (`./scripts/validate-skill.sh plugins/review/skills/deep`). Detail goes in `deep/references/untrusted-input.md`.
- Bash 3.2 compatible scripts. Stage named paths. `./scripts/commit-preflight.sh` before every commit.

## Corrections to the approved brief
1. The shared secret patterns live in `audit_record.py` (`SECRET_PATTERNS`, used by `redact()`), not `codex_review.py`. `secret_scan.py` imports them from there, and Slack tokens are added to that one list.
2. `audit_record.py`'s `openai-key` pattern has no left boundary, so `task-`, `risk-`, `desk-` followed by 20 kebab-case characters matched. On a diff that is a false `SECRET_SUSPECTED` stop. Both `sk-` patterns get a left boundary.
3. `gemini-review.sh` has no `--prior`; only `codex-review.sh` takes it. The Gemini scan covers `--diff` and `--findings`.
4. Gemini CLI 0.46.0 (`packages/cli/src/gemini.tsx`, `nonInteractiveCli`) builds its input as `stdin + "\n\n" + -p`, then runs `handleAtCommand` on the whole thing. So any `@path` in the diff or the findings is read from the workspace and sent to Google (#120). That is egress the secret scan never sees. `gemini-review.sh` writes every `@` in the data blocks as `\@` (the CLI's escape: `(?<!\\)@`) and tells the model so.
5. The secret-file-name list already exists in `detect-mode.sh` (`SECRET_NAME_GLOBS`, bash). `secret_scan.py` keeps a Python copy, and a test fails if the two lists differ.

## Tasks
1. **`secret_scan.py`** — scans files for `audit_record.SECRET_PATTERNS` and for diff headers naming a secret-looking file. Prints `<path>:<line> <pattern-name>`, never the value. Exit 0 clean, 4 match, 2 usage or unreadable input. Tests first (`test_secret_scan.py`).
2. **Scan before egress** — `codex_review.py` and `gemini-review.sh` scan every input they will send (diff, `--findings`, `--prior`) before any model call. A match prints `SECRET_SUSPECTED:` and exits 4; `--allow-secret-match` continues. Exit 4 is never treated as exit 3 (no Codex-to-Gemini switch, no Claude-only degrade).
3. **Gemini stdin** — brief, findings and diff go on stdin in nonce-tagged blocks; `-p` gets one fixed constant. Stub test records argv and stdin.
4. **`check-cites.py`** — for each selected finding, `path` must be a new-side file in the diff, inside the repo, and `line` (when set) must exist in the current file. Exit 0 / 1 / 2. Tests first.
5. **Docs** — `deep/SKILL.md`: R1/R2 dispatch marks the diff as untrusted, out-of-tree files need per-path confirmation, Step 2.5 runs `check-cites.py` and asks the user before commit and push when the PR author is not the operator, the Gemini fallback shows only the stdin form, a Red Flag forbids diff text in a shell argument. `adversarial/SKILL.md`: exit 4 handling, untrusted dispatch. Agents: an untrusted-input rule. New `deep/references/untrusted-input.md`.
6. **Versions** — `review` 1.1.0, `deep` 1.1.0, `adversarial` 1.1.0; plugin, skill and root CHANGELOGs; README via `catalogue.py`.

## Acceptance criteria → evidence
- No `-p "<…>"` form with diff or finding text in SKILL.md → doc test.
- Red Flag forbids diff text in a shell argument and names `-p "$(cat f)"` → doc test.
- Diff delimited and labelled untrusted in R1 and R2 → doc tests + agent files + Gemini stdin test.
- Every finding's `file:line` checked before the implementer → `check-cites.py` + tests + Step 2.5 doc test.
- Step 2.5 confirmation when PR author is not the operator → doc test.
- Secret scan over the assembled diff before egress, can stop the run → `secret_scan.py` tests + codex/gemini gating tests.
- Out-of-tree files need explicit confirmation → doc test.
- One SKILL.md copy updated, plugin version bumped → manifests, CHANGELOGs, `catalogue.py`.

## Out of scope (named, not done)
- Running Gemini from an empty temp dir with a scrubbed env (issue #123 comment of 2026-10-04, item 1) and Codex home isolation (item 2).
- Local mode building its diff from a committed range only (issue #123 comment, suggested extra criterion). The secret scan now covers unstaged content, which was the risk named there.
