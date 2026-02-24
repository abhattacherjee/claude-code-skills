# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own CHANGELOG.md within its directory.
## [2026-02-24] — Monorepo sync

Synced 5 skills from local source.

### changelog-keeper

## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`

### claudeception

## [3.2.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`

### conversation-search

## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option


## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`

### claudeception

## [3.2.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`

### conversation-search

## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option


## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`

### claudeception

## [3.2.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`

### conversation-search

## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option


## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`

### claudeception

## [3.2.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`

### conversation-search

## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option


## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`

### conversation-search

## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option


## [1.1.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — full skill definition covering conversation search workflow:
  - Natural language to script flag mapping
  - Step-by-step workflow (parse query, present results, show detail, summarize)
  - Quick reference with all commands and options
  - Tips for session ID prefix matching, date formats, large conversations
  - Integration with `conversation-summarizer` agent for AI-powered summaries
- **scripts/search-conversations.sh** — the search engine:
  - `list` — list recent conversations across all projects
  - `search` — search by topic, date range, branch, project (index-based, fast)
  - `search --deep` — full-text search inside JSONL conversation content
  - `show` — display verbatim conversation content with metadata
  - `stats` — conversation statistics
  - Session ID prefix matching (8-character shorthand)
  - JSON output mode for agent consumption
  - Colored terminal output with `NO_COLOR` support

### skill-authoring

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands

### skill-publishing

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option
