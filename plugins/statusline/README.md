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
