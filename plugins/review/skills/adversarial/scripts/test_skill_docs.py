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
        # one covers both skills. The skill one started a fresh 1.0.0 entry that says
        # where the skill came from and keeps the older history below it. Later
        # releases go above 1.0.0; the oldest numbered entry stays 1.0.0.
        lines = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        entries = [l for l in lines if l.startswith("## [")]
        self.assertTrue(entries[-1].startswith("## [1.0.0]"), entries)
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

    # #137 put the never-idle rule in every dispatch step. #121 moved it, with the
    # delivery contract, into references/dispatch-contract.md: each step now points
    # there and names its own results file. DispatchContractTests checks the rule text.
    CONTRACT = "./references/dispatch-contract.md"

    def each_round(self):
        return section(self.read("SKILL.md"), "### Each round", "### Phase 1 convergence")

    def test_phase1_step1_dispatch_uses_the_contract(self):
        step1 = norm(section(self.each_round(), "1. **Dispatch", "2. **Aggregate"))
        self.assertIn(self.CONTRACT, step1)
        self.assertIn("<RUN_DIR>/p1-r<N>-<dimension>.json", step1)

    def test_phase1_step2_aggregate_collects_from_disk_and_checks_waiting(self):
        step2 = norm(section(self.each_round(), "2. **Aggregate", "3. **Fix"))
        self.assertIn(self.CONTRACT, step2)
        self.assertIn("from disk", step2)
        self.assertIn("NO REPORT", step2)
        self.assertIn("waiting on a background job", step2)

    def test_phase1_step3_fix_implementer_uses_the_contract(self):
        step3 = norm(section(self.each_round(), "3. **Fix", "4. **Re-review"))
        self.assertIn(self.CONTRACT, step3)
        self.assertIn("<RUN_DIR>/p1-r<N>-fix.md", step3)

    def test_phase1_step4_rereview_uses_the_contract_with_a_new_path(self):
        step4 = norm(section(self.each_round(), "4. **Re-review", "5. **Converge"))
        self.assertIn("contract block again", step4)
        self.assertIn("p1-r<N+1>-<dimension>.json", step4)
        self.assertIn("from disk", step4)

    def test_phase1_convergence_excludes_no_report(self):
        conv = norm(section(self.read("SKILL.md"), "### Phase 1 convergence", "Commit Phase 1"))
        self.assertIn("`NO REPORT` and `PARTIAL` are not CONVERGED", conv)

    def test_step_2_1_r1_briefs_use_the_contract(self):
        step21 = norm(section(self.read("SKILL.md"), "### Step 2.1", "### Step 2.2"))
        self.assertIn(self.CONTRACT, step21)
        self.assertIn("<RUN_DIR>/r1-bug-hunter.json", step21)
        self.assertIn("<RUN_DIR>/r1-convention.json", step21)
        self.assertIn("from disk", step21)

    def test_step_2_2_r2_brief_uses_the_contract(self):
        step22 = norm(section(self.read("SKILL.md"), "### Step 2.2", "### Step 2.3"))
        self.assertIn(self.CONTRACT, step22)
        self.assertIn("NO REPORT", step22)

    def test_step_2_5_implementer_uses_the_contract(self):
        step25 = norm(section(self.read("SKILL.md"), "### Step 2.5", "### Step 2.6"))
        self.assertIn(self.CONTRACT, step25)
        self.assertIn("<RUN_DIR>/p2-fix-<n>.md", step25)

    def test_the_never_idle_rule_lives_in_one_place(self):
        # The rule used to be repeated six times in SKILL.md.
        skill = self.read("SKILL.md")
        self.assertNotIn("10-minute cap", skill)
        self.assertNotIn("ps -axo pid,etime,command", skill)

    def test_final_report_lists_every_no_report(self):
        final = norm(section(self.read("SKILL.md"), "## Final report", "## Red Flags"))
        self.assertIn("`NO REPORT`", final)
        self.assertIn('Never fold one into "converged"', final)

    def test_red_flags_names_agent_silence(self):
        red_flags = norm(section(self.read("SKILL.md"), "## Red Flags", "## Integration"))
        self.assertIn("**Treat agent silence as a clean verdict.**", red_flags)
        self.assertIn("Chase at most twice", red_flags)

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

    def test_every_adversary_command_has_an_exit_4_rule_nearby(self):
        lines = self.deep.splitlines()
        cmds = [i for i, l in enumerate(lines) if re.search(r'(codex|gemini)-review\.sh" --', l)]
        self.assertGreaterEqual(len(cmds), 4)
        for i in cmds:
            with self.subTest(line=i + 1):
                near = norm("\n".join(lines[i:i + 16]))
                self.assertRegex(near, r"[Ee]xit (code is )?4\b", lines[i])

    def test_out_of_tree_files_are_appended_as_a_diff(self):
        phase0 = norm(section(self.deep, "## Phase 0", "## Phase 1"))
        self.assertIn("git diff --no-index /dev/null <path> >> <DIFF>", phase0)
        self.assertIn("git diff --no-index /dev/null <path> >> <DIFF>", norm(self.ref))
        self.assertIn("not detected", norm(self.ref))

    def test_step_2_6_diffs_are_deterministic_and_cites_are_checked(self):
        step = norm(section(self.deep, "### Step 2.6", "## Final report"))
        for flag in ("--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/"):
            self.assertIn(flag, step)
        self.assertNotRegex(step, r"`git diff <REVIEWED_SHA>")
        self.assertIn('--findings "<RUN_DIR>/round-<K>.json" --status survivor', step)
        self.assertIn("<BASE_REF>...<FIX_SHA>", step)

    def test_check_cites_exit_codes_match_the_script(self):
        step = norm(section(self.deep, "### Step 2.5", "### Step 2.6"))
        self.assertIn("Exit 3", step)
        self.assertNotIn("Exit 1:", step)
        for text in (norm(self.ref), norm(PLUGIN_README.read_text(encoding="utf-8"))):
            self.assertIn("3 some failed", text)

    def test_step_2_5_treats_an_empty_login_as_someone_else(self):
        step = norm(section(self.deep, "### Step 2.5", "### Step 2.6"))
        self.assertIn("If either login is empty", step)

    def test_the_gemini_size_cap_is_stated_correctly(self):
        self.assertNotIn("well below that", self.ref)
        self.assertIn("refuses an input over 8 MiB", norm(self.ref))

    def test_the_direct_gemini_fallback_goes_on_only_on_exit_0(self):
        self.assertIn("Go on only on exit 0", norm(self.ref))

    def test_adversarial_steps_give_exit_1_and_exit_4_their_own_rules(self):
        for start, end in (("### Step 2 ", "### Step 3 "), ("### Step 3 ", "### Step 4 ")):
            part = section(self.adv, start, end)
            with self.subTest(step=start):
                self.assertIn("**If exit code is 4**", part)
                self.assertIn("**If exit code is 1**", part)

    def test_agents_and_readme_wording(self):
        for agent in ("bug-hunter.md", "convention-reviewer.md"):
            self.assertNotIn("`DIFF_FILE`, and every", (AGENTS_DIR / agent).read_text(encoding="utf-8"))
        self.assertNotIn("gemini -p ...", PLUGIN_README.read_text(encoding="utf-8"))

    def test_the_reference_is_linked_and_has_contents(self):
        self.assertIn("references/untrusted-input.md", self.deep)
        if len(self.ref.splitlines()) > 100:
            self.assertIn("## Contents", "\n".join(self.ref.splitlines()[:30]))


