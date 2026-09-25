"""Doc-contract tests: the skill steps run scripts that exist, and wire in the adversary."""
import os
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
PLUGIN_README = HERE.parent.parent.parent / "README.md"
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

    def test_r2_digest_relays_unjudged(self):
        # Final review, Important 1: a partial judge exits 0, and synthesize's
        # per-direction unjudged= count is the only sign. The digest and the relay
        # list must carry it, and the wrong "total - judged" formula must be gone.
        step3 = section(self.text, "### Step 3", "### Step 4 —")
        digest = section(step3, "=== R2 Cross-Examination Digest ===", "```")
        self.assertEqual(digest.count("unjudged="), 2)
        self.assertEqual(digest.count("⚠ UNJUDGED"), 2)
        self.assertIn("unjudged > 0", step3)
        self.assertNotIn("− judged", self.text)
        self.assertNotIn("may derive", self.text)
        step4 = section(self.text, "### Step 4 —", "### Step 4b")
        self.assertIn("`unjudged=`", step4)
        self.assertIn("unjudged > 0", step4)

    def test_a_forced_adversary_never_falls_back_at_run_time(self):
        # Final review, Important 2: with --adversary set, an exit 3 at R1 or R2
        # stops the run, the same as PICK_RC=3 at Step 0.
        for start, end in (("### Step 2", "### Step 3"), ("### Step 3", "### Step 4 —"),
                           ("## Degradation Behavior", "## Same-Diff Invariant")):
            part = section(self.text, start, end)
            self.assertIn("ADVERSARY_FLAG", part, start)
            self.assertIn("ADVERSARY_UNAVAILABLE", part, start)
            self.assertIn("stop the run with exit 3", part, start)
            self.assertIn("never fall back", part.lower(), start)

    def test_r2_failure_keeps_the_adversarys_r1_findings(self):
        # Final review, minor 4: an R2 judge failure must not drop the adversary's
        # R1 findings or Claude's verdicts on them.
        degraded = section(self.text, "## Degradation Behavior", "## Same-Diff Invariant")
        self.assertIn('--adversary-findings "$RUN_DIR/r1-$ADVERSARY.json"', degraded)
        self.assertIn('--claude-verdicts "$RUN_DIR/r2-claude-verdicts.json"', degraded)
        self.assertIn('--adversary-verdicts "$RUN_DIR/r2-empty.json"', degraded)

    def test_codex_timeout_fits_the_bash_tool(self):
        # Final review, minor 2: the default is below the Bash tool's 600 s cap, and
        # the docs say how to run a call that may make up to three Codex runs.
        self.assertIn("default 540 s", self.text)
        self.assertNotIn("900 s", self.text)
        self.assertIn("run_in_background", self.text)
        self.assertIn("SIGTERM", self.text)


class PluginReadmeDocTests(unittest.TestCase):
    """Fix round 1: plugins/adversarial-review/README.md's `## Contents` bullets
    (### Skills and ### Agents) still asserted a Claude<->Gemini-only pipeline
    after the rest of the file was made adversary-neutral -- a plain missed
    edit, not a regenerated/stale artifact (review: task-8-review.md Important
    #1/#2). These bullets are not auto-generated by anything, so a fixed string
    check is the right test, not a sync-tool run."""

    def setUp(self):
        self.text = PLUGIN_README.read_text(encoding="utf-8")

    def test_no_gemini_only_pipeline_description_remains(self):
        # The exact regressions the review caught, checked verbatim so a
        # reintroduction of either fails loudly instead of blending back in.
        self.assertNotIn("Claude↔Gemini", self.text)
        self.assertNotIn("reads Gemini's R1 findings", self.text)

    def test_skills_bullet_names_the_adversary_not_just_gemini(self):
        contents = section(self.text, "## Contents", "## Installation")
        skills = section(contents, "### Skills", "### Agents")
        self.assertIn("Codex", skills)

    def test_cross_examiner_bullet_names_the_adversary_not_just_gemini(self):
        contents = section(self.text, "## Contents", "## Installation")
        agents = section(contents, "### Agents", "### Scripts")
        [cross_examiner_line] = [
            line for line in agents.splitlines() if "adversarial-cross-examiner" in line
        ]
        self.assertIn("Codex", cross_examiner_line)


