"""CLI tests for pr-audit.py against a stateful `gh` stub."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_record as ar  # noqa: E402
PR_AUDIT = HERE / "pr-audit.py"
STUB = HERE / "fixtures" / "gh_stub.py"
SHA1, SHA2, SHA3 = "1" * 40, "2" * 40, "3" * 40
FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def finding(fid="X-001", **over):
    f = {
        "id": fid, "origin": "codex", "path": "src/a.py", "line": 41,
        "severity": "important", "category": "bug",
        "title": "Retry loop never resets the backoff",
        "rationale": "The delay doubles forever.",
        "status": "survivor", "events": [],
    }
    f.update(over)
    return f


def record(findings, rnd=1, head=SHA1, prev=None, **over):
    r = {
        "schema": "audit-round/v1", "run_id": "ar-test-1", "skill": "deep-review",
        "phase": "phase2", "round": rnd, "adversary": "codex",
        "head_sha": head, "prev_head_sha": prev, "findings": findings,
    }
    r.update(over)
    return r


def ev(kind, by="claude", text="because", **kw):
    e = {"by": by, "kind": kind, "text": text}
    e.update(kw)
    return e


class Harness:
    def __init__(self, test, **state):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-audit-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        bindir = self.dir / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "{STUB}" "$@"\n')
        gh.chmod(0o755)
        self.state_path = self.dir / "state.json"
        self.log_path = self.dir / "log.jsonl"
        self.state_path.write_text(json.dumps(state))
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "GH_STUB_STATE": str(self.state_path), "GH_STUB_LOG": str(self.log_path),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.fallback = self.dir / "fallback.md"

    def write(self, rec, name="round.json"):
        path = self.dir / name
        path.write_text(json.dumps(rec) if isinstance(rec, dict) else rec)
        return path

    def run(self, *args):
        return subprocess.run([sys.executable, str(PR_AUDIT), *map(str, args)],
                              capture_output=True, text=True, env=self.env, cwd=self.dir)

    def post(self, rec, name="round.json"):
        return self.run("post", "--pr", "7", "--repo", "octo/demo",
                        "--record", self.write(rec, name), "--fallback-out", self.fallback)

    def calls(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def posted(self, kind):
        out = []
        for c in self.calls():
            argv = c["argv"]
            if "-X" not in argv:
                continue
            ep = next(a for a in argv if a.startswith("repos/"))
            if (kind == "thread" and ep.endswith("/comments")) or \
               (kind == "reply" and ep.endswith("/replies")) or \
               (kind == "review" and ep.endswith("/reviews")):
                out.append(c)
        return out

    def resolves(self):
        return [c for c in self.calls() if c["argv"][:2] == ["api", "graphql"]
                and any("resolveReviewThread" in a for a in c["argv"])]

    def state(self):
        return json.loads(self.state_path.read_text())


class InputTests(unittest.TestCase):
    def test_malformed_record_exits_2_and_makes_no_calls(self):
        h = Harness(self)
        res = h.run("post", "--pr", "7", "--record", h.write("{not json"))
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("invalid record", res.stderr)
        self.assertEqual(h.calls(), [])

    def test_short_head_sha_exits_2(self):
        h = Harness(self)
        res = h.post(record([finding()], head="abc1234"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("head_sha", res.stderr)
        self.assertEqual(h.calls(), [])


class LocalTests(unittest.TestCase):
    def test_local_appends_markdown_without_markers(self):
        h = Harness(self)
        out = h.dir / "branch.adversarial-review.md"
        out.write_text("# existing report\n")
        rec = record([finding(events=[ev("verdict", verdict="confirm", text="Reproduced it.")])])
        res = h.run("local", "--record", h.write(rec), "--out", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = out.read_text()
        self.assertTrue(text.startswith("# existing report\n"))
        self.assertIn("Retry loop never resets the backoff", text)
        self.assertIn("**[Claude] verdict: confirm** — Reproduced it.", text)
        self.assertNotIn("<!-- audit:v1", text)
        self.assertEqual(h.calls(), [])

    def test_post_without_auth_falls_back_to_local(self):
        h = Harness(self, auth=False)
        res = h.post(record([finding()]))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not logged in", res.stdout)
        self.assertIn("Retry loop never resets the backoff", h.fallback.read_text())
        self.assertEqual([c["argv"][:2] for c in h.calls()], [["auth", "status"]])


class PostTests(unittest.TestCase):
    def test_first_round_opens_threads_and_posts_summary(self):
        h = Harness(self)
        rec = record([finding(events=[ev("verdict", verdict="confirm")]),
                      finding("X-002", path=None, title="No location")])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        threads = h.posted("thread")
        self.assertEqual(len(threads), 1)
        body = threads[0]["input"]
        self.assertEqual(body["commit_id"], SHA1)
        self.assertEqual((body["path"], body["line"], body["side"]), ("src/a.py", 41, "RIGHT"))
        self.assertTrue(body["body"].endswith("<!-- audit:v1 run=ar-test-1 finding=X-001 event=1.0 -->"))
        self.assertEqual(len(h.posted("reply")), 1)
        reviews = h.posted("review")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["input"]["event"], "COMMENT")
        self.assertEqual(reviews[0]["input"]["commit_id"], SHA1)
        summary = reviews[0]["input"]["body"]
        self.assertIn("| X-002 | important | codex | confirmed | no thread: no path |", summary)
        self.assertIn("Findings with no inline thread", summary)
        self.assertIn("posted 3,", res.stdout)

    def test_second_round_replies_to_existing_thread(self):
        h = Harness(self)
        self.assertEqual(h.post(record([finding()])).returncode, 0)
        second = record([finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])],
                        rnd=2, head=SHA2, prev=SHA1)
        res = h.post(second, "round2.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.posted("thread")), 1)
        replies = h.posted("reply")
        self.assertEqual(len(replies), 1)
        self.assertIn("/comments/1001/replies", " ".join(replies[0]["argv"]))
        self.assertIn("fixed in `2222222`", replies[0]["input"]["body"])
        self.assertEqual(h.resolves(), [])

    def test_refuted_is_resolved_in_same_run(self):
        h = Harness(self)
        rec = record([finding(status="rejected", events=[ev("verdict", verdict="refute")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.resolves()), 1)
        self.assertEqual(h.state()["resolved"], [1001])
        self.assertIn("resolved 1,", res.stdout)

    def test_fixed_stays_open_until_recheck(self):
        h = Harness(self)
        h.post(record([finding()]))
        h.post(record([finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])],
                      rnd=2, head=SHA2), "r2.json")
        self.assertEqual(h.resolves(), [])
        h.post(record([finding(events=[ev("recheck", by="codex", result="resolved")])],
                      rnd=3, head=SHA3), "r3.json")
        self.assertEqual(len(h.resolves()), 1)

    def test_422_falls_back_to_file_then_summary(self):
        h = Harness(self, reject_inline=[["src/a.py", 41], ["src/b.py", 9]], reject_file=["src/b.py"])
        rec = record([finding(), finding("X-002", path="src/b.py", line=9)])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        file_level = [c["input"] for c in h.posted("thread") if c["input"].get("subject_type") == "file"]
        self.assertEqual([c["path"] for c in file_level], ["src/a.py", "src/b.py"])
        comments = h.state()["comments"]
        self.assertEqual([c["path"] for c in comments], ["src/a.py"])
        summary = h.posted("review")[0]["input"]["body"]
        self.assertIn("| X-002 | important | codex | confirmed | no thread: GitHub rejected", summary)

    def test_rerun_posts_nothing(self):
        h = Harness(self)
        rec = record([finding(status="rejected", events=[ev("verdict", verdict="refute")])])
        h.post(rec)
        before = len(h.calls())
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        new = h.calls()[before:]
        self.assertEqual([c for c in new if "-X" in c["argv"]], [])
        self.assertIn("posted 0,", res.stdout)
        self.assertIn("skipped 3 already on the PR", res.stdout)

    def test_partial_rerun_posts_only_missing(self):
        h = Harness(self, fail=["reply"])
        rec = record([finding(events=[ev("verdict", verdict="confirm"), ev("counter", by="codex")])])
        first = h.post(rec)
        self.assertEqual(first.returncode, 1)
        state = h.state()
        state["fail"] = []
        h.state_path.write_text(json.dumps(state))
        second = h.post(rec)
        self.assertEqual(second.returncode, 0, second.stderr)
        bodies = [c["body"] for c in h.state()["comments"] if c["in_reply_to_id"]]
        self.assertEqual(len(bodies), 2)
        self.assertEqual(len(h.posted("thread")), 1)

    def test_partial_failure_exits_1_and_names_the_finding(self):
        h = Harness(self, fail=["reply"])
        rec = record([finding(events=[ev("verdict", verdict="confirm")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAILED X-001 reply 1.1", res.stderr)
        self.assertIn("failed 1,", res.stdout)
        self.assertIn("Posting failures: 1", h.posted("review")[0]["input"]["body"])

    def test_secret_is_redacted_everywhere(self):
        h = Harness(self)
        rec = record([finding(rationale=f"leaked {FAKE_GH}",
                              events=[ev("verdict", verdict="confirm", text=f"saw {FAKE_GH}")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        for c in h.calls():
            self.assertNotIn(FAKE_GH, json.dumps(c))
        self.assertIn("Redacted: 2", h.posted("review")[0]["input"]["body"])

    def test_oversize_rationale_is_truncated(self):
        h = Harness(self)
        res = h.post(record([finding(rationale="x" * 70000)]))
        self.assertEqual(res.returncode, 0, res.stderr)
        body = h.posted("thread")[0]["input"]["body"]
        self.assertLessEqual(len(body), 60000)
        self.assertIn("truncated", body)
        self.assertTrue(body.endswith("event=1.0 -->"))

    def test_other_run_ids_open_new_threads(self):
        h = Harness(self)
        h.post(record([finding()]))
        h.post(record([finding()], run_id="ar-test-2"), "other.json")
        self.assertEqual(len(h.posted("thread")), 2)

    def test_unknown_pr_exits_1_cleanly(self):
        h = Harness(self, fail=["read"])
        res = h.post(record([finding()]))
        self.assertEqual(res.returncode, 1)
        self.assertIn("could not read PR #7", res.stderr)
        self.assertNotIn("Traceback", res.stderr)


class ForgeryTests(unittest.TestCase):
    def test_forged_opener_from_other_user_is_ignored(self):
        h = Harness(self, comments=[{"id": 5, "body": "planted\n" + ar.marker("ar-test-1", "X-001", 1, 0),
                                     "user": "mallory", "html_url": "https://x/5", "in_reply_to_id": None,
                                     "path": "src/a.py", "line": 41}])
        res = h.post(record([finding(events=[ev("verdict", verdict="confirm")])]))
        self.assertEqual(res.returncode, 0, res.stderr)
        threads = h.posted("thread")
        self.assertEqual(len(threads), 1)
        replies = h.posted("reply")
        self.assertEqual(len(replies), 1)
        self.assertIn("/comments/1001/replies", " ".join(replies[0]["argv"]))

    def test_forged_summary_from_other_user_does_not_suppress(self):
        h = Harness(self, reviews=[{"id": 6, "body": ar.summary_marker("ar-test-1", 1, 1), "user": "mallory"}])
        res = h.post(record([finding()]))
        self.assertEqual(res.returncode, 0, res.stderr)
        reviews = h.posted("review")
        self.assertEqual(len(reviews), 1)

    def test_marker_not_on_last_line_is_ignored(self):
        h = Harness(self, comments=[{"id": 7, "body": ar.marker("ar-test-1", "X-001", 1, 0) + "\nedited later",
                                     "user": "audit-bot", "html_url": "https://x/7", "in_reply_to_id": None,
                                     "path": "src/a.py", "line": 41}])
        res = h.post(record([finding(events=[ev("verdict", verdict="confirm")])]))
        self.assertEqual(res.returncode, 0, res.stderr)
        threads = h.posted("thread")
        self.assertEqual(len(threads), 1)


REPORT = {"summary": {}, "findings": [
    {"id": "C-001", "origin": "claude", "path": "src/a.py", "line": 41, "severity": "important",
     "category": "bug", "title": "Off by one", "rationale": "Loop skips the last item.",
     "status": "survivor", "gemini_verdict": "confirm", "claude_verdict": None,
     "verdict_reason": "Reproduced with a 3-item list.", "kill_reason": None},
    {"id": "G-001", "origin": "gemini", "path": "", "line": "12", "severity": "minor",
     "category": "convention", "title": "Name", "rationale": None, "status": "rejected",
     "gemini_verdict": None, "claude_verdict": "refute", "verdict_reason": None,
     "kill_reason": "The name matches the module convention."},
    {"id": "C-002", "origin": "claude", "path": "src/c.py", "line": None, "severity": "minor",
     "category": None, "title": "Unjudged", "rationale": "x", "status": "unconfirmed",
     "gemini_verdict": None, "claude_verdict": None},
]}


class RecordTests(unittest.TestCase):
    def build(self, h, adversary="gemini"):
        report = h.write(json.dumps(REPORT), "report.json")
        out = h.dir / "round-1.json"
        res = h.run("record", "--report-json", report, "--run-id", "ar-20260924-1",
                    "--skill", "adversarial-review", "--phase", "review", "--round", "1",
                    "--adversary", adversary, "--head-sha", SHA1, "--out", out)
        return res, out

    def test_record_maps_verdicts_to_events(self):
        h = Harness(self)
        res, out = self.build(h)
        self.assertEqual(res.returncode, 0, res.stderr)
        rec = json.loads(out.read_text())
        by_id = {f["id"]: f for f in rec["findings"]}
        self.assertEqual(by_id["C-001"]["events"], [
            {"by": "gemini", "kind": "verdict", "verdict": "confirm",
             "text": "Reproduced with a 3-item list."}])
        self.assertEqual(by_id["G-001"]["events"][0]["by"], "claude")
        self.assertEqual(by_id["G-001"]["events"][0]["text"], "The name matches the module convention.")
        self.assertEqual((by_id["G-001"]["path"], by_id["G-001"]["line"]), (None, 12))
        self.assertEqual(by_id["G-001"]["rationale"], "")
        self.assertEqual(by_id["C-002"]["events"], [])
        self.assertEqual(by_id["C-002"]["category"], "other")

    def test_claude_only_writes_no_verdicts(self):
        h = Harness(self)
        res, out = self.build(h, adversary="claude-only")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(all(f["events"] == [] for f in json.loads(out.read_text())["findings"]))

    def test_record_output_posts_cleanly(self):
        # C-001 opens an inline thread. C-002 has a path but no line, so it opens a
        # file-level thread. G-001 has no path, so it appears in the summary only.
        h = Harness(self)
        _, out = self.build(h)
        res = h.run("post", "--pr", "7", "--repo", "octo/demo", "--record", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.posted("thread")), 2)
        self.assertEqual(len(h.posted("review")), 1)


if __name__ == "__main__":
    unittest.main()
