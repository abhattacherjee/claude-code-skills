# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own `CHANGELOG.md` within its directory.

Format: Monorepo-level events only. For per-skill change details, see `<skill>/CHANGELOG.md`.

## [1.11.1] - 2026-02-28

### Added

- sync skill-publishing plugin to v3.5.0 (auto GitHub releases)

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.11.0] - 2026-02-28

### Added

- auto-create GitHub releases in release-monorepo.sh

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.3] - 2026-02-28

### Changed

- add conversation-search ↔ context-shield cross-references

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.2] - 2026-02-28

### Added

- v1.3.0 — 6 new common patterns and expanded triggers

### Changed

- add bidirectional context-shield cross-references across skills

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.1] - 2026-02-28

### Changed

- sync context-shield plugin to v1.2.0 (auto-ralph)

### Fixed

- preserve plugin CHANGELOGs like READMEs + enrich bare-bones entries

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.2.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.2.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed for large workloads.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.0] - 2026-02-28

### Added

- auto-detect ralph-loop for large workloads (v1.2.0)

### Fixed

- unbound variable with empty array under set -u

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.2.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.9.0] - 2026-02-28

### Added

- add figma-ui-designer as bare skill (+ agents)

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.8.1] - 2026-02-28

### Changed

- bump skill-publishing to v3.4.0 (agent auto-discovery in sync)

### Fixed

- auto-discover agents from plugin-manifest.json in bare skill sync
- include content-distiller agent in context-shield bare skill

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.8.0] - 2026-02-28

### Added

- add context-shield skill and plugin (v1.1.0)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.3.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.7.0] - 2026-02-28

### Added

- re-assemble skill-authoring & skill-publishing plugins with enriched READMEs
- rich plugin README generation (v3.3.0)

### Changed

- replace barebones figma-ui-designer README with enriched version

### Fixed

- remove stale build/ artifacts, add --exclude='build' to rsync

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.3.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.6.1] - 2026-02-28

### Added

- add agent cross-reference validation to validate-plugin.sh (v3.2.3)
- add figma-ux-expert agent to figma-ui-designer plugin

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.3 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.6.0] - 2026-02-28

### Added

- v3.1.0 — UX expert agent for brainstorming
- add figma-ui-designer plugin v3.0.0

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.3] - 2026-02-27

### Changes

- Sync all plugins with source CHANGELOGs

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.2] - 2026-02-27

### Fixed

- preserve plugin CHANGELOG.md during sync, bash 3.2 compat

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.1] - 2026-02-27

### Fixed

- preserve plugin READMEs during --add-plugin sync

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.0] - 2026-02-27

### Changes

- Sync skill-publishing v3.2.0: auto-sync on publish

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.1] - 2026-02-27

### Changed

- enrich plugin READMEs with detailed feature descriptions and usage

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.0] - 2026-02-27

### Added

- add skill-authoring and skill-publishing as plugins

### Changed

- remove stale individual repo links for skill-authoring and skill-publishing

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.3.0] - 2026-02-27

### Added

- add interactive publishing flow with target selection

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.1] - 2026-02-27

### Added

- add plugin marketplace support

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.0] - 2026-02-27

### Added

- add plugin support + git-flow plugin (skill-publishing v3.0.0)

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.1.2] - 2026-02-24

### Fixed

- sync changelog-keeper v1.1.1 + release-monorepo.sh newline fix

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.1] - 2026-02-24

### Added

- sync validate-skill.sh with version-mismatch check

### Changed

- sync skill-authoring v2.1.0 CHANGELOG entry
- sync changelog-keeper v1.1.0 — multi-script CHANGELOG coordination

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.0] - 2026-02-24

### Added

- `worktree` v1.0.0 — creates isolated git worktrees for parallel Claude Code sessions
- `claudeception` v3.2.0 — extracts reusable knowledge from work sessions into skills
- `changelog-keeper` v1.0.0 — keeps CHANGELOG.md up to date from git commit history
- `release-monorepo.sh` — versioned release workflow with semver tags (patch/minor/major)
- Contribution workflow for all repos: CONTRIBUTING.md, PR template, CI validation, branch protection rulesets
- "Install all skills" section in monorepo README

### Changed

- CHANGELOG rewritten as audit log (was duplicating per-skill changelogs on every sync)
- `sync-monorepo.sh` generates compact skill inventory instead of dumping full per-skill changelogs
- `sync-individual-repos.sh` skips READMEs with custom sections (preserves claudeception fork attribution)
- `skill-authoring` v2.0.0 → v2.1.0 (added `((var++))` bash pitfall docs)
- `skill-publishing` v2.0.0 → v2.1.0 (added release-monorepo.sh, Workflow D)

### Fixed

- `validate-skill.sh` — `((var++))` arithmetic bug with `set -e`, missing `--help` flags
- `sync-monorepo.sh` — copy local READMEs instead of generating generic ones
- Restored `claudeception/README.md` with original fork attribution and research references

### Skill Inventory (7 skills)

- `changelog-keeper` v1.0.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history by topic, date, branch, or project
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices
- `skill-publishing` v2.1.0 — Publishes skills to GitHub repos and monorepo with versioned releases
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions

## [1.0.0] - 2026-02-24

### Added

- Initial monorepo with 3 skills:
  - `conversation-search` v1.1.0 — searches Claude Code conversation history
  - `skill-authoring` v2.0.0 — creates and optimizes Claude Code skills
  - `skill-publishing` v2.0.0 — publishes skills to GitHub repos and monorepo
- Auto-generated root README with skill catalog table
- MIT license