class DispatchContractTests(unittest.TestCase):
    """#121: references/dispatch-contract.md holds the delivery contract and the
    never-idle rule that every dispatch in deep and adversarial points to."""

    def setUp(self):
        self.text = (DEEP / "references" / "dispatch-contract.md").read_text(encoding="utf-8")
        self.flat = norm(self.text)

    def test_the_block_says_write_the_file_before_replying(self):
        block = section(self.text, "## The block every dispatch starts with", "## Results files")
        block = norm(fenced_code(block))
        self.assertIn("DELIVERY CONTRACT — READ FIRST", block)
        self.assertIn("use the Write tool to write your results to <RESULTS_FILE>", block)
        self.assertIn("Write it even if you found nothing", block)
        self.assertIn("Your reply can be one word", block)
        self.assertIn("Budget about 15 tool calls", block)

    def test_the_block_carries_the_never_idle_rule(self):
        block = norm(fenced_code(section(self.text, "## The block every dispatch starts with",
                                         "## Results files")))
        self.assertIn("in the foreground", block)
        self.assertIn("10-minute cap", block)
        self.assertIn("20 minutes", block)
        self.assertIn("Never go idle", block)

    def test_the_orchestrator_checks_before_reporting_waiting(self):
        part = norm(self.text.split("## When an agent says it is waiting", 1)[1])
        self.assertIn("ps -axo pid,etime,command", part)
        self.assertIn("10 minutes", part)
        self.assertIn('Never report "waiting on X"', part)

    def test_silence_is_no_report_with_a_chase_cap_of_two(self):
        part = norm(section(self.text, "## Silence, the chase cap, and NO REPORT", "## When an agent"))
        self.assertIn("**Chase at most twice.**", part)
        self.assertIn("Do not chase a third time", part)
        self.assertIn("switch mechanism once", part)
        self.assertIn("never CONVERGED", part)
        self.assertIn("List every NO REPORT and PARTIAL in the final report", part)

    def test_results_are_read_from_disk_not_replies(self):
        part = norm(section(self.text, "## Collect results from disk", "## Silence"))
        self.assertIn("read each results file from disk", part)
        self.assertIn("The reply is not the result", part)

    def test_a_dispatch_path_must_not_exist_yet(self):
        self.assertIn("**The path must not exist when you dispatch.**", self.flat)
        self.assertIn("-retry1", self.flat)

    def test_a_delivered_retry_is_copied_to_the_base_name(self):
        # PR #218 review I4: synthesize.py reads the fixed name, never -retry1.
        self.assertIn("When a retry delivers, copy it to the slot's base name before any step or "
                      "script reads that name", self.flat)

    def test_partial_never_counts_as_converged(self):
        # PR #218 review I3: a reviewer writes "partial" early; that file must not converge.
        block = norm(fenced_code(section(self.text, "## The block every dispatch starts with",
                                         "## Results files")))
        self.assertIn("Never mark partial work CONVERGED or complete", block)
        collect = norm(section(self.text, "## Collect results from disk", "## Silence"))
        self.assertIn("still marked partial: **not delivered yet**", collect)
        self.assertIn("A PARTIAL file never counts as CONVERGED", collect)

    def test_a_partial_r2_delivery_keeps_its_verdicts(self):
        # PR #218 Codex X-003: only NO REPORT empties r2-claude-verdicts.json.
        part = norm(section(self.text, "## Silence, the chase cap, and NO REPORT", "## When an agent"))
        r2 = part.split("- R2,", 1)[1].split("- Implementer:", 1)[0]
        self.assertIn('NO REPORT: write `{"verdicts":[]}`', r2)
        self.assertIn("PARTIAL: keep the delivered verdicts", r2)
        self.assertIn("Never replace a partial file with an empty one", r2)

    def test_markdown_results_have_their_own_partial_marker(self):
        # PR #218 review S4: the implementer files are Markdown, not JSON.
        self.assertIn("the first line PARTIAL in Markdown", self.flat)
        self.assertIn("one `## Fix <i>` heading per numbered fix", self.flat)

    def test_step_2_6_names_the_recheck_judge_file(self):
        step26 = norm(section((DEEP / "SKILL.md").read_text(encoding="utf-8"), "### Step 2.6", "## Final report"))
        self.assertIn("<RUN_DIR>/r2-claude-verdicts-recheck-<K>.json", step26)

    def test_exit_5_never_lets_the_orchestrator_pick_a_verdict(self):
        # PR #218 review S3: re-ask the judge; renaming a key or deleting an entry only.
        deep = norm(section((DEEP / "SKILL.md").read_text(encoding="utf-8"), "### Step 2.4", "### Step 2.5"))
        adv = norm(section(SKILL.read_text(encoding="utf-8"), "### Step 4 ", "### Step 4b"))
        self.assertIn("never set a verdict value yourself", deep)
        self.assertIn("never set or change a verdict value yourself", adv)
        for text in (deep, adv):
            self.assertIn("rename a wrong key", text)

    def test_results_file_names_do_not_collide_with_script_outputs(self):
        table = section(self.text, "| Dispatch | Results file | Shape |", "\n\n")
        names = re.findall(r"^\|[^|]*\| `([^`]+)` \|", table, re.M)
        self.assertEqual(len(names), 8, names)
        # PR #218 review I4: the Step 2.6 re-check judge has its own name per round.
        self.assertIn("r2-claude-verdicts-recheck-<K>.json", names)
        script_outputs = re.compile(
            r"^(r1-(codex|gemini|claude-only|claude|empty)\.json|r2-(codex|gemini|claude-only|empty)"
            r"(-verdicts)?\.json|r3-codex-counters\.json|report\.(md|json)|round-.*\.json|"
            r"fix-range-.*\.diff|cites-.*\.diff|recheck-.*\.json|r2-gemini-prompt\.txt)$")
        for name in names:
            self.assertNotRegex(name, script_outputs)
        # r2-claude-verdicts.json is the one name a Claude agent and synthesize.py share on purpose.
        self.assertIn("r2-claude-verdicts.json", names)

    def test_the_skills_name_the_contract_file(self):
        self.assertIn("references/dispatch-contract.md", (DEEP / "SKILL.md").read_text(encoding="utf-8"))
        adv = norm(SKILL.read_text(encoding="utf-8"))
        self.assertIn("`../deep/references/dispatch-contract.md`", adv)
        self.assertTrue((SKILL.parent / "../deep/references/dispatch-contract.md").is_file())

    def test_adversarial_dispatches_name_their_results_files(self):
        adv = SKILL.read_text(encoding="utf-8")
        step2 = section(adv, "### Step 2 — R1", "### Step 3 — R2")
        self.assertIn("<RUN_DIR>/r1-bug-hunter.json", step2)
        self.assertIn("<RUN_DIR>/r1-convention.json", step2)
        self.assertIn("Read both files from disk", step2)
        step3 = section(adv, "### Step 3 — R2", "### Step 4 — Converge")
        self.assertIn("same delivery contract", step3)
        self.assertIn("r2-claude-verdicts.prev.json", step3)

    def test_every_agent_writes_its_results_file_first(self):
        for name in ("bug-hunter.md", "convention-reviewer.md", "cross-examiner.md"):
            rules = (PLUGIN / "agents" / name).read_text(encoding="utf-8").split("## Rules", 1)[1]
            self.assertIn("**Write your results file before you reply.**", rules, name)
            self.assertIn("`NO REPORT`", rules, name)


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

    def run_synth(self, verdicts_text, expect_exit=0):
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
        self.assertEqual(res.returncode, expect_exit, res.stderr)
        if expect_exit:
            self.assertFalse(out.exists())
            return res.stderr
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
        # a bare `verdict` key; since #189 it stops with exit 5 and names both keys.
        err = self.run_synth(json.dumps({"verdicts": [{"id": "C-001", "verdict": "confirm", "reason": "x"}]}),
                             expect_exit=5)
        self.assertIn("expected key 'adversary_verdict'", err)
        self.assertIn("found key 'verdict' on C-001", err)
        self.assertNotIn("verdict:confirm|refute", self.step22)
        self.assertIn("adversary_verdict", self.documented_json())

    def test_empty_verdicts_cover_gemini_as_well_as_codex(self):
        missing = section(self.step22, "**Missing verdicts", "Emit an R2 digest")
        self.assertIn('{"verdicts":[]}', missing)
        self.assertIn("Gemini", missing)
        self.assertIn("Codex", missing)
        got = self.run_synth('{"verdicts":[]}')
        self.assertTrue(all(f["status"] == "unconfirmed" for f in got.values()))


