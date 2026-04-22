# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.4.1] - 2026-04-22

### Fixed
- `/recall` Step 4 could silently close still-open items when Claude's paraphrased candidate presentation didn't match the candidate's actual text. Approval now lands on the verbatim text that will be matched on disk, and each candidate's source line is Read-verified before any Edit. Closes #47.

### Changed
- `/recall` Step 4 now uses Claude Code's native `AskUserQuestion` multi-select picker when ≤4 checkoff candidates are surfaced. At >4 candidates, the text prompt still applies but now shows each candidate's verbatim `- [ ] <text>` line and `file:line` anchor so users can verify before confirming. Items skipped due to source drift are excluded from the cascade step. (See #47.)

## [2.4.0] - 2026-04-21

### Added
- **ci**: `scripts/ci-checks/no-default-db.py` — AST-based guard that fails CI when any call to `ensure_index()`, `rebuild_index()`, or `deep_analysis_pipeline()` inside `tests/` omits `db_path=`. Wired as the `no-default-db-check` job in `.github/workflows/ci.yml` with a 2-minute timeout. Exit 1 on violations, exit 2 on script malfunction (missing dir, unreadable file, syntax error) so CI logs can distinguish the two. `# noqa: no-default-db` marker on any line of a multi-line call span suppresses. `**kwargs` expansion emits a stderr warning so reviewers can verify forwarding callers (GH #46)
- **snapshots**: First-class mid-session checkpoint support. Snapshots now carry `status: auto-logged` (or `summarized`) and `source_session_note` wikilink frontmatter, use seconds-resolution filenames (`-snapshot-HHMMSS`), and are AI-summarized lazily at `/recall` time alongside session notes via a dedicated snapshot prompt
- **session-end**: Threshold bypass — writes the session note even when the transcript is below `min_turns`/`min_duration_minutes` if sibling snapshots exist, so every snapshot has a navigable parent anchor. Emits a `snapshots: [...]` list when siblings are present
- **recall**: `_augment_session_input_with_snapshots()` prepends snapshot summary bodies to the session summarization input so the generated summary describes the full pre- and post-compact arc cohesively
- **recall**: Nested `↳ HH:MM:SS` snapshot rows in the session history table; `LOAD_MANIFEST` surfaces `snapshot_count` and per-snapshot summaries at auto-load depth
- **vault-index**: `log_access()` cascades snapshot accesses to the parent session via a single `executemany`, preventing hot snapshots from outranking their own parent under activation scoring
- **obsidian_utils**: Public helper `fetch_snapshot_summaries(sessions_folder, session_id, date, project)` returning ordered snapshot dicts for presentation reuse across skills; `find_snapshots_for_session()` promoted to public API
- **vault-stats**: `## Snapshots` section — trigger breakdown (compact/clear/auto), sessions-with-snapshots, max snapshots per session, orphan and broken-backlink counters, summarization fraction
- **emerge**: `--include-snapshots` opt-in flag. `collect_vault_corpus()` gains `include_types` / `exclude_types` kwargs (default excludes `claude-snapshot` so mid-session "Key context" bullets don't dilute cross-session pattern synthesis); `run_corpus` cache key includes `include_snapshots` to prevent shape-mismatch returns
- **check-items**: `collect_open_items()` filters to `type: claude-session` (legacy notes without a `type:` field preserved as sessions); snapshot bullets no longer produce false-positive open-item proposals
- **vault-search**: Session hits annotate with `· 📸 N` marker and list snapshots as nested `↳ HH:MM:SS` rows; snapshot hits annotate with `→ [[parent-stem]]`; loading a snapshot pick opens the parent session at session-depth (body + all snapshot summaries)
- **vault-ask**: Synthesis pool includes parent session body for snapshot hits and snapshot summaries for session hits, so answers reflect the full session arc rather than the post-compact tail; snapshot citations accompany parent-session wikilinks
- **config**: `/vault-config` and `/obsidian-setup` warn when `snapshot_on_clear` or `snapshot_on_compact` is set to `false`
- **vault-doctor**: `snapshot-integrity` check module (Phase B) — 5 integrity checks for snapshot notes: `snapshot-orphan` (warn), `snapshot-broken-backlink` (fix), `session-snapshot-list-stale` (fix), `session-snapshot-list-missing` (fix), `snapshot-summary-status-mismatch` (fix). All fix paths are idempotent, short-circuit to `status="skipped"` when the write is a no-op, only mutate inside the YAML frontmatter block (body-level `status:` / `source_session_note:` lines in code blocks or headings are left untouched), and normalise CRLF + UTF-8 BOM on read. Inline-list YAML (`snapshots: [...]`) parsed defensively to avoid string-iteration foot-guns (GH #57)
- **vault-doctor**: `snapshot-migration` check module (Phase C) — 4 ordered idempotent legacy-backfill checks: `snapshot-legacy-filename` (rename `-snapshot.md` → `-snapshot-HHMMSS.md` using file mtime, with collision guard and vault-wide `[[old-stem]]` wikilink rewrite rooted at the resolved vault path so sibling `insights/` and `decisions/` folders are reached even when `sessions_folder` is nested), `snapshot-missing-status` (add `status: auto-logged` or `summarized` based on `## Summary` presence; defensive idempotency re-check against stale Issue replays), `snapshot-missing-backlink` (compute parent stem from `date + slugify(project) + sha256(session_id)[:4]` and write `source_session_note` wikilink when parent exists on disk), `session-missing-snapshots-list` (backfill `snapshots:` block on parent sessions; regex constrained to frontmatter so body-level `status:` lines are never matched). `apply()` processes checks in fixed order, renames files FIRST and rolls back on wikilink-rewrite failure, and forwards both renamed paths AND renamed stems to later checks so the session's backfilled `snapshots:` list points at the POST-rename filename (GH #58)
- **vault-doctor**: skill version bumped `1.0.0 → 1.2.0` with new `--check snapshot-integrity` and `--check snapshot-migration` invocations documented

- **vault-index**: Phase 2 theme engine — `themes`, `theme_members`, and `term_df` tables; `tfidf_vector` JSON column on `notes` (auto-migrated on first `ensure_index()` call)
- **vault-index**: `_tokenize_for_tfidf()`, `_compute_tfidf_vector()` (smoothed IDF), `_cosine_similarity()` for sparse dict vectors, `_update_term_df()` for incremental IDF maintenance
- **vault-index**: `assign_to_theme()` — incremental cosine-similarity clustering after note summarization; notes joining a theme update its centroid via running average under a BEGIN IMMEDIATE transaction so concurrent callers cannot clobber each other
- **vault-index**: `detect_surprise()` — negation-proximity contradiction score persisted on `theme_members.surprise` for Phase 4 retrieval boosting
- **recall**: `upgrade_note_with_summary()` now re-indexes the summarized note, runs incremental theme assignment, and persists a surprise score when the note joins a theme. All theme-side errors are non-fatal — the note upgrade itself is never rolled back by a theme-pipeline failure
- **obsidian-setup**: Step 8.7 Performance Dependencies — optional `numpy`/`scipy` install prompt with idempotent persistence (`optional_deps_prompted`, `optional_deps_declined` config fields); `/obsidian-setup --deps` re-triggers the prompt
- **config**: `check_optional_deps()` returns import-availability for numpy and scipy

### Changed
- **pre-compact hook**: filename pattern extends from `-snapshot.md` to `-snapshot-HHMMSS.md` so multiple `/compact` events in one session no longer collide on write
- **obsidian_session_log**: writes `snapshots: [...]` back-reference list when sibling snapshots exist for this `session_id` (bidirectional link surface)
- **recall**: Replace sub-agent batch summarization (Wave 1-2-3) with parallel Haiku pipelines; sub-agents demoted to per-note fallback only
- **vault-index**: `search_vault()` and `query_related_notes()` now batch their access-log writes via `executemany` on the existing connection (1 commit instead of N, Phase 1 Copilot review deferred item)
- **vault-reindex**: Now **non-destructive by default** — preserves `access_log` (ACT-R activation history), `themes`, and `theme_members` (cluster centroids + surprise scores) while reconciling the note index with current vault contents via incremental `_sync`. Rows whose paths fall outside the current scanned folders are cleaned up (pytest fixture pollution); orphaned access-log and theme-member rows referencing notes no longer on disk are pruned, and `themes.note_count` is recomputed with zero-member themes dropped. Opt into `/vault-reindex --full` for the previous destructive behavior (full DB delete + rebuild from empty schema). `rebuild_index()` gains a `full: bool = False` kwarg and emits `preserved` / `pruned_orphans` fields in its stats dict. Skill version 1.0.0 → 2.0.0

### Fixed
- **recall**: Step 2 Phase 1 now dispatches a single Bash tool call into a Python `upgrade_batch()` helper that fans out Haiku invocations via `concurrent.futures.ThreadPoolExecutor`, instead of N parallel Bash calls. The Claude Code harness serializes parallel Bash tool calls for subprocess-blocking work, so the previous design ran sequentially (wall time ≈ Σ per-call, ~2-3 min for N=10). With true Python-thread fan-out wall time is ≈ max per-call (~30s). `upgrade_batch()` preserves input order, catches per-note exceptions as `Failed: ...` status strings so one bad note can't kill the batch, and lives in `hooks/obsidian_utils.py` (GH #69)
- **tests**: Five `test_standup_deep.py` cases (`TestFtsScopingPerProject::test_fts_evidence_scoped_to_project`, `TestPipelineDirCreation::test_creates_output_dir_if_missing`, `TestRepresentativeKey::test_groups_use_representative_key`, `TestEncodingCorruption::test_pipeline_handles_binary_content_in_notes`, `TestPipelineErrorHandling::test_ensure_index_failure`) passed no `db_path=` to `ensure_index()`/`deep_analysis_pipeline()`, silently writing fixture rows into the user's live `~/.claude/obsidian-brain-vault.db`. Each test now routes through an isolated `tmp_vault / "test.db"` (GH #46)
- **vault-index**: `_sync()` uses `Path.is_relative_to()` instead of prefix-only `startswith()` so sibling folders like `claude-sessions-archive` are no longer incorrectly treated as nested inside `claude-sessions` (Phase 1 Copilot review deferred item)
- **vault-index**: `_prior_terms_for()` → `_prior_tokens_for()` — re-tokenises the stored note body instead of reading the top-K=50 truncated `tfidf_vector` keys, so common-but-low-IDF terms (outside the top-50 cutoff) are no longer incremented on every reindex without a matching decrement. Fixes `term_df.df` drifting upward past the total note count across repeated `index_note` calls (caught by Phase 2 dev-test Step 11 invariant checker, missed by 522 pytest + 27 validator assertions). Existing drift clears on `rebuild_index()`. Regression gates: pytest `test_reindex_does_not_drift_term_df` + validator `test_reindex_invariance`
- **vault-index**: `rebuild_index()` now calls `_ensure_access_log_indexes()` alongside `_ensure_theme_indexes()` so `idx_access_note` / `idx_access_time` are present immediately after a full rebuild, matching `ensure_index()`'s invariants. Previously a rebuilt DB was missing access-log indexes until the next `ensure_index()` call. Regression gate: pytest `TestRebuildIndex` now asserts both indexes exist post-rebuild (Phase 2 Copilot round 4)
- **validate_phase2**: Module-level hook resolution now short-circuits when `-h`/`--help` is present in `sys.argv`, so `--help` produces argparse usage output even when the plugin cache path cannot be located (Phase 2 Copilot round 4)

## [2.3.0] - 2026-04-16

### Added
- `/vault-stats` skill — vault health diagnostics and usage analytics showing signal coverage, access patterns, importance distribution, and top accessed notes; saves report to vault as `claude-stats` note for trend tracking
- **vault-index**: ACT-R access tracking — `access_log` table records every note read with context type (recall, search, ask, related) for activation-based ranking
- **vault-index**: `batch_activations()` computes ACT-R base-level activation (`ln(Σ t_i^(-0.5))`) for combined recency+frequency scoring
- **vault-index**: `importance` column on `notes` table — 1-10 write-time score extracted from Haiku/sub-agent summarization output
- **vault-index**: `detect_task_context()` — heuristic detection of debugging/standup/search/general from git branch and caller skill
- **vault-index**: Context-adaptive type scores — error-fix notes rank higher when debugging, session notes rank higher for standup

### Changed
- **vault-index**: Reranker upgraded from 5 to 7 signals — adds activation (0.20 weight) and importance (0.10 weight), rebalances existing signals
- **recall**: Sub-agent summarization prompt now includes importance scoring (1-10)

## [2.2.0] - 2026-04-14

### Changed
- **vault-index**: FTS5 search now uses AND-mode queries (both terms must appear) instead of OR-mode, with automatic OR fallback when AND returns zero results
- **vault-index**: BM25 column weighting — title matches rank 10x, tag matches 5x over body matches
- **vault-index**: New Python reranker scores results by term proximity (0.35), BM25 (0.25), note type (0.15), recency (0.15), and term density (0.10)
- **vault-index**: `notes` table now stores body text for reranker proximity scoring (auto-migrated on first run)

## [2.1.0] - 2026-04-13

### Added
- `/emerge` skill — cross-project pattern discovery across vault notes within configurable time window (7d/30d/90d/this week). Python-first pipeline with single AI sub-agent for synthesis. Surfaces technical patterns, process patterns, knowledge gaps, cross-project connections, and unnamed habits.
- `/standup deep` mode — evidence-based open-item consolidation. Collects all open items across projects, gathers completion evidence from git log, GitHub releases, changelogs, and FTS5 vault search, classifies items as COMPLETED/REDUNDANT/STALE/ACTIVE via AI sub-agent, suggests link/merge opportunities, detects orphaned notes, and cascades checkoffs vault-wide.
- `encoding-corruption` vault-doctor check — detects and repairs vault notes with invalid UTF-8 bytes that cause grep binary file handling
- `collect_vault_corpus()` and `upgrade_and_collect_corpus()` in obsidian_utils.py — single-pass vault scan for pattern analysis with unsummarized note upgrade
- `deep_analysis_pipeline()` and `build_deep_presentation()` in open_item_dedup.py — similarity pass, item dedup, evidence gathering via subprocess (git/gh), orphan detection
- `emerge_cli.py` and `deep_cli.py` — extracted CLI modules for skill orchestration
- 15-minute result caching for `/emerge` and `/standup deep` to avoid redundant runs
- Acted-on item tracking (24h TTL) to prevent re-recommending previously consolidated items
- Module-level compiled section-parsing regexes shared across vault functions
- SNIP_05 test: glob import validation for SKILL.md snippets
- `project-name-normalization` vault-doctor check — detects and auto-fixes underscored project names in frontmatter
- `_glob_project_jsonls()` helper — centralizes `~/.claude/projects/` globbing with underscore-to-hyphen fallback

### Fixed
- Python 3.9 compatibility: add `from __future__ import annotations` to `vault_index.py` and `obsidian_context_snapshot.py`
- Fix underscore-to-hyphen project path matching across session ID resolution functions
- Fix ambiguous hash instructions in 4 skills to prevent 3-char hash bug
- Normalize project names (underscore → hyphen) in session context and vault-doctor comparisons
- Atomic writes with path containment for all batch vault edit operations
- `errors='replace'` on all vault file reads to handle encoding corruption gracefully

## [2.0.1] - 2026-04-12

### Fixed
- Escape bash `[[` conditionals in raw conversation excerpts to prevent Obsidian from parsing them as wikilinks
- Restore vault-index features silently dropped during v2.0.0 release merge (README, skill files, import os fixes)

### Added
- `escape_wikilinks()` helper in `obsidian_utils.py`
- `spurious-wikilinks` vault-doctor check — detects and repairs unescaped `[[` in existing session notes

## [2.0.0] - 2026-04-12

### Security
- **CRITICAL:** Move all temp/cache files from `/tmp` to `~/.claude/obsidian-brain/` (0o700) — prevents symlink attacks (C1)
- **CRITICAL:** Remove `OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX` env var override — prevents arbitrary file write (C2)
- **HIGH:** Add path traversal validation to `write_vault_note()` — blocks `../` escape from vault (H1)
- **HIGH:** Add `scrub_secrets()` — best-effort regex redaction of API keys, tokens, passwords in raw session notes (H2)
- **HIGH:** Add `log_raw_messages` config toggle — disable raw conversation logging entirely (H2)
- **HIGH:** Validate `transcript_path` stays inside `~/.claude/projects/` (H3)
- **HIGH:** Fix shell injection in `commit-preflight.sh` — pass path via `sys.argv` (H4)
- Change all file permissions from 0o644 to 0o600 for vault notes, DB, and config (M1, M2)
- Fix SKILL.md config output to newline-separated KEY=VALUE — supports vault paths with spaces (M3)
- Fix `vault-reindex` to use `sys.argv` instead of inline interpolation (M4)
- Replace `sed -i` in standup with atomic `flip_note_status()` (M5)
- Cap `sys.stdin.read()` to 1MB in all hook entry points (M6)
- Escape LIKE wildcards in vault_index tag queries (M7)
- Validate `find_transcript_jsonl` output stays inside projects dir (M8)
- Standardize JSON cascade checkoff calls to use stdin pattern (L1)

### Added
- `/vault-config` skill — interactive settings menu for toggling obsidian-brain configuration
- `scripts/test-security.sh` — automated security validation (27 checks), runs from `/dev-test install` and CI
- `security-tests` CI job — runs security checks on every PR
- Security Patterns section in CLAUDE.md
- `/compress <topic>` update mode — searches vault index for existing notes via FTS5 and offers to append a dated `## Update (YYYY-MM-DD)` section instead of creating duplicates
- New `last_updated` frontmatter field set on each append to existing insight/decision notes
- New topic tags from update content are appended without duplicating existing tags
- `enforce-pr-base-branch.py` PreToolUse hook — blocks pull request creation without `--base develop` on feature branches and verifies base branch before merge, preventing accidental merges to main
- `hooks/vault_index.py` — SQLite + FTS5 vault index with lazy mtime-based sync, layered ranking queries (backlinks → tags → FTS keywords), and sub-millisecond ad-hoc search
- `/vault-reindex` skill — full index rebuild for recovery, setup, and after bulk Obsidian edits
- `/obsidian-setup` Step 8.5 — bootstraps vault index on first setup and upgrades
- `/vault-search` FTS fast path — tries instant FTS5 search before falling back to Grep
- `/vault-ask` FTS pre-filter — reduces sub-agent file reads by pre-filtering with FTS5

### Changed
- Haiku summarization timeout bumped from 15s to 30s (retry escalation: 30s/60s). Empirical measurement showed ~9-10s CLI startup overhead, leaving insufficient time for generation at 15s.
- `upgrade_unsummarized_note()` timeout is now a passthrough to `generate_summary()` — single source of truth instead of duplicated defaults.
- `check_hook_status()` SID mismatch (common after reconnects) is now `ok=True`. Only warns when bootstrap file is missing or no session files are found.
- `/recall` hook-status messages reworded for end users: `[OK]` lines suppressed from output, `[WARN]` shows actionable guidance.
- README updated with vault-index architecture details and `/vault-reindex` skill.
- `build_context_brief()` insight loading now surfaces contextually relevant insights via layered ranking (backlinks → tags → FTS keywords) instead of most-recent-by-mtime. Falls back to the original file scan if the vault index is unavailable.
- `/vault-search` and `/vault-ask` FTS snippets now call `ensure_index()` before `search_vault()` so newly written notes are always picked up.
- FTS5 schema uses contentless tables (`content=''`) — orphaned FTS entries are filtered out by JOIN, no DELETE needed.
- `build_context_brief()` fallback narrowed from `except Exception` to `except (sqlite3.Error, OSError)` so programming bugs propagate instead of silently degrading to file scan.
- All `vault_index.py` public functions use `try/finally` for connection cleanup.
- Corrupt DB recovery now removes WAL/SHM sidecar files and logs to stderr.
- Layer query failures log to stderr instead of silently passing.

### Fixed
- FTS5 hyphen-as-NOT bug: `_sanitize_fts_query()` now replaces hyphens with spaces before tokenization. Previously, `"maintain-catalog"` was interpreted as `"maintain" NOT "catalog"` by FTS5's unicode61 tokenizer.
- Contentless FTS5 delete compatibility: `_upsert_note()` and `_delete_note()` no longer use `DELETE FROM notes_fts` (invalid for contentless tables). Orphaned FTS entries are filtered by the JOIN in all queries.
- `source_session` column mapping: `_upsert_note()` now correctly reads `parsed.get("source_session")` instead of `parsed.get("session_id")`.
- Missing `import os` in `/recall` Step 4 cascade checkoff inline Python snippet.
- `upgrade_note_with_summary()` now guarantees that a returned `Upgraded` status means the summary actually landed on disk. The rewritten tempfile is `fsync`'d before `os.replace()`, the parent directory is `fsync`'d after the rename (crash-durable rename), and the target file is re-read and verified before the function returns. Verification checks that `status: summarized` appears in the **YAML frontmatter block** (anchored to the start of the file via `re.match`, not a whole-file substring match — so a body that happens to mention the literal string or contains a Markdown `---` horizontal rule cannot false-positive) AND that the first real content line of the supplied summary is present in the **`## Summary` section** as its own stripped line (line-granularity, not substring match). Empty or heading-only Summary bodies are rejected upfront with `Failed: malformed summary`. Post-write mismatches return distinct `Failed: post-write verification — …` statuses (status not flipped, summary body missing, `## Summary` section not found, YAML frontmatter not found at start, post-write read failure) so callers (and `/recall`) can no longer be told "Upgraded" about a note that did not actually receive its summary.

## [1.9.0] - 2026-04-11

### Added
- `/standup` Step 14: cascade completed open items across vault notes using `batch_cascade_checkoff()` — when items are marked done in standup, all matching `- [ ]` entries in other session notes are automatically checked off
- `/vault-doctor` skill — diagnostic and repair tool for the Obsidian vault with a pluggable check-module registry. Ships with a `source-sessions` check that scans the last 7 days of insight/decision/error-fix/retro notes, detects stale `source_session` backlinks by matching note mtimes against JSONL session windows, and atomically rewrites only the affected frontmatter fields under `--apply` with per-project confirmation and automatic backups.
- `~/.claude/obsidian-brain-hook.log` — rolling audit log of SessionStart hook invocations with the authoritative session id, rotated at 100 KB.
- `scripts/verify-hooks.sh` — manual diagnostic that simulates a SessionStart hook invocation and confirms the bootstrap and log were written.
- `/recall` brief now leads with a `[OK]`/`[WARN]` SessionStart hook status line.

### Fixed
- Session hint hook now writes the authoritative session id to the bootstrap cache, fixing stale `source_session` backlinks that pointed at previous sessions when `/compress`, `/decide`, `/error-log`, or `/retro` were run in a second-or-later session of a given project.
- `_get_session_id_fast()` now detects a new session by comparing the newest JSONL's basename against the cached sid (with a same-second mtime tie-breaker that trusts the hook-written bootstrap), invalidating the cache when a different session has become authoritative. This is defense-in-depth against the rare case where the SessionStart hook did not fire.
- `_get_session_id_fast()` slow path is now strictly read-only so it can no longer clobber the SessionStart hook's authoritative bootstrap write during the hook's own invocation, preventing a race where Claude Code fires SessionStart before flushing the new session's JSONL to disk.
- `apply()` preserves the patched note's original mtime so `/vault-doctor` re-runs never re-flag their own fixes.
- `apply()` sanitizes the project name via `_safe_project_slug()` before joining it onto the backup path, preventing path-traversal via frontmatter-provided project values.
- `apply()` separates backup and rewrite error reporting so failures are distinguishable and the backup path is preserved for recovery even when the rewrite stage fails.
- `_jsonl_dir_for_project()` uses `glob.escape()` on project names and `_safe_mtime()` wrapper to tolerate transient filesystem races between glob and stat.
- `_find_matching_session()` iterates deterministically with a same-mtime tiebreaker so window-boundary cases pick the most recently started session reproducibly.
- `_write_bootstrap_atomic()` forces absolute paths before computing the temp directory, preventing `EXDEV` errors when `OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX` is relative and `/tmp` is a separate filesystem.
- `_write_bootstrap_atomic()` and `apply()` clean up orphaned temp files in `finally` blocks if `os.replace()` did not consume them.
- `vault_doctor_checks` registry now catches per-module import errors and logs them to stderr rather than aborting the whole dispatcher, keeping the check system pluggable.
- `check_hook_status()` now uses a bootstrap-independent slow-path helper so the health check is not circular and correctly flags stale bootstraps as `[WARN]`.
- `/recall` brief hook status line handles the "no JSONLs discoverable" case with a clear `could not determine current session id from JSONLs` message.
- `verify-hooks.sh` derives `PROJECT` via `get_project_name()` so it agrees with the Python hook's project-name resolution, and passes `cwd` to its Python helper via `sys.argv` rather than string interpolation (quote-safe for paths containing special characters).
- `_cleanup_session_cache()` now runs in a `try/finally` at the top level of the SessionEnd hook, so orphaned cache files are cleaned up on every SessionEnd path (threshold skips, missing config, auto-log disabled, errors) — not just the happy path.
- Several test suites migrated from `time.mktime()` (local time) to `calendar.timegm()` (UTC) to prevent CI flakiness on non-UTC runners.
- `vault_doctor.py` `_load_config()` respects strict `CLI > env > config file > default` precedence for every field; previously environment-set folder names could be overridden by config file values.
- `vault_doctor.py` validates `--days` as positive before running any check.
- `apply()` now writes backups to `<backup_root>/<project>/<folder>/<basename>` to prevent basename collisions across insight-type folders.
- All generated output uses ASCII glyphs (`[OK]`/`[WARN]`/`[FAIL]`) instead of Unicode emoji, matching the project-wide no-emoji convention.

### Changed
- SessionEnd hook now cleans up the per-session disk cache file `/tmp/.obsidian-brain-cache-<sid>.json` to prevent `/tmp` accumulation over time.

## [1.8.2] - 2026-04-10

### Added
- `/recall` session history table now includes a Duration column (e.g. `1h 20m`, `27m`)
- `/recall` session history table now includes a `#` column for easy session selection
- `/recall` skill now instructs Claude to paraphrase session titles into concise one-liners
- `_safe_sort_key()` helper for graceful handling of broken symlinks during session scan
- 12 new tests: sort order, duration formatting, session number, stat failure, 60-min boundary, cache glob regression guards

### Fixed
- `/recall` session history now sorts by date descending then mtime descending, fixing random hash-based ordering for same-day sessions
- All 12 skills now resolve hooks from plugin cache, fixing `ModuleNotFoundError` when running from non-obsidian-brain project directories
- Session scan now filters to `.md` files before sorting, avoiding unnecessary `stat()` calls on non-session files

## [1.8.1] - 2026-04-10

### Added
- pytest test suite with 101 tests across 7 test files covering all Python hook modules
- SKILL.md `python3 -c` syntax validation via parameterized compile() tests (26 snippets)
- 90% line coverage enforcement via pytest-cov (98% achieved on measured modules)
- `python-tests` CI job in GitHub Actions for all PRs
- pytest + coverage detection in `commit-preflight.sh` test section
- `setup.cfg` with pytest and coverage configuration

### Fixed
- `skills/obsidian-setup/SKILL.md` f-string escape bug caught by snippet validator

### Changed
- Upgraded GitHub Actions from v4/v5 to v6 (Node.js 24 compatible)
- `commit-preflight.sh` now fails if `tests/` directory exists but pytest is not installed

## [1.8.0] - 2026-04-10

### Added
- User-visible task manifest during `/recall` showing progress across all
  steps with per-note granularity during summarization.
- `prepare_summary_input()` helper in `obsidian_utils.py` for conditional
  JSONL-to-temp-file extraction.
- `/dev-test` skill and `test-dev-skill.sh` script for swapping the installed
  plugin cache with the repo working copy during local testing.

### Changed
- `/recall` Step 2 now uses parallel sub-agents as the default summarization
  strategy when 2+ unsummarized notes are found, with conditional JSONL
  transcript extraction for truncated sessions. Sub-agent summaries written to
  temp files (no heredoc pass-through). Per-note sub-tasks skipped when N>5.
  Single-note case unchanged (Haiku pipeline + sub-agent fallback).
- `/recall` Step 3 context building done by pure Python `build_context_brief()`
  function (<3s, direct file I/O) instead of sub-agent (~145s, 70 Read calls).
  Unsummarized note detection also moved to Python `find_unsummarized_notes()`.
  Total `/recall` reduced from ~4 min to ~1.3 min.
- `/recall` steps reduced from 8 to 4. Config + project merged into single call.
  Task manifest collapsed from 6 to 4 top-level tasks.
- Session history table titles use first sentence of `## Summary` instead of
  generic H1 heading, making each row descriptive of what happened.

### Fixed
- f-string SyntaxError in all 10 skill templates — `python3 -c '...'` one-liners
  used f-strings with dict key access (`c[\"vault_path\"]`) which breaks inside
  Bash single-quoted strings. Replaced with string concatenation across config
  load (10 skills) and session context (4 skills).
- `/recall` and `/standup` grep for unsummarized notes matched tool-usage logs
  in conversation excerpts, causing false positives and unnecessary re-summarization.
  Changed from body text pattern (`"AI summary unavailable"`) to frontmatter
  field (`^status: auto-logged`).
- Legacy notes (119 across all projects) had `status: auto-logged` but already
  contained real AI summaries from old SessionEnd inline-summarization path.
  Added defense-in-depth guard to `/recall` Step 2 and `/standup` Step 5 that
  checks for `## Summary` before re-summarizing and auto-fixes stale status fields.
- Stale metadata cache caused `find_unsummarized_notes()` to skip genuinely
  unsummarized notes and re-summarize already-upgraded ones. Function now reads
  frontmatter directly from disk, and `upgrade_note_with_summary()` invalidates
  cache entries after status changes.

## [1.7.2] - 2026-04-09

### Fixed
- **Haiku summarization timeout retry** — `generate_summary()` now retries once at 2x timeout (15s → 30s) before giving up, reducing unnecessary sub-agent fallbacks

## [1.7.1] - 2026-04-09

### Added
- **Sub-agent summary fallback** — when Haiku API times out during `/recall` Step 3, parallel sub-agents (inheriting parent model) produce structured summaries. New `upgrade_note_with_summary()` function accepts pre-generated summary text and handles the pipeline finish (frontmatter flip, dedup, atomic write). Minimal overhead when Haiku succeeds.

## [1.7.0] - 2026-04-09

### Added
- **Open item deduplication** — new `hooks/open_item_dedup.py` module with hybrid matching (distinctive tokens + fuzzy overlap) prevents duplicate open items across session notes
  - Creation-time prevention: `generate_summary()` appends existing items to Haiku prompt + post-generation dedup pass strips duplicates before disk write
  - Check-off cascading: checking off an item auto-checks matching duplicates in older notes (high confidence) or suggests them (fuzzy confidence)
  - `/recall` Step 3: `dedup_note_open_items()` runs after note upgrade (zero items loaded into model context)
  - `/recall` Step 7.5 + `/check-items`: `batch_cascade_checkoff()` handles cascade in a single Python call
- **Session-scoped cache** — file-based cache at `/tmp/.obsidian-brain-cache-{session_id}.json` avoids repeated vault scans across skills within one session (~650 tokens + ~190ms saved for 5 skills)
- **Shared helpers** — `load_config()` (cache-backed), `get_session_context()`, `read_note_metadata()` consolidate redundant config/session/frontmatter parsing across skills
- **`upgrade_unsummarized_note()`** — single Python call replaces the multi-step JSONL parse → summarize → write → dedup pipeline in `/recall` Step 3 (~1,000 tokens saved per note upgrade)
- **`match_items_against_evidence()`** — moves completion detection matching from model context to Python (~400-600 tokens saved per `/recall` invocation)
- **Config/session consolidation** — all 12 skills now use `load_config()` shared helper instead of inline `cat`/`Read` config parsing (~2,470 tokens saved per multi-skill session)
- **`/standup` always parallelizes** unsummarized note upgrades via `upgrade_unsummarized_note()` helper (60-80% time reduction)

### Fixed
- Defensive initialization of `parsed` variable in `upgrade_unsummarized_note()` to prevent potential `NameError` on future refactors
- **`/recall` Step 8 UX** — replaced vague "Want me to load this context?" with an explicit load manifest showing which sessions and insights are in the conversation, and made the session history table actionable for loading additional sessions

## [1.6.2] - 2026-04-07

### Added
- **`commit-preflight.sh` plugin manifest version sync check** — Preflight now parses `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` and fails the commit if the registry pointer version drifts from the actual plugin version. Prevents the class of bug where the marketplace listing advertises a stale version to users.
- **`bump-version.sh` auto-updates `marketplace.json`** — Running `./scripts/bump-version.sh <type>` now updates every matching plugin entry in `marketplace.json` alongside `plugin.json`, so release-branch bumps stay in lockstep by default.

### Fixed
- Bumped `.claude-plugin/marketplace.json` plugin version from stale `1.1.0` to `1.6.1` so the marketplace registry pointer matches the actually published plugin version.

### Changed
- **`/recall` Step 3 hardened against skipping** — Added an explicit mandatory-step callout, large-note chunked-read handling (Read token-limit errors are not a skip signal), missing-JSONL fallback clarification, and a required one-line status emission (`Step 3: processing N unsummarized note(s)` / `no unsummarized notes`) so the upgrade decision is auditable in the tool trace. Fixes the failure mode where `/recall` silently skipped unsummarized notes under execution momentum.

## [1.6.1] - 2026-04-07

### Fixed
- `/recall` now produces accurate summaries for long sessions. Previously the raw session note was truncated to ~40 conversation turns and `/recall` summarized only that slice; now `/recall` deterministically locates the original Claude Code transcript JSONL by `session_id` and re-parses it when it has more data than the raw note. Very large transcripts (>5 MB) are sliced into head+tail halves with an explicit warning surfaced to the user. Falls back gracefully when the JSONL is no longer on disk.

### Changed
- Raw session notes now keep more context standalone — `build_raw_fallback()` caps bumped: 120 conversation turns (was 40), 1200 chars per message (was 600), 80 tool uses (was 30), 60 files touched (was 30), 30 errors (was 15). Typical sessions remain self-contained without needing the JSONL fallback.

## [1.6.0] - 2026-04-07

### Added

- **Cross-project open items dashboard** — New `claude-dashboards/open-items.md` Dataview dashboard installed by `/obsidian-setup`. Shows all unchecked `- [ ]` items from session notes' `## Open Questions / Next Steps` sections, grouped by project, with separate "Recent (7d)" and "Items from sessions 30-90 days ago" views plus stats. Scoped to the last 90 days for performance.
- **`/check-items` skill** — Cross-project sweep that scans all session notes for unchecked items (unbounded), gathers evidence from sessions in the last 14 days per project, proposes matches via substring + completion-phrase heuristics, and flips confirmed items from `- [ ]` to `- [x]` in the source notes. The 14-day window applies only to the evidence pool used for matching; open-item collection itself is unbounded. Configurable via `/check-items <Nd>`.
- **`/recall` auto-detect** — `/recall` now detects open items from the current project that may have been completed in the most recent loaded session. Proposes candidates with evidence snippets; user confirms before any edits.
- **`/standup` Closed This Period section** — Standup notes now include a section listing items checked off during the standup window, grouped by project. Detected via file modification time. Omitted if zero items closed.

### Changed

- **`obsidian-setup` skill** — Now installs the new `open-items.md` dashboard. Skill version bumped to 1.3.0.
- **`recall` skill** — New Step 7.5 detects completed open items. Skill version bumped to 1.1.0.
- **`standup` skill** — New "Closed This Period" section. Skill version bumped to 1.1.0.

## [1.5.3] - 2026-04-06

### Added

- **Permission pre-flight check in `/obsidian-setup`** — Detects restrictive Claude Code permission modes via canary write before attempting out-of-workspace writes. Presents three options: switch mode (`Shift+Tab`), whitelist paths in settings, or continue manually.
- **Vault path canary** — Tests vault writability in `/obsidian-setup` Step 5 before creating folders, catching cases where `~/.claude/` is writable but the vault is not.
- **README troubleshooting section** — Covers silent setup failures (permission modes), `python` not found on macOS, and vault path not writable.

### Changed

- **Auto-logging description** — README now accurately reflects deferred summarization (removed reference to in-hook `claude -p` subprocess).

## [1.5.2] - 2026-04-06

### Added

- **Standup highlights summary** — `/standup` now generates a highlights summary and key open items section at the top of standup notes for quick scanning.

### Fixed

- **Python 3.9 compatibility** — Added `from __future__ import annotations` to `obsidian_utils.py` so `X | None` type hints (PEP 604) work on macOS system Python 3.9.6. Previously caused `TypeError` at import time, breaking all hooks.
- **SessionEnd hook cancellation** — Removed in-hook AI summarization (`claude -p` subprocess) from `obsidian_session_log.py`. SessionEnd hooks are fire-and-forget; the slow subprocess was killed when Claude Code's process tree exited. Summarization is now fully deferred to `/recall`.

## [1.5.1] - 2026-04-05

### Fixed

- **Hookify nudge scope** — `/obsidian-setup` now writes the claudeception-compress nudge rule to `~/.claude/` (global) instead of the project's `.claude/` directory, so the nudge triggers in any project where claudeception runs. Also fixes the existence check to look for the `.local.md` rule file instead of grepping `settings.json`.
- **Changelog PR hook now detects stale entries** — The `update-changelog-before-pr` hook now diffs CHANGELOG.md against the base branch instead of just checking for any entries under `[Unreleased]`. Stale entries from previous releases no longer cause false passes.

## [1.5.0] - 2026-04-05

### Added

- **Claudeception-to-Compress bridge** — `/compress` now detects `/claudeception` output in the conversation and surfaces extracted skills/knowledge as top-priority insight candidates. Uses layered detection: high-confidence structured markers (skill validator output, skill file paths) first, broad phrase scanning as fallback. Claudeception candidates are labeled `[from claudeception]` or `[possibly from claudeception]` and included when the user selects `all`.
- **Hookify nudge via `/obsidian-setup`** — New idempotent step in `/obsidian-setup` configures a hookify nudge that reminds users to run `/compress` after claudeception produces output. Existing users can re-run `/obsidian-setup` to pick up the nudge.

### Changed

- **`/obsidian-setup` is now idempotent** — Detects existing installations and offers upgrade/reconfigure/cancel. In upgrade mode, preserves existing config and user-customized dashboards while adding new features (dashboards, hookify nudges). Safe to re-run anytime.

## [1.4.0] - 2026-04-05

### Added

- `/standup` skill: daily/weekly summary generation across projects with AI summarization, context-shield deep reads, and source note backlinks
- `/link` skill: cross-reference related notes with bidirectional wikilinks and auto-suggestion
- `/retro` skill: honest session retrospective for meta-learning with session backlinks
- `/vault-ask` skill: synthesize answers from vault knowledge with source citations and relevance ranking
- Learning Velocity dashboard: topic frequency from curated insights, retrospective history, error patterns
- Decision Timeline dashboard: chronological decision tracking with active/superseded status views

## [1.3.0] - 2026-04-05

### Fixed

- **SessionStart hook output** — Added required `hookEventName: "SessionStart"` field to `obsidian_session_hint.py` JSON output. Claude Code silently drops `hookSpecificOutput` JSON that omits this field, causing the session hint to never appear at startup.
- **SessionStart hook matcher** — Added explicit `matcher` field to `hooks.json` SessionStart entry for clarity (optional but documents intent).

### Added

- **Session backlinks in insights** — All insight-producing skills (`/compress`, `/error-log`, `/decide`) now derive the current session ID and include a `source_session_note` wikilink in frontmatter, enabling bidirectional navigation between session notes and insights in Obsidian's graph view.
- **Session ID derivation** — Skills now detect the active session by finding the most recently modified `.jsonl` file in the Claude Code project directory, replacing the broken `$CLAUDE_SESSION_ID` environment variable approach.

### Changed

- **Templates updated** — `insight.md`, `error-fix.md`, and `decision.md` templates now include `source_session` and `source_session_note` frontmatter fields.

## [1.2.0] - 2026-04-04

### Added

- **Git Flow enforcement** — Claude Code hooks to prevent direct push to main/develop, validate branch naming (`feature/*`, `release/*`, `hotfix/*`), and require preflight checks before commit
- **Commit preflight system** — `scripts/commit-preflight.sh` with secret scanning, one-time token mechanism, and skip-tests escape hatch
- **Release pipeline** — `scripts/bump-version.sh` (targets `.claude-plugin/plugin.json`) and `scripts/git-flow-finish.sh` for automated release/hotfix completion
- **GitHub Actions CI** — Secret scan on all PRs, changelog check on PRs to main, release verification on main push
- **Branch protection** — Status check enforcement on main and develop (admin-lenient)

### Documentation

- **README vault details** — Added detailed descriptions of each `claude-*` folder, how content gets loaded into sessions, and a context loading summary table

## [1.1.0] - 2026-04-04

### Improved

- **Richer session notes** — raw fallback notes now include assistant messages, tool usage details (commands run, files edited, searches performed), and interleaved conversation (up to 40 turns). System noise (task notifications, skill loading) is filtered out.
- **Better `/recall` summaries** — summarization prompt now demands specific technical details: file paths, function names, decision rationale, error root causes with fixes, and concrete next steps.

### Fixed

- Raw notes previously only captured user messages (15 max). Now captures full conversation with both sides for `/recall` to produce high-quality summaries.

## [1.0.0] - 2026-04-04

### Added

- **Auto-logging** — SessionEnd hook automatically writes structured session notes to your Obsidian vault with YAML frontmatter, tags, and metadata. Uses a write-first pattern: raw note is always saved, AI summary attempted as best-effort upgrade.
- **Context hints** — SessionStart hook injects a one-line summary of the last session for the current project, giving you immediate continuity.
- **Context snapshots** — PreCompact hook saves a snapshot of your current context before compression or clear, preserving context that would otherwise be lost.
- **`/obsidian-setup`** — Interactive first-run configuration. Sets vault path, creates folders, copies Dataview dashboards, writes config.
- **`/compress`** — Curate and save specific insights from the current session. Suggests candidates or accepts a topic argument. Interactive preview with tag editing.
- **`/recall`** — Load project-scoped context from vault history. Finds your last session, open items, and all curated insights. Includes deferred summarization — upgrades raw notes with AI summaries on demand.
- **`/vault-search`** — Search across all sessions and insights by keyword, tag, or structured queries (e.g., `project:api-service type:decision`).
- **`/decide`** — Log architectural decisions in ADR-lite format: Context, Options, Decision, Rationale, Consequences.
- **`/error-log`** — Capture errors with root cause, fix, and prevention steps for future reference.
- **`/vault-import`** — Backfill historical sessions from CC conversation history. Uses `/conversation-search` for discovery and parallel `/context-shield` sub-agents for processing.
- **Dataview dashboards** — 3 ready-to-use dashboards: Sessions Overview, Project Index, Weekly Review.
- **Note templates** — 6 templates for all note types: session, insight, decision, error-fix, snapshot, imported session.
- **Plugin distribution** — Installable via Claude Code plugin system from GitHub.
