# Plugin-only monorepos (#190)

A plugin-only monorepo has `plugins/*/.claude-plugin/plugin.json` and no top-level skill directory. Its skills live at `plugins/<plugin>/skills/<name>/`, and you edit them in place. `claude-code-skills` is one. Here `sync-monorepo.sh` never writes anything but the catalogue.

## Modes

| Mode | What it does |
|---|---|
| plain | Runs `validate-plugin.sh` on every plugin. Any failure: exit 1, nothing written. Then `catalogue.py` writes the catalogue. |
| `--dry-run` | The same validation, then `catalogue.py` with `--check`. Prints the drift and writes nothing. |
| `--add-plugin <name>` | Validates `./build/<name>/`, then validates every plugin and runs `catalogue.py` with `--check` on a staging copy with the build in it. Only if that passes does it copy the build to `plugins/<name>/` and write the catalogue. `--dry-run --add-plugin` runs the same checks. |
| `--skills`, `--add`, `--init` | Refused: exit 1, nothing written. |
| `--json` | Prints one JSON object on stdout: `{"layout": "plugin-only", "validated": N, "catalogue": "written"}`. `catalogue` is `"written"`, `"clean"`, `"drift"`, or `"not-run"` when the run stopped before `catalogue.py` ran (a refusal, a failed validation, or a missing or unreadable standalone list); a failed run adds `"error"`. The log goes to stderr. `--json` is refused in other layouts. |

Plugins listed in `scripts/standalone-plugins.txt` ship from their own marketplace and are skipped. A missing or unreadable list stops the run.

A sync exits 1 when a plugin fails validation or when `catalogue.py` cannot run (for example, the README has no catalogue markers, or a `plugin.json` has no description). These are all checked before the first write (with an `--add-plugin` build, on a staging copy), so nothing is written. A `catalogue.py` that crashes counts as "cannot run", never as drift. Only a failure while writing can leave a partial result: `catalogue.py` writes each file to a temp file first and names any file it already replaced. A sync also exits 1 when some drift needs a hand edit (a plugin README that does not name one of its skills or agents); it says whether it wrote the catalogue first.

`validate-pre-sync.sh` runs the same plugin validation and `catalogue.py` with `--check`, and exits 1 if either fails. `--add` is refused there too.

## The catalogue

`catalogue.py` writes three things, and each `plugin.json` is their only source:

- the root README plugin table, between `<!-- catalogue:start -->` and `<!-- catalogue:end -->` (text outside the markers is never touched);
- `.claude-plugin/marketplace.json`'s `plugins[]` (every other key, such as `owner` and `metadata`, is kept);
- one meta line in each plugin README, between `<!-- plugin-meta:start -->` and `<!-- plugin-meta:end -->` (a README with no markers gets them after its first `# ` heading).

Run it yourself after you change a `plugin.json` (the command is in the note at the top of `SKILL.md`). With `--check` it writes nothing and reports drift: exit 0 clean, 1 drift, 2 cannot run.

Both modes also check what a write cannot fix: each plugin README must name each of its skills and agents (as inline code `` `name` ``, as `<plugin>:name` or as `/name`; a plain word does not count), and the README's `/plugin install` lines must use this marketplace. `--validate-plugins` only loads and checks every plugin and write target, without the README markers; the sync runs it before its first write in the other layouts.

## Other layouts

A new or empty directory, or a monorepo with top-level skills, takes the old sync flow. There too `catalogue.py` writes the README plugin table and `marketplace.json`, after the README is generated, and is copied into the monorepo's `scripts/` for its CI (which skips the check when there is no `plugins/`). The sync runs `catalogue.py` with `--validate-plugins` before its first write and again before the README, so a plugin it would refuse stops the run early. If both a skill is refused (exit 3) and the catalogue needs a hand edit, both are reported and the exit is 3. `--init` does not initialise the repository while the catalogue needs a hand edit. Known limit: this layout always names the marketplace `claude-code-skills` when it creates `marketplace.json`, as the README template does throughout.
