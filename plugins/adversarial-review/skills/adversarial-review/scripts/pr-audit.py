#!/usr/bin/env python3
"""pr-audit.py — save one review round's model exchange on a PR as an audit trail.

Usage:
  pr-audit.py post   --pr N --record ROUND.json [--repo OWNER/NAME] [--fallback-out FILE]
  pr-audit.py local  --record ROUND.json --out FILE
  pr-audit.py record --report-json REPORT.json --run-id ID --skill SKILL --phase PHASE
                     --round K --adversary ADV --head-sha SHA [--prev-head-sha SHA]
                     --out ROUND.json

Each finding with a path gets one thread. It is inline when GitHub accepts the
line, file-level when GitHub rejects the line (HTTP 422) or there is no line,
and none when GitHub rejects both. Findings with no thread appear only in the
summary. Each later event is a reply in the finding's thread. Each round gets
one COMMENT review with a summary table; a long table is split over several
numbered reviews. Earlier threads and summaries are found by a hidden marker,
so no local state is kept. A rerun updates its own summary in place.

When gh is missing, not logged in, or cannot read the PR, `post` says why,
writes the same content to the local markdown file instead, and exits 1. A gh
call that fails, or returns output that cannot be parsed, is a failed post.

Exit codes:
  0  everything was posted (or `local`/`record` succeeded)
  1  the trail is incomplete: some posts failed, or it went to the local file
  2  usage error, invalid record, or invalid report
  3  unexpected error (one line on stderr, no traceback); the trail may be partial
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
    """Run gh and return its stdout.

    Raise GhError on any failure: gh missing, a timeout, or a non-zero exit.
    GhError.status is 422 only when gh's stderr contains "(HTTP 422)"; it is
    None for every other failure.
    """
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


# What went wrong in a gh call that returned output. A bad response (invalid
# JSON, or JSON of the wrong shape) counts as a failed post, the same as GhError.
POST_ERRORS = (GhError, ValueError, KeyError, TypeError)


def gh_ready():
    """Return (ready, reason). ready is True when gh can read the account that will
    post; reason says why not. `gh api user` tests the token gh will actually use,
    on every gh version, and is not fooled by a logged-in account on another host."""
    try:
        proc = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True,
                              text=True, timeout=30)
    except FileNotFoundError:
        return False, "gh is not installed"
    except subprocess.TimeoutExpired:
        return False, "gh timed out checking the login"
    except OSError as exc:
        return False, f"gh could not run ({exc})"
    if proc.returncode != 0:
        err = " ".join(proc.stderr.split()) or f"gh exited {proc.returncode}"
        if "401" in err or "auth login" in err:
            return False, f"gh is not logged in ({err})"
        return False, f"gh could not check the login ({err})"
    if not proc.stdout.strip():
        return False, "gh returned no login"
    return True, ""


def load_record(path):
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        ar.validate(rec)
    except (OSError, json.JSONDecodeError, ar.RecordError) as exc:
        print(f"pr-audit: invalid record {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    return rec


GITIGNORE_PATTERN = "*.adversarial-review.md"


def ensure_gitignored(out):
    """When out is a *.adversarial-review.md file inside a git repo, make sure the
    pattern is in that repo's root .gitignore. No-op outside a git repo, or when
    out doesn't end with the local-fallback suffix. deep-review writes local files
    without going through sink.sh's own gitignore step, so this covers that path."""
    if not str(out).endswith(LOCAL_SUFFIX):
        return
    folder = Path(out).resolve().parent
    try:
        proc = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"pr-audit: could not run git ({exc}); not updating .gitignore", file=sys.stderr)
        return
    if proc.returncode != 0:
        print(f"pr-audit: {folder} is not in a git repo; not updating .gitignore", file=sys.stderr)
        return
    gitignore = Path(proc.stdout.strip()) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if GITIGNORE_PATTERN in existing.splitlines():
            return
        with open(gitignore, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(GITIGNORE_PATTERN + "\n")
    except OSError as exc:
        print(f"pr-audit: could not update {gitignore}: {exc}", file=sys.stderr)
        return
    print(f"pr-audit: added '{GITIGNORE_PATTERN}' to {gitignore}")


def write_local(rec, out):
    text, counts = ar.markdown(rec)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write("\n" + text + "\n")
    ensure_gitignored(out)
    return counts


def default_local_out():
    def git(*args):
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
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
    ready, reason = gh_ready()
    if not ready:
        out = args.fallback_out or default_local_out()
        print(f"pr-audit: {reason}; writing the audit trail to {out} instead.",
              file=sys.stderr)
        write_local(rec, out)
        return 1
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


def json_object(text):
    """Parse gh output that must be one JSON object. Raise ValueError otherwise."""
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object from gh, got {type(obj).__name__}")
    return obj


class GitHub:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr
        self.base = f"repos/{repo}/pulls/{pr}"

    def login(self):
        return gh(["api", "user", "-q", ".login"]).strip()

    def comments(self):
        return json_lines(gh(["api", "--paginate", f"{self.base}/comments?per_page=100",
                              "--jq", ".[] | {id, body, html_url, subject_type, line, "
                                      "user: .user.login}"]))

    def reviews(self):
        return json_lines(gh(["api", "--paginate", f"{self.base}/reviews?per_page=100",
                              "--jq", ".[] | {id, body, user: .user.login}"]))

    def new_thread(self, sha, path, line, body):
        payload = {"body": body, "commit_id": sha, "path": path}
        if line is None:
            payload["subject_type"] = "file"
        else:
            payload.update(line=line, side="RIGHT")
        return json_object(gh(["api", "-X", "POST", f"{self.base}/comments", "--input", "-"],
                              payload))

    def reply(self, comment_id, body):
        return json_object(gh(["api", "-X", "POST", f"{self.base}/comments/{comment_id}/replies",
                               "--input", "-"], {"body": body}))

    def review(self, sha, body):
        return json_object(gh(["api", "-X", "POST", f"{self.base}/reviews", "--input", "-"],
                              {"commit_id": sha, "body": body, "event": "COMMENT"}))

    def update_review(self, review_id, body):
        return json_object(gh(["api", "-X", "PUT", f"{self.base}/reviews/{review_id}",
                               "--input", "-"], {"body": body}))

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
        opener = hub.new_thread(rec["head_sha"], path, None, body)
    except GhError as exc:
        if exc.status != 422:
            raise
        return None, "GitHub rejected the inline and file comment (422)"
    return opener, anchor_note(f, opener)


def anchor_note(f, opener):
    """Say when a thread is file-level, so the summary shows the line anchor was lost.
    Worked out from the opener itself, so a rerun renders the same note. When the
    opener has no subject_type, a missing line means the thread is file-level."""
    subject = opener.get("subject_type")
    if subject is None:
        subject = "line" if opener.get("line") is not None else "file"
    if subject != "file":
        return None
    if f.get("line") is not None:
        return "inline rejected (422); file-level"
    return "file-level (no line)"


def error_text(exc):
    """GhError already carries gh's message; name the type for a bad response."""
    if isinstance(exc, GhError):
        return str(exc)
    return f"bad response from gh: {type(exc).__name__}: {exc}"


def post_round(rec, args):
    try:
        repo = args.repo or gh(["repo", "view", "--json", "nameWithOwner",
                                "-q", ".nameWithOwner"]).strip()
        hub = GitHub(repo, args.pr)
        me = hub.login()
        existing = hub.comments()
        reviews = hub.reviews()
    except POST_ERRORS as exc:
        print(f"pr-audit: could not read PR #{args.pr}: {exc}", file=sys.stderr)
        out = args.fallback_out or default_local_out()
        write_local(rec, out)
        print(f"pr-audit: wrote the audit trail to {out} instead.", file=sys.stderr)
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

    n_posted = n_skipped = n_resolved = n_updated = 0
    failures, rows, no_thread, to_resolve = [], [], [], []
    redacted = Counter()
    for f in rec["findings"]:
        fid = f["id"]
        opener = openers.get(fid)
        note = None
        # "new" means the thread was opened in this round, so a rerun of the same
        # round renders the same summary and does not rewrite it.
        is_new = opener is None or (
            ar.parse_marker(ar.trailing_line(opener["body"]))["round"] == rec["round"])
        if opener is None:
            mark = ar.marker(rec["run_id"], fid, rec["round"], 0)
            body, red = ar.finalize(ar.opener_content(rec, f), mark)
            redacted += red
            try:
                opener, note = open_thread(hub, rec, f, body)
                n_posted += opener is not None
            except POST_ERRORS as exc:
                failures.append((fid, "open thread", error_text(exc)))
                note = "posting failed"
        else:
            if is_new:
                n_skipped += 1
            note = anchor_note(f, opener)

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
                except POST_ERRORS as exc:
                    failures.append((fid, f"reply {rec['round']}.{idx}", error_text(exc)))
            if ar.should_resolve(f, rec):
                to_resolve.append((fid, opener))
        rows.append({"id": fid, "severity": f["severity"], "origin": f["origin"],
                     "outcome": ar.outcome(f), "new": is_new,
                     "thread": opener.get("html_url") if opener else None, "note": note})

    # Resolve in a second pass, after every thread this round has been opened (and
    # every reply posted), so a thread opened later in this same loop is not missed
    # by a threads() snapshot taken before it existed.
    if to_resolve:
        try:
            threads = hub.threads()
        except POST_ERRORS as exc:
            for fid, _ in to_resolve:
                failures.append((fid, "resolve thread", error_text(exc)))
        else:
            for fid, opener in to_resolve:
                entry = threads.get(opener["id"])
                if entry is None:
                    failures.append((fid, "resolve thread", "thread not found"))
                    continue
                thread_id, done = entry
                if done:
                    continue
                try:
                    hub.resolve(thread_id)
                    n_resolved += 1
                except POST_ERRORS as exc:
                    failures.append((fid, "resolve thread", error_text(exc)))

    details, red = ar.no_thread_details(rec, no_thread)
    redacted += red
    total_redacted = sum(redacted.values())
    # Our own earlier summary parts, by marker. A rerun rewrites a part in place
    # when its body changed (for example, a failure count that is now 0). If the
    # rerun needs fewer parts, the extra old parts are left as they are.
    own_summaries = {}
    for r in reviews:
        if r.get("user") == me:
            own_summaries.setdefault(ar.trailing_line(r.get("body")), r)
    for i, body in enumerate(ar.summary_bodies(rec, rows, total_redacted, len(failures), details), 1):
        old = own_summaries.get(ar.summary_marker(rec["run_id"], rec["round"], i))
        try:
            if old is None:
                hub.review(rec["head_sha"], body)
                n_posted += 1
            elif (old.get("body") or "").strip() == body.strip():
                n_skipped += 1
            else:
                hub.update_review(old["id"], body)
                n_updated += 1
        except POST_ERRORS as exc:
            failures.append(("summary", f"part {i}", error_text(exc)))

    print(f"pr-audit: PR #{args.pr}: posted {n_posted}, updated {n_updated}, "
          f"skipped {n_skipped} already on the PR, "
          f"resolved {n_resolved}, failed {len(failures)}, redacted {total_redacted}")
    for fid, what, err in failures:
        print(f"pr-audit: FAILED {fid} {what}: {err}", file=sys.stderr)
    return 1 if failures else 0


def _as_line(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value) or None
    return None


SEVERITY_ALIASES = {
    "critical": "critical", "important": "important", "minor": "minor",
    "high": "important", "low": "minor", "medium": "important",
}


def normalize_severity(raw, rationale):
    """Map a report's free-form severity to one of audit_record's SEVERITIES.

    Known aliases (case-insensitive) map silently. Anything else falls back to
    "important" and the raw value is noted in the rationale, so the record still
    validates instead of failing the whole round over one finding's severity spelling.
    """
    low = str(raw).strip().lower() if raw is not None else ""
    norm = SEVERITY_ALIASES.get(low)
    if norm is not None:
        return norm, rationale
    return "important", f"(severity was '{raw}') " + rationale


VERDICT_ALIASES = {"confirm": "confirm", "confirmed": "confirm",
                   "refute": "refute", "refuted": "refute"}


def cmd_record(args):
    try:
        with open(args.report_json, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"pr-audit: cannot read {args.report_json}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print(f"pr-audit: {args.report_json} is not a JSON object", file=sys.stderr)
        return 2
    findings = []
    for f in report.get("findings", []):
        origin = f.get("origin")
        if origin == "claude":
            judge, verdict = args.adversary, f.get("gemini_verdict")
        else:
            judge, verdict = "claude", f.get("claude_verdict")
        events = []
        rationale = f.get("rationale") or ""
        if args.adversary != "claude-only" and verdict not in (None, ""):
            norm = VERDICT_ALIASES.get(str(verdict).strip().lower())
            if norm:
                events.append({"by": judge, "kind": "verdict", "verdict": norm,
                               "text": f.get("verdict_reason") or f.get("kill_reason") or ""})
            else:
                print(f"pr-audit: warning: {f.get('id')}: verdict '{verdict}' was not recognised; "
                      "no verdict event written", file=sys.stderr)
                rationale = f"(verdict '{verdict}' was not recognised) " + rationale
        line = _as_line(f.get("line"))
        if line is None and f.get("line") not in (None, ""):
            rationale = f"(line '{f.get('line')}' was not a line number) " + rationale
        severity, rationale = normalize_severity(f.get("severity"), rationale)
        findings.append({
            "id": f.get("id"), "origin": origin, "path": f.get("path") or None,
            "line": line, "severity": severity,
            "category": f.get("category") or "other", "title": f.get("title") or "(no title)",
            "rationale": rationale, "status": f.get("status"), "events": events,
        })
    rec = {"schema": ar.SCHEMA, "run_id": args.run_id, "skill": args.skill, "phase": args.phase,
           "round": args.round, "adversary": args.adversary, "head_sha": args.head_sha,
           "prev_head_sha": args.prev_head_sha, "findings": findings}
    try:
        ar.validate(rec)
    except ar.RecordError as exc:
        print(f"pr-audit: report does not make a valid record: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    print(f"pr-audit: wrote {args.out} ({len(findings)} findings)")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Save a review round's model exchange on a PR.")
    sub = p.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--report-json", required=True)
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--skill", required=True, choices=sorted(ar.SKILLS))
    rec.add_argument("--phase", required=True)
    rec.add_argument("--round", type=int, required=True)
    rec.add_argument("--adversary", required=True, choices=sorted(ar.ADVERSARIES))
    rec.add_argument("--head-sha", required=True)
    rec.add_argument("--prev-head-sha")
    rec.add_argument("--out", required=True)
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
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "post":
        return cmd_post(args)
    return cmd_local(args)


def run(argv=None):
    """main() with a guard: an unexpected error prints one line and exits 3.
    Some posts may already be on the PR by then, so the trail may be partial."""
    try:
        return main(argv)
    except Exception as exc:  # noqa: BLE001 - the last line of defence
        print(f"pr-audit: unexpected error: {type(exc).__name__}: {exc}; "
              "the audit trail may be partial", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(run())
