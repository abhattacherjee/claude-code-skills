#!/usr/bin/env python3
"""check-cites.py — check each finding's file:line before an implementer acts on it.

Usage: check-cites.py --diff <file> --findings <file> [--repo <dir>]
                      [--status <status>] [--id <ID> ...]

The diff and the findings come from untrusted text and from models that read it.
A finding passes only when:
  - it has an id and a path;
  - the path is relative, stays inside the repo (no "..", no symlink out), and is a
    file the diff adds or changes (deleted files do not count);
  - the file exists in the repo now; and
  - its line, when not null, is a whole number from 1 to the file's line count.

--findings takes {"findings": [...]}, a bare list, or synthesize.py's report.json.
With no --status or --id, every finding is checked. --status survivor checks those
with that status; each --id adds that finding (for example an R3 concession). An
--id that is not in the file is a failure.

Prints one line per failing finding, "<id> <reason>", and a count on stderr. A
cited line that passes but sits outside every hunk of the diff gets a "note:" line
on stderr; it does not fail, since a real finding can cite an unchanged caller.

Exit codes:
  0  every selected finding passed
  2  usage error, the diff or findings cannot be read, --status was given but no
     finding has a status field, or an internal error (send nothing on)
  3  one or more findings failed
Exit 1 is never returned on purpose: it means Python crashed before main() ran.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

EXIT_OK, EXIT_USAGE, EXIT_FAILED = 0, 2, 3


class Unreadable(Exception):
    pass


def repo_root():
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return os.getcwd()
    top = proc.stdout.strip()
    return top if proc.returncode == 0 and top else os.getcwd()


def load_findings(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise Unreadable("cannot read %s: %s" % (path, exc))
    items = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise Unreadable("%s has no findings list" % path)
    return items


def problem(finding, diff_paths, repo):
    """Why this finding's citation does not hold, or None if it does."""
    path = finding.get("path")
    if not isinstance(path, str) or not path.strip():
        return "has no path"
    if os.path.isabs(path) or ".." in Path(path).parts:
        return "path %r is outside the repo" % path
    rel = os.path.normpath(path)
    if rel not in diff_paths:
        return "path %r is not a file in the diff" % path
    full = os.path.realpath(os.path.join(repo, rel))
    if os.path.commonpath([full, repo]) != repo:
        return "path %r is outside the repo (a symlink points out)" % path
    if not os.path.isfile(full):
        return "path %r is not in the repo" % path
    line = finding.get("line")
    if line is None:
        return None
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return "line %r is not a line number" % (line,)
    try:
        with open(full, "rb") as fh:
            count = sum(1 for _ in fh)
    except OSError as exc:
        return "path %r cannot be read: %s" % (path, exc.strerror or exc)
    if line > count:
        return "line %d is past the end of %s (%d lines)" % (line, path, count)
    return None


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="check-cites.py", description="Check each finding's file:line against the diff and the repo. "
        "Exit codes: 0 all passed, 3 some failed, 2 usage, unreadable input or internal error.")
    p.add_argument("--diff", required=True, help="the diff the findings are about")
    p.add_argument("--findings", required=True, help="findings JSON, or synthesize.py's report.json")
    p.add_argument("--repo", help="repository root (default: git top level)")
    p.add_argument("--status", help="check only findings with this status (for example survivor)")
    p.add_argument("--id", action="append", default=[], dest="ids",
                   help="also check this finding id; repeat for more")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return check(args)
    except Exception as exc:  # noqa: BLE001 - a crash must never read as "some failed"
        print("check-cites: internal error (%s: %s); nothing was checked" % (type(exc).__name__, exc),
              file=sys.stderr)
        return EXIT_USAGE


def check(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from secret_scan import hunk_lines, new_side_paths
    try:
        try:
            with open(args.diff, "rb") as fh:
                diff_text = fh.read().decode("utf-8", "replace")
        except OSError as exc:
            raise Unreadable("cannot read %s: %s" % (args.diff, exc.strerror or exc))
        findings = load_findings(args.findings)
    except Unreadable as exc:
        print("check-cites: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    if args.status is not None and findings and not any("status" in f for f in findings):
        # Otherwise --status would pick nothing and the run would pass unchecked.
        print("check-cites: --status %s given, but no finding has a status field (pass "
              "synthesize.py's report.json, or leave --status out)" % args.status, file=sys.stderr)
        return EXIT_USAGE
    repo = os.path.realpath(args.repo or repo_root())
    diff_paths = {os.path.normpath(p) for p in new_side_paths(diff_text)}
    shown = {os.path.normpath(p): lines for p, lines in hunk_lines(diff_text).items()}

    failures = ["(entry %d) is not an object" % n for n, f in enumerate(findings, 1)
                if not isinstance(f, dict)]
    findings = [f for f in findings if isinstance(f, dict)]
    if args.status is None and not args.ids:
        selected = findings
    else:
        selected = [f for f in findings
                    if (args.status is not None and f.get("status") == args.status)
                    or (isinstance(f.get("id"), str) and f["id"] in args.ids)]
    present = {f["id"] for f in findings if isinstance(f.get("id"), str)}
    failures += ["%s not in the findings file" % fid for fid in args.ids if fid not in present]
    for f in selected:
        fid = f.get("id")
        if not isinstance(fid, str) or not fid:
            failures.append("(no id) has no id (path %r)" % (f.get("path"),))
            continue
        why = problem(f, diff_paths, repo)
        if why:
            failures.append("%s %s" % (fid, why))
        elif f.get("line") is not None and f["line"] not in shown.get(os.path.normpath(f["path"]), ()):
            print("note: %s line %d of %s is outside every hunk of the diff" % (fid, f["line"], f["path"]),
                  file=sys.stderr)
    for line in failures:
        print(line)
    print("check-cites: checked=%d failed=%d" % (len(selected), len(failures)), file=sys.stderr)
    return EXIT_FAILED if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
