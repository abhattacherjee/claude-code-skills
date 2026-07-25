# Changelog

All notable changes to spec-implement are documented here.

## [1.0.0] - 2026-07-25

Initial plugin release.

### Added

- `spec-implement` skill published as a marketplace plugin (#59).
- Bundled `references/delegated-verification.md` so the delegated-work
  verification step resolves without the `ship` skill installed.

### Fixed

- Script invocations use bare-relative `scripts/` paths rather than
  `~/.claude/skills/spec-implement/scripts/`.
- Prefixed skill-owned script invocations with `./` and added a "Path
  convention" note after the title clarifying they resolve against this
  skill's base directory, not the Bash tool's working directory (#59).
- Delegation matrix and Phase 3 now reference `Skill(superpowers:brainstorming)`
  (its real registered name) instead of the unqualified `Skill(brainstorming)` (#59).
- Tightened the "Path convention" note to also cover `./references/…` paths
  explicitly (previously only `./scripts/…` was called out, leaving bare
  `references/...` references ambiguous between skill-relative and
  target-project meanings) and prefixed the `references/delegated-verification.md`
  reference in Phase 4 accordingly (#59).
- Replaced the per-row `ui-from-requirements` "requires a separately installed
  skill" caveats in the Skill Delegation Matrix and Phase 3 with a single
  blanket note above the matrix and in See Also, and reworded the frontmatter
  description to say the skill "optionally delegates" to separately-installed
  skills — the per-row caveats had landed inconsistently, appearing at some
  call sites but not others (#59, #60).
- Reworded a hardcoded `SendMessage your final result to main` instruction in
  `references/delegated-verification.md` to `the orchestrator that dispatched
  you`, since `main` is one workspace's orchestrator name, not universal (#60).
- Restored the optional-external-plugin caveat at the Phase 3 execution site
  (the previous round's blanket note above the matrix left Phase 3, the actual
  invocation point, with no caveat of its own), and narrowed the matrix-level
  note's wording from "All skills in this matrix" to "Every `Skill(...)`
  referenced in this matrix" so it no longer implies the built-in `Agent`
  tool (also a matrix row) is an optional external plugin (#59, #60).
