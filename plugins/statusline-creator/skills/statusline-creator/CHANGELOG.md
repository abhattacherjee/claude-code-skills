# Changelog

## [1.0.1] - 2026-10-06

### Changed

- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).
- plugin.json carries the "Deprecated: …" description that only marketplace.json had (#190).

## [1.0.0] - 2026-03-14

### Included

- Composable statusline items: model, dir, git branch, git sync, context bar, cost, duration
- `generate-statusline.sh` script with `--items`, `--lines`, `--install` options
- `generate-output.py` for Python-based output formatting
- JSON schema reference for all available statusline data fields
- Item recipes reference with copy-paste snippets
- Adaptive multi-line support for narrow terminals (iPhone/tablet)
