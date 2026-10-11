"""The secret scan must pass on this plugin's own files. Otherwise every review of
the plugin's own PRs stops at exit 4 on a fake fixture and needs a manual override.
Build fake secrets in tests by concatenation, and describe secret formats in docs
in a way that does not match them."""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]  # plugins/review
sys.path.insert(0, str(HERE))
import secret_scan  # noqa: E402


def tracked_files():
    """(repo root, tracked paths under plugins/review relative to it), or None."""
    top = subprocess.run(["git", "-C", str(PLUGIN), "rev-parse", "--show-toplevel"], capture_output=True,
                         text=True)
    if top.returncode != 0:
        return None
    root = Path(top.stdout.strip())
    res = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", str(PLUGIN)],
                         capture_output=True, check=True)
    return root, [p for p in res.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


class SelfScanTests(unittest.TestCase):
    def test_every_tracked_plugin_file_scans_clean_as_a_new_file_diff(self):
        found = tracked_files()
        if found is None:
            self.skipTest("not in a git checkout")
        root, files = found
        self.assertGreater(len(files), 20)
        hits = []
        for rel in files:
            # The same shape a review sends: a diff that adds the whole file.
            diff = subprocess.run(["git", "diff", "--no-index", "--no-color", "--no-ext-diff", "--no-textconv",
                                   "--src-prefix=a/", "--dst-prefix=b/", "/dev/null", rel],
                                  cwd=str(root), capture_output=True)
            self.assertIn(diff.returncode, (0, 1), diff.stderr)
            hits += secret_scan.scan_text(diff.stdout.decode("utf-8", "replace"), rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
