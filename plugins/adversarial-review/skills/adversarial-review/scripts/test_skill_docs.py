"""Doc-contract tests: the skill steps run scripts that exist, and wire in the adversary."""
import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_review as cr  # noqa: E402

SKILL = HERE.parent / "SKILL.md"
PLUGIN_README = HERE.parent.parent.parent / "README.md"
SCRIPT_REF = re.compile(r"\$SCRIPTS/([A-Za-z0-9_.-]+)")


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


WS = re.compile(r"\s+")


def norm(text):
    """Collapse whitespace/newlines to a single space, so a phrase-match assertion
    doesn't break just because Markdown line-wraps it mid-phrase (#137 tests)."""
    return WS.sub(" ", text)


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

    def test_every_passthrough_env_var_is_documented(self):
        # deep-review X-003: the docs said Codex gets only PATH, HOME and CODEX_HOME,
        # but build_env also passes the PASSTHROUGH_ENV list. Derive it from the code.
        sandbox = section(self.text, "### Codex sandbox", "One `codex-review.sh` call")
        self.assertTrue(cr.PASSTHROUGH_ENV)
        for name in ("PATH", "HOME", "CODEX_HOME") + tuple(cr.PASSTHROUGH_ENV):
            self.assertIn("`%s`" % name, sandbox, name)
        self.assertNotIn("holding only `PATH`, `HOME` and your own `CODEX_HOME`", self.text)

    def test_changelogs_list_the_passthrough_env_vars(self):
        paths = [HERE.parent / "CHANGELOG.md", HERE.parent.parent.parent / "CHANGELOG.md"]
        root = HERE.parents[4] / "CHANGELOG.md"
        if (HERE.parents[4] / "deep-review").is_dir() and root.is_file():
            paths.append(root)  # the monorepo checkout only
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("only `PATH`, `HOME` and", text, str(path))
            for name in cr.PASSTHROUGH_ENV:
                self.assertIn("`%s`" % name, text, (str(path), name))

    def test_strict_is_documented_as_the_hardened_judge(self):
        # deep-review X-002: --strict must be described as what it does.
        self.assertIn("verbatim", section(self.text, "**Low-signal escalation:**", "- Claude rubber-stamping"))
        self.assertNotIn("one strict retry", self.text)

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

    def test_step_2_r1_dispatch_never_idle_on_its_own_background_run(self):
        # #137: a reviewer that starts a harness in the background and says "I'll
        # report once it finishes" goes idle -- it is not woken when its own job
        # ends. R1's Claude finders must carry the never-idle rule.
        step2 = norm(section(self.text, "### Step 2 — R1", "### Step 3 — R2"))
        self.assertIn("10-minute cap", step2)
        self.assertIn("20 minutes", step2)
        self.assertIn("Never go idle", step2)

    def test_step_2_orchestrator_checks_before_reporting_waiting(self):
        # #137: the orchestrator must not report "waiting on X" without having
        # checked X's process or output within ~10 minutes.
        step2 = section(self.text, "### Step 2 — R1", "### Step 3 — R2")
        self.assertIn("ps -axo pid,etime,command", step2)
        self.assertIn("10 minutes", step2)
        self.assertIn('waiting on', step2.lower())

    def test_step_3_r2_dispatch_never_idle_on_its_own_background_run(self):
        step3 = norm(section(self.text, "### Step 3 — R2", "### Step 4 — Converge"))
        self.assertIn("10-minute cap", step3)
        self.assertIn("never go idle", step3.lower())

    def test_step_3_orchestrator_checks_before_reporting_waiting(self):
        step3 = section(self.text, "### Step 3 — R2", "### Step 4 — Converge")
        self.assertIn("ps -axo pid,etime,command", step3)
        self.assertIn("10 minutes", step3)
        self.assertIn('waiting on', step3.lower())

    def test_codex_sandbox_run_in_background_has_orchestrator_check(self):
        # #137: the Codex/Gemini adversary scripts are the other background job the
        # orchestrator waits on (Codex sandbox's run_in_background note).
        sandbox = section(self.text, "### Codex sandbox", "## Quick Start")
        self.assertIn("run_in_background", sandbox)
        self.assertIn("do not go idle waiting on it", sandbox)
        self.assertIn("ps -axo pid,etime,command", sandbox)
        self.assertIn("10 minutes", sandbox)


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


AGENTS_DIR = HERE.parent.parent.parent / "agents"


