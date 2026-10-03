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

`install` and `create` write `~/.claude/statusline-command.sh` (or `create --output PATH`). Every script they write carries `# managed-by: statusline-plugin` on line 2.

- An existing script without that line is yours: they leave it untouched and exit 3. Pass `--force` to replace it.
- Any file they replace, script or `settings.json`, is first copied to `<file>.bak-<UTC time>`.
- Writes go to a temp file in the same directory, then `mv`, so a failed write (disk full, no permission) leaves the old file in place.
- A `settings.json` that is not one JSON object stops the install before anything is written (exit 2). A symlinked `settings.json` is updated through its link.

Exit codes for both: 0 done; 1 failed (a write failed, `jq` is missing, or `settings.json` cannot be read; a file that was not written is unchanged); 2 bad input; 3 refused. The guard lives in `lib/write-statusline.sh`.

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
