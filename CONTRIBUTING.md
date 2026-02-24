# Contributing to claude-code-skills

Thank you for your interest in contributing! This guide covers the workflow for submitting changes.

## Getting Started

1. **Fork** this repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/claude-code-skills.git
   cd claude-code-skills
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b my-change
   ```

## Making Changes

### Adding a new skill

1. Create a new directory at the repo root (e.g., `my-skill/`)
2. Add a `SKILL.md` with valid YAML frontmatter
3. Optionally add `scripts/` and `references/` directories

### Improving an existing skill

- Edit the skill's `SKILL.md` to improve instructions or metadata
- Add or improve scripts in the skill's `scripts/` directory
- Add or update reference material in the skill's `references/` directory
- Fix bugs or improve documentation

### Quality Requirements

Every skill must pass validation before merge:

| Requirement | Rule |
|-------------|------|
| `SKILL.md` exists | At the skill root with YAML frontmatter |
| `name` | Lowercase + hyphens, ≤64 characters |
| `description` | ≤1024 chars, third person, includes "Use when:" |
| `metadata.version` | Valid semver (X.Y.Z) |
| Frontmatter fields | Only `name`, `description`, `metadata` allowed |
| Body length | ≤500 lines |
| Scripts | Executable, `#!/usr/bin/env bash` shebang, `--help` flag |

### Local Validation

Run the validation script before pushing:

```bash
scripts/validate-skill.sh <skill-directory>
```

## Submitting a Pull Request

1. **Push** your branch to your fork:
   ```bash
   git push origin my-change
   ```
2. **Open a Pull Request** against `main` on this repository
3. **Fill out the PR template** — describe your change and confirm the checklist
4. **Wait for CI** — the `validate` check must pass
5. **Address review feedback** if any

## PR Review

- PRs require 1 approval + passing CI before merge
- The maintainer may suggest changes or ask questions
- Keep PRs focused — one logical change per PR

## Code of Conduct

Be respectful and constructive. We're all here to build useful tools.

## Questions?

Open an issue if you have questions about contributing.
