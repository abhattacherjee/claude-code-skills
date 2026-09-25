"""Tests for pick-adversary.sh: Codex, then Gemini, then Claude-only, and forced choices."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_ensure_codex import StubEnv, parse_lines  # noqa: E402

PICK = HERE / "pick-adversary.sh"
BASE_PATH = "/usr/bin:/bin"


def stage(test, codex_script=None, gemini_script=None):
    """Copy pick-adversary.sh into a fresh temp dir, alongside either the real
    ensure-codex.sh/ensure-gemini.sh or a caller-supplied stand-in for one of
    them. pick-adversary.sh resolves its SCRIPT_DIR from its own path, so this
    is how a test swaps in a broken ensure-*.sh without touching the real one.
    """
    tmp = Path(tempfile.mkdtemp(prefix="pick-adversary-stage-"))
    test.addCleanup(shutil.rmtree, tmp, True)
    pick = tmp / "pick-adversary.sh"
    pick.write_text(PICK.read_text())
    pick.chmod(0o755)
    codex = tmp / "ensure-codex.sh"
    codex.write_text(codex_script if codex_script is not None else (HERE / "ensure-codex.sh").read_text())
    codex.chmod(0o755)
    gemini = tmp / "ensure-gemini.sh"
    gemini.write_text(gemini_script if gemini_script is not None else (HERE / "ensure-gemini.sh").read_text())
    gemini.chmod(0o755)
    return pick


def env_with_working_gemini(test):
    """A HOME/bin/PATH environment where the real ensure-gemini.sh reports
    Gemini installed and authed via a stub `gemini` binary and an API key."""
    root = Path(tempfile.mkdtemp(prefix="pick-adversary-env-"))
    test.addCleanup(shutil.rmtree, root, True)
    home = root / "home"
    home.mkdir()
    bindir = root / "bin"
    bindir.mkdir()
    gemini = bindir / "gemini"
    gemini.write_text('#!/usr/bin/env bash\necho "0.40.0"\n')
    gemini.chmod(0o755)
    return {"PATH": str(bindir) + os.pathsep + BASE_PATH, "HOME": str(home), "GEMINI_API_KEY": "stub-value"}


class PickAdversaryTests(unittest.TestCase):
    def pick(self, env, *args):
        res = env.run(PICK, *args)
        return res, parse_lines(res.stdout)

    def test_codex_first_when_installed_and_logged_in(self):
        env = StubEnv(self, gemini=True, gemini_key=True, login=0)
        res, out = self.pick(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(out["ADVERSARY"], "codex")
        self.assertIn("0.155.1", out["ADVERSARY_REASON"])
        self.assertEqual(out["GEMINI_AUTHED"], "yes")

    def test_gemini_when_codex_is_logged_out(self):
        env = StubEnv(self, gemini=True, gemini_key=True, login=1)
        res, out = self.pick(env)
        self.assertEqual(out["ADVERSARY"], "gemini")
        self.assertIn("Codex is not logged in", out["ADVERSARY_REASON"])

    def test_claude_only_when_neither_is_installed(self):
        env = StubEnv(self, codex=False)
        res, out = self.pick(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(out["ADVERSARY"], "claude-only")
        self.assertIn("Codex is not installed", out["ADVERSARY_REASON"])
        self.assertIn("Gemini is not installed", out["ADVERSARY_REASON"])
        self.assertIn("CODEX_INSTALL_HINT", out)
        self.assertIn("INSTALL_HINT", out)

    def test_gemini_without_a_key_is_not_usable(self):
        env = StubEnv(self, gemini=True, gemini_key=False, login=1)
        res, out = self.pick(env)
        self.assertEqual(out["ADVERSARY"], "claude-only")
        self.assertIn("Gemini has no headless credential", out["ADVERSARY_REASON"])

    def test_forced_codex_that_is_logged_out_is_an_error(self):
        env = StubEnv(self, gemini=True, gemini_key=True, login=1)
        res, out = self.pick(env, "--adversary", "codex")
        self.assertEqual(res.returncode, 3)
        self.assertIn("ADVERSARY_UNAVAILABLE", res.stderr)
        self.assertIn("Codex is not logged in", res.stderr)
        self.assertIn("codex login", res.stderr)
        self.assertNotIn("ADVERSARY", out)

    def test_forced_gemini_skips_a_usable_codex(self):
        env = StubEnv(self, gemini=True, gemini_key=True, login=0)
        res, out = self.pick(env, "--adversary", "gemini")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(out["ADVERSARY"], "gemini")

    def test_forced_gemini_that_is_missing_is_an_error(self):
        env = StubEnv(self, login=0)
        res, out = self.pick(env, "--adversary", "gemini")
        self.assertEqual(res.returncode, 3)
        self.assertIn("Gemini is not installed", res.stderr)
        self.assertNotIn("ADVERSARY", out)

    def test_bad_values_are_usage_errors(self):
        env = StubEnv(self)
        self.assertEqual(env.run(PICK, "--adversary", "claude").returncode, 2)
        self.assertEqual(env.run(PICK, "--adversary").returncode, 2)
        self.assertEqual(env.run(PICK, "--bogus").returncode, 2)

    def test_output_is_eval_safe(self):
        env = StubEnv(self, codex=False)
        res = subprocess.run(["/bin/bash", "-c", 'eval "$(/bin/bash "$1")"; printf "%s" "$ADVERSARY"',
                              "_", str(PICK)], capture_output=True, text=True, env=env.env, timeout=60)
        self.assertEqual(res.stdout, "claude-only", res.stderr)

    def test_output_survives_adversarial_hint_values(self):
        # A value containing a single quote, a double quote, a backtick+$(...)
        # pair and a $(...) pair (each right after a quote, the exact spot a
        # naive escape breaks out of), and an embedded newline. If emit()'s
        # escaping is wrong, eval'ing pick-adversary's stdout either mangles
        # this value or actually runs the touch commands inside it.
        tmp = Path(tempfile.mkdtemp(prefix="pick-adversary-adv-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        marker = tmp / "marker"
        adversarial = (
            "line1 it's a \"quoted\" value\n"
            "line2 backtick '`touch " + str(marker) + "`' "
            "and dollar '$(touch " + str(marker) + ")'"
        )
        # The adversarial text is written to a plain data file and read back
        # with `cat`, never embedded as literal source in the stub script.
        # bash 3.2 (macOS's /bin/bash) mis-parses a heredoc whose body has an
        # odd number of single quotes even with a quoted, non-expanding
        # delimiter (`<<'EOF'`) -- "unexpected EOF while looking for
        # matching `''" -- so a heredoc can't safely carry arbitrary text here.
        data_file = tmp / "codex-version.txt"
        data_file.write_text(adversarial)
        codex_stub = (
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "emit() {\n"
            "  local q=\"'\" bs='\\'\n"
            "  local v=\"${2//$q/$q$bs$q$q}\"\n"
            "  printf \"%s='%s'\\n\" \"$1\" \"$v\"\n"
            "}\n"
            "VERSION=\"$(cat \"" + str(data_file) + "\")\"\n"
            "emit CODEX_INSTALLED yes\n"
            "emit CODEX_VERSION \"$VERSION\"\n"
            "emit CODEX_AUTHED yes\n"
            "emit CODEX_INSTALL_HINT fake\n"
            "emit CODEX_AUTH_HINT fake\n"
        )
        pick = stage(self, codex_script=codex_stub)
        env = {"PATH": BASE_PATH, "HOME": str(tmp / "home")}
        (tmp / "home").mkdir()
        res = subprocess.run(
            ["/bin/bash", "-c",
             'eval "$(/bin/bash "$1")"; printf "%s\\x1f%s\\x1f%s" "$ADVERSARY" "$ADVERSARY_REASON" "$CODEX_VERSION"',
             "_", str(pick)],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(marker.exists(), "adversarial value ran as code instead of round-tripping as data")
        adversary, reason, version = res.stdout.split("\x1f")
        self.assertEqual(adversary, "codex")
        self.assertEqual(version, adversarial)
        self.assertIn(adversarial, reason)

    def test_ensure_codex_exit_nonzero_is_treated_as_unavailable(self):
        pick = stage(self, codex_script='#!/usr/bin/env bash\necho "ensure-codex exploded" >&2\nexit 2\n')
        env = env_with_working_gemini(self)
        res = subprocess.run(["/bin/bash", str(pick)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = parse_lines(res.stdout)
        self.assertEqual(out["ADVERSARY"], "gemini")
        self.assertIn("Codex detection failed", out["ADVERSARY_REASON"])
        self.assertIn("ensure-codex.sh", res.stderr)

        res2 = subprocess.run(["/bin/bash", str(pick), "--adversary", "codex"],
                               capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res2.returncode, 3)
        self.assertIn("ADVERSARY_UNAVAILABLE", res2.stderr)
        self.assertIn("Codex detection failed", res2.stderr)
        self.assertNotIn("ADVERSARY", parse_lines(res2.stdout))

    def test_ensure_codex_unparseable_output_is_treated_as_unavailable(self):
        pick = stage(self, codex_script='#!/usr/bin/env bash\necho "this is not KEY=VALUE output"\n')
        env = env_with_working_gemini(self)
        res = subprocess.run(["/bin/bash", str(pick)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = parse_lines(res.stdout)
        self.assertEqual(out["ADVERSARY"], "gemini")
        self.assertIn("Codex detection failed", out["ADVERSARY_REASON"])

        res2 = subprocess.run(["/bin/bash", str(pick), "--adversary", "codex"],
                               capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res2.returncode, 3)
        self.assertIn("ADVERSARY_UNAVAILABLE", res2.stderr)
        self.assertIn("Codex detection failed", res2.stderr)
        self.assertNotIn("ADVERSARY", parse_lines(res2.stdout))


if __name__ == "__main__":
    unittest.main()