class AgentNeverIdleOnOwnBackgroundRunTests(unittest.TestCase):
    """#137: each agent that a reviewer dispatch can hand a long harness to must
    carry the never-idle rule in its own instructions, not only in the skill
    that dispatches it -- whoever dispatches it (adversarial-review, deep-review,
    or a future caller) gets the rule for free."""

    def test_bug_hunter_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "adversarial-bug-hunter.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)

    def test_convention_reviewer_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "adversarial-convention-reviewer.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)

    def test_cross_examiner_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "adversarial-cross-examiner.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)


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

    def test_step_2_6_does_not_converge_with_unchecked_findings(self):
        # deep-review X-001: pr-audit.py recheck carries a prior finding Codex did not
        # re-check over with no events and prints unchecked=<N>. Step 2.6 must treat
        # those as not resolved: keep looping (within the cap), and surface them at
        # the cap.
        step26 = section(self.read("SKILL.md"), "### Step 2.6", "\n---\n")
        self.assertIn("unchecked=", step26)
        self.assertIn("not resolved", step26)
        self.assertIn("unchecked=0", step26)
        stop = section(step26, "Stop when", "\n\n")
        self.assertIn("unchecked=0", stop)
        self.assertIn("unchecked", section(stop, "reaches 3", "\n\n"))
        audit = self.read("references/audit-trail.md")
        self.assertIn("unchecked=", audit)
        self.assertIn("carried over", audit)

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

    def test_phase1_step1_dispatch_never_idle_on_its_own_background_run(self):
        # #137: reviewers must run long harnesses in the foreground and never go
        # idle waiting on their own background job.
        each_round = section(self.read("SKILL.md"), "### Each round", "### Phase 1 convergence")
        step1 = norm(section(each_round, "1. **Dispatch", "2. **Aggregate"))
        self.assertIn("10-minute cap", step1)
        self.assertIn("20 minutes", step1)
        self.assertIn("Never go idle", step1)

    def test_phase1_step2_aggregate_checks_before_reporting_waiting(self):
        each_round = section(self.read("SKILL.md"), "### Each round", "### Phase 1 convergence")
        step2 = section(each_round, "2. **Aggregate", "3. **Fix")
        self.assertIn("ps -axo pid,etime,command", step2)
        self.assertIn("10 minutes", step2)
        self.assertIn('Never report "waiting on X"', step2)

    def test_phase1_step3_fix_implementer_never_idle_on_its_own_background_run(self):
        # #137 follow-up: item 2 (Aggregate) tells the orchestrator to watch a
        # background job, but item 3 (Fix) never told the implementer itself the
        # never-idle rule. It must carry the same rule as the reviewers.
        each_round = section(self.read("SKILL.md"), "### Each round", "### Phase 1 convergence")
        step3 = norm(section(each_round, "3. **Fix", "4. **Re-review"))
        self.assertIn("10-minute cap", step3)
        self.assertIn("20 minutes", step3)
        self.assertIn("never go idle", step3.lower())

    def test_phase1_step4_rereview_never_idle_on_its_own_background_run(self):
        each_round = section(self.read("SKILL.md"), "### Each round", "### Phase 1 convergence")
        step4 = section(each_round, "4. **Re-review", "5. **Converge")
        self.assertIn("foreground", step4)
        self.assertIn("never go idle", step4.lower())

    def test_step_2_1_r1_briefs_never_idle_and_orchestrator_checks(self):
        step21 = section(self.read("SKILL.md"), "### Step 2.1", "### Step 2.2")
        self.assertIn("10-minute cap", step21)
        self.assertIn("never go idle", step21.lower())
        self.assertIn("ps -axo pid,etime,command", step21)
        self.assertIn("10 minutes", step21)

    def test_step_2_2_r2_briefs_never_idle_and_orchestrator_checks(self):
        step22 = norm(section(self.read("SKILL.md"), "### Step 2.2", "### Step 2.3"))
        self.assertIn("10-minute cap", step22)
        self.assertIn("never go idle", step22.lower())
        self.assertIn("ps -axo pid,etime,command", step22)
        self.assertIn("10 minutes", step22)

    def test_step_2_5_implementer_never_idle_on_its_own_background_run(self):
        # #137 follow-up: Step 2.5's implementer dispatch (Phase 2's fix step) must
        # carry the same never-idle rule as Phase 1's Fix step and the R1/R2 briefs.
        step25 = norm(section(self.read("SKILL.md"), "### Step 2.5", "### Step 2.6"))
        self.assertIn("10-minute cap", step25)
        self.assertIn("20 minutes", step25)
        self.assertIn("never go idle", step25.lower())

    def test_red_flags_names_idle_reviewer_wait(self):
        red_flags = section(self.read("SKILL.md"), "## Red Flags", "## Integration")
        self.assertIn(
            'Report "waiting on a reviewer" without checking whether it is idle', red_flags)

    def test_step_2_1_and_2_2_stop_on_a_forced_unavailable_adversary(self):
        # #135 follow-up: adversarial-review's own Step 2/3 already stop the run
        # on exit 3 when ADVERSARY_FLAG is set (never fall back for a forced
        # adversary). deep-review's Step 2.1 (R1 finder) and Step 2.2 (R2 judge)
        # must apply the same rule instead of always taking the auto-mode
        # fallback path. Auto mode (no ADVERSARY_FLAG) keeps its documented
        # fallback -- see test_step_2_2_writes_empty_verdicts_when_the_codex_judge_fails.
        skill = self.read("SKILL.md")
        for start, end in (("### Step 2.1", "### Step 2.2"), ("### Step 2.2", "### Step 2.3")):
            part = section(skill, start, end)
            self.assertIn("ADVERSARY_FLAG", part, start)
            self.assertIn("ADVERSARY_UNAVAILABLE", part, start)
            self.assertIn("stop the run with exit 3", part, start)
            self.assertIn("never fall back", part.lower(), start)


if __name__ == "__main__":
    unittest.main()
