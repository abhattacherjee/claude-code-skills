# claude-code-skills

A monorepo of reusable Agent Skills and Plugins for Codex. Each skill lives
in a plugin, at `plugins/<group>/skills/<name>/`.

## Git Flow Rules

- Never commit directly to `main` or `develop` — use feature branches
- Branch naming: `feature/*`, `release/*`, `hotfix/*`
- Features branch from and merge to `develop`
- Releases branch from `develop`, merge to both `main` and `develop`
- Hotfixes branch from `main`, merge to both `main` and `develop`
- Run `./scripts/commit-preflight.sh` before every commit
- Git Flow slash commands are provided by the installed [`git-flow`](https://github.com/abhattacherjee/git-flow) plugin under the `git-flow:` namespace: `git-flow:feature`, `git-flow:release`, `git-flow:hotfix`, `git-flow:finish`, `git-flow:flow-status`

## Validation

- `scripts/validate-skill.sh` and `scripts/validate-plugin.sh` validate skill/plugin
  structure; the same checks run in CI via `.github/workflows/validate-skill.yml`
- Run validation before opening a PR
