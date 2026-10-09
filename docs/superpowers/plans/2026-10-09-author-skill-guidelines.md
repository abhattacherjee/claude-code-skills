# skill-kit:author follows Anthropic's skill authoring guidelines — Implementation Plan

> **For agentic workers:** one implementation pass, TDD task by task, one commit per task. Review happens once on the whole branch.

**Goal:** `validate-skill.sh` enforces the size, reference and name rules from Anthropic's skill authoring best practices, in step with `scripts/check-skill-structure.py`, and `skill-kit:author` teaches the four rules it is missing.

**Issue:** #214. **Guide:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

**Architecture:** `validate-skill.sh` stays a dependency-free bash script (it ships to published skill repos and runs without Python). Its new checks port the rules of `check-skill-structure.py` (S1 size, S2 named-or-read, S3 Contents list). A parity test runs both on one fixture set and asserts identical verdicts, so the two cannot drift.

## Global Constraints
- `validate-skill.sh` has 7 byte-identical copies: `scripts/validate-skill.sh` and `plugins/{context/skills/search,dev-flow/skills/changelog,dev-flow/skills/worktree,skill-kit/skills/author,skill-kit/skills/extract,skill-kit/skills/publish}/scripts/validate-skill.sh`. `plugins/skill-kit/tests/run-tests.sh:107` and `scripts/test-validate-plugin.sh:110` enforce this. Edit the root copy, then copy it to the other six.
- Bash 3.2 compatible (CI runs a bash 3.2 job). No Python in `validate-skill.sh`.
- Exit codes stay 0 pass, 1 fail, 2 usage.
- Every changed plugin (context, dev-flow, skill-kit) gets a CHANGELOG entry and the version bump the validators require; root CHANGELOG `[Unreleased]` entry.
- Stage named paths; `./scripts/commit-preflight.sh` before every commit.

## Review Focus
1. A body of exactly 500 lines must fail (today `≤500` passes).
2. S2 must match the exact path or basename with boundaries, as `check-skill-structure.py` does after #215: `references/x.md.bak`, `other/./references/x.md` and a script naming `x.md.bak` do not count.
3. S3 must ignore `## Contents` inside a fenced block, and must not treat a ```` ```inline``` ```` line as a fence.
4. Names containing `claude` or `anthropic` as a substring (e.g. `headless-claude-job-hardening`) fail; names that merely resemble them do not.
5. Nothing in the repo's 25 plugin skills starts failing CI because of the new checks.

---

### Task 1: S1 — body under 500 lines
- Change the body check from `-le 500` to `-lt 500`, message "body: N lines (must be under 500)". Update the usage text.
- Test (`plugins/skill-kit/tests/run-tests.sh`): a fixture with a 500-line body fails; 499 passes.

### Task 2: name rules
- Fail a `name` longer than 64 characters (keep the existing charset check), and a `name` containing `anthropic` or `claude` (case-insensitive).
- Tests: 64 passes, 65 fails; `my-claude-helper` fails; `anthropic-tools` fails; `clad-tools` passes.

### Task 3: S2 and S3 — reference files
- For every `*.md` under the skill directory except `SKILL.md`, `README.md` and `CHANGELOG.md` (any depth): fail unless SKILL.md names its relative path (bare, `./`-prefixed or `${CLAUDE_SKILL_DIR}/`-prefixed) or a file under the skill's `scripts/` names its basename, each match bounded so a longer path or name does not count.
- For each such file over 100 lines: fail unless a `## Contents` or `## Table of contents` heading appears in its first 30 lines outside a fenced block. Fence rule: a line starting with up to 3 spaces then ```` ``` ```` (with no further backtick on the line) or `~~~` opens or closes a fence.
- Tests: one planted violation per rule, plus the boundary cases from Review Focus 2 and 3.

### Task 4: parity with check-skill-structure.py
- Add a case to `scripts/test-check-skill-structure.sh` that builds a fixture set (pass and fail cases for S1, S2, S3, including every boundary case above), runs `scripts/check-skill-structure.py` and `scripts/validate-skill.sh` on it, and asserts both reach the same verdict for each fixture and rule.
- Mutation-check: break one rule in either script and the parity case goes red.

### Task 5: copies, guidance, versions
- Copy the root validator to the six skill copies.
- `skill-kit:author` SKILL.md (body now 424 lines; keep it under 500): add, once each and in the right step, gerund naming (`processing-pdfs`; avoid `helper`, `utils`), justified constants (every value in a script carries a reason), the `head -100` reason for one-level references, and evaluations first (three scenarios against a no-skill baseline before extensive docs). Make `references/quality-checklist.md` match the new validator rules.
- Run every repo validator over all 25 plugin skills; all must pass.
- CHANGELOG entries and version bumps for context, dev-flow and skill-kit; root CHANGELOG.
