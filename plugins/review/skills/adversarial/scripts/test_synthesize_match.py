"""Cross-side matching and the opt-in synthesis rule."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synthesize  # noqa: E402


def finding(fid, line, path="a.py", category="bug"):
    return {"id": fid, "path": path, "line": line, "category": category}


class CrossFindingTests(unittest.TestCase):
    def test_same_file_near_line_same_category_matches(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 13)]), [("C-001", "X-001")])

    def test_line_gap_of_four_is_not_a_match(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 14)]), [])

    def test_different_category_is_not_a_match(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 10, category="correctness")]), [])

    def test_different_file_is_not_a_match(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 10, path="b.py")]), [])

    def test_missing_line_is_not_a_match(self):
        for claude_line, adversary_line in ((None, 10), (10, None)):
            with self.subTest(claude=claude_line, adversary=adversary_line):
                self.assertEqual(synthesize.match_cross_findings(
                    [finding("C-001", claude_line)], [finding("X-001", adversary_line)]), [])

    def test_each_id_matches_once_nearest_wins(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 12), finding("X-002", 11)]),
            [("C-001", "X-002")])

    def test_id_order_and_ties_are_deterministic(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-002", 10), finding("C-001", 10)],
            [finding("X-002", 11), finding("X-001", 9)]),
            [("C-001", "X-001"), ("C-002", "X-002")])

    def test_duplicate_ids_are_used_only_once(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10), finding("C-001", 11), finding("C-002", 10)],
            [finding("X-001", 10), finding("X-001", 11), finding("X-002", 10)]),
            [("C-001", "X-001"), ("C-002", "X-002")])

    def test_custom_window(self):
        self.assertEqual(synthesize.match_cross_findings(
            [finding("C-001", 10)], [finding("X-001", 14)], window=4),
            [("C-001", "X-001")])

    def test_absent_line_key_is_not_a_match(self):
        missing = finding("C-001", 10)
        del missing["line"]
        self.assertEqual(synthesize.match_cross_findings([missing], [finding("X-001", 10)]), [])
        self.assertEqual(synthesize.match_cross_findings([finding("X-001", 10)], [missing]), [])

    def test_non_integer_lines_and_non_lowercase_categories_do_not_match(self):
        for line in ("10", 10.0, True):
            for left, right in ((line, 10), (10, line)):
                with self.subTest(left=left, right=right):
                    self.assertEqual(synthesize.match_cross_findings(
                        [finding("C-001", left)], [finding("X-001", right)]), [])
        for category in ("Bug", None, 1):
            with self.subTest(category=category):
                self.assertEqual(synthesize.match_cross_findings(
                    [finding("C-001", 10, category=category)],
                    [finding("X-001", 10, category=category)]), [])

    def run_main(self, match=False, verdicts=None, missing_files=False):
        with tempfile.TemporaryDirectory(prefix="synth-match-test-") as tmp:
            root = Path(tmp)
            claude, adversary = root / "claude.json", root / "adversary.json"
            claude.write_text(json.dumps([finding("C-001", 10)]))
            adversary.write_text(json.dumps([finding("X-001", 13)]))
            output = root / "report.json"
            args = ["synthesize.py", "--claude-findings", str(claude),
                    "--adversary-findings", str(adversary), "--json", str(output)]
            if match:
                args.append("--match")
            if missing_files:
                args.extend(["--adversary-verdicts", str(root / "missing-adversary.json"),
                             "--claude-verdicts", str(root / "missing-claude.json")])
            if verdicts is not None:
                for flag, fid, field in (("--adversary-verdicts", "C-001", "adversary_verdict"),
                                         ("--claude-verdicts", "X-001", "claude_verdict")):
                    path = root / (fid + ".json")
                    entries = [{"id": fid, field: verdicts}] if verdicts else []
                    path.write_text(json.dumps({"verdicts": entries}))
                    args.extend([flag, str(path)])
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                synthesize.main()
            return json.loads(output.read_text())

    def assert_pair_labels(self, report):
        partners = {"C-001": "X-001", "X-001": "C-001"}
        self.assertEqual({f["id"] for f in report["findings"]}, set(partners))
        for f in report["findings"]:
            self.assertIs(f["raised_by_both"], True)
            self.assertEqual(f["matched_with"], partners[f["id"]])

    def test_match_labels_pair_without_changing_status(self):
        report = self.run_main(match=True)
        self.assert_pair_labels(report)
        for f in report["findings"]:
            self.assertEqual(f["status"], "unconfirmed")

    def test_without_match_flag_behaviour_is_unchanged(self):
        report = self.run_main(verdicts="")
        self.assertEqual([f["status"] for f in report["findings"]],
                         ["unconfirmed", "unconfirmed"])
        self.assertTrue(all("status_reason" not in f for f in report["findings"]))

    def test_match_with_missing_verdict_file_path_fails(self):
        # A given path that does not exist is a typo, not "no verdicts yet".
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            self.run_main(match=True, missing_files=True)
        self.assertNotEqual(cm.exception.code, 0)

    def test_match_never_overrides_refuting_verdicts(self):
        report = self.run_main(match=True, verdicts="refute")
        self.assert_pair_labels(report)
        baseline = self.run_main(verdicts="refute")
        for f, original in zip(report["findings"], baseline["findings"]):
            self.assertEqual(f["status"], "rejected")
            self.assertEqual(f["killed_by"], original["killed_by"])
            self.assertEqual(f["kill_reason"], original["kill_reason"])
            self.assertNotIn("status_reason", f)

    def test_match_with_confirming_verdicts_survive(self):
        report = self.run_main(match=True, verdicts="confirm")
        self.assert_pair_labels(report)
        for f in report["findings"]:
            self.assertEqual(f["status"], "survivor")

    def test_markdown_labels_pairs_in_each_status(self):
        for verdict in (None, "refute", "confirm"):
            with self.subTest(verdict=verdict):
                findings = self.run_main(match=True, verdicts=verdict)["findings"]
                groups = [[f for f in findings if f["status"] == status]
                          for status in ("survivor", "unconfirmed", "rejected")]
                markdown = synthesize.format_markdown(*groups)
                self.assertIn("(no title) (raised by both, with X-001)", markdown)
                self.assertIn("(no title) (raised by both, with C-001)", markdown)


if __name__ == "__main__":
    unittest.main()
