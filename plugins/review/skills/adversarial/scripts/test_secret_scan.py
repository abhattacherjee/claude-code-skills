"""Tests for secret_scan.py. Every fake secret is built by concatenation so the
repo's own pre-commit secret scan does not flag this file."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "secret_scan.py"
sys.path.insert(0, str(HERE))

FAKE_AWS = "AKIA" + "EXAMPLEEXAMPLE12"
FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_PAT = "github_" + "pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"
FAKE_ANT = "sk-" + "ant-" + "api03-EXAMPLEexampleEXAMPLEexample"
FAKE_OAI = "sk-" + "proj-EXAMPLEexampleEXAMPLEexample"
FAKE_SLACK = "xox" + "b-" + "123456789012-EXAMPLEexample"
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
PEM_HEAD = "-----BEGIN RSA " + "PRIVATE" + " KEY-----"
PEM_TAIL = "-----END RSA " + "PRIVATE" + " KEY-----"


def diff(path, *added, start=1):
    body = "".join("+%s\n" % line for line in added)
    return ("diff --git a/%s b/%s\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
            "+++ b/%s\n@@ -0,0 +%d,%d @@\n%s" % (path, path, path, start, len(added), body))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="secret-scan-test-"))
        self.addCleanup(shutil.rmtree, str(self.dir), True)

    def put(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_scan(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


class ExitCodeTests(Base):
    def test_clean_diff_exits_0_and_prints_nothing(self):
        res = self.run_scan(self.put("c.diff", diff("src/a.py", "x = 1", "print(x)")))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "")

    def test_a_match_exits_4(self):
        res = self.run_scan(self.put("d.diff", diff("src/a.py", "key = '%s'" % FAKE_AWS)))
        self.assertEqual(res.returncode, 4)

    def test_no_files_is_a_usage_error(self):
        self.assertEqual(self.run_scan().returncode, 2)

    def test_a_missing_file_fails_closed(self):
        res = self.run_scan(self.dir / "nope.diff")
        self.assertEqual(res.returncode, 2)
        self.assertIn("nope.diff", res.stderr)

    def test_a_directory_fails_closed(self):
        self.assertEqual(self.run_scan(self.dir).returncode, 2)

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_an_unreadable_file_fails_closed_even_next_to_a_clean_one(self):
        clean = self.put("clean.diff", diff("a.py", "x"))
        locked = self.put("locked.diff", diff("a.py", "y"))
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o600)
        self.assertEqual(self.run_scan(clean, locked).returncode, 2)

    def test_help_exits_0(self):
        res = self.run_scan("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Exit codes", res.stdout)


class PatternTests(Base):
    CASES = [("aws-key-id", FAKE_AWS), ("github-token", FAKE_GH), ("github-token", FAKE_PAT),
             ("anthropic-key", FAKE_ANT), ("openai-key", FAKE_OAI), ("slack-token", FAKE_SLACK),
             ("jwt", FAKE_JWT), ("private-key", PEM_HEAD)]

    def test_each_pattern_is_found_and_named_without_its_value(self):
        for name, value in self.CASES:
            with self.subTest(name=name):
                res = self.run_scan(self.put("p.diff", diff("src/conf.py", "a = 1", "v = '%s'" % value)))
                self.assertEqual(res.returncode, 4, res.stdout + res.stderr)
                self.assertIn("src/conf.py:2 %s" % name, res.stdout)
                self.assertNotIn(value, res.stdout + res.stderr)

    def test_a_pem_block_is_reported_at_its_first_line(self):
        res = self.run_scan(self.put("k.diff", diff("k.txt", "x", PEM_HEAD, "MIIEexample", PEM_TAIL)))
        self.assertEqual(res.stdout.strip().splitlines(), ["k.txt:2 private-key"])

    def test_kebab_case_words_ending_in_sk_are_not_openai_keys(self):
        # Split so the repo's pre-commit scan, which has this false positive, passes.
        text = diff("a.md", "see ta" + "sk-" + "a" * 30, "ri" + "sk-" + "assessment-for-the-new-module-today")
        res = self.run_scan(self.put("k.diff", text))
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_a_key_after_equals_or_a_quote_is_still_found(self):
        for line in ("OPENAI_API_KEY=" + FAKE_OAI, 'k="%s"' % FAKE_OAI, "Bearer " + FAKE_OAI):
            with self.subTest(line=line):
                res = self.run_scan(self.put("e.diff", diff("a.sh", line)))
                self.assertIn("a.sh:1 openai-key", res.stdout)


class LineMappingTests(Base):
    def test_line_numbers_follow_the_hunk_header(self):
        text = ("diff --git a/src/b.py b/src/b.py\nindex 1..2 100644\n--- a/src/b.py\n+++ b/src/b.py\n"
                "@@ -10,3 +40,4 @@ def f():\n ctx\n-old\n+new\n+t = '%s'\n ctx2\n" % FAKE_GH)
        res = self.run_scan(self.put("m.diff", text))
        self.assertEqual(res.stdout.strip(), "src/b.py:42 github-token")

    def test_a_removed_line_reports_the_old_path_and_line(self):
        text = ("diff --git a/old.py b/old.py\nindex 1..2 100644\n--- a/old.py\n+++ b/old.py\n"
                "@@ -5,2 +5,1 @@\n-t = '%s'\n ctx\n" % FAKE_AWS)
        res = self.run_scan(self.put("r.diff", text))
        self.assertEqual(res.stdout.strip(), "old.py:5 aws-key-id (removed line)")

    def test_a_hunk_line_that_looks_like_a_header_stays_in_its_file(self):
        # "-- x" removed shows as "--- x"; "++ y" added shows as "+++ y". Hunk counts,
        # not prefixes, decide where the hunk ends.
        text = ("diff --git a/doc.md b/doc.md\nindex 1..2 100644\n--- a/doc.md\n+++ b/doc.md\n"
                "@@ -1,1 +1,2 @@\n--- x\n+++ y\n+t = '%s'\n" % FAKE_AWS)
        res = self.run_scan(self.put("h.diff", text))
        self.assertEqual(res.stdout.strip(), "doc.md:2 aws-key-id")

    def test_text_outside_any_diff_reports_the_input_file_and_line(self):
        path = self.put("findings.json", '{\n "rationale": "token %s"\n}\n' % FAKE_GH)
        res = self.run_scan(path)
        self.assertEqual(res.stdout.strip(), "%s:2 github-token" % path)

    def test_two_files_in_one_diff(self):
        text = diff("a.py", "x") + diff("b/c.py", "y", "z = '%s'" % FAKE_SLACK)
        res = self.run_scan(self.put("two.diff", text))
        self.assertEqual(res.stdout.strip(), "b/c.py:2 slack-token")

    def test_a_quoted_path_is_unquoted(self):
        text = ('diff --git "a/sp ace.py" "b/sp ace.py"\nnew file mode 100644\n--- /dev/null\n'
                '+++ "b/sp ace.py"\n@@ -0,0 +1,1 @@\n+k = \'%s\'\n' % FAKE_AWS)
        res = self.run_scan(self.put("q.diff", text))
        self.assertEqual(res.stdout.strip(), "sp ace.py:1 aws-key-id")


class SecretFileNameTests(Base):
    def test_each_secret_looking_name_is_flagged(self):
        for path in (".env", "app/.env.production", "certs/server.pem", "tls.key", ".ssh/id_rsa",
                     "id_ed25519.pub", "aws/credentials", "my-credentials.json", "store.p12",
                     "store.pfx", "App/.ENV"):
            with self.subTest(path=path):
                res = self.run_scan(self.put("n.diff", diff(path, "harmless")))
                self.assertEqual(res.returncode, 4, path)
                self.assertIn("%s:0 secret-file-name" % path, res.stdout)

    def test_ordinary_names_are_not_flagged(self):
        for path in ("src/env.py", "keys.md", "docs/environment.md", "monkey.py"):
            with self.subTest(path=path):
                self.assertEqual(self.run_scan(self.put("o.diff", diff(path, "x"))).returncode, 0)

    def test_a_deleted_secret_file_is_flagged(self):
        text = ("diff --git a/.env b/.env\ndeleted file mode 100644\nindex 1..0\n--- a/.env\n"
                "+++ /dev/null\n@@ -1 +0,0 @@\n-A=1\n")
        res = self.run_scan(self.put("del.diff", text))
        self.assertIn(".env:0 secret-file-name", res.stdout)

    def test_a_binary_secret_file_is_flagged(self):
        text = ("diff --git a/store.p12 b/store.p12\nnew file mode 100644\nindex 0..1\n"
                "Binary files /dev/null and b/store.p12 differ\n")
        res = self.run_scan(self.put("bin.diff", text))
        self.assertIn("store.p12:0 secret-file-name", res.stdout)

    def test_a_rename_onto_a_secret_name_is_flagged(self):
        text = ("diff --git a/notes.txt b/.env\nsimilarity index 100%\nrename from notes.txt\n"
                "rename to .env\n")
        res = self.run_scan(self.put("ren.diff", text))
        self.assertIn(".env:0 secret-file-name", res.stdout)

    def test_the_name_list_matches_detect_mode(self):
        import secret_scan
        src = (HERE / "detect-mode.sh").read_text(encoding="utf-8")
        line = re.search(r"^SECRET_NAME_GLOBS=\((.*)\)$", src, re.M).group(1)
        self.assertEqual(list(secret_scan.SECRET_NAME_GLOBS), re.findall(r"'([^']*)'", line))


class SharedPatternTests(unittest.TestCase):
    def test_one_pattern_list_shared_with_redaction(self):
        import audit_record
        import secret_scan
        self.assertIs(secret_scan.SECRET_PATTERNS, audit_record.SECRET_PATTERNS)

    def test_redaction_also_catches_slack_tokens(self):
        import audit_record
        text, counts = audit_record.redact("t " + FAKE_SLACK)
        self.assertNotIn(FAKE_SLACK, text)
        self.assertEqual(counts["slack-token"], 1)


if __name__ == "__main__":
    unittest.main()
