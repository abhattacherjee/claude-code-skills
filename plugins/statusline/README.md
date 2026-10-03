# statusline

Claude Code statusline skills in one install: install a ready-made adaptive statusline, build your own from composable items, or check how full the context window is.

```shell
/plugin install statusline@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/statusline:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `install` | `install-statusline` (plugin `custom-statusline`) | Installs the 3-tier adaptive statusline: model, folder, git branch with sync status, color-coded context bar. |
| `create` | `statusline-creator` | Generates a statusline script from 20 composable items (model, dir, git, cost, duration, context-bar and more). |
| `context-bar` | `context-bar` | Prints a one-off, color-coded bar of how much context the current session has used. |

The three old plugins all wrote `~/.claude/statusline-command.sh` or read the session transcript; they were one feature split three ways. `context-bar` stays its own skill because it is a one-off check, not a statusline. Its old `statusline-command.sh` variant is gone: `create` builds the same bar with its `context-bar` item.

## Your own statusline is safe

`install` and `create` write `~/.claude/statusline-command.sh` (or `$CLAUDE_CONFIG_DIR/statusline-command.sh`, or `create --output PATH`). Every script they write carries `# managed-by: statusline-plugin` on line 2.

- An existing script without that line is yours: they leave it untouched and exit 3. Pass `--force` to replace it.
- Any file they replace, script or `settings.json`, is first copied to `<file>.bak-<UTC time>`.
- Writes go to a temp file in the same directory, then `mv`, so a failed write (disk full, no permission) leaves the old file in place.
- A `settings.json` that is not one JSON object stops the install before anything is written (exit 2). A symlinked `settings.json` is updated through its link.

Exit codes for both: 0 done; 1 failed (a write failed, `jq` is missing, or `settings.json` cannot be read; a file that was not written is unchanged); 2 bad input; 3 refused. The guard lives in `lib/write-statusline.sh`.

## Security: what a repo can make git run

The statuslines run git on every prompt, in whatever repo the session is in. A repo you cloned or unpacked can carry config and attributes that make git run its own programs. Every git call the shipped statuslines (`install`'s script, `create`'s generated scripts and the recipes in `item-recipes.md`) make goes through `_git`, which is `GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL=none git --no-pager -c core.fsmonitor=false -c core.untrackedCache=false -c protocol.allow=never --no-optional-locks`. "Probed" means a test or probe set the vector up, saw plain git run it, and saw the statusline not run it.

| git call | What a repo could make it run | How it is closed |
|---|---|---|
| every call | `core.fsmonitor` hook | `-c core.fsmonitor=false` |
| every call | `core.pager`, `pager.<cmd>` | `--no-pager`; the output is never a terminal anyway |
| every call | lazy fetch of missing objects in a partial clone, through the remote's transport (`ext::`, `core.sshCommand`, remote helpers) | No transport can start on any git version: `GIT_ALLOW_PROTOCOL=none` allows no protocol and overrides the repo's own `protocol.<name>.allow` (which beats `-c protocol.allow=never`, also set). On top: `GIT_NO_LAZY_FETCH=1` (git 2.44+), and `unsafe_repo` skips status and diff in any partial clone. Probed with `ext::` and with `ssh` plus `core.sshCommand`, without the other two guards. |
| `status --porcelain --ignore-submodules=all` (install) | `filter.<name>.clean` / `.process` | `unsafe_repo` skips the call when a filter is defined in any scope but global or system, including `include.path` and worktree config, or when the config lookup fails. Probed. |
| same | the `post-index-change` hook (an index refresh write) | `--no-optional-locks`: no index write. Probed. |
| same | a submodule's own fsmonitor or filters, which `unsafe_repo` never sees | `--ignore-submodules=all`. Probed. |
| `diff [--cached] --numstat --ignore-submodules=all --no-textconv --no-ext-diff` (create, recipes) | filters, submodules, lazy fetch | as above. Probed. |
| same | `diff.external`, `diff.<driver>.textconv` / `.command` | `--no-ext-diff --no-textconv`. `--numstat` never called them in the probe; the flags make that explicit. |
| `config --includes --show-scope --get-regexp` | none: includes and `includeIf` only read files | a failed lookup skips the counts |
| `rev-parse --git-dir`, `rev-parse --abbrev-ref @{upstream}`, `branch --show-current` | none: they read `HEAD` and refs | Probed with hooks, filters, a pager and an `ext::` remote set up: nothing ran. |
| `rev-list --count` | none: walks commits, which a partial clone always has | Probed. |
| `remote get-url origin` (create's `git-link`) | none: prints config and never connects | Probed with an `ext::` URL. |

None of these commands runs hooks other than `post-index-change`, uses credentials or `askpass`, or starts `gc --auto` / maintenance.

## Install preview

```
Opus 4.6 | 📁 my-project | 🌿 develop(⇡⇣) | 🧠 ●●●●●●●●●○○○○○○○○○○○○○○○○ 36%
```

On a narrow terminal the same statusline moves the branch and the bar onto their own lines.

## Uninstall

```shell
/plugin uninstall statusline@claude-code-skills
```

This leaves `~/.claude/statusline-command.sh` and the `statusLine` entry in `~/.claude/settings.json` in place. Delete the script and the entry by hand to remove the statusline itself.

## Contents

- **3** skills (`install`, `create`, `context-bar`), **0** commands, **0** agents

## License

[MIT](LICENSE)
