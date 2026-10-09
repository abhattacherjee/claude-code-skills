"""Doc-contract tests for the review plugin: the skill steps run scripts that exist, and wire in
the adversary. They read only plugins/review/ (the `adversarial` and `deep` skills, the agents and
the README); the old adversarial-review plugin (removed in v4.0.0) had its own copy."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_review as cr  # noqa: E402

PLUGIN = HERE.parents[2]  # plugins/review
SKILL = HERE.parent / "SKILL.md"
PLUGIN_README = PLUGIN / "README.md"
DEEP = PLUGIN / "skills" / "deep"
SCRIPT_REF = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_.-]+)")


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


WS = re.compile(r"\s+")


def fenced_code(text):
    """The text inside every ``` fence in `text`."""
    return "\n".join(re.findall(r"```[^\n]*\n(.*?)```", text, re.S))


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
        self.assertIn("${CLAUDE_SKILL_DIR}/scripts/pick-adversary.sh", step0)
        self.assertIn("Do not fall back", step0)
        # Ruling F6: eval "$(pick-adversary.sh ...)" discards pick-adversary's own
        # exit code (eval returns its own status), so the documented exit 3 branch
        # could never be reached. Step 0 now reads the printed lines and the
        # script's own exit code, and never evals the output.
        self.assertIn("Exit code 3", step0)
        self.assertNotRegex(fenced_code(step0), r"\beval\b")

    def test_synthesize_is_told_the_adversary(self):
        step4 = section(self.text, "### Step 4 —", "### Step 4b")
        # The actual synthesize.py invocation, not just any prose mentioning
        # --adversary "$ADVERSARY" elsewhere in the step (the claude-only
        # paragraph below it references pr-audit.py with the same flag string).
        synth_call = section(step4, '"${CLAUDE_SKILL_DIR}/scripts/synthesize.py"', "```")
        self.assertIn('--adversary "<ADVERSARY>"', synth_call)
        self.assertIn("--adversary-findings", synth_call)
        self.assertIn("--adversary-verdicts", synth_call)

    def test_step_1_documents_base_and_the_local_diff(self):
        step1 = section(self.text, "### Step 1", "### Step 2")
        self.assertIn("`--base <branch>` when the user named a base", step1)
        self.assertIn("offer `--base <branch>`", step1)
        self.assertIn("exits 1", step1)
        self.assertIn("exits 2", step1)
        self.assertIn("--include-untracked", step1)
        self.assertIn("never sent", step1)
        self.assertIn("external service", step1)
        deep = (DEEP / "SKILL.md").read_text(encoding="utf-8")
        phase0 = section(deep, "## Phase 0", "## Phase 1")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts/detect-mode.sh", phase0)
        self.assertIn("--base <branch>", phase0)
        self.assertIn("--include-untracked", phase0)
        self.assertIn("never sent", phase0)
        self.assertIn("sent to the adversary model", phase0)

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
        paths = [HERE.parent / "CHANGELOG.md"]
        root = HERE.parents[4] / "CHANGELOG.md"
        if (HERE.parents[4] / ".claude-plugin" / "marketplace.json").is_file() and root.is_file():
            paths.append(root)  # the monorepo checkout only
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("only `PATH`, `HOME` and", text, str(path))
            for name in cr.PASSTHROUGH_ENV:
                self.assertIn("`%s`" % name, text, (str(path), name))

    def test_skill_changelog_starts_at_1_0_0_and_names_its_origin(self):
        # The skill and plugin changelogs no longer mirror each other: the plugin
        # one covers both skills. The skill one starts a fresh 1.0.0 entry that says
        # where the skill came from and keeps the older history below it.
        lines = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        first = next(l for l in lines if l.startswith("## ["))
        self.assertTrue(first.startswith("## [1.0.0]"), first)
        self.assertIn("was `adversarial-review`", "\n".join(lines[:4]))
        self.assertIn("adversarial-review` 0.2.0", "\n".join(lines))
        self.assertIn("## [1.0.0]", (PLUGIN / "CHANGELOG.md").read_text(encoding="utf-8"))

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
        # stops the run, the same as exit code 3 at Step 0.
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
        self.assertIn('--adversary-findings "<RUN_DIR>/r1-<ADVERSARY>.json"', degraded)
        self.assertIn('--claude-verdicts "<RUN_DIR>/r2-claude-verdicts.json"', degraded)
        self.assertIn('--adversary-verdicts "<RUN_DIR>/r2-empty.json"', degraded)

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
    """The README's skills table and agents table must name the adversary as Codex
    or Gemini, not Gemini alone (an earlier README kept a Claude<->Gemini-only
    description after the rest was made adversary-neutral). Nothing generates
    these rows, so a fixed string check is the right test."""

    def setUp(self):
        self.text = PLUGIN_README.read_text(encoding="utf-8")

    def test_no_gemini_only_pipeline_description_remains(self):
        # The exact regressions the review caught, checked verbatim so a
        # reintroduction of either fails loudly instead of blending back in.
        self.assertNotIn("Claude↔Gemini", self.text)
        self.assertNotIn("reads Gemini's R1 findings", self.text)

    def test_skills_row_names_the_adversary_not_just_gemini(self):
        skills = section(self.text, "## Skills", "## Agents")
        [row] = [line for line in skills.splitlines() if line.startswith("| `adversarial`")]
        self.assertIn("Codex", row)

    def test_cross_examiner_row_names_the_adversary_not_just_gemini(self):
        agents = section(self.text, "## Agents", "## How `adversarial` works")
        [cross_examiner_line] = [
            line for line in agents.splitlines() if line.startswith("| `cross-examiner`")
        ]
        self.assertIn("Codex", cross_examiner_line)

    def test_untracked_files_policy_is_stated(self):
        local = section(self.text, "- **Local mode**", "\n\n")
        self.assertIn("--include-untracked", local)
        self.assertIn("never sent", local)
        self.assertIn("sent to the adversary model", local)
        for name in (".env", "*.pem", "id_rsa*", "*credentials*"):
            self.assertIn(name, local)

    def test_no_script_install_advice_for_this_plugin(self):
        # scripts/install-plugin.sh copies skills and agents loose into ~/.claude. That
        # breaks deep's ${CLAUDE_PLUGIN_ROOT} script paths and the review:* agent names,
        # and a loose copy shadows the plugin's skills. Install through /plugin only.
        self.assertNotIn("install-plugin.sh", self.text)
        self.assertIn("claude plugin install", self.text)
        for path in (PLUGIN.parents[1] / "LOCAL-TESTING.md",):
            if path.is_file():
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"install-plugin\.sh[^\n]*plugins/review")

    def test_readme_names_both_skills_and_all_three_agents_with_their_old_names(self):
        for new, old in (("deep", "deep-review"), ("adversarial", "adversarial-review"),
                         ("bug-hunter", "adversarial-bug-hunter"),
                         ("convention-reviewer", "adversarial-convention-reviewer"),
                         ("cross-examiner", "adversarial-cross-examiner")):
            [row] = [l for l in self.text.splitlines() if l.startswith("| `%s` |" % new)]
            self.assertIn("`%s`" % old, row)


