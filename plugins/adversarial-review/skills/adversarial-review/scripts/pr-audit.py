#!/usr/bin/env python3
"""pr-audit.py — save one review round's model exchange on a PR as an audit trail.

Usage:
  pr-audit.py post   --pr N --record ROUND.json [--repo OWNER/NAME] [--fallback-out FILE]
  pr-audit.py local  --record ROUND.json --out FILE
  pr-audit.py record --report-json REPORT.json --run-id ID --skill SKILL --phase PHASE
                     --round K --adversary ADV --head-sha SHA [--prev-head-sha SHA]
                     --out ROUND.json

Each finding gets one inline thread; each later event is a reply in it; each
round gets one COMMENT review with a summary table. Earlier threads are found by
a hidden marker, so no local state is kept. Without gh (or when logged out),
post writes the same content to the local markdown file instead.

Exit codes: 0 ok, 1 one or more posts failed, 2 usage error or invalid record.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_record as ar  # noqa: E402

LOCAL_SUFFIX = ".adversarial-review.md"


class GhError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def gh(args, payload=None):
    """Run gh and return stdout. Raise GhError with .status=422 on validation failures."""
    try:
        proc = subprocess.run(
            ["gh", *args], input=None if payload is None else json.dumps(payload),
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise GhError("gh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh timed out after 60s") from exc
    if proc.returncode != 0:
        err = proc.stderr.strip() or f"gh exited {proc.returncode}"
        raise GhError(err, 422 if "(HTTP 422)" in err else None)
    return proc.stdout


def gh_ready():
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True,
                              timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_record(path):
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        ar.validate(rec)
    except (OSError, json.JSONDecodeError, ar.RecordError) as exc:
        print(f"pr-audit: invalid record {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    return rec


def write_local(rec, out):
    text, counts = ar.markdown(rec)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write("\n" + text + "\n")
    return counts


def default_local_out():
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
    root = git("rev-parse", "--show-toplevel") or "."
    branch = (git("rev-parse", "--abbrev-ref", "HEAD") or "unknown-branch").replace("/", "-")
    return str(Path(root) / f"{branch}{LOCAL_SUFFIX}")


def cmd_local(args):
    rec = load_record(args.record)
    counts = write_local(rec, args.out)
    print(f"pr-audit: wrote round {rec['round']} to {args.out} "
          f"(redacted {sum(counts.values())})")
    return 0


def cmd_post(args):
    rec = load_record(args.record)
    if not gh_ready():
        out = args.fallback_out or default_local_out()
        print(f"pr-audit: gh is missing or not logged in; writing the audit trail to {out} instead.")
        write_local(rec, out)
        return 0
    return post_round(rec, args)


def post_round(rec, args):
    raise NotImplementedError("filled in by Task 5")


def build_parser():
    p = argparse.ArgumentParser(description="Save a review round's model exchange on a PR.")
    sub = p.add_subparsers(dest="cmd", required=True)
    post = sub.add_parser("post")
    post.add_argument("--pr", type=int, required=True)
    post.add_argument("--record", required=True)
    post.add_argument("--repo")
    post.add_argument("--fallback-out")
    local = sub.add_parser("local")
    local.add_argument("--record", required=True)
    local.add_argument("--out", required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "post":
        return cmd_post(args)
    return cmd_local(args)


if __name__ == "__main__":
    sys.exit(main())
