# Contributing to {{REPO_NAME}}

Thank you for your interest in contributing! This guide covers the workflow for submitting changes.

## Getting Started

1. **Fork** this repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/{{REPO_NAME}}.git
   cd {{REPO_NAME}}
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b my-change
   ```

## Making Changes

{{CONTRIBUTING_SCOPE}}

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
{{VALIDATE_COMMAND}}
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
