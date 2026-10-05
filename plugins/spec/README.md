# spec

Three skills for story specs in one install. `create` writes the spec, `review` checks it against the real code, and `implement` builds it.

```shell
/plugin install spec@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/spec:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `create` | `spec-creator` | Writes a story spec file from a Claude plan, a requirements file, a prompt or a GitHub issue, with TDD implementation steps, success metrics and a Figma mockup gate for UI stories (needs `ui-design:figma`). Finds the project's spec conventions at run time, brainstorms approaches with you (and recommends vertical splitting for large stories), writes a spec that follows the template, checks it for over-engineering, and can hand off to `spec:review`. |
| `review` | `spec-review` | Reviews and enriches an existing story spec. Verifies the spec's claims against the codebase, checks architecture alignment, then runs four parallel analyses and adds implementation-ready sub-tasks, a current-codebase-state section, design simplification notes and an API test plan. It reviews a spec, not code or a pull request; use the `review` plugin for those. |
| `implement` | `spec-implement` | Builds a created and reviewed spec end-to-end: reads the spec, creates a feature branch, implements the sub-tasks with progress tracking, validates build, lint and acceptance criteria, updates tracking files and opens a PR. For complex UI work it can hand off to separately installed brainstorming, frontend-design and ui-from-requirements skills. |

The usual order is `create`, then `review`, then `implement`.

### Use `create` when

- you want to write a new story spec,
- you are turning a plan or requirements into a formal spec,
- you are creating specs from GitHub issues,
- you are breaking a large feature into shippable vertical slices.

### Use `review` when

- a new story spec needs review before implementation,
- a spec has high-level tasks but lacks implementation-ready detail,
- you need to check a spec's assumptions against the codebase,
- a spec changes an API but has no test plan,
- a spec mentions data shapes or pipeline ordering,
- sub-tasks say "add field X to object Y" or "call function at line N".

`review` has two parts. Part 1 is a codebase verification checklist you can use on its own. Part 2 is the full planning workflow: discover and extract (scripts), parallel analysis by four agents, synthesis, and a report.

How the full workflow runs:

1. **Discover and extract.** Two scripts find the project's architecture and pull out the spec sections the agents need.
2. **Four agents run at once**, all launched in a single message:

   | Agent | Looks at | Catches |
   |---|---|---|
   | Codebase Verifier | File paths, function names, data shapes | Made-up module names, wrong line numbers, missing exports |
   | Architecture Reviewer | Layer boundaries found in your project | Layer violations, data flowing the wrong way, missing steps |
   | Design Simplifier | The spec's technical design (checked against `references/design-simplification-checklist.md`) | Over-engineering, needless abstractions, redundant wrappers |
   | Test Plan Extractor | Acceptance criteria | Scenarios with no test, incomplete assertions |

   The first three agents need the separately installed `feature-dev` plugin. Without it, `review` uses a general-purpose agent in their place and says so.
3. **Synthesis.** The results are merged and the changes are written into the spec file.

What `review` can add to the spec:

- a "Current Codebase State" section: what exists, what to change and what to create, with verified paths,
- detailed sub-tasks (file, function, change, verification command, dependencies, size),
- "Design Simplification Notes", each with the current approach, the simpler one and why,
- an API test plan in the format your project already uses (Bruno `.bru` files, Postman collections, plain HTTP files or unit-test specs), shown only when the spec touches an API,
- an implementation readiness score out of 25.

### Use `implement` when

- you say `/spec:implement` or "implement this spec",
- a spec has been created and reviewed and is ready to build,
- you give a spec file path to implement.

`implement` has eight phases (plus 4b for UI-heavy specs), a skill delegation matrix and an error recovery table.

## Scripts

Each skill's commands run its own scripts through `${CLAUDE_SKILL_DIR}`, so they work from your project directory. You normally do not run them yourself.

| Skill | Script | Purpose |
|---|---|---|
| `create` | `discover-conventions.sh <project-root> [--json]` | Finds the project's spec conventions (spec directory, epic layout, numbering). Text report, or JSON with `--json`. |
| `create` | `task-manifest.sh <workflow>` | Task list for `single-story` or `vertical-split`. |
| `review` | `discover-project-architecture.sh <project-root> [--json]` | Finds the project's architecture at run time. The result goes to the architecture reviewer. |
| `review` | `extract-spec-sections.sh <spec-file> [--json]` | Pulls the sections of a spec that the reviewers need. |
| `review` | `task-manifest.sh <workflow>` | Task list for `full-review` (used by `SKILL.md`) or `quick-check` (verification only; `SKILL.md` does not use it). |
| `implement` | `task-manifest.sh <workflow>` | Task list for `standard` or `ui-heavy`. |

## Tests

`tests/` has smoke tests for every script, run from a project directory the way the skills call them. They also run every script command written in the three `SKILL.md` files:

```bash
bash plugins/spec/tests/run-tests.sh
```

## Installation

### Via Claude Code (recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install spec@claude-code-skills
```

### Via the command line

```bash
claude plugin install spec@claude-code-skills
```

Install only through `/plugin` or `claude plugin install`. There is no script or manual copy install for this plugin. A hand copy (for example `cp -r plugins/spec/skills/* ~/.claude/skills/`) puts the skills loose into `~/.claude`, where `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` no longer point at the plugin and the `spec:*` names do not exist. It also shadows the plugin.

## Uninstall

```bash
# Via Claude Code
/plugin uninstall spec@claude-code-skills

# Via the command line
claude plugin uninstall spec@claude-code-skills
```

## Moving from the old plugins

The old `spec-creator`, `spec-review` and `spec-implement` plugins are deprecated and stay published for one more release. Install `spec`, then uninstall all three, so the old names cannot win a plain-language request.

## See also

These are separate skills and may not be installed with this plugin.

- `review:deep` and `review:adversarial`: code and pull request review. `spec:review` is for specs only.
- `skill-kit:author`: how these skills were built.
- `context:shield`: use it when a spec points at many external docs that need reading.
- `git-flow:finish`: merges the feature branch after the PR is approved.
- `ui-from-requirements`: the full UI build pipeline for complex specs.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
