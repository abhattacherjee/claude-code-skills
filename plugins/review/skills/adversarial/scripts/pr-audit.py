#!/usr/bin/env python3
"""pr-audit.py — save one review round's model exchange on a PR as an audit trail.

Usage:
  pr-audit.py post   --pr N --record ROUND.json [--repo OWNER/NAME] [--fallback-out FILE]
  pr-audit.py local  --record ROUND.json --out FILE
  pr-audit.py record --report-json REPORT.json --run-id ID --skill SKILL --phase PHASE
                     --round K --adversary ADV --head-sha SHA [--prev-head-sha SHA]
                     --out ROUND.json
  pr-audit.py recheck --prior ROUND.json --rechecks MODEL_OUT.json --round K
                      [--adversary codex|gemini]
                      --head-sha SHA [--phase PHASE] [--gemini-sweep] --out ROUND.json

Each finding with a path gets one thread. It is inline when GitHub accepts the
line, file-level when GitHub rejects the line (HTTP 422) or there is no line,
and none when GitHub rejects both. Findings with no thread appear only in the
summary. Each later event is a reply in the finding's thread. Each round gets
one COMMENT review with a summary table; a long table is split over several
numbered reviews. Earlier threads and summaries are found by a hidden marker.
A rerun updates its own summary in place.

`post` spaces writes by PR_AUDIT_WRITE_GAP seconds (default 1, 0 disables the
gap). Processes share pacing and rate-limit deadlines through PR_AUDIT_STATE_DIR
(default ~/.cache/pr-audit). A rate-limited write gets up to PR_AUDIT_RETRIES
retries (4), using GitHub's wait time or exponential back-off starting at
PR_AUDIT_BACKOFF_BASE seconds (60). PR_AUDIT_BACKOFF_CAP (600 seconds) caps
each computed back-off; a wait GitHub names (Retry-After or x-ratelimit-reset)
is used in full. PR_AUDIT_RETRY_BUDGET (300 seconds) limits their sum per run.
PR_AUDIT_RUN_LIMIT (540 seconds, 0 for no limit) stops a run from starting or
waiting for a write that would pass it, so `post` reports before the Bash tool's
600 s cap. After any of these limits is reached, rerun later to post missing items.

`recheck` builds the record for an adversary re-check round: each earlier
finding the adversary re-checked gets one recheck event by the adversary, and
its new findings are added unconfirmed. An earlier finding the adversary did
not re-check is carried over unchanged with no events (its thread stays open),
and stderr reports `unchecked=<N> (<ids>)`; the exit is still 0, since the
record is valid, so the caller must read that count. A "resolved" re-check by the adversary
closes the thread when the record is posted. By default `recheck` is Codex-only: only
`codex-review.sh --mode find --prior` re-checks earlier findings against
current source, so a prior round whose adversary is not `codex` (Gemini or
Claude-only) is refused (exit 2). Pass --gemini-sweep when Codex refused the
re-check (ADVERSARY_REFUSED). --rechecks is then `gemini-review.sh --mode find`
output for the fix range: every earlier finding (Codex's and Claude's) is
carried over unchanged with no events, so no thread closes, and Gemini's
findings are added with origin gemini. Their severity is mapped as in `record`
(an unknown spelling becomes important and is noted in the rationale).
With --adversary gemini, --rechecks is Gemini find output with prior_status:
resolved findings whose origin is gemini or claude get closing recheck events,
as a Codex re-check closes Codex and Claude findings. Gemini never closes a
Codex finding: those stay open and are named on stderr. This cannot be combined with
--gemini-sweep.

When gh is missing, not logged in, or cannot read the PR, `post` says why on
stderr and exits 1. It writes the same content to a local markdown file only
when --fallback-out is given; otherwise it writes nothing. A gh call that
fails, or returns output that cannot be parsed, is a failed post.

Exit codes:
  0  everything was posted (or `local`/`record` succeeded)
  1  the trail is incomplete: some posts failed, or `post` could not reach the PR
     (the trail went to --fallback-out if given, else nowhere)
  2  usage error (including a bad PR_AUDIT_* setting), invalid record, or invalid report, or `record`/`recheck` could
     not write --out
  3  unexpected error (one line on stderr, no traceback); the trail may be partial
"""
import argparse
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_record as ar  # noqa: E402

LOCAL_SUFFIX = ".adversarial-review.md"


