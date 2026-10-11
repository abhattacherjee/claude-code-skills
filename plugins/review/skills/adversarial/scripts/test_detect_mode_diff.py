"""detect-mode.sh must write the same diff whatever the user's git config says:
no color, a/ and b/ prefixes, no external diff tool, no textconv. Otherwise the
secret scan misses file names and check-cites misreads every path."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DETECT = HERE / "detect-mode.sh"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t"] + list(args),
                   check=True, capture_output=True)


class DeterministicDiffTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="detect-mode-diff-"))
        self.addCleanup(shutil.rmtree, str(self.dir), True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.gh_log = self.dir / "gh.log"

    def stub_gh(self, body):
        gh = self.bin / "gh"
        gh.write_text("#!/usr/bin/env bash\nprintf '%%s\\n' \"$*\" >> %s\n%s\n" % (self.gh_log, body))
        gh.chmod(0o755)

    def env(self):
        return dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])

    def hostile_repo(self):
        repo = self.dir / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / "a.txt").write_text("one\n")
        (repo / "data.enc").write_text("CIPHERTEXT\n")
        (repo / ".gitattributes").write_text("*.enc diff=decrypt\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        git(repo, "checkout", "-q", "-b", "feature/x")
        ext = self.dir / "ext-diff.sh"
        ext.write_text("#!/bin/sh\necho EXTERNAL-DIFF-RAN\n")
        ext.chmod(0o755)
        for key, value in (("color.ui", "always"), ("color.diff", "always"), ("diff.mnemonicPrefix", "true"),
                           ("diff.noprefix", "true"), ("diff.external", str(ext)),
                           ("diff.decrypt.textconv", "sed s/CIPHERTEXT/PLAINTEXT-SECRET/")):
            git(repo, "config", key, value)
        (repo / "a.txt").write_text("one\ntwo\n")
        (repo / "data.enc").write_text("CIPHERTEXT\nCIPHERTEXT-2\n")
        return repo

    def run_detect(self, repo, *args):
        res = subprocess.run(["bash", str(DETECT)] + list(args), cwd=str(repo), capture_output=True,
                             text=True, env=self.env(), timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        vals = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)
        self.addCleanup(lambda: [os.path.exists(vals[k]) and os.remove(vals[k]) for k in ("DIFF_FILE", "FILES_FILE")])
        return Path(vals["DIFF_FILE"]).read_text(), Path(vals["FILES_FILE"]).read_text()

    def test_local_mode_ignores_color_prefix_external_and_textconv_config(self):
        self.stub_gh("exit 1")
        diff, files = self.run_detect(self.hostile_repo(), "--base", "main")
        self.assertNotIn("\x1b", diff + files)
        self.assertIn("diff --git a/a.txt b/a.txt\n", diff)
        self.assertIn("+++ b/a.txt\n", diff)
        self.assertNotIn("EXTERNAL-DIFF-RAN", diff)
        self.assertNotIn("PLAINTEXT-SECRET", diff)
        self.assertIn("+CIPHERTEXT-2", diff)
        self.assertEqual(sorted(files.split()), ["a.txt", "data.enc"])

    def test_pr_mode_asks_gh_for_no_color(self):
        self.stub_gh('case "$*" in\n'
                     '  *"pr list"*|*"pr view"*) echo 7 ;;\n'
                     '  *"pr diff"*"--name-only"*) echo a.txt ;;\n'
                     '  *"pr diff"*) printf "diff --git a/a.txt b/a.txt\\n" ;;\n'
                     '  *) echo main ;;\n'
                     'esac')
        repo = self.dir / "prrepo"
        subprocess.run(["git", "init", "-q", "-b", "feature/x", str(repo)], check=True)
        git(repo, "commit", "-q", "--allow-empty", "-m", "i")
        self.run_detect(repo)
        diff_calls = [l for l in self.gh_log.read_text().splitlines() if "pr diff" in l]
        self.assertTrue(diff_calls)
        for call in diff_calls:
            self.assertIn("--color=never", call)


if __name__ == "__main__":
    unittest.main()
