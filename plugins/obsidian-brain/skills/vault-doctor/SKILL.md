---
name: vault-doctor
description: "Diagnostic and repair skill for the Obsidian vault. Runs a battery of checks against vault notes and offers to fix detected issues. Dry-run by default — requires 'fix' to write. Use when: (1) /vault-doctor command to scan for vault health issues, (2) /vault-doctor fix to apply repairs, (3) /vault-doctor --check <name> for a specific check, (4) user reports stale backlinks or wants to audit vault integrity."
metadata:
  version: 1.2.0
---

# vault-doctor — Audit and Repair the Obsidian Vault

Audit and repair the Obsidian vault. Ships with one check initially (`source-sessions`); more can be added as separate modules under `scripts/vault_doctor_checks/` without changing this skill.

**Tools needed:** Bash, Read

## Invocation

- `/vault-doctor` — run all checks, report only (dry-run)
- `/vault-doctor fix` — run all checks, apply after per-project confirmation
- `/vault-doctor --check source-sessions` — run one specific check
- `/vault-doctor --check snapshot-integrity` — snapshot orphans, broken backlinks, stale/missing session snapshot lists, status/summary mismatches
- `/vault-doctor --check snapshot-migration` — migrate pre-spec snapshots (legacy filenames, missing status/backlink fields, missing session snapshot lists). Runs 4 ordered sub-checks; idempotent.
- `/vault-doctor --days 14` — override default window (default: 7 days)
- `/vault-doctor --project obsidian-brain` — limit to one project
- `/vault-doctor fix --check source-sessions --days 7` — combine flags

## Procedure

Follow these steps exactly. Do not skip steps or reorder them.

### Step 1 — Parse arguments and locate the dispatcher

Parse the user's invocation into flags:

- No args → dry-run mode, all checks
- `fix` → apply mode, all checks
- `--check <name>` → specific check only
- `--days <N>` → window override
- `--project <name>` → project filter

Locate the Python dispatcher via the standard plugin cache glob, with a fallback for local dev sessions where the repo is checked out as `$PWD`:

```bash
DISPATCHER="$(ls -dt ~/.claude/plugins/cache/*/obsidian-brain/*/scripts/vault_doctor.py 2>/dev/null | head -1)"
if [[ -z "$DISPATCHER" ]]; then
    if [[ -f "$(pwd)/scripts/vault_doctor.py" ]]; then
        DISPATCHER="$(pwd)/scripts/vault_doctor.py"
    fi
fi
if [[ -z "$DISPATCHER" || ! -f "$DISPATCHER" ]]; then
    echo "ERROR: could not find scripts/vault_doctor.py" >&2
    exit 1
fi
```

If the dispatcher cannot be located, tell the user:

> Could not find `scripts/vault_doctor.py`. Make sure the obsidian-brain plugin is installed via `/dev-test install` (for local dev) or the marketplace.

Stop here if the dispatcher is missing.

### Step 2 — Run the dispatcher in JSON report mode

Always run with `--json` first so you can parse the output deterministically. Pass through only the flags the user provided:

```bash
ARGS=()
[[ -n "${CHECK:-}" ]] && ARGS+=(--check "$CHECK")
[[ -n "${DAYS:-}" ]] && ARGS+=(--days "$DAYS")
[[ -n "${PROJECT:-}" ]] && ARGS+=(--project "$PROJECT")
ARGS+=(--json)
python3 "$DISPATCHER" "${ARGS[@]}"
```

Capture stdout as the JSON report. Exit codes:

- `0` — clean vault, nothing to do
- `1` — issues found (expected for a dry-run that finds things)
- `2` — apply errors
- `3` — usage error (bad args, missing config)

If exit code is `3`, surface the stderr message directly to the user and stop.

### Step 3 — Present the report to the user

Parse the JSON and present a grouped-by-project table.

