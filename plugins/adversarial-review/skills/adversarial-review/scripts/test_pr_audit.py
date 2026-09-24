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


if __name__ == "__main__":
    unittest.main()
