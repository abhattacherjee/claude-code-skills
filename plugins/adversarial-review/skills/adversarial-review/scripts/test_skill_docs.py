"""Doc-contract tests: the skill steps run scripts that exist, and wire in the adversary."""
import os
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
SCRIPT_REF = re.compile(r"\$SCRIPTS/([A-Za-z0-9_.-]+)")


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


class AdversarialReviewDocTests(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_every_script_the_steps_run_exists_and_is_executable(self):
        names = set(SCRIPT_REF.findall(self.text))
        self.assertIn("codex-review.sh", names)
        for name in sorted(names):
            path = HERE / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(os.access(str(path), os.X_OK), name + " is not executable")

    def test_step_0_picks_the_adversary(self):
        step0 = section(self.text, "### Step 0", "### Step 1")
        self.assertIn("$SCRIPTS/pick-adversary.sh", step0)
        self.assertIn("Do not fall back", step0)
        # Ruling F6: eval "$(pick-adversary.sh ...)" discards pick-adversary's own
        # exit code (eval returns its own status), so the documented "Exit 3"
        # branch could never be reached. Step 0 must capture the real exit code.
        self.assertIn("PICK_RC", step0)

    def test_synthesize_is_told_the_adversary(self):
        step4 = section(self.text, "### Step 4 —", "### Step 4b")
        # The actual synthesize.py invocation, not just any prose mentioning
        # --adversary "$ADVERSARY" elsewhere in the step (the claude-only
        # paragraph below it references pr-audit.py with the same flag string).
        synth_call = section(step4, "$SCRIPTS/synthesize.py", "```")
        self.assertIn('--adversary "$ADVERSARY"', synth_call)
        self.assertIn("--adversary-findings", synth_call)
        self.assertIn("--adversary-verdicts", synth_call)

    def test_codex_sandbox_limits_are_documented(self):
        self.assertIn("read any file your user can read", self.text)
        self.assertIn("pure tests only", self.text)
        self.assertIn("project_doc_max_bytes=0", self.text)
        self.assertIn("--self-test", self.text)

    def test_the_verdict_key_is_adversary_verdict(self):
        self.assertIn("adversary_verdict", self.text)
        self.assertEqual(self.text.count("gemini_verdict"), 1)

    def test_all_four_canary_surfaces_are_named(self):
        """R-EX: the isolation canary covers AGENTS.md, .codex/config.toml,
        .agents/skills and .mcp.json (codex_review.py CANARY_SURFACES). Docs must
        name all four, not just the first two."""
        for surface in ("AGENTS.md", ".codex/config.toml", ".agents/skills", ".mcp.json"):
            self.assertIn(surface, self.text)

    def test_the_stamp_key_is_documented(self):
        self.assertIn("codex-isolation-<version>-<key>.ok", self.text)
        self.assertIn("CODEX_HOME", self.text)

    def test_claude_only_adversary_is_documented(self):
        step4 = section(self.text, "### Step 4 —", "### Step 4b")
        self.assertIn("claude-only", step4)


if __name__ == "__main__":
    unittest.main()
