"""Unit tests for codex_review.py. No subprocess and no Codex."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_review as cr  # noqa: E402

FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def raw_finding(**over):
    f = {"path": "src/a.py", "line": 41, "severity": "important", "category": "bug",
         "title": "Retry loop never resets the backoff", "rationale": "The delay doubles forever."}
    f.update(over)
    return f


class ValidateFindTests(unittest.TestCase):
    def test_numbers_findings_from_id_start_and_marks_origin(self):
        out = cr.validate_find({"findings": [raw_finding(), raw_finding(title="Second")]}, id_start=7)
        self.assertEqual([f["id"] for f in out["findings"]], ["X-007", "X-008"])
        f = out["findings"][0]
        self.assertEqual(f["origin"], "codex")
        for key in ("claude_verdict", "adversary_verdict", "status", "killed_by", "kill_reason"):
            self.assertIsNone(f[key], key)
        self.assertNotIn("rechecks", out)

    def test_model_supplied_ids_are_ignored(self):
        out = cr.validate_find({"findings": [raw_finding(id="C-001")]})
        self.assertEqual(out["findings"][0]["id"], "X-001")

    def test_missing_findings_list_is_bad_output(self):
        for raw in ({}, {"findings": "x"}, [], "text", None):
            with self.assertRaises(cr.BadOutput):
                cr.validate_find(raw)

    def test_hostile_output_is_capped_and_redacted(self):
        many = [raw_finding(title="t%d" % i) for i in range(500)]
        many[0] = raw_finding(title="leak " + FAKE_GH, rationale="x" * 1000000)
        out = cr.validate_find({"findings": many})
        self.assertEqual(len(out["findings"]), cr.MAX_FINDINGS)
        first = out["findings"][0]
        self.assertNotIn(FAKE_GH, first["title"])
        self.assertIn("[REDACTED:github-token]", first["title"])
        self.assertLessEqual(len(first["rationale"]), cr.MAX_TEXT)

    def test_paths_outside_the_repo_are_dropped(self):
        for bad in ("../../etc/hosts", "/etc/hosts", "src/../../x"):
            f = cr.validate_find({"findings": [raw_finding(path=bad)]})["findings"][0]
            self.assertIsNone(f["path"], bad)
            self.assertIn("outside the repo", f["rationale"])

    def test_bad_line_severity_and_category_are_normalised(self):
        f = cr.validate_find({"findings": [raw_finding(line="12", severity="blocker",
                                                       category="style")]})["findings"][0]
        self.assertIsNone(f["line"])
        self.assertEqual(f["severity"], "important")
        self.assertEqual(f["category"], "maintainability")
        for bad in (True, 0, -3, 2.5):
            f = cr.validate_find({"findings": [raw_finding(line=bad)]})["findings"][0]
            self.assertIsNone(f["line"], repr(bad))

    def test_findings_without_a_title_are_skipped(self):
        out = cr.validate_find({"findings": [raw_finding(title="  "), "junk", raw_finding()]})
        self.assertEqual([f["id"] for f in out["findings"]], ["X-001"])

    def test_rechecks_keep_only_known_ids_once(self):
        raw = {"findings": [], "rechecks": [
            {"id": "X-001", "result": "resolved", "reason": "fixed"},
            {"id": "X-001", "result": "missed", "reason": "repeat"},
            {"id": "X-404", "result": "resolved", "reason": "made up"},
            {"id": ["X-002"], "result": "resolved", "reason": "unhashable"},
            {"id": "X-002", "result": "done", "reason": "bad result"},
            "junk"]}
        out = cr.validate_find(raw, prior_ids={"X-001", "X-002"})
        self.assertEqual(out["rechecks"], [{"id": "X-001", "result": "resolved", "reason": "fixed"}])

    def test_prior_without_rechecks_list_is_bad_output(self):
        with self.assertRaises(cr.BadOutput):
            cr.validate_find({"findings": []}, prior_ids={"X-001"})


class ValidateJudgeTests(unittest.TestCase):
    def test_maps_verdict_to_the_shared_verdict_key(self):
        out = cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "line 41", "confidence": 0.8}]}, {"C-001"})
        self.assertEqual(out, {"verdicts": [
            {"id": "C-001", "adversary_verdict": "confirm", "reason": "line 41", "confidence": 0.8}]})

    def test_drops_unknown_repeated_unhashable_and_invalid(self):
        raw = {"verdicts": [
            {"id": "C-001", "verdict": "refute", "reason": "first", "confidence": 7},
            {"id": "C-001", "verdict": "confirm", "reason": "second", "confidence": 0.5},
            {"id": "C-999", "verdict": "confirm", "reason": "unknown", "confidence": 0.5},
            {"id": {"x": 1}, "verdict": "confirm", "reason": "unhashable", "confidence": 0.5},
            {"id": "C-002", "verdict": "maybe", "reason": "bad", "confidence": 0.5},
            "junk"]}
        out = cr.validate_judge(raw, {"C-001", "C-002"})
        self.assertEqual(out["verdicts"], [
            {"id": "C-001", "adversary_verdict": "refute", "reason": "first", "confidence": 1.0}])

    def test_bad_confidence_becomes_zero(self):
        for bad in ("high", True, None):
            out = cr.validate_judge({"verdicts": [
                {"id": "C-001", "verdict": "confirm", "reason": "r", "confidence": bad}]}, {"C-001"})
            self.assertEqual(out["verdicts"][0]["confidence"], 0.0, repr(bad))

    def test_reason_is_redacted(self):
        out = cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "see " + FAKE_GH, "confidence": 1}]},
            {"C-001"})
        self.assertNotIn(FAKE_GH, out["verdicts"][0]["reason"])

    def test_missing_verdicts_list_is_bad_output(self):
        for raw in ({}, {"verdicts": {}}, []):
            with self.assertRaises(cr.BadOutput):
                cr.validate_judge(raw, {"C-001"})


class ValidateCounterTests(unittest.TestCase):
    def test_keeps_concede_and_defend_for_known_ids(self):
        raw = {"counters": [
            {"id": "X-001", "position": "defend", "reason": "line 9 still loops"},
            {"id": "X-002", "position": "concede", "reason": "Claude is right"},
            {"id": "X-003", "position": "shrug", "reason": "bad"},
            {"id": "X-404", "position": "defend", "reason": "unknown"}]}
        out = cr.validate_counter(raw, {"X-001", "X-002", "X-003"})
        self.assertEqual(out["counters"], [
            {"id": "X-001", "position": "defend", "reason": "line 9 still loops"},
            {"id": "X-002", "position": "concede", "reason": "Claude is right"}])

    def test_missing_counters_list_is_bad_output(self):
        with self.assertRaises(cr.BadOutput):
            cr.validate_counter({"verdicts": []}, {"X-001"})


if __name__ == "__main__":
    unittest.main()
