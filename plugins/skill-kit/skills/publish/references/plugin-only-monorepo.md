# Plugin-only monorepos (#190)

A plugin-only monorepo has `plugins/*/.claude-plugin/plugin.json` and no top-level skill directory. Its skills live at `plugins/<plugin>/skills/<name>/`, and you edit them in place. `claude-code-skills` is one. Here `sync-monorepo.sh` never writes anything but the catalogue.

## Modes

| Mode | What it does |
|---|---|
| plain | Runs `validate-plugin.sh` on every plugin. Any failure: exit 1, nothing written. Then `catalogue.py` writes the catalogue. |
| `--dry-run` | The same validation, then `catalogue.py` with `--check`. Prints the drift and writes nothing. |
| `--add-plugin <name>` | Validates `./build/<name>/` and every plugin, copies the build to `plugins/<name>/`, then writes the catalogue. |
| `--skills`, `--add`, `--init` | Refused: exit 1, nothing written. |
| `--json` | Prints one JSON object on stdout: `{"layout": "plugin-only", "validated": N, "catalogue": "written"}` (or `"clean"`, or `"drift"`), plus `"error"` when the run fails. The log goes to stderr. `--json` is refused in other layouts. |

Plugins listed in `scripts/standalone-plugins.txt` ship from their own marketplace and are skipped. A missing list stops the run.

A sync exits 1, with nothing written, when a plugin fails validation or when `catalogue.py` cannot run (for example, the README has no catalogue markers, or a `plugin.json` has no description). It also exits 1 after writing the catalogue when some drift needs a hand edit: a plugin README that does not name one of its skills or agents.

`validate-pre-sync.sh` runs the same plugin validation and `catalogue.py` with `--check`, and exits 1 if either fails. `--add` is refused there too.

## The catalogue

`catalogue.py` writes three things, and each `plugin.json` is their only source:

- the root README plugin table, between `<!-- catalogue:start -->` and `<!-- catalogue:end -->` (text outside the markers is never touched);
- `.claude-plugin/marketplace.json`'s `plugins[]` (every other key, such as `owner` and `metadata`, is kept);
- one meta line in each plugin README, between `<!-- plugin-meta:start -->` and `<!-- plugin-meta:end -->` (a README with no markers gets them after its first `# ` heading).

Run it yourself after you change a `plugin.json` (the command is in the note at the top of `SKILL.md`). With `--check` it writes nothing and reports drift: exit 0 clean, 1 drift, 2 cannot run.

`--check` also checks what it cannot write: each plugin README must name each of its skills and agents, and the README's `/plugin install` lines must use this marketplace.

## Other layouts

A new or empty directory, or a monorepo with top-level skills, takes the old sync flow. There too `catalogue.py` writes the README plugin table and `marketplace.json`, after the README is generated, and is copied into the monorepo's `scripts/` for its CI.