AGENTS_DIR = PLUGIN / "agents"


class AgentNeverIdleOnOwnBackgroundRunTests(unittest.TestCase):
    """#137: each agent that a reviewer dispatch can hand a long harness to must
    carry the never-idle rule in its own instructions, not only in the skill
    that dispatches it -- whoever dispatches it (review:adversarial, review:deep,
    or a future caller) gets the rule for free."""

    def test_bug_hunter_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "bug-hunter.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)

    def test_convention_reviewer_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "convention-reviewer.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)

    def test_cross_examiner_never_idle_on_its_own_background_run(self):
        text = (AGENTS_DIR / "cross-examiner.md").read_text(encoding="utf-8")
        rules = text.split("## Rules", 1)[1]
        self.assertIn("10-minute cap", rules)
        self.assertIn("20 minutes", rules)
        self.assertIn("Never go idle", rules)


AR_SCRIPT_NAME = re.compile(
    r"\b((?:codex|gemini)-review\.sh|pick-adversary\.sh|ensure-(?:codex|gemini)\.sh|pr-audit\.py|synthesize\.py"
    r"|check-cites\.py|secret_scan\.py)\b")


class DeepReviewDocTests(unittest.TestCase):
    """The same contract checks for the `deep` skill, read from plugins/review/skills/deep/."""

    def read(self, rel):
        return (DEEP / rel).read_text(encoding="utf-8")

    def test_the_deep_skill_is_where_the_tests_look(self):
        self.assertTrue((DEEP / "SKILL.md").is_file())
        self.assertTrue((DEEP / "references" / "audit-trail.md").is_file())

    def test_named_adversarial_review_scripts_exist(self):
        text = (self.read("SKILL.md") + self.read("references/audit-trail.md")
                + self.read("references/untrusted-input.md"))
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
        # exit code. Step 2.0 reads the printed lines and the exit code, never evals.
        self.assertIn("Exit code 3", phase2)
        self.assertNotRegex(fenced_code(section(phase2, "### Step 2.0", "### Step 2.1")), r"\beval\b")

    def test_recheck_rounds_use_pr_audit_recheck(self):
        text = self.read("references/audit-trail.md")
        self.assertIn('pr-audit.py" recheck', text)
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
        self.assertIn("r2-<ADVERSARY>-verdicts.json", step22)

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
        # #135 follow-up: the adversarial skill's own Step 2/3 already stop the run
        # on exit 3 when ADVERSARY_FLAG is set (never fall back for a forced
        # adversary). The deep skill's Step 2.1 (R1 finder) and Step 2.2 (R2 judge)
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


