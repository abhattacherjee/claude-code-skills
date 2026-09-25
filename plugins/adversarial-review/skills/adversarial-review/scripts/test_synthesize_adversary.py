"""The adversary_verdict key (old gemini_verdict files still load), synthesize.py
--adversary, and a Codex run from codex-review output to the round record."""
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
import codex_review as cr  # noqa: E402

SYNTH = HERE / "synthesize.py"
PR_AUDIT = HERE / "pr-audit.py"
GEMINI_REVIEW = HERE / "gemini-review.sh"
SHA1 = "1" * 40
OLD = "gemini_verdict"


def claude_finding(fid, title, key="adversary_verdict"):
    f = {"id": fid, "path": "src/a.py", "line": 3, "severity": "important", "category": "bug",
         "title": title, "rationale": "grounded", "origin": "claude", "claude_verdict": None,
         "status": "unconfirmed", "killed_by": None, "kill_reason": None}
    f[key] = None
    return f


def raw(title):
    return {"path": "src/b.py", "line": 5, "severity": "minor", "category": "perf",
            "title": title, "rationale": "loop in a loop"}


class Run:
    """Claude findings C-001 (confirmed by the adversary) and C-002 (refuted); adversary
    findings X-001 (confirmed by Claude) and X-002 (refuted).

    HOME and XDG_CACHE_HOME are temp dirs for every subprocess this fixture starts
    (synth, record, and any gemini-review call built on it), so a test never reads
    or writes the real user cache (Global Constraint; ruling F7)."""

    def __init__(self, test, key="adversary_verdict"):
        self.dir = Path(tempfile.mkdtemp(prefix="synth-adv-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.home = self.dir / "home"
        self.cache = self.dir / "cache"
        self.home.mkdir()
        self.cache.mkdir()
        self.claude = self.put("r1-claude.json", {"findings": [
            claude_finding("C-001", "Off by one", key), claude_finding("C-002", "Null deref", key)]})
        self.adv = self.put("r1-codex.json", cr.validate_find(
            {"findings": [raw("Quadratic scan"), raw("Useless copy")]}))
        verdicts = cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "line 3 skips the last item", "confidence": 0.9},
            {"id": "C-002", "verdict": "refute", "reason": "handled at line 9", "confidence": 0.8}]},
            {"C-001", "C-002"})
        for v in verdicts["verdicts"]:
            v[key] = v.pop("adversary_verdict")
        self.adv_verdicts = self.put("r2-codex-verdicts.json", verdicts)
        self.claude_verdicts = self.put("r2-claude-verdicts.json", {"verdicts": [
            {"id": "X-001", "claude_verdict": "confirm", "reason": "yes, line 5"},
            {"id": "X-002", "claude_verdict": "refute", "reason": "the copy is needed"}]})

    def put(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data))
        return path

    def env(self, **extra):
        e = dict(os.environ, HOME=str(self.home), XDG_CACHE_HOME=str(self.cache))
        e.update(extra)
        return e

    def synth(self, *flags):
        res = subprocess.run([sys.executable, str(SYNTH), "--claude-findings", str(self.claude),
                              "--claude-verdicts", str(self.claude_verdicts),
                              "--md", str(self.dir / "report.md"), "--json", str(self.dir / "report.json")]
                             + [str(f) for f in flags], capture_output=True, text=True, timeout=60,
                             env=self.env())
        report = json.loads((self.dir / "report.json").read_text()) if res.returncode == 0 else None
        return res, report

    def record(self, report_path, adversary="codex"):
        out = self.dir / "round-1.json"
        res = subprocess.run(
            [sys.executable, str(PR_AUDIT), "record", "--report-json", str(report_path),
             "--run-id", "ar-codex-1", "--skill", "adversarial-review", "--phase", "review",
             "--round", "1", "--adversary", adversary, "--head-sha", SHA1, "--out", str(out)],
            capture_output=True, text=True, timeout=60, env=self.env())
        return res, (json.loads(out.read_text()) if res.returncode == 0 else None)


def by_id(items):
    return {f["id"]: f for f in items}


