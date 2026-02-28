# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-02-28

### Added

- **Auto-detect ralph-loop mode** — automatically determines whether to use direct processing (≤2 batches) or ralph-loop (>2 batches) based on source count and batch size
- **Large Website / Documentation Site pattern** — new common pattern for breaking a single large site into section URLs with auto-ralph activation
- **Enhanced When to Use table** — added auto-ralph signals and large documentation site trigger

### Fixed

- **Unbound variable with empty arrays** — `manage-manifest.sh` crashed under `set -u` when `local_args` array was empty. Fixed with safe expansion pattern `${array[@]+"${array[@]}"}`

## [1.1.0] - 2026-02-28

### Added

- **Manifest-driven batch processing** — `manage-manifest.sh` script for creating, tracking, and collecting content distillation work across batches
- **Visualization system** — `visualize.sh` shows animated progress of agents being dispatched, working, and returning through the context boundary
- **Content-distiller agent** — isolated sub-agent that reads one source (URL, Figma, file, wiki, codebase) and returns a ~500-token distilled summary
- **Ralph-loop integration** — hand off multi-batch processing to `/ralph-loop` for fresh context per iteration
- **Five source types** — `url`, `figma`, `file`, `wiki`, `codebase` with type-specific reading strategies
- **Common patterns** — Figma design analysis, competitor research, GitHub wiki crawl

### Included

- **1 skill**: `context-shield`
- **1 agent**: `content-distiller`
- **2 scripts**: `manage-manifest.sh`, `visualize.sh`