For each issue, after the `proposed:` line (when present), render a
`signal: <capture_signal> (conf <capture_confidence>)` line. The values
come from the top-level `capture_signal` and `capture_confidence` fields
in the JSON payload (not from `extra.*`). `capture_confidence` reports
how reliable the capture-time *signal* is (created_at=1.0, date=0.9,
filename=0.85, mtime=0.5); the issue's top-level `confidence` field
reports the *rewrite-proposal* confidence (created_at=0.95, mtime=0.3,
otherwise 0.6) that gates `--apply --min-confidence`. The two are
distinct — render `capture_confidence` here so heuristic-fall cases
are visible (e.g., `signal=mtime conf=0.5` indicates no immutable
signal was available — the operator should sample a few flagged
notes before running `fix`). For
unresolved issues with no `proposed:` line, render `signal:` after `reason:`.
When `convergence_warning` is `true` in the issue, prefix the issue line
with `[CONVERGED <N> flags]` where `N` is `convergence_count`.

Example:

```
vault_doctor report — 3 issue(s) across 1 check(s)

## source-sessions

### Project: obsidian-brain (2 issues)
[FAIL] 2026-04-10-recall-profiling.md
  current:  [[2026-04-09-obsidian-brain-abcd]]
  proposed: [[2026-04-10-obsidian-brain-ef01]]
  signal:   date (conf 0.9)
  reason:   note calendar day 2026-04-10 (signal=date, conf=0.9) overlaps session ef010000 window most, not current source abcd0000

### Project: tiny-vacation-agent (1 issue)
[FAIL] 2026-04-11-enrichment-scope.md
  current:  [[2026-04-10-tiny-vacation-agent-aaaa]]
  proposed: [[2026-04-11-tiny-vacation-agent-bbbb]]
  signal:   created_at (conf 1.0)
  reason:   note capture_time 2026-04-11T09:15:00+00:00 (signal=created_at, conf=1.0) matches session bbbb0000 window, not current source aaaa0000
```

Use `[FAIL]` for actionable issues (those with a proposed fix) and `[WARN]` for unresolved ones (those the check could not auto-repair). Always include a one-line summary at the top with the total count.

If the report is empty (exit code 0), tell the user:

> Vault is clean. No issues found.

Stop here.

### Step 4 — Ask whether to apply (only if `fix` was requested)

If the user did NOT pass `fix`:

> Dry-run complete. Found **N** stale backlink(s) across **K** project(s).
> Run `/vault-doctor fix` to apply repairs. Backups will be written to `~/.claude/obsidian-brain-doctor-backup/<timestamp>/`.

Stop here.

If the user DID pass `fix`:

> Found **N** repairable issue(s) across **K** project(s). I'll apply per project with confirmation.

Re-run the dispatcher with `--apply` (do NOT pass `--yes` — let the dispatcher prompt per project interactively):

```bash
ARGS=()
[[ -n "${CHECK:-}" ]] && ARGS+=(--check "$CHECK")
[[ -n "${DAYS:-}" ]] && ARGS+=(--days "$DAYS")
[[ -n "${PROJECT:-}" ]] && ARGS+=(--project "$PROJECT")
ARGS+=(--apply)
python3 "$DISPATCHER" "${ARGS[@]}"
```

The dispatcher will prompt `Apply N fix(es) for project 'X' in check 'Y'? [y/N]` on stderr for each project. Relay each prompt to the user and pipe their response to the dispatcher's stdin.

### Step 5 — Report the outcome

Parse the final stderr output from the dispatcher and summarize:

```
vault_doctor apply complete
  obsidian-brain: 3 applied, 0 unresolved, 0 errors
  tiny-vacation-agent: 1 applied, 0 unresolved, 0 errors

Backups saved to: ~/.claude/obsidian-brain-doctor-backup/2026-04-11T17-04-22+00-00/
```

If any errors occurred (exit code 2), surface them prominently and recommend the user diff one of the backup files under the backup root to understand what went wrong.

### Step 6 — Offer next steps

After a successful fix run:

> Repairs applied. You can diff any fixed note against its backup under the backup root.
> Re-run `/vault-doctor` to confirm the vault is clean.

## Notes for the model

- All detection and repair logic lives in `scripts/vault_doctor.py` and `scripts/vault_doctor_checks/*.py`. **Do not re-implement any of it in this skill.** The skill is pure orchestration and presentation.
- The dispatcher is dry-run by default. Pass `--apply` only when the user explicitly requests `fix`.
- Unresolved issues are never automatically repaired. Surface them in the report but do not try to guess a replacement.
- Backups are written automatically by the dispatcher to `~/.claude/obsidian-brain-doctor-backup/<ISO-timestamp>/<project>/<basename>`. Always mention the backup path in your summary so the user knows where to look.
