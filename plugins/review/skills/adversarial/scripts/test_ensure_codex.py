"""Tests for ensure-codex.sh with a stub codex. The real Codex is never run."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
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
    """A HOME, a bin dir, and an environment holding only PATH, HOME and a
    CODEX_APP_BIN that points at nothing."""

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
        # CODEX_APP_BIN points at nothing by default, so a real ChatGPT.app on the
        # machine running the tests is never run.
        self.env = {"PATH": str(self.bin) + os.pathsep + BASE_PATH, "HOME": str(self.home),
                    "CODEX_APP_BIN": str(root / "no-such-app" / "codex")}
        self.root = root
        if gemini_key:
            self.env["GEMINI_API_KEY"] = "stub-value"

    def cache(self, value, codex_home=None):
        """Write models_cache.json; a str is written as is, else as JSON."""
        d = Path(codex_home) if codex_home else self.home / ".codex"
        d.mkdir(parents=True, exist_ok=True)
        (d / "models_cache.json").write_text(value if isinstance(value, str) else json.dumps(value))

    def app(self, body, dirname="app"):
        """A fake ChatGPT-bundled codex whose --version runs `body` (shell)."""
        d = self.root / dirname
        d.mkdir(parents=True, exist_ok=True)
        path = d / "codex"
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        self.env["CODEX_APP_BIN"] = str(path)
        return path

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


class StaleCliTests(unittest.TestCase):
    """#185: CODEX_STALE compares `codex --version` with models_cache.json's
    client_version and the ChatGPT-bundled binary. Exit 0 in every case."""

    def check(self, env):
        res = env.run(ENSURE, "--check")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = parse_lines(res.stdout)
        for key in ("CODEX_STALE", "CODEX_NEWER_BIN", "CODEX_STALE_HINT"):
            self.assertIn(key, out, res.stdout)
        return out

    def test_stale_against_the_models_cache(self):
        env = StubEnv(self)
        env.cache({"client_version": "0.159.0", "models": []})
        out = self.check(env)
        self.assertEqual(out["CODEX_STALE"], "yes")
        self.assertEqual(out["CODEX_NEWER_BIN"], "-")
        self.assertIn("0.159.0", out["CODEX_STALE_HINT"])
        self.assertIn("update the Codex CLI", out["CODEX_STALE_HINT"])

    def test_the_cache_is_read_from_codex_home(self):
        env = StubEnv(self)
        env.env["CODEX_HOME"] = str(env.root / "ch")
        env.cache({"client_version": "0.160.0"}, codex_home=env.root / "ch")
        env.cache({"client_version": "0.100.0"})   # ~/.codex: ignored when CODEX_HOME is set
        self.assertEqual(self.check(env)["CODEX_STALE"], "yes")

    def test_stale_against_the_bundled_binary(self):
        env = StubEnv(self)
        app = env.app('echo "codex-cli 0.159.0-alpha.12.1"')
        out = self.check(env)
        self.assertEqual(out["CODEX_STALE"], "yes")
        self.assertEqual(out["CODEX_NEWER_BIN"], str(app))
        hint = out["CODEX_STALE_HINT"]
        self.assertIn("ln -sfn", hint)
        self.assertIn(str(app), hint)
        self.assertIn(str(env.bin / "codex"), hint)

    def test_current(self):
        env = StubEnv(self)
        env.cache({"client_version": "0.155.1"})
        env.app('echo "codex-cli 0.155.1-alpha.3"')
        out = self.check(env)
        self.assertEqual(out["CODEX_STALE"], "no")
        self.assertEqual(out["CODEX_NEWER_BIN"], "-")
        self.assertEqual(out["CODEX_STALE_HINT"], "-")

    def test_an_older_source_is_not_stale(self):
        env = StubEnv(self, version="codex-cli 0.159.0-alpha.12.1")
        env.cache({"client_version": "0.159.0"})
        env.app('echo "codex-cli 0.99.10"')
        self.assertEqual(self.check(env)["CODEX_STALE"], "no")

    def test_versions_compare_numerically_not_as_text(self):
        env = StubEnv(self, version="codex-cli 0.99.0")
        env.cache({"client_version": "0.100.0"})
        self.assertEqual(self.check(env)["CODEX_STALE"], "yes")

    def test_unknown_with_no_source(self):
        out = self.check(StubEnv(self))
        self.assertEqual(out["CODEX_STALE"], "unknown")
        self.assertEqual(out["CODEX_NEWER_BIN"], "-")

    def test_unknown_when_codex_is_not_installed(self):
        env = StubEnv(self, codex=False)
        env.cache({"client_version": "0.159.0"})
        self.assertEqual(self.check(env)["CODEX_STALE"], "unknown")

    def test_unknown_when_the_current_version_is_unreadable(self):
        env = StubEnv(self, version="codex-cli dev-build")
        env.cache({"client_version": "0.159.0"})
        self.assertEqual(self.check(env)["CODEX_STALE"], "unknown")

    def test_an_unreadable_cache_gives_unknown_not_no(self):
        bad = ["{not json", "[]", '{"client_version": 159}', '{"client_version": "latest"}', ""]
        for text in bad:
            with self.subTest(cache=text):
                env = StubEnv(self)
                env.cache(text)
                res = env.run(ENSURE, "--check")
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertNotIn("Traceback", res.stderr)
                self.assertEqual(parse_lines(res.stdout)["CODEX_STALE"], "unknown")

    def test_a_failing_bundled_binary_gives_unknown(self):
        for body in ("exit 3", "echo garbage", "echo 0.200.0; exit 1"):
            with self.subTest(body=body):
                env = StubEnv(self)
                env.app(body)
                self.assertEqual(self.check(env)["CODEX_STALE"], "unknown")

    def test_a_hanging_bundled_binary_is_bounded(self):
        env = StubEnv(self)
        env.app("sleep 60")
        start = time.time()
        out = self.check(env)
        self.assertLess(time.time() - start, 30)
        self.assertEqual(out["CODEX_STALE"], "unknown")

    def test_the_bundled_binary_gets_no_stdin(self):
        env = StubEnv(self)
        env.app('if read -r line; then echo "0.300.0"; else echo "0.100.0"; fi')
        res = subprocess.run(["/bin/bash", str(ENSURE), "--check"], input="x\n", capture_output=True,
                             text=True, env=env.env, timeout=60)
        self.assertEqual(parse_lines(res.stdout)["CODEX_STALE"], "no")

    def test_stale_output_is_eval_safe(self):
        env = StubEnv(self)
        app = env.app('echo "0.200.0"', dirname="it's here $(touch pwned)")
        res = subprocess.run(
            ["/bin/bash", "-c", 'eval "$(/bin/bash "$1" --check)"; printf "%s|%s|%s" '
             '"$CODEX_STALE" "$CODEX_NEWER_BIN" "$CODEX_STALE_HINT"', "_", str(ENSURE)],
            capture_output=True, text=True, env=env.env, timeout=60, cwd=str(env.root))
        self.assertEqual(res.returncode, 0, res.stderr)
        stale, newer, hint = res.stdout.split("|", 2)
        self.assertEqual((stale, newer), ("yes", str(app)))
        self.assertIn(str(app), hint)
        self.assertFalse((env.root / "pwned").exists())

    def test_help_names_the_new_lines(self):
        res = StubEnv(self).run(ENSURE, "--help")
        for key in ("CODEX_STALE=yes|no|unknown", "CODEX_NEWER_BIN", "CODEX_STALE_HINT", "CODEX_APP_BIN"):
            self.assertIn(key, res.stdout)


if __name__ == "__main__":
    unittest.main()