REPO = HERE.parents[4]
DR_SOURCE = REPO / "deep-review"
DR_COPY = REPO / "plugins" / "deep-review" / "skills" / "deep-review"
AR_SCRIPT_NAME = re.compile(
    r"\b((?:codex|gemini)-review\.sh|pick-adversary\.sh|ensure-(?:codex|gemini)\.sh|pr-audit\.py|synthesize\.py)\b")


@unittest.skipUnless(DR_SOURCE.is_dir() and DR_COPY.is_dir(), "not in the monorepo checkout")
class DeepReviewDocTests(unittest.TestCase):
    def read(self, rel):
        return (DR_SOURCE / rel).read_text(encoding="utf-8")

    def test_published_copy_is_byte_identical(self):
        for src in sorted(DR_SOURCE.rglob("*")):
            if src.is_dir() or src.name == "plugin-manifest.json":
                continue
            rel = src.relative_to(DR_SOURCE)
            self.assertEqual((DR_COPY / rel).read_bytes(), src.read_bytes(), str(rel))
        for copy in sorted(DR_COPY.rglob("*")):
            if copy.is_file():
                self.assertTrue((DR_SOURCE / copy.relative_to(DR_COPY)).is_file(), str(copy))

    def test_named_adversarial_review_scripts_exist(self):
        text = self.read("SKILL.md") + self.read("references/audit-trail.md")
        for name in sorted(set(AR_SCRIPT_NAME.findall(text))):
            self.assertTrue((HERE / name).is_file(), name)

    def test_phase_2_picks_the_adversary_and_never_calls_codex_directly(self):
        phase2 = section(self.read("SKILL.md"), "## Phase 2", "## Final report")
        self.assertIn("pick-adversary.sh", phase2)
        self.assertIn("codex-review.sh", phase2)
        self.assertIn("--mode counter", phase2)
        self.assertIn("### Step 2.6", phase2)
        self.assertIn("Never call `codex` directly", phase2)
        # Ruling F6: eval "$(pick-adversary.sh ...)" discards pick-adversary's own
        # exit code, so Step 2.0 must capture it explicitly, same as AR's Step 0.
        self.assertIn("PICK_RC", phase2)

    def test_recheck_rounds_use_pr_audit_recheck(self):
        text = self.read("references/audit-trail.md")
        self.assertIn('"$AUDIT" recheck', text)
        self.assertIn("phase2-recheck", text)
        self.assertNotIn("Phase 2 has no adversary re-check round yet", text)

    def test_step_2_6_handles_codex_becoming_unavailable_mid_recheck(self):
        # Fix round 1, Important: codex-review.sh (exit 3) and pr-audit.py recheck
        # (exit 2) can both fail partway through the Step 2.6 loop, after Step 2.0
        # already picked Codex. Step 2.6 must say what to do -- stop, leave threads
        # open, no retry, no fallback -- the same way Steps 2.1/2.2 already do for
        # their own exit-3 cases.
        step26 = section(self.read("SKILL.md"), "### Step 2.6", "\n---\n")
        self.assertIn("Exit 3", step26)
        self.assertIn("Stop the re-check loop", step26)
        self.assertIn("Exit 2", step26)
        self.assertIn("leave the remaining threads open", step26)


    def test_step_2_2_writes_empty_verdicts_when_the_codex_judge_fails(self):
        # Final review, minor 1: synthesize.py exits 1 on a missing verdicts file.
        step22 = section(self.read("SKILL.md"), "### Step 2.2", "### Step 2.3")
        self.assertIn('{"verdicts":[]}', step22)
        self.assertIn("r2-$ADVERSARY-verdicts.json", step22)

    def test_step_2_6_handles_codex_review_exit_1(self):
        # Final review, minor 7: exit 1 (for example a missing --prior file) stops
        # the loop the same way exit 3 does.
        step26 = section(self.read("SKILL.md"), "### Step 2.6", "\n---\n")
        self.assertIn("**Exit 1**", step26)
        exit1 = section(step26, "**Exit 1**", "\n3. ")
        self.assertIn("Stop the re-check loop", exit1)
        self.assertIn("leave the remaining threads open", exit1)
        self.assertIn("round summary", exit1)

if __name__ == "__main__":
    unittest.main()
