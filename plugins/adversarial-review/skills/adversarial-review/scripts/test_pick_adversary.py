"""Tests for pick-adversary.sh: Codex, then Gemini, then Claude-only, and forced choices."""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_ensure_codex import StubEnv, parse_lines  # noqa: E402

PICK = HERE / "pick-adversary.sh"


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


if __name__ == "__main__":
    unittest.main()
