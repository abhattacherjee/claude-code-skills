#!/usr/bin/env python3
"""
Drive the production SessionEnd hook code path against a captured JSONL
fixture and emit a machine-readable outcome.

Usage:
    replay-sessionend.py --jsonl PATH --cwd PATH
                         [--mode sessionend|reaper] [--dry-run] [--json]

Modes:
    sessionend (default) — synthesize SessionEnd hook input dict and call
                           hooks.obsidian_session_log._run() directly.
    reaper               — call hooks.obsidian_session_reaper
                           ._reap_orphaned_sessions(); requires #125.

Exit codes:
    0 = ran to completion (outcome printed; may be SKIPPED_*, OK, EXCEPTION,
        or NO_LOG_LINE_EMITTED — caller inspects outcome= field)
    1 = bug in this script (e.g., malformed --json output)
    2 = argparse error or reaper module not yet imported (pre-#125)
    3 = vault-sentinel safety stop
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "hooks"))
sys.path.insert(0, str(_REPO_ROOT))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jsonl", required=True, type=Path)
    p.add_argument("--cwd", required=True, type=str)
    p.add_argument("--mode", choices=["sessionend", "reaper"], default="sessionend")
    p.add_argument("--dry-run", action="store_true",
                   help="Patch write_vault_note to record calls without writing")
    p.add_argument("--json", dest="emit_json", action="store_true",
                   help="Emit JSON object instead of human-readable key=value lines")
    return p.parse_args(argv)


def _check_vault_sentinel(config_path: Path) -> tuple[bool, str]:
    """Return (ok, message). If guard active and config's vault_path resolves
    under ~/obsidian/, refuse to run (hardcoded protection for the author's
    production vault path).
    """
    if os.environ.get("_REAL_VAULT_GUARD") != "1":
        return True, ""
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return True, ""  # No config yet — later code will handle it
    except json.JSONDecodeError:
        return True, ""  # Malformed config — _run() will surface it
    except OSError as exc:
        # PermissionError, IsADirectoryError, etc. — fail-safe (refuse to proceed).
        return False, f"cannot read config for vault-sentinel check: {exc}"
    vault = cfg.get("vault_path", "")
    real_vault = str(Path("~/obsidian").expanduser())
    resolved = str(Path(vault).expanduser().resolve()) if vault else ""
    # Append os.sep + equality check so ~/obsidian-work doesn't match ~/obsidian.
    if resolved == real_vault or resolved.startswith(real_vault + os.sep):
        return False, f"refusing to run: vault path {vault} appears to be the user's real vault"
    return True, ""


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        try:
            print(json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            print(f"BUG: JSON emit failed: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        for k, v in payload.items():
            print(f"{k}={v}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = Path(os.path.expanduser("~/.claude/obsidian-brain-config.json"))
    ok, msg = _check_vault_sentinel(config_path)
    if not ok:
        print(msg, file=sys.stderr)
        return 3

    if args.mode == "reaper":
        return _run_reaper(args)
    return _run_sessionend(args)


def _hook_log_path() -> Path:
    return Path(os.path.expanduser("~/.claude/obsidian-brain-hook.log"))


def _snapshot_log_size() -> int:
    p = _hook_log_path()
    return p.stat().st_size if p.exists() else 0


def _read_new_log_lines(pre_size: int) -> list[str]:
    """Read log lines appended since pre_size, surviving rotation.

    `_append_sessionend_log()` rotates at 100 KB via `os.replace()` — the
    new log file may be smaller than `pre_size`. In that case, seeking to
    pre_size lands past EOF and we'd silently miss the new SessionEnd line
    (false NO_LOG_LINE_EMITTED). Detect post-rotation shrink and re-read
    from offset 0.
    """
    p = _hook_log_path()
    if not p.exists():
        return []
    current_size = p.stat().st_size
    seek_to = pre_size if current_size >= pre_size else 0
    with open(p, "rb") as f:
        f.seek(seek_to)
        new = f.read().decode("utf-8", errors="replace")
    return [ln for ln in new.splitlines() if ln.strip()]


def _parse_sessionend_log_line(line: str) -> dict:
    """Extract key=value pairs after the SessionEnd marker."""
    # Format: <ISO8601> SessionEnd project=X sid=Y outcome=Z msgs=N dur=M detail=...
    out: dict[str, str] = {}
    if "SessionEnd" not in line:
        return out
    tail = line.split("SessionEnd", 1)[1].strip()
    # Tokenize on space, but `detail=...` may contain spaces — capture rest after detail=.
    parts = tail.split(" ")
    i = 0
    while i < len(parts):
        kv = parts[i]
        if "=" not in kv:
            i += 1
            continue
        k, v = kv.split("=", 1)
        if k == "detail":
            v = " ".join([v] + parts[i + 1:]).strip()
            out[k] = v
            break
        out[k] = v
        i += 1
    return out


def _stage_fixture_under_projects(jsonl: Path, cwd: str) -> Path:
    """Ensure the JSONL satisfies the production containment check at
    `~/.claude/projects/`. Two paths:

    1. If `jsonl` already resolves under `~/.claude/projects/`, return it
       as-is — no staging needed (containment check already passes, and
       copying would clobber a real session transcript with itself).
    2. Otherwise, copy to `~/.claude/projects/<slug>/replay-<stem>.jsonl`.
       The `replay-` prefix guarantees no collision with real CC session
       JSONLs (which are UUID-stemmed) even if someone passes a fixture
       whose stem happens to look UUID-like.

    Production `_run()` requires `transcript_path` to be inside
    `~/.claude/projects/` (containment check at obsidian_session_log.py:224).
    Without staging, every fixture replay would short-circuit with
    `SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS` and we'd never exercise the
    threshold/write/skip logic the bug actually lives in.

    WARNING: when invoked without HOME redirected to a tmpdir, this writes
    into the user's real `~/.claude/projects/<slug>/`. The `replay-` prefix
    prevents collision with real session JSONLs, but staged files do
    accumulate. Tests use `monkeypatch.setenv("HOME", tmp_path)`; the
    manual runner uses `tempfile.mkdtemp()`. Direct CLI invocation should
    set `HOME` first.
    """
    projects_root = Path(os.path.expanduser("~/.claude/projects")).resolve()
    try:
        resolved_jsonl = jsonl.resolve()
        # Path.is_relative_to is 3.9+; fall back to startswith for older.
        if str(resolved_jsonl).startswith(str(projects_root) + os.sep):
            return resolved_jsonl  # Already inside — no staging needed.
    except OSError:
        pass  # Resolution failed; fall through to staging.

    slug = "-" + cwd.lstrip("/").replace("/", "-")
    projects_dir = Path(os.path.expanduser("~/.claude/projects")) / slug
    projects_dir.mkdir(parents=True, exist_ok=True)
    staged = projects_dir / f"replay-{jsonl.stem}.jsonl"
    staged.write_bytes(jsonl.read_bytes())
    return staged


def _run_sessionend(args: argparse.Namespace) -> int:
    if not args.jsonl.exists():
        print(f"ERROR: --jsonl not found: {args.jsonl}", file=sys.stderr)
        return 2

    derived_sid = args.jsonl.stem  # basename without .jsonl
    try:
        staged_jsonl = _stage_fixture_under_projects(args.jsonl, args.cwd)
    except OSError as exc:
        print(
            f"ERROR: cannot stage fixture under ~/.claude/projects/: {exc}\n"
            f"  Hint: set HOME to a tmpdir to redirect ~/.claude/projects/.",
            file=sys.stderr,
        )
        return 2

    # Optionally patch write_vault_note for --dry-run.
    vault_writes: list[tuple[str, int]] = []
    original = None
    original_sl = None
    if args.dry_run:
        import obsidian_utils  # type: ignore
        original = obsidian_utils.write_vault_note

        def _record_call(vault_path, folder, filename, content, *a, **kw):  # noqa: ARG001
            # Match production signature: write_vault_note(vault_path, folder, filename, content).
            dest = str(Path(vault_path) / folder / filename)
            vault_writes.append((dest, len(content)))
            return None  # None = success under Optional[str] contract (truthy True was wrong)

        obsidian_utils.write_vault_note = _record_call  # type: ignore[assignment]
        # Also patch in the imported namespace inside obsidian_session_log
        # (it does `from obsidian_utils import write_vault_note`, binding
        # the reference at import time — patching the module above isn't enough).
        try:
            import obsidian_session_log  # type: ignore
            if hasattr(obsidian_session_log, "write_vault_note"):
                original_sl = obsidian_session_log.write_vault_note
                obsidian_session_log.write_vault_note = _record_call  # type: ignore[assignment]
        except ImportError:
            # Module not importable — leaves only obsidian_utils patched, which
            # is partial protection. Surface so the user knows --dry-run is incomplete.
            print(
                "WARNING: --dry-run: obsidian_session_log not importable; "
                "vault-write suppression is partial",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"WARNING: --dry-run: failed to patch obsidian_session_log.write_vault_note: "
                f"{exc.__class__.__name__}: {exc} — vault writes may not be suppressed",
                file=sys.stderr,
            )

    pre = _snapshot_log_size()

    stdin_payload = {
        "session_id": derived_sid,
        "transcript_path": str(staged_jsonl.resolve()),
        "cwd": args.cwd,
    }

    payload: dict = {}
    try:
        import obsidian_session_log  # type: ignore
        # _run() reads from sys.stdin in production; we shim it to read our dict.
        import io
        original_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(stdin_payload))
        try:
            obsidian_session_log._run()
        finally:
            sys.stdin = original_stdin
    except SystemExit as exc:
        # _run() is a contract violation if it calls sys.exit() — main() does.
        # Surface even exit(0) so a regression in #123's universal-emit guarantee
        # doesn't hide behind a silent absorption.
        if exc.code in (0, None):
            print(
                "WARNING: _run() called sys.exit(0) — unexpected early exit; "
                "outcome may be incomplete",
                file=sys.stderr,
            )
            payload["outcome"] = "UNEXPECTED_SYSEXIT_0"
            payload["detail"] = "sys.exit(0) from within _run() — see #123"
        else:
            payload["outcome"] = "EXCEPTION"
            payload["detail"] = f"SystemExit({exc.code})"
    except Exception as exc:
        payload["outcome"] = "EXCEPTION"
        payload["detail"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if args.dry_run and original is not None:
            import obsidian_utils  # type: ignore
            obsidian_utils.write_vault_note = original  # type: ignore[assignment]
            if original_sl is not None:
                import obsidian_session_log  # type: ignore
                obsidian_session_log.write_vault_note = original_sl  # type: ignore[assignment]

    new_lines = _read_new_log_lines(pre)
    # Filter to lines whose sid= matches THIS run's derived_sid[:8]. Hooks
    # truncate sid to 8 chars in log lines (per memory
    # technical_load_config_cache_keyed_by_cwd_sid.md); without this filter,
    # a concurrent SessionEnd from another process could attribute its
    # outcome to our replay.
    sid_marker = f"sid={derived_sid[:8]}"
    sessionend_lines = [ln for ln in new_lines if "SessionEnd" in ln and sid_marker in ln]

    if not sessionend_lines and "outcome" not in payload:
        # CLI-side sentinel — NOT an _Outcome enum value.
        payload["outcome"] = "NO_LOG_LINE_EMITTED"
        payload["detail"] = "no SessionEnd line appended to hook log; #123 universal-emit regression"
        payload["msgs"] = ""
        payload["dur"] = ""
        payload["hook_log_line"] = ""
    elif sessionend_lines:
        parsed = _parse_sessionend_log_line(sessionend_lines[-1])
        payload.setdefault("outcome", parsed.get("outcome", "UNKNOWN"))
        payload["msgs"] = parsed.get("msgs", "")
        payload["dur"] = parsed.get("dur", "")
        payload["hook_log_line"] = sessionend_lines[-1]

    payload["vault_writes"] = vault_writes
    _emit(payload, args.emit_json)
    return 0


def _run_reaper(args: argparse.Namespace) -> int:
    try:
        from obsidian_session_reaper import _reap_orphaned_sessions  # type: ignore
    except ImportError:
        print("reaper module not yet implemented (#125)", file=sys.stderr)
        return 2

    if not args.jsonl.exists():
        print(f"ERROR: --jsonl not found: {args.jsonl}", file=sys.stderr)
        return 2

    # Load config to get vault_path + sessions_folder.
    config_path = Path(os.path.expanduser("~/.claude/obsidian-brain-config.json"))
    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: config not found at {config_path}; create it first", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read config: {exc}", file=sys.stderr)
        return 2

    vault_path = config.get("vault_path", "")
    # Default must match obsidian_utils._DEFAULTS["sessions_folder"] == "claude-sessions".
    # Using "sessions" was wrong and would misroute the reaper's dedupe lookup
    # when sessions_folder is absent from config.
    sessions_folder = config.get("sessions_folder", "claude-sessions")
    if not vault_path:
        print("ERROR: vault_path missing from config", file=sys.stderr)
        return 2

    # Derive project name from --cwd (basename, same as get_project_name()).
    project = Path(args.cwd).name or "unknown"

    # Stage the fixture under ~/.claude/projects/<slug>/ so the reaper's
    # _resolve_project_jsonl_dir() can find it. Use the same staging logic as
    # _run_sessionend but always stage (never skip) since the fixture needs to
    # live in the project dir for _reap_orphaned_sessions to pick it up.
    try:
        staged_jsonl = _stage_fixture_under_projects(args.jsonl, args.cwd)
    except OSError as exc:
        print(
            f"ERROR: cannot stage fixture under ~/.claude/projects/: {exc}\n"
            f"  Hint: set HOME to a tmpdir to redirect ~/.claude/projects/.",
            file=sys.stderr,
        )
        return 2

    # Set watermark to 0 so the staged fixture (mtime > 0) always passes the
    # watermark check. Write it under the same HOME-relative path the reaper uses.
    watermark_path = Path(os.path.expanduser("~/.claude")) / "obsidian-brain" / f"reaper-watermark-{project}"
    watermark_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    watermark_path.write_text("0")

    # Patch write_vault_note for --dry-run.
    vault_writes: list[tuple[str, int]] = []
    _originals: list = []
    if args.dry_run:
        import obsidian_utils  # type: ignore

        def _record_call(vault_path_arg, folder, filename, content, *a, **kw):  # noqa: ARG001
            dest = str(Path(vault_path_arg) / folder / filename)
            vault_writes.append((dest, len(content)))
            return None  # None = success in reaper's write_vault_note contract

        _originals.append((obsidian_utils, "write_vault_note", obsidian_utils.write_vault_note))
        obsidian_utils.write_vault_note = _record_call  # type: ignore[assignment]

        try:
            import obsidian_session_reaper  # type: ignore
            if hasattr(obsidian_session_reaper, "write_vault_note"):
                _originals.append((
                    obsidian_session_reaper, "write_vault_note",
                    obsidian_session_reaper.write_vault_note,
                ))
                obsidian_session_reaper.write_vault_note = _record_call  # type: ignore[assignment]
        except ImportError:
            pass

    payload: dict = {}
    try:
        result = _reap_orphaned_sessions(project, vault_path, sessions_folder, config)
        # Determine a single top-level outcome key for easy assertion.
        if result.skipped_permission_blocked:
            payload["outcome"] = "SKIPPED_PERMISSION_BLOCKED"
        elif result.reaped > 0:
            payload["outcome"] = "REAPED_OK"
        elif result.skipped_below_threshold > 0:
            payload["outcome"] = "SKIPPED_BELOW_THRESHOLD"
        elif result.skipped_already_written > 0:
            payload["outcome"] = "SKIPPED_ALREADY_WRITTEN"
        elif result.timeout:
            payload["outcome"] = "TIMEOUT"
        else:
            payload["outcome"] = "NO_ORPHANS"
        payload["reaped"] = result.reaped
        payload["skipped_below_threshold"] = result.skipped_below_threshold
        payload["skipped_already_written"] = result.skipped_already_written
        payload["skipped_permission_blocked"] = result.skipped_permission_blocked
        payload["timeout"] = result.timeout
        payload["wall_ms"] = result.wall_ms
    except Exception as exc:
        payload["outcome"] = "EXCEPTION"
        payload["detail"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if args.dry_run:
            for mod, attr, orig in _originals:
                setattr(mod, attr, orig)

    payload["vault_writes"] = vault_writes
    _emit(payload, args.emit_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