GEMINI_COMMAND = re.compile(r"`(gemini [^`]*)`|^\s*(gemini .*)$", re.M)


class UntrustedInputDocTests(unittest.TestCase):
    """#123: the diff is untrusted. It never reaches a shell argument, every model is
    told it is data, a secret stops the run, and a finding's file:line is checked
    before the implementer commits and pushes."""

    def setUp(self):
        self.deep = (DEEP / "SKILL.md").read_text(encoding="utf-8")
        self.ref = (DEEP / "references" / "untrusted-input.md").read_text(encoding="utf-8")
        self.adv = SKILL.read_text(encoding="utf-8")

    def gemini_commands(self, text):
        return [a or b for a, b in GEMINI_COMMAND.findall(text)]

    def test_every_gemini_command_shown_reads_its_prompt_from_a_file_on_stdin(self):
        for name, text in (("deep", self.deep), ("untrusted-input.md", self.ref), ("adversarial", self.adv)):
            commands = self.gemini_commands(text)
            for cmd in commands:
                with self.subTest(doc=name, cmd=cmd):
                    self.assertNotIn("$(", cmd)
                    self.assertNotIn("`", cmd)
                    self.assertNotRegex(cmd, r'-p\s+"<')
                    if " -p " in cmd:
                        self.assertRegex(cmd, r"\s<\s*\S")
        shown = self.gemini_commands(self.deep) + self.gemini_commands(self.ref)
        self.assertTrue(any(re.search(r"\s<\s*\S", c) for c in shown), shown)

    def test_the_old_argument_forms_are_gone(self):
        for text in (self.deep, self.ref, self.adv):
            self.assertNotIn('-p "<prompt>"', text)
            self.assertNotIn('-p "<brief', text)

    def test_a_red_flag_forbids_diff_text_in_a_shell_argument(self):
        flags = norm(section(self.deep, "## Red Flags", "## Integration"))
        self.assertIn("shell argument", flags)
        self.assertIn('-p "$(cat f)"', flags)
        self.assertIn("still unsafe", flags)

    def test_r1_and_r2_mark_the_diff_as_untrusted_data(self):
        r1 = norm(section(self.deep, "### Step 2.1", "### Step 2.2"))
        r2 = norm(section(self.deep, "### Step 2.2", "### Step 2.3"))
        for part in (r1, r2):
            self.assertIn("untrusted data", part)
            self.assertIn("never instructions", part)
        adv_r1 = norm(section(self.adv, "### Step 2 ", "### Step 3 "))
        adv_r2 = norm(section(self.adv, "### Step 3 ", "### Step 4 "))
        for part in (adv_r1, adv_r2):
            self.assertIn("untrusted data", part)

    def test_every_agent_treats_the_diff_as_data(self):
        for agent in ("bug-hunter.md", "convention-reviewer.md", "cross-examiner.md"):
            with self.subTest(agent=agent):
                text = norm((AGENTS_DIR / agent).read_text(encoding="utf-8"))
                self.assertIn("## Untrusted input", text)
                self.assertIn("never instructions", text)

    def test_out_of_tree_files_need_confirmation_per_path(self):
        phase0 = norm(section(self.deep, "## Phase 0", "## Phase 1"))
        step3 = phase0.split("3. ", 1)[1].split("4. ", 1)[0]
        self.assertIn("confirm", step3)
        self.assertIn("each path", step3)
        self.assertIn("secret scan", step3)

    def test_a_secret_hit_stops_and_never_falls_back(self):
        for name, text in (("deep", self.deep), ("adversarial", self.adv)):
            with self.subTest(doc=name):
                flat = norm(text)
                self.assertIn("SECRET_SUSPECTED", flat)
                self.assertIn("--allow-secret-match", flat)
                self.assertIn("exit code is 4", flat)
                self.assertRegex(flat, r"[Ee]xit (code )?4 is not exit (code )?3")
        degrade = norm(section(self.adv, "## Degradation Behavior", "## Same-Diff Invariant"))
        self.assertIn("exit 4", degrade.lower())

    def test_step_2_5_checks_cites_before_the_implementer(self):
        step = norm(section(self.deep, "### Step 2.5", "### Step 2.6"))
        self.assertIn("check-cites.py", step)
        self.assertLess(step.index("check-cites.py"), step.index("implementer sub-agent"))
        self.assertIn("--status survivor", step)

    def test_step_2_5_asks_before_pushing_someone_elses_pr(self):
        step = norm(section(self.deep, "### Step 2.5", "### Step 2.6"))
        self.assertIn("gh pr view <PR> --json author --jq .author.login", step)
        self.assertIn("gh api user --jq .login", step)
        self.assertIn("confirm", step)
        self.assertLess(step.index("gh api user"), step.index("Commit Phase 2"))

    def test_the_reference_is_linked_and_has_contents(self):
        self.assertIn("references/untrusted-input.md", self.deep)
        if len(self.ref.splitlines()) > 100:
            self.assertIn("## Contents", "\n".join(self.ref.splitlines()[:30]))


