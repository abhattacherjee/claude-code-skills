"""Tests for ensure-codex.sh with a stub codex. The real Codex is never run."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENSURE = HERE / "ensure-codex.sh"
STUB = HERE / "fixtures" / "codex_stub.py"
BASE_PATH = "/usr/bin:/bin"


def parse_lines(text):
    """KEY='value' lines -> dict, read the way `eval` reads them."""
    out = {}
    for line in text.splitlines():
        parts = shlex.split(line)
        if len(parts) == 1 and "=" in parts[0]:
            key, value = parts[0].split("=", 1)
            out[key] = value
    return out


def install_stub(bindir):
    codex = bindir / "codex"
    codex.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' % (sys.executable, STUB))
    codex.chmod(0o755)


class StubEnv:
    """A HOME, a bin dir, and an environment holding only PATH and HOME."""

    def __init__(self, test, codex=True, gemini=False, gemini_key=False, **state):
        for name in ("codex", "gemini"):
            if shutil.which(name, path=BASE_PATH):
                test.skipTest(name + " is installed in " + BASE_PATH)
        root = Path(tempfile.mkdtemp(prefix="codex-detect-test-"))
        test.addCleanup(shutil.rmtree, root, True)
        self.home = root / "home"
        self.home.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        if codex:
            install_stub(self.bin)
        if gemini:
            stub = self.bin / "gemini"
            stub.write_text('#!/usr/bin/env bash\necho "0.40.0"\n')
            stub.chmod(0o755)
        (self.home / "codex-stub.json").write_text(json.dumps(state))
        self.env = {"PATH": str(self.bin) + os.pathsep + BASE_PATH, "HOME": str(self.home)}
        if gemini_key:
            self.env["GEMINI_API_KEY"] = "stub-value"

    def run(self, script, *args):
        return subprocess.run(["/bin/bash", str(script)] + [str(a) for a in args],
                              capture_output=True, text=True, env=self.env, timeout=60)

    def calls(self):
        log = self.home / "codex-stub.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]


class EnsureCodexTests(unittest.TestCase):
    def test_not_installed(self):
        env = StubEnv(self, codex=False)
        res = env.run(ENSURE, "--check")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = parse_lines(res.stdout)
        self.assertEqual(out["CODEX_INSTALLED"], "no")
        self.assertEqual(out["CODEX_VERSION"], "-")
        self.assertEqual(out["CODEX_AUTHED"], "unknown")
        self.assertIn("npm install -g @openai/codex", out["CODEX_INSTALL_HINT"])
        self.assertIn("codex login", out["CODEX_AUTH_HINT"])

    def test_installed_and_logged_in(self):
        env = StubEnv(self, login=0)
        out = parse_lines(env.run(ENSURE, "--check").stdout)
        self.assertEqual(out["CODEX_INSTALLED"], "yes")
        self.assertEqual(out["CODEX_VERSION"], "0.155.1")
        self.assertEqual(out["CODEX_AUTHED"], "yes")
        self.assertIn(["login", "status"], [c["argv"] for c in env.calls()])

    def test_logged_out_uses_the_exit_code_not_the_output(self):
        env = StubEnv(self, login=1, login_stdout="Logged in using ChatGPT")
        out = parse_lines(env.run(ENSURE, "--check").stdout)
        self.assertEqual(out["CODEX_AUTHED"], "no")

    def test_output_is_eval_safe(self):
        env = StubEnv(self, login=0)
        res = subprocess.run(
            ["/bin/bash", "-c", 'eval "$(/bin/bash "$1" --check)"; printf "%s|%s" "$CODEX_AUTHED" "$CODEX_AUTH_HINT"',
             "_", str(ENSURE)], capture_output=True, text=True, env=env.env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        authed, hint = res.stdout.split("|", 1)
        self.assertEqual(authed, "yes")
        self.assertIn("codex login", hint)

    def test_unknown_argument_exits_2(self):
        env = StubEnv(self)
        self.assertEqual(env.run(ENSURE, "--bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