class ClaudeVerdictShapeTests(unittest.TestCase):
    """#189: deep Step 2.2 and adversarial Step 3 name the exact shape the
    cross-examiner writes to r2-claude-verdicts.json, and synthesize.py reads it."""

    SHAPE = re.compile(r'```json\n\s*(\{"verdicts":\[\{"id":"X-001","claude_verdict".*?)```', re.S)

    def documented(self, text):
        match = self.SHAPE.search(text)
        self.assertIsNotNone(match, "no claude_verdict json block")
        return match.group(1)

    def synth(self, verdicts_text):
        tmp = Path(tempfile.mkdtemp(prefix="claude-shape-"))
        self.addCleanup(__import__("shutil").rmtree, str(tmp), True)
        finding = lambda fid: {"id": fid, "path": "a.py", "line": 1, "severity": "minor",
                               "category": "bug", "title": fid, "rationale": "r", "origin": "codex"}
        (tmp / "c.json").write_text('{"findings":[]}')
        (tmp / "x.json").write_text(json.dumps({"findings": [finding("X-001"), finding("X-002")]}))
        (tmp / "xv.json").write_text('{"verdicts":[]}')
        (tmp / "cv.json").write_text(verdicts_text)
        res = subprocess.run(
            [sys.executable, str(HERE / "synthesize.py"), "--adversary", "codex",
             "--claude-findings", str(tmp / "c.json"), "--adversary-findings", str(tmp / "x.json"),
             "--adversary-verdicts", str(tmp / "xv.json"), "--claude-verdicts", str(tmp / "cv.json"),
             "--json", str(tmp / "r.json")],
            capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(res.returncode, 0, res.stderr)
        return {f["id"]: f["status"] for f in json.loads((tmp / "r.json").read_text())["findings"]}

    def check(self, step):
        self.assertIn("r2-claude-verdicts.json", step)
        self.assertIn("`claude_verdict` (not `verdict`)", norm(step))
        self.assertRegex(step, r"exits? 5")
        got = self.synth(self.documented(step))
        self.assertEqual(got, {"X-001": "survivor", "X-002": "rejected"})

    def test_deep_step_2_2_names_the_shape(self):
        text = (DEEP / "SKILL.md").read_text(encoding="utf-8")
        self.check(section(text, "### Step 2.2", "### Step 2.3"))

    def test_adversarial_step_3_names_the_shape(self):
        self.check(section(SKILL.read_text(encoding="utf-8"), "### Step 3 — R2", "### Step 4 — Converge"))

    def test_cross_examiner_agent_uses_the_same_key(self):
        agent = (PLUGIN / "agents" / "cross-examiner.md").read_text(encoding="utf-8")
        self.assertIn('"claude_verdict": "confirm"', agent)
        self.assertIn('"claude_verdict": "refute"', agent)
        self.assertNotRegex(agent, r'"verdict"\s*:')


if __name__ == "__main__":
    unittest.main()