class GeminiFallbackShapeTests(unittest.TestCase):
    """Step 2.2 of deep tells you to write Gemini's verdicts by hand when
    gemini-review.sh fails. synthesize.py must read the file exactly as documented."""

    def setUp(self):
        text = (DEEP / "SKILL.md").read_text(encoding="utf-8")
        self.step22 = section(text, "### Step 2.2", "### Step 2.3")
        self.tmp = Path(tempfile.mkdtemp(prefix="fallback-shape-"))
        self.addCleanup(__import__("shutil").rmtree, str(self.tmp), True)

    def documented_json(self):
        note = section(self.step22, "**Gemini reliability note:**", "**Missing verdicts")
        return re.search(r"```json\n(.*?)```", note, re.S).group(1)

    def run_synth(self, verdicts_text):
        def put(name, obj):
            path = self.tmp / name
            path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
            return str(path)
        finding = lambda fid: {"id": fid, "path": "a.py", "line": 1, "severity": "minor", "category": "bug",
                               "title": "t", "rationale": "r", "origin": "claude"}
        claude = put("r1-claude.json", {"findings": [finding("C-001"), finding("C-002"), finding("C-003")]})
        adv = put("r1-gemini.json", {"findings": []})
        cv = put("r2-claude-verdicts.json", {"verdicts": []})
        gv = put("r2-gemini-verdicts.json", verdicts_text)
        out = self.tmp / "report.json"
        res = subprocess.run(
            [sys.executable, str(HERE / "synthesize.py"), "--adversary", "gemini",
             "--claude-findings", claude, "--adversary-findings", adv,
             "--adversary-verdicts", gv, "--claude-verdicts", cv, "--json", str(out)],
            capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(res.returncode, 0, res.stderr)
        return {f["id"]: f for f in json.loads(out.read_text())["findings"]}

    def test_the_documented_shape_is_read_as_confirm_and_refute(self):
        got = self.run_synth(self.documented_json())
        self.assertEqual(got["C-001"]["status"], "survivor")
        self.assertEqual(got["C-001"]["adversary_verdict"], "confirm")
        self.assertEqual(got["C-002"]["status"], "rejected")
        self.assertEqual(got["C-002"]["adversary_verdict"], "refute")
        self.assertEqual(got["C-003"]["status"], "unconfirmed")  # no entry

    def test_the_old_prompt_shape_is_not_what_the_docs_ask_for(self):
        # The earlier text asked for {id, verdict, reason}. synthesize.py does not read
        # a bare `verdict` key, so every finding would have stayed unconfirmed.
        got = self.run_synth(json.dumps({"verdicts": [{"id": "C-001", "verdict": "confirm", "reason": "x"}]}))
        self.assertEqual(got["C-001"]["status"], "unconfirmed")
        self.assertNotIn("verdict:confirm|refute", self.step22)
        self.assertIn("adversary_verdict", self.documented_json())

    def test_empty_verdicts_cover_gemini_as_well_as_codex(self):
        missing = section(self.step22, "**Missing verdicts", "Emit an R2 digest")
        self.assertIn('{"verdicts":[]}', missing)
        self.assertIn("Gemini", missing)
        self.assertIn("Codex", missing)
        got = self.run_synth('{"verdicts":[]}')
        self.assertTrue(all(f["status"] == "unconfirmed" for f in got.values()))


if __name__ == "__main__":
    unittest.main()
