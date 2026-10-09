"""Tests for check-cites.py: a finding reaches the implementer only when its path
is a file in the diff, inside the repo, and its line exists in the current file."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "check-cites.py"

DIFF = ("diff --git a/src/a.py b/src/a.py\nindex 1..2 100644\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -1,2 +1,3 @@\n x = 1\n+y = 2\n z = 3\n"
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex 1..0\n--- a/gone.py\n"
        "+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        "diff --git a/link.py b/link.py\nnew file mode 120000\nindex 0..1\n--- /dev/null\n"
        "+++ b/link.py\n@@ -0,0 +1 @@\n+../outside.py\n")


def finding(fid, path, line, status="survivor"):
    return {"id": fid, "path": path, "line": line, "severity": "minor", "category": "bug",
            "title": "t", "rationale": "r", "status": status}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="check-cites-test-"))
        self.addCleanup(shutil.rmtree, str(self.dir), True)
        self.repo = self.dir / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
        (self.dir / "outside.py").write_text("secret = 1\n" * 50)
        os.symlink(str(self.dir / "outside.py"), str(self.repo / "link.py"))
        self.diff = self.dir / "change.diff"
        self.diff.write_text(DIFF)

    def write(self, obj, name="findings.json"):
        path = self.dir / name
        path.write_text(json.dumps(obj))
        return path

    def run_cites(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def check(self, findings, *extra):
        f = self.write({"findings": findings})
        return self.run_cites("--diff", self.diff, "--findings", f, "--repo", self.repo, *extra)


class PassTests(Base):
    def test_a_cited_line_in_a_changed_file_passes(self):
        res = self.check([finding("C-001", "src/a.py", 2), finding("X-001", "src/a.py", None),
                          finding("C-002", "./src/a.py", 3)])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout, "")
        self.assertIn("checked=3 failed=0", res.stderr)

    def test_a_bare_list_and_a_report_both_load(self):
        f = self.write([finding("C-001", "src/a.py", 1)])
        res = self.run_cites("--diff", self.diff, "--findings", f, "--repo", self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)


class FailTests(Base):
    def assert_fails(self, item, reason_part):
        res = self.check([finding("C-001", "src/a.py", 1), item])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        lines = res.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, res.stdout)
        self.assertTrue(lines[0].startswith(item.get("id") or "(no id)"), lines[0])
        self.assertIn(reason_part, lines[0])

    def test_a_path_not_in_the_diff_fails(self):
        self.assert_fails(finding("C-009", "src/other.py", 1), "not a file in the diff")

    def test_a_deleted_file_fails(self):
        self.assert_fails(finding("C-009", "gone.py", 1), "not a file in the diff")

    def test_a_line_past_the_end_fails(self):
        self.assert_fails(finding("C-009", "src/a.py", 4), "past the end")

    def test_line_zero_negative_or_not_a_number_fails(self):
        for line in (0, -1, "2", 2.0, True):
            with self.subTest(line=line):
                self.assert_fails(finding("C-009", "src/a.py", line), "line")

    def test_an_absolute_path_fails(self):
        self.assert_fails(finding("C-009", str(self.repo / "src/a.py"), 1), "outside the repo")

    def test_a_dotdot_path_fails(self):
        self.assert_fails(finding("C-009", "src/../../outside.py", 1), "outside the repo")

    def test_a_symlink_out_of_the_repo_fails(self):
        self.assert_fails(finding("C-009", "link.py", 1), "outside the repo")

    def test_a_missing_path_fails(self):
        self.assert_fails(finding("C-009", "", 1), "no path")

    def test_a_finding_with_no_id_fails(self):
        item = finding("C-009", "src/a.py", 1)
        del item["id"]
        self.assert_fails(item, "no id")

    def test_a_file_in_the_diff_missing_from_the_repo_fails(self):
        (self.repo / "src" / "a.py").unlink()
        res = self.check([finding("C-001", "src/a.py", 1)])
        self.assertEqual(res.returncode, 1)
        self.assertIn("not in the repo", res.stdout)


class SelectionTests(Base):
    def test_status_picks_only_survivors(self):
        res = self.check([finding("C-001", "src/a.py", 1),
                          finding("C-002", "nope.py", 1, status="rejected")], "--status", "survivor")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("checked=1", res.stderr)

    def test_id_adds_r3_concessions(self):
        res = self.check([finding("C-001", "src/a.py", 1),
                          finding("C-002", "nope.py", 1, status="rejected")],
                         "--status", "survivor", "--id", "C-002")
        self.assertEqual(res.returncode, 1)
        self.assertIn("C-002", res.stdout)

    def test_an_id_that_is_not_in_the_findings_fails(self):
        res = self.check([finding("C-001", "src/a.py", 1)], "--id", "C-404")
        self.assertEqual(res.returncode, 1)
        self.assertIn("C-404 not in the findings file", res.stdout)


class UsageTests(Base):
    def test_missing_arguments_exit_2(self):
        self.assertEqual(self.run_cites().returncode, 2)
        self.assertEqual(self.run_cites("--diff", self.diff).returncode, 2)

    def test_an_unreadable_findings_file_exits_2(self):
        res = self.run_cites("--diff", self.diff, "--findings", self.dir / "nope.json", "--repo", self.repo)
        self.assertEqual(res.returncode, 2)

    def test_findings_that_are_not_json_exit_2(self):
        bad = self.dir / "bad.json"
        bad.write_text("{not json")
        res = self.run_cites("--diff", self.diff, "--findings", bad, "--repo", self.repo)
        self.assertEqual(res.returncode, 2)

    def test_a_missing_diff_exits_2(self):
        f = self.write({"findings": []})
        res = self.run_cites("--diff", self.dir / "nope.diff", "--findings", f, "--repo", self.repo)
        self.assertEqual(res.returncode, 2)

    def test_help_exits_0(self):
        res = self.run_cites("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Exit codes", res.stdout)


if __name__ == "__main__":
    unittest.main()
