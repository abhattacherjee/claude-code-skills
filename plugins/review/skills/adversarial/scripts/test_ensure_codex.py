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
        # The stub codex is a real file, so the hint must not ln -sfn over it.
        self.assertNotIn("ln -sfn", hint)
        self.assertIn(str(app), hint)
        self.assertIn("in PATH", hint)

    def link_codex(self, env, target):
        """Move the stub codex to `target` and leave a symlink to it on PATH."""
        target.parent.mkdir(parents=True, exist_ok=True)
        (env.bin / "codex").rename(target)
        (env.bin / "codex").symlink_to(target)

    def test_a_standalone_install_link_gets_the_ln_hint(self):
        # The standalone installer links codex into ${CODEX_HOME:-~/.codex}/packages/.
        for codex_home in (None, "ch"):
            with self.subTest(codex_home=codex_home):
                env = StubEnv(self)
                base = env.home / ".codex"
                if codex_home:
                    base = env.root / codex_home
                    env.env["CODEX_HOME"] = str(base)
                app = env.app('echo "codex-cli 0.159.0-alpha.12.1"')
                self.link_codex(env, base / "packages" / "standalone" / "0.155.1" / "codex")
                out = self.check(env)
                self.assertEqual(out["CODEX_NEWER_BIN"], str(app))
                self.assertIn("ln -sfn '%s' '%s'" % (app, env.bin / "codex"), out["CODEX_STALE_HINT"])

    def test_a_package_manager_link_gets_no_ln_hint(self):
        # npm and Homebrew install codex as a symlink too; ln -sfn over it would
        # break the package manager's link (code I3).
        for rel in ("lib/node_modules/@openai/codex/bin/codex.js", "Caskroom/codex/0.155.1/codex",
                    "home/.codex-other/packages/codex", "home/.codex/packagesX/codex"):
            with self.subTest(target=rel):
                env = StubEnv(self)
                app = env.app('echo "codex-cli 0.159.0"')
                self.link_codex(env, env.root / rel)
                hint = self.check(env)["CODEX_STALE_HINT"]
                self.assertNotIn("ln -sfn", hint)
                self.assertIn(str(app), hint)
                self.assertIn("in PATH", hint)

    def test_a_cache_newer_than_the_app_gets_no_app_hint(self):
        # Linking the app binary would leave the CLI stale (code S2).
        for link in (False, True):
            with self.subTest(standalone_link=link):
                env = StubEnv(self)
                env.cache({"client_version": "0.161.2"})
                app = env.app('echo "codex-cli 0.160.0-alpha.1"')
                if link:
                    self.link_codex(env, env.home / ".codex" / "packages" / "standalone" / "codex")
                out = self.check(env)
                self.assertEqual(out["CODEX_STALE"], "yes")
                self.assertEqual(out["CODEX_NEWER_BIN"], "-")
                self.assertNotIn("ln -sfn", out["CODEX_STALE_HINT"])
                self.assertNotIn(str(app), out["CODEX_STALE_HINT"])
                self.assertIn("0.161.2", out["CODEX_STALE_HINT"])

    def test_an_app_as_new_as_the_cache_gets_the_app_hint(self):
        env = StubEnv(self)
        env.cache({"client_version": "0.160.0"})
        app = env.app('echo "codex-cli 0.160.0"')
        out = self.check(env)
        self.assertEqual(out["CODEX_NEWER_BIN"], str(app))
        self.assertIn(str(app), out["CODEX_STALE_HINT"])

    def test_major_versions_compare_first(self):
        # tests I3: no 0.x version reaches the major compare.
        for cli, cache, want in (("1.0.0", "0.200.0", "no"), ("0.200.0", "1.0.0", "yes"),
                                 ("2.0.0", "10.0.0", "yes")):
            with self.subTest(cli=cli, cache=cache):
                env = StubEnv(self, version="codex-cli " + cli)
                env.cache({"client_version": cache})
                self.assertEqual(self.check(env)["CODEX_STALE"], want)

    def test_leading_zeros_are_decimal(self):
        # tests S4: without 10#, bash reads 08 as a bad octal number.
        for cli, cache, want in (("0.155.1", "0.08.0", "no"), ("0.07.0", "0.08.0", "yes"),
                                 ("0.155.09", "0.155.10", "yes")):
            with self.subTest(cli=cli, cache=cache):
                env = StubEnv(self, version="codex-cli " + cli)
                env.cache({"client_version": cache})
                res = env.run(ENSURE, "--check")
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(res.stderr, "")
                self.assertEqual(parse_lines(res.stdout)["CODEX_STALE"], want)

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

    def test_an_unread_app_with_a_current_cache_gives_unknown(self):
        # errors I2: the app binary is there but gave no version, so it was not
        # checked; that must never read as "not stale".
        for body in ("exit 3", "echo garbage", "echo codex-cli 9.9.9; exit 1", "sleep 60"):
            with self.subTest(body=body):
                env = StubEnv(self)
                env.cache({"client_version": "0.155.1"})
                env.app(body)
                out = self.check(env)
                self.assertEqual(out["CODEX_STALE"], "unknown")
                self.assertEqual(out["CODEX_NEWER_BIN"], "-")

    def test_a_missing_helper_gives_unknown(self):
        env = StubEnv(self)
        env.cache({"client_version": "0.155.1"})
        env.app('echo "codex-cli 0.200.0"')
        copy = env.root / "scripts" / "ensure-codex.sh"
        copy.parent.mkdir()
        shutil.copy(str(ENSURE), str(copy))
        res = env.run(copy, "--check")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(parse_lines(res.stdout)["CODEX_STALE"], "unknown")

    def test_a_current_cache_and_no_app_gives_no(self):
        env = StubEnv(self)
        env.cache({"client_version": "0.155.1"})
        self.assertEqual(self.check(env)["CODEX_STALE"], "no")

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