class SynthesizeAdversaryTests(unittest.TestCase):
    def test_codex_labels_the_report(self):
        run = Run(self)
        res, report = run.synth("--adversary", "codex", "--adversary-findings", run.adv,
                                "--adversary-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("codex_on_claude: confirmed=1 refuted=1", res.stdout)
        self.assertIn("claude_on_codex: confirmed=1 refuted=1", res.stdout)
        self.assertNotIn("gemini", res.stdout)
        self.assertEqual(report["summary"]["adversary"], "codex")
        f = by_id(report["findings"])
        self.assertEqual((f["C-001"]["status"], f["X-001"]["status"]), ("survivor", "survivor"))
        self.assertEqual(f["C-001"]["adversary_verdict"], "confirm")
        self.assertEqual(f["C-002"]["killed_by"], "codex")
        self.assertEqual(f["X-002"]["killed_by"], "claude")
        self.assertEqual(f["X-001"]["origin"], "codex")
        md = (run.dir / "report.md").read_text()
        self.assertIn("> Confirmed by Codex.", md)
        self.assertIn("> Confirmed by Claude.", md)
        self.assertNotIn("Gemini", md)

    def test_default_is_still_gemini(self):
        run = Run(self)
        res, report = run.synth("--gemini-findings", run.adv, "--gemini-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("gemini_on_claude: confirmed=1 refuted=1", res.stdout)
        self.assertEqual(report["summary"]["adversary"], "gemini")
        self.assertEqual(by_id(report["findings"])["C-002"]["killed_by"], "gemini")

    def test_unknown_adversary_is_a_usage_error(self):
        run = Run(self)
        res, _ = run.synth("--adversary", "claude-only", "--gemini-findings", run.adv,
                           "--gemini-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 2)
        # argparse's own choices-rejection is what actually fires here; without
        # this the guard could vanish and the test would stay green for the
        # wrong reason (ruling F8).
        self.assertIn("invalid choice", res.stderr)

    def test_codex_run_becomes_a_valid_round_record(self):
        run = Run(self)
        res, _ = run.synth("--adversary", "codex", "--adversary-findings", run.adv,
                           "--adversary-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 0, res.stderr)
        rec_res, rec = run.record(run.dir / "report.json")
        self.assertEqual(rec_res.returncode, 0, rec_res.stderr)
        ar.validate(rec)
        f = by_id(rec["findings"])
        self.assertEqual(f["C-002"]["events"], [
            {"by": "codex", "kind": "verdict", "verdict": "refute", "text": "handled at line 9"}])
        self.assertEqual(f["X-002"]["events"][0]["by"], "claude")
        self.assertEqual(f["X-001"]["origin"], "codex")

    def test_new_output_never_writes_the_old_key(self):
        run = Run(self)
        res, _ = run.synth("--adversary", "codex", "--adversary-findings", run.adv,
                           "--adversary-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(OLD, (run.dir / "report.json").read_text())


class UnjudgedTests(unittest.TestCase):
    """Task 4 carry-forward: codex-review's judge mode can return partial verdicts
    (validate_judge drops missing/unknown ids) with exit 0. A Claude finding the
    adversary never judged at all must stay unconfirmed (never silently confirmed),
    and synthesize must surface how many findings, per direction, got no verdict."""

    def test_unjudged_findings_stay_unconfirmed_and_are_surfaced(self):
        d = Path(tempfile.mkdtemp(prefix="synth-adv-unjudged-"))
        self.addCleanup(shutil.rmtree, d, True)
        home, cache = d / "home", d / "cache"
        home.mkdir()
        cache.mkdir()
        env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(cache))

        claude = d / "r1-claude.json"
        claude.write_text(json.dumps({"findings": [
            claude_finding("C-001", "Off by one"),
            claude_finding("C-002", "Null deref"),
            claude_finding("C-003", "Race condition"),
        ]}))
        adv = d / "r1-codex.json"
        adv.write_text(json.dumps(cr.validate_find({"findings": [raw("Quadratic scan")]})))
        # C-003 never appears in Codex's answer -- exactly what validate_judge
        # produces when Codex's own output omits or misspells an id: the verdict
        # is dropped, not defaulted to anything.
        adv_verdicts = d / "r2-codex-verdicts.json"
        adv_verdicts.write_text(json.dumps(cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "line 3 skips the last item",
             "confidence": 0.9},
            {"id": "C-002", "verdict": "refute", "reason": "handled at line 9", "confidence": 0.8},
            {"id": "NOPE", "verdict": "confirm", "reason": "unknown id", "confidence": 0.5},
        ]}, {"C-001", "C-002", "C-003"})))
        claude_verdicts = d / "r2-claude-verdicts.json"
        claude_verdicts.write_text(json.dumps({"verdicts": []}))
        md, out = d / "report.md", d / "report.json"

        res = subprocess.run(
            [sys.executable, str(SYNTH), "--claude-findings", str(claude),
             "--claude-verdicts", str(claude_verdicts), "--adversary", "codex",
             "--adversary-findings", str(adv), "--adversary-verdicts", str(adv_verdicts),
             "--md", str(md), "--json", str(out)],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("codex_on_claude: confirmed=1 refuted=1", res.stdout)
        self.assertIn("unjudged=1", res.stdout)

        report = json.loads(out.read_text())
        f = by_id(report["findings"])
        self.assertEqual(f["C-003"]["status"], "unconfirmed")
        self.assertIsNone(f["C-003"]["adversary_verdict"])
        self.assertEqual(report["summary"]["unjudged"]["codex_on_claude"], 1)
        # Claude never judged the one adversary finding either (empty claude-verdicts).
        self.assertEqual(report["summary"]["unjudged"]["claude_on_codex"], 1)


class LegacyKeyTests(unittest.TestCase):
    def test_synthesize_reads_old_gemini_verdict_files(self):
        run = Run(self, key=OLD)
        self.assertIn(OLD, run.adv_verdicts.read_text())
        res, report = run.synth("--gemini-findings", run.adv, "--gemini-verdicts", run.adv_verdicts)
        self.assertEqual(res.returncode, 0, res.stderr)
        f = by_id(report["findings"])
        self.assertEqual((f["C-001"]["status"], f["C-002"]["status"]), ("survivor", "rejected"))
        self.assertEqual(f["C-001"]["adversary_verdict"], "confirm")
        self.assertNotIn(OLD, (run.dir / "report.json").read_text())

    def test_pr_audit_record_reads_an_old_report(self):
        """Regression guard, not a fail-first test: pr-audit.py record already read
        gemini_verdict before this change (ruling F4). Negative control (d) in the
        brief proves this test actually exercises the fallback read."""
        run = Run(self)
        old_report = run.put("old-report.json", {"findings": [dict(
            claude_finding("C-002", "Null deref", OLD), status="rejected",
            killed_by="gemini", kill_reason="handled at line 9", **{OLD: "refute"})]})
        res, rec = run.record(old_report, adversary="gemini")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(rec["findings"][0]["events"], [
            {"by": "gemini", "kind": "verdict", "verdict": "refute", "text": "handled at line 9"}])

    def test_gemini_review_renames_the_old_key_from_the_model(self):
        run = Run(self)
        bindir = run.dir / "bin"
        bindir.mkdir()
        stub = bindir / "gemini"
        stub.write_text("#!/usr/bin/env bash\nprintf '%s\\n' '{\"verdicts\":[{\"id\":\"C-001\",\""
                        + OLD + "\":\"confirm\",\"reason\":\"r\",\"confidence\":0.9}]}'\n")
        stub.chmod(0o755)
        env = run.env(PATH=str(bindir) + os.pathsep + os.environ["PATH"])
        res = subprocess.run(["bash", str(GEMINI_REVIEW), "--diff", str(run.claude), "--findings",
                              str(run.claude), "--mode", "judge"], capture_output=True, text=True,
                             env=env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        [v] = json.loads(res.stdout)["verdicts"]
        self.assertEqual(v["adversary_verdict"], "confirm")
        self.assertNotIn(OLD, v)


if __name__ == "__main__":
    unittest.main()
