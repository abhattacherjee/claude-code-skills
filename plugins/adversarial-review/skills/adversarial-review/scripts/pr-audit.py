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


THREADS_QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first: 1) { nodes { databaseId } } }
      }
    }
  }
}"""
RESOLVE_MUTATION = """
mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"""


def json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class GitHub:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr
        self.base = f"repos/{repo}/pulls/{pr}"

    def login(self):
        return gh(["api", "user", "-q", ".login"]).strip()

    def comments(self):
        return json_lines(gh(["api", "--paginate", f"{self.base}/comments?per_page=100",
                              "--jq", ".[] | {id, body, html_url, user: .user.login}"]))

    def reviews(self):
        return json_lines(gh(["api", "--paginate", f"{self.base}/reviews?per_page=100",
                              "--jq", ".[] | {id, body, user: .user.login}"]))

    def new_thread(self, sha, path, line, body):
        payload = {"body": body, "commit_id": sha, "path": path}
        if line is None:
            payload["subject_type"] = "file"
        else:
            payload.update(line=line, side="RIGHT")
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/comments", "--input", "-"], payload))

    def reply(self, comment_id, body):
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/comments/{comment_id}/replies",
                              "--input", "-"], {"body": body}))

    def review(self, sha, body):
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/reviews", "--input", "-"],
                             {"commit_id": sha, "body": body, "event": "COMMENT"}))

    def threads(self):
        """Map each thread's first comment id to (thread node id, isResolved)."""
        owner, name = self.repo.split("/", 1)
        out, after = {}, None
        while True:
            args = ["api", "graphql", "-f", f"query={THREADS_QUERY}", "-f", f"owner={owner}",
                    "-f", f"name={name}", "-F", f"pr={self.pr}"]
            if after:
                args += ["-f", f"after={after}"]
            conn = json.loads(gh(args))["data"]["repository"]["pullRequest"]["reviewThreads"]
            for node in conn["nodes"]:
                first = node["comments"]["nodes"]
                if first:
                    out[first[0]["databaseId"]] = (node["id"], node["isResolved"])
            if not conn["pageInfo"]["hasNextPage"]:
                return out
            after = conn["pageInfo"]["endCursor"]

    def resolve(self, thread_id):
        gh(["api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-f", f"id={thread_id}"])


def open_thread(hub, rec, f, body):
    """Open a thread: inline, else file-level on a 422, else none. Returns (comment, note)."""
    path, line = f.get("path"), f.get("line")
    if not path:
        return None, "no path"
    if line is not None:
        try:
            return hub.new_thread(rec["head_sha"], path, line, body), None
        except GhError as exc:
            if exc.status != 422:
                raise
    try:
        return hub.new_thread(rec["head_sha"], path, None, body), None
    except GhError as exc:
        if exc.status != 422:
            raise
        return None, "GitHub rejected the inline and file comment (422)"


def post_round(rec, args):
    try:
        repo = args.repo or gh(["repo", "view", "--json", "nameWithOwner",
                                "-q", ".nameWithOwner"]).strip()
        hub = GitHub(repo, args.pr)
        me = hub.login()
        existing = hub.comments()
        reviews = hub.reviews()
    except GhError as exc:
        print(f"pr-audit: could not read PR #{args.pr}: {exc}", file=sys.stderr)
        return 1

    posted_markers, openers = set(), {}
    for c in existing:
        if c.get("user") != me:
            continue
        m = ar.parse_marker(ar.trailing_line(c.get("body")))
        if m:
            posted_markers.add(m["marker"])
            if m["run"] == rec["run_id"] and m["index"] == 0:
                openers.setdefault(m["finding"], c)

    n_posted = n_skipped = n_resolved = 0
    failures, rows, no_thread = [], [], []
    redacted = Counter()
    threads = None
    for f in rec["findings"]:
        fid = f["id"]
        opener = openers.get(fid)
        is_new, note = opener is None, None
        if opener is None:
            mark = ar.marker(rec["run_id"], fid, rec["round"], 0)
            body, red = ar.finalize(ar.opener_content(rec, f), mark)
            redacted += red
            try:
                opener, note = open_thread(hub, rec, f, body)
                n_posted += opener is not None
            except GhError as exc:
                failures.append((fid, "open thread", str(exc)))
                note = "posting failed"
        elif ar.parse_marker(opener["body"])["round"] == rec["round"]:
            n_skipped += 1

        if opener is None:
            no_thread.append(f)
        else:
            for idx, event in enumerate(f["events"], start=1):
                mark = ar.marker(rec["run_id"], fid, rec["round"], idx)
                if mark in posted_markers:
                    n_skipped += 1
                    continue
                body, red = ar.finalize(ar.event_content(rec, event), mark)
                redacted += red
                try:
                    hub.reply(opener["id"], body)
                    n_posted += 1
                except GhError as exc:
                    failures.append((fid, f"reply {rec['round']}.{idx}", str(exc)))
            if ar.should_resolve(f, rec):
                try:
                    if threads is None:
                        threads = hub.threads()
                    thread_id, done = threads.get(opener["id"], (None, True))
                    if thread_id and not done:
                        hub.resolve(thread_id)
                        n_resolved += 1
                except GhError as exc:
                    failures.append((fid, "resolve thread", str(exc)))
        rows.append({"id": fid, "severity": f["severity"], "origin": f["origin"],
                     "outcome": ar.outcome(f), "new": is_new,
                     "thread": opener.get("html_url") if opener else None, "note": note})

    details, red = ar.no_thread_details(rec, no_thread)
    redacted += red
    total_redacted = sum(redacted.values())
    own_summary_lines = {ar.trailing_line(r.get("body")) for r in reviews if r.get("user") == me}
    for i, body in enumerate(ar.summary_bodies(rec, rows, total_redacted, len(failures), details), 1):
        if ar.summary_marker(rec["run_id"], rec["round"], i) in own_summary_lines:
            n_skipped += 1
            continue
        try:
            hub.review(rec["head_sha"], body)
            n_posted += 1
        except GhError as exc:
            failures.append(("summary", f"part {i}", str(exc)))

    print(f"pr-audit: PR #{args.pr}: posted {n_posted}, skipped {n_skipped} already on the PR, "
          f"resolved {n_resolved}, failed {len(failures)}, redacted {total_redacted}")
    for fid, what, err in failures:
        print(f"pr-audit: FAILED {fid} {what}: {err}", file=sys.stderr)
    return 1 if failures else 0


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
