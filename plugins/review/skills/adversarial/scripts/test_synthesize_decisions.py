"""R3 tiebreak decisions reach the synthesis reports."""
import unittest

from test_synthesize_adversary import Run, by_id


class SynthesizeDecisionsTests(unittest.TestCase):
    def synth(self, run, *flags):
        return run.synth("--adversary", "codex", "--adversary-findings", run.adv,
                         "--adversary-verdicts", run.adv_verdicts, *flags)

    def test_refuted_finding_survives(self):
        run = Run(self)
        decisions = run.put("decisions.json", {"decisions": [
            {"id": "X-002", "status": "survivor", "reason": "copy is unnecessary"}]})
        res, report = self.synth(run, "--decisions", decisions)
        self.assertEqual(res.returncode, 0, res.stderr)
        finding = by_id(report["findings"])["X-002"]
        self.assertEqual(finding["status"], "survivor")
        self.assertIsNone(finding["killed_by"])
        self.assertEqual(finding["decided_by"], "r3")
        self.assertEqual(finding["decision_reason"], "copy is unnecessary")
        self.assertEqual(finding["kill_reason"], "the copy is needed")
        self.assertEqual(report["summary"]["survivors"], 3)
        self.assertEqual(report["summary"]["rejected"], 1)
        self.assertEqual(report["summary"]["decided"], 1)
        md = (run.dir / "report.md").read_text()
        survivors = md.split("## Confirmed Findings (Survivors)")[1].split("## Unconfirmed")[0]
        self.assertIn("Useless copy", survivors)
        self.assertIn("Survivors: 3 | Unconfirmed: 0 | Rejected: 1", md)

    def test_confirmed_finding_rejected(self):
        run = Run(self)
        decisions = run.put("decisions.json", {"decisions": [
            {"id": "X-001", "status": "rejected", "reason": ""},
            {"id": "X-002", "status": "rejected", "reason": "still rejected"}]})
        res, report = self.synth(run, "--decisions", decisions)
        self.assertEqual(res.returncode, 0, res.stderr)
        findings = by_id(report["findings"])
        self.assertEqual(findings["X-001"]["status"], "rejected")
        self.assertEqual(findings["X-001"]["killed_by"], "r3")
        self.assertEqual(findings["X-001"]["decision_reason"], "")
        self.assertEqual(findings["X-002"]["killed_by"], "claude")
        self.assertEqual(report["summary"]["decided"], 2)

    def test_invalid_decisions_clear_reports(self):
        decision = {"id": "X-001", "status": "survivor", "reason": "ok"}
        cases = [
            ({"decisions": [dict(decision, id="X-999")]}, "X-999"),
            ({"decisions": [dict(decision, status="confirmed")]}, "X-001"),
            ({"decisions": [decision, decision]}, "X-001"),
            ({}, "<unknown>"),
            ([], "<unknown>"),
            ({"decisions": {}}, "<unknown>"),
            ({"decisions": [None]}, "<unknown>"),
            ({"decisions": [dict(decision, reason=None)]}, "X-001"),
        ]
        for data, fid in cases:
            with self.subTest(data=data):
                run = Run(self)
                self.synth(run)
                decisions = run.put("decisions.json", data)
                res, _ = self.synth(run, "--decisions", decisions)
                self.assertEqual(res.returncode, 5, res.stderr)
                self.assertIn(fid, res.stderr)
                self.assertFalse((run.dir / "report.json").exists())
                self.assertFalse((run.dir / "report.md").exists())

    def test_ambiguous_id_is_rejected(self):
        run = Run(self)
        run.claude = run.put("duplicate-findings.json", {"findings": [
            {"id": "X-001", "title": "Duplicate"}]})
        run.adv_verdicts = run.put("empty-verdicts.json", {"verdicts": []})
        decisions = run.put("decisions.json", {"decisions": [
            {"id": "X-001", "status": "survivor", "reason": "ok"}]})
        res, _ = self.synth(run, "--decisions", decisions)
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertIn("X-001", res.stderr)
        self.assertIn("matches 2 findings", res.stderr)
        self.assertFalse((run.dir / "report.json").exists())

    def test_no_decisions_preserves_output(self):
        run = Run(self)
        res, report = self.synth(run)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(report["summary"]["decided"], 0)
        self.assertEqual(report["summary"]["survivors"], 2)
        self.assertEqual(report["summary"]["rejected"], 2)
        md = (run.dir / "report.md").read_text()
        empty = run.put("decisions.json", {"decisions": []})
        res, explicit = self.synth(run, "--decisions", empty)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(report, explicit)
        self.assertEqual(md, (run.dir / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
