---
name: vault-doctor
description: "Diagnostic and repair skill for the Obsidian vault. Runs a battery of checks against vault notes and offers to fix detected issues. Dry-run by default — requires 'fix' to write. Use when: (1) /vault-doctor command to scan for vault health issues, (2) /vault-doctor fix to apply repairs, (3) /vault-doctor --check <name> for a specific check, (4) user reports stale backlinks or wants to audit vault integrity."
metadata:
  version: 1.0.0
---

# vault-doctor — Audit and Repair the Obsidian Vault

Audit and repair the Obsidian vault. Ships with one check initially (`source-sessions`); more can be added as separate modules under `scripts/vault_doctor_checks/` without changing this skill.

**Tools needed:** Bash, Read

## Invocation

- `/vault-doctor` — run all checks, report only (dry-run)
- `/vault-doctor fix` — run all checks, apply after per-project confirmation
- `/vault-doctor --check source-sessions` — run one specific check
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

Parse the JSON and present a grouped-by-project table. Example:

```
vault_doctor report — 3 issue(s) across 1 check(s)

## source-sessions

### Project: obsidian-brain (2 issues)
[FAIL] 2026-04-10-recall-profiling.md
  current:  [[2026-04-09-obsidian-brain-abcd]]
  proposed: [[2026-04-10-obsidian-brain-ef01]]
  reason:   note mtime 2026-04-10T14:22 matches session ef010000 window...

### Project: tiny-vacation-agent (1 issue)
[FAIL] 2026-04-11-enrichment-scope.md
  current:  [[2026-04-10-tiny-vacation-agent-aaaa]]
  proposed: [[2026-04-11-tiny-vacation-agent-bbbb]]
  reason:   note mtime 2026-04-11T09:15 matches session bbbb0000 window...
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