class GhError(RuntimeError):
    def __init__(self, message, status=None, *, rate_limited=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.rate_limited = rate_limited
        self.retry_after = retry_after


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


RUN_LIMIT_MESSAGE = "not attempted: run time limit reached"


def _error_items(errors):
    """(message, type) for each item of a response's `errors` list. An item is a string
    (a message) or an object; a field that is not a string reads as ""."""
    items = []
    for item in errors if isinstance(errors, list) else []:
        if isinstance(item, str):
            items.append((item, ""))
        elif isinstance(item, dict):
            text, kind = item.get("message"), item.get("type")
            items.append((text if isinstance(text, str) else "", kind if isinstance(kind, str) else ""))
    return items


def is_rate_limited(code, headers, body):
    """Decide from the parsed response alone. Only these exact signs count; free text
    elsewhere (stderr, a file path echoed in an error) never does."""
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):
        parsed = None
    parsed = parsed if isinstance(parsed, dict) else {}
    message = parsed.get("message")
    message = message.strip().lower() if isinstance(message, str) else ""
    errors = _error_items(parsed.get("errors"))
    exhausted = headers.get("x-ratelimit-remaining") == "0"
    if code == 429:
        return True
    if code == 403:
        return (exhausted or "retry-after" in headers
                or any(p in message for p in ("secondary rate limit", "abuse detection",
                                              "submitted too quickly"))
                or message.startswith("api rate limit exceeded"))
    if code == 200:  # GraphQL reports a rate limit as HTTP 200 with an error body
        return exhausted or any(kind == "RATE_LIMITED" for _, kind in errors)
    if code == 422:
        return any(text.strip().lower() == "was submitted too quickly" for text, _ in errors)
    return False


def write_response(proc):
    parts = re.split(r"\r?\n\r?\n", proc.stdout, maxsplit=1)
    body = parts[-1]
    if proc.returncode == 0:
        return body

    lines = parts[0].splitlines() if len(parts) == 2 else []
    status = re.match(r"HTTP/\S+\s+(\d{3})\b", lines[0]) if lines else None
    if not status:
        status = re.search(r"\(HTTP (\d{3})\)", proc.stderr)
    code = int(status[1]) if status else None
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.lower()] = value.strip()
    message = proc.stderr.strip() or f"gh exited {proc.returncode}"
    if is_rate_limited(code, headers, body):
        wait = finite_number(headers.get("retry-after"))
        if wait is None or wait < 0:
            reset = (finite_number(headers.get("x-ratelimit-reset"))
                     if headers.get("x-ratelimit-remaining") == "0" else None)
            wait = max(0.0, reset - time.time()) if reset is not None else None
        raise GhError(message, rate_limited=True, retry_after=wait)
    raise GhError(message, 422 if code == 422 else None)


