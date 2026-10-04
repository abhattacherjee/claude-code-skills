# dev-flow

Two skills for the daily git loop, in one install. `worktree` gives each parallel Claude Code session its own directory and branch, and `changelog` writes CHANGELOG.md entries from your commit history.

```shell
/plugin install dev-flow@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/dev-flow:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `worktree` | `worktree` | Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch. Worktrees are siblings of the repo (`../repo-name--branch-suffix/`). Lists, creates and removes them, and prints the `cd` + `claude` command to start a session there. |
| `changelog` | `changelog-keeper` | Keeps CHANGELOG.md up to date by generating categorized entries from git commit history. Conventional commit prefixes (`feat:` to Added, `fix:` to Fixed and so on) first, then file paths for commits with no prefix. Outputs Keep-a-Changelog format. |

### Use `worktree` when

- you say `/worktree`,
- you want to work on several branches at once,
- two Claude Code sessions are fighting over the same branch,
- you want to set up parallel development.

A branch checked out in one worktree cannot be checked out in another (git enforces this). Each worktree has its own `node_modules`, and the script installs them. A worktree has no Python virtualenv, so run the project's own setup first and check that imports resolve inside the worktree.

### Use `changelog` when

- you ask to update the changelog,
- you are about to commit a change that should be documented,
- you are preparing a release and need entries,
- you ask what changed since the last release.

`changelog` always previews first (`--dry-run`), then writes the `[Unreleased]` section or a versioned entry (`--version X.Y.Z`). It also covers keeping several scripts that write the same CHANGELOG from overwriting each other.

```shell
/dev-flow:worktree create a new branch story-10.12 and a worktree for it
/dev-flow:changelog what changed since v1.0.0?
```

## Scripts

Each skill's commands run its own script through `${CLAUDE_SKILL_DIR}`, so they work from your project directory. You normally do not run them yourself.

| Skill | Script | Purpose |
|---|---|---|
| `worktree` | `setup-worktree.sh list\|create [--new]\|remove\|install` | Manages the worktrees of the repo you are in. |
| `worktree` | `validate-skill.sh <skill-dir>` | Same validator as the repo root. |
| `changelog` | `update-changelog.sh [--dry-run] [--since REF] [--version X.Y.Z] [repo-dir]` | Builds the changelog entry from git history. |
| `changelog` | `validate-skill.sh <skill-dir>` | Same validator as the repo root. |

## Install and uninstall

Install the plugin; do not copy the skills by hand. A loose copy breaks the `${CLAUDE_SKILL_DIR}` paths and shadows the plugin.

```shell
/plugin marketplace add abhattacherjee/claude-code-skills
/plugin install dev-flow@claude-code-skills
/plugin uninstall dev-flow@claude-code-skills
```

If you used the old names, install `dev-flow` first, then remove the old `worktree` and `changelog-keeper` copies so they cannot win a plain-language request.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
