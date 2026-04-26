#!/usr/bin/env python3
"""vault_doctor — audit and repair the Obsidian vault.

Dispatches to check modules under scripts/vault_doctor_checks/.
Dry-run by default — requires --apply to write anything.

Config priority:
  1. CLI args (--vault, --sessions-folder, --insights-folder)
  2. Env vars (OBSIDIAN_BRAIN_VAULT, *_SESSIONS_FOLDER, *_INSIGHTS_FOLDER)
  3. ~/.claude/obsidian-brain-config.json (read directly via json.load
     to avoid hooks/obsidian_utils.load_config()'s session-scoped cache,
     which can be stale when the CLI runs outside a live Claude Code
     session)

Exit codes:
  0 — clean, no issues
  1 — issues found (dry-run or successful apply)
  2 — apply errors (one or more fixes failed)
  3 — usage error (bad args, no config)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the check package importable
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

import vault_doctor_checks  # noqa: E402


def _load_config(args) -> dict:
    """Resolve vault path + folders from args → env → obsidian-brain config file.

    Precedence (strict): CLI arg > env var > config file > default.
    """
    vault = args.vault or os.environ.get("OBSIDIAN_BRAIN_VAULT")
    env_sessions = os.environ.get("OBSIDIAN_BRAIN_SESSIONS_FOLDER")
    env_insights = os.environ.get("OBSIDIAN_BRAIN_INSIGHTS_FOLDER")
    sessions = args.sessions_folder or env_sessions
    insights = args.insights_folder or env_insights

    if not vault or not sessions or not insights:
        # Fall back to config file only for values not yet resolved.
        # Read directly (bypass obsidian_utils.load_config's session cache,
        # which can be stale when the CLI runs outside a live session).
        cfg_path = Path.home() / ".claude" / "obsidian-brain-config.json"
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if isinstance(cfg, dict):
                if not vault:
                    vault = cfg.get("vault_path", "")
                if not sessions:
                    sessions = cfg.get("sessions_folder", "claude-sessions")
                if not insights:
                    insights = cfg.get("insights_folder", "claude-insights")
        except (OSError, json.JSONDecodeError):
            pass

    # Apply defaults for any unresolved folders
    sessions = sessions or "claude-sessions"
    insights = insights or "claude-insights"

    if not vault:
        print(
            "error: no vault_path configured; set OBSIDIAN_BRAIN_VAULT "
            "or run /obsidian-setup",
            file=sys.stderr,
        )
        sys.exit(3)

    if not Path(vault).is_dir():
        print(
            f"error: vault_path does not exist or is not a directory: {vault}",
            file=sys.stderr,
        )
        sys.exit(3)

    return {"vault": vault, "sessions_folder": sessions, "insights_folder": insights}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vault_doctor")
    p.add_argument("--check", dest="check", default=None, help="run only this check by name")
    p.add_argument("--days", type=int, default=None, help="override default window (days)")
    p.add_argument("--project", default=None, help="limit scan to this project name")
    p.add_argument("--vault", default=None, help="override vault path")
    p.add_argument("--sessions-folder", default=None)
    p.add_argument("--insights-folder", default=None)
    p.add_argument("--apply", action="store_true", help="apply fixes (default: dry-run)")
    p.add_argument("--yes", action="store_true", help="assume yes for all confirmations")
    p.add_argument("--json", dest="json_out", action="store_true",
                   help="emit JSON on stdout (for skill integration)")
    return p


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_scan(mod, cfg: dict, days: int, project: str | None) -> list:
    return mod.scan(
        cfg["vault"],
        cfg["sessions_folder"],
        cfg["insights_folder"],
        days,
        project=project,
    )


def _print_report_human(issues_by_check: dict) -> None:
    total = sum(len(v) for v in issues_by_check.values())
    print(f"\nvault_doctor report — {total} issue(s) across {len(issues_by_check)} check(s)", file=sys.stderr)
    for check_name, issues in issues_by_check.items():
        by_project: dict[str, list] = {}
        for i in issues:
            by_project.setdefault(i.project, []).append(i)
        for proj, proj_issues in sorted(by_project.items()):
            print(f"\n  Project: {proj}  [{check_name}]", file=sys.stderr)
            for i in proj_issues:
                mark = "!" if i.extra.get("unresolved") else "x"
                print(f"    {mark} {Path(i.note_path).name}", file=sys.stderr)
                print(f"      current:  {i.current_source}", file=sys.stderr)
                print(f"      proposed: {i.proposed_source or '(unresolved)'}", file=sys.stderr)
                print(f"      reason:   {i.reason}", file=sys.stderr)


def main() -> int:
    args = _build_parser().parse_args()

    if args.days is not None and args.days <= 0:
        print(
            f"error: --days must be positive, got {args.days}",
            file=sys.stderr,
        )
        return 3

    cfg = _load_config(args)

    if args.check:
        try:
            modules = [vault_doctor_checks.get_check(args.check)]
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
    else:
        modules = vault_doctor_checks.all_checks()

    if not modules:
        print("error: no checks registered", file=sys.stderr)
        return 3

    issues_by_check: dict = {}
    for mod in modules:
        days = args.days if args.days is not None else getattr(mod, "DEFAULT_WINDOW_DAYS", 7)
        issues = _run_scan(mod, cfg, days, args.project)
        if issues:
            issues_by_check[mod.NAME] = issues

    total_issues = sum(len(v) for v in issues_by_check.values())

    # JSON output for skill consumption
    if args.json_out:
        payload = {
            "timestamp": _iso_now(),
            "total_issues": total_issues,
            "issues": [
                {
                    "check": i.check,
                    "note_path": i.note_path,
                    "project": i.project,
                    "current_source": i.current_source,
                    "proposed_source": i.proposed_source,
                    "reason": i.reason,
                    "confidence": i.confidence,
                    "unresolved": i.extra.get("unresolved", False),
                    "capture_signal": i.extra.get("capture_signal", ""),
                    "capture_confidence": i.extra.get("capture_confidence", 0.0),
                    "convergence_warning": i.extra.get("convergence_warning", False),
                    "convergence_count": i.extra.get("convergence_count", 0),
                }
                for issues in issues_by_check.values() for i in issues
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_report_human(issues_by_check)

    if total_issues == 0:
        print("vault_doctor: clean", file=sys.stderr)
        return 0

    if not args.apply:
        return 1  # issues found, not applied (dry-run default)

    # --apply: per-project confirmation
    backup_root = os.path.expanduser(
        f"~/.claude/obsidian-brain-doctor-backup/{_iso_now().replace(':', '-')}"
    )
    print(f"\nBackup root: {backup_root}", file=sys.stderr)

    any_errors = False
    for mod in modules:
        issues = issues_by_check.get(mod.NAME, [])
        if not issues:
            continue
        by_project: dict[str, list] = {}
        for i in issues:
            by_project.setdefault(i.project, []).append(i)
        for proj, proj_issues in sorted(by_project.items()):
            resolvable = [i for i in proj_issues if not i.extra.get("unresolved")]
            if not resolvable:
                continue
            if not args.yes:
                sys.stderr.write(
                    f"Apply {len(resolvable)} fix(es) for project '{proj}' "
                    f"in check '{mod.NAME}'? [y/N] "
                )
                sys.stderr.flush()
                answer = sys.stdin.readline().strip().lower()
                if answer not in ("y", "yes"):
                    print(f"  skipped {proj}", file=sys.stderr)
                    continue
            results = mod.apply(resolvable, backup_root)
            for r in results:
                status_mark = {"applied": "+", "unresolved": "!", "error": "x", "skipped": "-"}.get(
                    r.status, "?"
                )
                print(f"  {status_mark} {r.status}  {Path(r.note_path).name}", file=sys.stderr)
                if r.status == "error":
                    any_errors = True

    return 2 if any_errors else 1


if __name__ == "__main__":
    sys.exit(main())