def gh(args, payload=None):
    """Return gh's output, stripping HTTP headers for writes. A 422 status on
    GhError identifies a validation failure eligible for file-level fallback."""
    try:
        proc = subprocess.run(
            ["gh", *args], input=None if payload is None else json.dumps(payload),
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise GhError("gh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh timed out after 60s") from exc
    if args[:2] == ["api", "-i"]:
        return write_response(proc)
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
    out doesn't end with the local-fallback suffix. The deep skill writes local files
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


def write_record(rec, out):
    """Write a built record to --out. On failure say why and return False; the
    caller exits 2, since no usable record was made."""
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
    except OSError as exc:
        print(f"pr-audit: cannot write --out {out}: {exc}", file=sys.stderr)
        return False
    return True


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


def local_fallback_or_note(rec, reason, out):
    """The post paths' failure sink. An explicit --fallback-out gets the audit
    trail written there; without one, only the error is printed — inventing an
    unknown-branch file next to an unusable run made a failed post look
    recorded (#266)."""
    if out is None:
        print(f"pr-audit: {reason}; pass --fallback-out to keep a local copy.",
              file=sys.stderr)
        return
    print(f"pr-audit: {reason}; writing the audit trail to {out} instead.",
          file=sys.stderr)
    write_local(rec, out)


def pacing_number(name, default):
    name = f"PR_AUDIT_{name}"
    kind = type(default)
    try:
        value = kind(os.environ.get(name, default))
        if value >= 0 and (kind is int or math.isfinite(value)):
            return value
    except ValueError:
        pass
    unit = "integer" if kind is int else "finite number"
    raise ValueError(f"{name} must be a non-negative {unit}")


class WritePacer:
    def __init__(self):
        self.gap = pacing_number("WRITE_GAP", 1.0)
        self.retries = pacing_number("RETRIES", 4)
        self.base = pacing_number("BACKOFF_BASE", 60.0)
        self.cap = pacing_number("BACKOFF_CAP", 600.0)
        self.budget = pacing_number("RETRY_BUDGET", 300.0)
        self.run_limit = pacing_number("RUN_LIMIT", 540.0)
        self.started = time.monotonic()
        directory = os.environ.get("PR_AUDIT_STATE_DIR", "~/.cache/pr-audit")
        if not directory:
            raise ValueError("PR_AUDIT_STATE_DIR must be a non-empty path")
        self.directory = Path(os.path.expanduser(directory))
        self.last_write = self.blocked_until = 0.0
        self.blocked = False
        self.timed_out = False

    def _use_local_state(self, exc):
        print(f"pr-audit: note: write pacing is not shared ({exc})", file=sys.stderr)
        self.directory = None

    def _read_state(self):
        try:
            state = json.loads((self.directory / "write-pace.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, RecursionError):
            return
        if isinstance(state, dict):
            self.last_write = max(self.last_write, finite_number(state.get("last_write")) or 0.0)
            self.blocked_until = max(self.blocked_until, finite_number(state.get("blocked_until")) or 0.0)

    def out_of_time(self):
        """True when this run has used its run limit, or a write already stopped for it."""
        return self.timed_out or bool(
            self.run_limit and time.monotonic() - self.started >= self.run_limit)

    def _flock(self, lock):
        """Take the exclusive lock. With a run limit, poll and give up (False) once it is
        used up, so another process holding the lock cannot stall this run past the cap."""
        if not self.run_limit:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return True
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if self.out_of_time():
                    return False
                time.sleep(0.05)

    def _lock_state(self, files):
        """Lock and read the shared state. False when the run limit passed while waiting."""
        if self.directory is None:
            return True
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            lock = files.enter_context((self.directory / "write-pace.lock").open("a"))
            if not self._flock(lock):
                return False
            self._read_state()
        except OSError as exc:
            files.close()
            self._use_local_state(exc)
        return True

    def _save_state(self):
        if self.directory is not None:
            # The exclusive lock also protects the temporary file.
            tmp = self.directory / "write-pace.tmp"
            try:
                tmp.write_text(json.dumps({"last_write": self.last_write,
                                           "blocked_until": self.blocked_until}), encoding="utf-8")
                os.replace(tmp, self.directory / "write-pace.json")
            except OSError as exc:
                self._use_local_state(exc)

    def _run_limit_reached(self, last_error):
        """Stop all later writes. When a rate-limited write was waiting to retry, GitHub's
        limit is the reason this write failed, so keep that error and not the run-limit one."""
        self.blocked = True
        self.timed_out = last_error is None

    @contextmanager
    def _write_turn(self, last_error):
        """Release the lock to sleep, then recheck the shared deadlines before yielding."""
        while not self.blocked:
            with ExitStack() as files:
                if not self._lock_state(files):
                    self._run_limit_reached(last_error)
                    break
                now = time.time()
                ready = max(self.last_write + self.gap, self.blocked_until)
                wait = max(0.0, ready - now)
                if self.run_limit and time.monotonic() - self.started + wait > self.run_limit:
                    self._run_limit_reached(last_error)
                    break
                if wait == 0.0:
                    yield
                    return
                # A shared cooldown counts against this run's budget, even on
                # its first attempt. Any additional gap time is free.
                rate_wait = max(0.0, self.blocked_until - now)
                if rate_wait > self.budget:
                    self.blocked = True
                    break
                self.budget -= rate_wait
            time.sleep(ready - now)

        if self.timed_out:
            raise GhError(RUN_LIMIT_MESSAGE, rate_limited=True)
        if last_error is not None:
            raise last_error
        raise GhError("not attempted: GitHub's secondary rate limit", rate_limited=True)

    def write(self, args, payload=None):
        backoff = min(self.base, self.cap)
        last_error = None
        for attempt in range(self.retries + 1):
            with self._write_turn(last_error):
                wait = None
                try:
                    return gh(["api", "-i", *args], payload)
                except GhError as exc:
                    if not exc.rate_limited:
                        raise
                    wait = exc.retry_after if exc.retry_after is not None else backoff
                    if attempt == self.retries or wait > self.budget:
                        self.blocked = True
                        raise
                    last_error = exc
                    backoff = min(self.cap, 2 * backoff)
                finally:
                    self.last_write = time.time()
                    if wait is not None:
                        self.blocked_until = self.last_write + wait
                    self._save_state()


def cmd_post(args):
    try:
        pacer = WritePacer()
    except ValueError as exc:
        print(f"pr-audit: {exc}", file=sys.stderr)
        return 2
    rec = load_record(args.record)
    ready, reason = gh_ready()
    if not ready:
        local_fallback_or_note(rec, reason, args.fallback_out)
        return 1
    return post_round(rec, args, pacer)


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
    def __init__(self, repo, pr, pacer):
        self.repo, self.pr = repo, pr
        self.base = f"repos/{repo}/pulls/{pr}"
        self.pacer = pacer

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
        return json_object(self.pacer.write(["-X", "POST", f"{self.base}/comments", "--input", "-"],
                                            payload))

    def reply(self, comment_id, body):
        return json_object(self.pacer.write(["-X", "POST", f"{self.base}/comments/{comment_id}/replies",
                                             "--input", "-"], {"body": body}))

    def review(self, sha, body):
        return json_object(self.pacer.write(["-X", "POST", f"{self.base}/reviews", "--input", "-"],
                                            {"commit_id": sha, "body": body, "event": "COMMENT"}))

    def update_review(self, review_id, body):
        return json_object(self.pacer.write(["-X", "PUT", f"{self.base}/reviews/{review_id}",
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
        self.pacer.write(["graphql", "-f", f"query={RESOLVE_MUTATION}", "-f", f"id={thread_id}"])


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


def post_round(rec, args, pacer):
    try:
        repo = args.repo or gh(["repo", "view", "--json", "nameWithOwner",
                                "-q", ".nameWithOwner"]).strip()
        hub = GitHub(repo, args.pr, pacer)
        me = hub.login()
        existing = hub.comments()
        reviews = hub.reviews()
    except POST_ERRORS as exc:
        local_fallback_or_note(rec, f"could not read PR #{args.pr}: {exc}",
                               args.fallback_out)
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
                failures.append((fid, "open thread", exc))
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
                    failures.append((fid, f"reply {rec['round']}.{idx}", exc))
            if ar.should_resolve(f, rec):
                to_resolve.append((fid, opener))
        rows.append({"id": fid, "severity": f["severity"], "origin": f["origin"],
                     "outcome": ar.outcome(f), "new": is_new,
                     "thread": opener.get("html_url") if opener else None, "note": note})

    # Resolve in a second pass, after every thread this round has been opened (and
    # every reply posted), so a thread opened later in this same loop is not missed
    # by a threads() snapshot taken before it existed.
    if to_resolve and pacer.out_of_time():
        # Out of time: every resolve would be refused anyway, so skip the thread lookup.
        for fid, _ in to_resolve:
            failures.append((fid, "resolve thread", GhError(RUN_LIMIT_MESSAGE, rate_limited=True)))
    elif to_resolve:
        try:
            threads = hub.threads()
        except POST_ERRORS as exc:
            for fid, _ in to_resolve:
                failures.append((fid, "resolve thread", exc))
        else:
            for fid, opener in to_resolve:
                entry = threads.get(opener["id"])
                if entry is None:
                    failures.append((fid, "resolve thread", GhError("thread not found")))
                    continue
                thread_id, done = entry
                if done:
                    continue
                try:
                    hub.resolve(thread_id)
                    n_resolved += 1
                except POST_ERRORS as exc:
                    failures.append((fid, "resolve thread", exc))

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
            failures.append(("summary", f"part {i}", exc))

    print(f"pr-audit: PR #{args.pr}: posted {n_posted}, updated {n_updated}, "
          f"skipped {n_skipped} already on the PR, "
          f"resolved {n_resolved}, failed {len(failures)}, redacted {total_redacted}")
    rate_limited = out_of_time = 0
    for fid, what, exc in failures:
        print(f"pr-audit: FAILED {fid} {what}: {error_text(exc)}", file=sys.stderr)
        if isinstance(exc, GhError) and exc.rate_limited:
            if str(exc) == RUN_LIMIT_MESSAGE:
                out_of_time += 1
            else:
                rate_limited += 1
    if rate_limited:
        print(f"pr-audit: {rate_limited} of {len(failures)} failed posts hit GitHub's rate limit; "
              "rerun the same command later and it posts only what is missing", file=sys.stderr)
    if out_of_time:
        print(f"pr-audit: {out_of_time} of {len(failures)} failed posts were not attempted because "
              "the run reached PR_AUDIT_RUN_LIMIT; rerun the same command and it posts only what is "
              "missing", file=sys.stderr)
    return 1 if failures else 0


def _as_line(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value) or None
    return None


def _as_text(value, default):
    """A non-empty string as is; None or blank gives default; anything else as JSON text."""
    if isinstance(value, str):
        return value if value.strip() else default
    if value is None:
        return default
    return json.dumps(value)


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
    summary = report.get("summary")
    report_adversary = summary.get("adversary") if isinstance(summary, dict) else None
    if report_adversary is not None and report_adversary != args.adversary:
        print(f"pr-audit: --adversary {args.adversary!r} does not match "
              f"{args.report_json}'s summary.adversary {report_adversary!r}", file=sys.stderr)
        return 2
    findings = []
    for f in report.get("findings", []):
        origin = f.get("origin")
        if origin == "claude":
            judge = args.adversary
            verdict = f.get("adversary_verdict")
            if verdict is None:
                verdict = f.get("gemini_verdict")
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
    if not write_record(rec, args.out):
        return 2
    print(f"pr-audit: wrote {args.out} ({len(findings)} findings)")
    return 0


RECHECK_KEEP = ("id", "origin", "path", "line", "severity", "category", "title", "rationale", "status")


# Origins a Gemini re-check may close: its own and Claude's, never Codex's.
GEMINI_RECHECKS = ("gemini", "claude")


def cmd_recheck(args):
    if args.adversary == "gemini" and args.gemini_sweep:
        print("pr-audit: --gemini-sweep cannot be combined with --adversary gemini", file=sys.stderr)
        return 2
    prior = load_record(args.prior)
    if args.adversary == "codex" and prior["adversary"] != "codex":
        print(f"pr-audit: recheck rounds are Codex-only; {args.prior}'s adversary is "
              f"{prior['adversary']!r}", file=sys.stderr)
        return 2
    try:
        with open(args.rechecks, encoding="utf-8") as fh:
            out = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"pr-audit: cannot read {args.rechecks}: {exc}", file=sys.stderr)
        return 2
    if args.adversary == "gemini":
        if not isinstance(out, dict) or not isinstance(out.get("prior_status"), dict):
            print(f"pr-audit: {args.rechecks} needs a prior_status object; "
                  "run gemini-review.sh --mode find with --prior", file=sys.stderr)
            return 2
        earlier = {f["id"]: f for f in prior["findings"]}
        rechecks = []
        for fid, status in out["prior_status"].items():
            if fid not in earlier:
                print(f"pr-audit: warning: skipped a re-check for unknown id {fid!r}", file=sys.stderr)
                continue
            if earlier[fid]["origin"] not in GEMINI_RECHECKS:
                print(f"pr-audit: warning: {fid} is {earlier[fid]['origin']}'s finding, which Gemini "
                      "cannot close; its thread stays open",
                      file=sys.stderr)
                continue
            if status not in ("resolved", "unresolved"):
                print(f"pr-audit: invalid prior_status for {fid}: {status!r}", file=sys.stderr)
                return 2
            rechecks.append({"id": fid, "result": "resolved" if status == "resolved" else "missed"})
        out = dict(out, rechecks=rechecks, adversary="gemini")
    if args.gemini_sweep:
        # Codex refused the re-check (ADVERSARY_REFUSED), so --rechecks is the
        # output of gemini-review.sh --mode find on the fix range (#171). It holds
        # new findings only: nothing in it can close a Codex thread.
        if not isinstance(out, dict) or not isinstance(out.get("findings"), list) \
                or "rechecks" in out or "adversary" in out:
            print(f"pr-audit: --gemini-sweep needs {args.rechecks} to be gemini-review.sh --mode find "
                  "output: a findings list, no rechecks and no adversary key", file=sys.stderr)
            return 2
        for nf in out["findings"]:
            if not isinstance(nf, dict) or nf.get("origin") != "gemini":
                print(f"pr-audit: --gemini-sweep: every new finding needs origin 'gemini'; got "
                      f"{nf.get('origin') if isinstance(nf, dict) else nf!r}", file=sys.stderr)
                return 2
        out = dict(out, rechecks=[], adversary=prior["adversary"])
    if not isinstance(out, dict) or not isinstance(out.get("rechecks"), list):
        print(f"pr-audit: {args.rechecks} has no rechecks list; "
              "run codex-review.sh --mode find with --prior", file=sys.stderr)
        return 2
    if args.adversary == "codex" and out.get("adversary") != prior["adversary"]:
        print(f"pr-audit: {args.rechecks}'s adversary {out.get('adversary')!r} does not match "
              f"{args.prior}'s adversary {prior['adversary']!r}", file=sys.stderr)
        return 2
    if args.round <= prior["round"]:
        print(f"pr-audit: --round {args.round} must come after the prior round {prior['round']}",
              file=sys.stderr)
        return 2
    by = args.adversary
    earlier = {f["id"]: f for f in prior["findings"]}
    events = {}
    for item in out["rechecks"]:
        rid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(rid, str) or rid not in earlier or rid in events:
            print(f"pr-audit: warning: skipped a re-check for unknown or repeated id {rid!r}",
                  file=sys.stderr)
            continue
        events[rid] = [{"by": by, "kind": "recheck", "result": item.get("result"),
                        "text": item.get("reason") or ""}]
    # Every earlier finding stays in the record, in its earlier order. One the
    # adversary did not re-check is carried over unchanged with no events, so its
    # thread stays open and Step 2.6 still sees it as not resolved.
    findings, unchecked = [], []
    for fid, old in earlier.items():
        f = {k: old.get(k) for k in RECHECK_KEEP}
        f["events"] = events.get(fid, [])
        if fid not in events:
            unchecked.append(fid)
            if args.gemini_sweep:
                print(f"pr-audit: warning: Codex refused the re-check; {fid} not closed "
                      "(carried over with no events, so its thread stays open)", file=sys.stderr)
            else:
                print(f"pr-audit: warning: no re-check for {fid}; carried over with no events, "
                      "so its thread stays open", file=sys.stderr)
        findings.append(f)
    print(f"pr-audit: unchecked={len(unchecked)}" + (f" ({', '.join(unchecked)})" if unchecked else ""),
          file=sys.stderr)
    for nf in out.get("findings") or []:
        if not isinstance(nf, dict):
            continue
        if isinstance(nf.get("id"), str) and nf["id"] in earlier:
            print(f"pr-audit: new finding id {nf.get('id')} is already used in {args.prior}; "
                  f"rerun {'gemini' if args.gemini_sweep else by}-review.sh with a higher --id-start",
                  file=sys.stderr)
            return 2
        # Gemini has no output schema, so its fields are free-form: map the
        # severity as cmd_record does, and turn a non-string text field into a
        # string, so one odd value never fails the whole round.
        rationale = _as_text(nf.get("rationale"), "")
        path = nf.get("path")
        if path not in (None, "") and not isinstance(path, str):
            rationale = f"(path {path!r} was not a string) " + rationale
        severity, rationale = normalize_severity(nf.get("severity"), rationale)
        findings.append({
            "id": nf.get("id"), "origin": nf.get("origin") or by,
            "path": path if isinstance(path, str) and path else None,
            "line": _as_line(nf.get("line")), "severity": severity,
            "category": nf["category"] if isinstance(nf.get("category"), str)
            and nf["category"].strip() else "other",
            "title": _as_text(nf.get("title"), "(no title)"),
            "rationale": rationale, "status": "unconfirmed", "events": [],
        })
    rec = {"schema": ar.SCHEMA, "run_id": prior["run_id"], "skill": prior["skill"],
           "phase": args.phase, "round": args.round, "adversary": by,
           "head_sha": args.head_sha, "prev_head_sha": prior["head_sha"], "findings": findings}
    try:
        ar.validate(rec)
    except ar.RecordError as exc:
        print(f"pr-audit: the re-check does not make a valid record: {exc}", file=sys.stderr)
        return 2
    if not write_record(rec, args.out):
        return 2
    print(f"pr-audit: wrote {args.out} ({len(events)} re-checked, {len(unchecked)} unchecked, "
          f"{len(findings) - len(earlier)} new)")
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
    rc = sub.add_parser("recheck")
    rc.add_argument("--prior", required=True)
    rc.add_argument("--rechecks", required=True)
    rc.add_argument("--round", type=int, required=True)
    rc.add_argument("--head-sha", required=True)
    rc.add_argument("--phase", default="phase2-recheck")
    rc.add_argument("--adversary", choices=("codex", "gemini"), default="codex",
                    help="model re-checking its findings (default: codex)")
    rc.add_argument("--gemini-sweep", action="store_true",
                    help="Codex refused the re-check: --rechecks is gemini-review.sh --mode find "
                         "output; every earlier finding is carried over unchanged with no events, "
                         "so none is closed, and its findings are added with origin gemini")
    rc.add_argument("--out", required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "post":
        return cmd_post(args)
    if args.cmd == "recheck":
        return cmd_recheck(args)
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
