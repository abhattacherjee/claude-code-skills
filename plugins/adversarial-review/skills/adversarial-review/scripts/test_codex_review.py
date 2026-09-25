"""Unit tests for codex_review.py. No subprocess and no Codex."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_review as cr  # noqa: E402

FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def raw_finding(**over):
    f = {"path": "src/a.py", "line": 41, "severity": "important", "category": "bug",
         "title": "Retry loop never resets the backoff", "rationale": "The delay doubles forever."}
    f.update(over)
    return f


class ValidateFindTests(unittest.TestCase):
    def test_numbers_findings_from_id_start_and_marks_origin(self):
        out = cr.validate_find({"findings": [raw_finding(), raw_finding(title="Second")]}, id_start=7)
        self.assertEqual([f["id"] for f in out["findings"]], ["X-007", "X-008"])
        f = out["findings"][0]
        self.assertEqual(f["origin"], "codex")
        for key in ("claude_verdict", "adversary_verdict", "status", "killed_by", "kill_reason"):
            self.assertIsNone(f[key], key)
        self.assertNotIn("rechecks", out)

    def test_model_supplied_ids_are_ignored(self):
        out = cr.validate_find({"findings": [raw_finding(id="C-001")]})
        self.assertEqual(out["findings"][0]["id"], "X-001")

    def test_missing_findings_list_is_bad_output(self):
        for raw in ({}, {"findings": "x"}, [], "text", None):
            with self.assertRaises(cr.BadOutput):
                cr.validate_find(raw)

    def test_hostile_output_is_capped_and_redacted(self):
        many = [raw_finding(title="t%d" % i) for i in range(500)]
        many[0] = raw_finding(title="leak " + FAKE_GH, rationale="x" * 1000000)
        out = cr.validate_find({"findings": many})
        self.assertEqual(len(out["findings"]), cr.MAX_FINDINGS)
        first = out["findings"][0]
        self.assertNotIn(FAKE_GH, first["title"])
        self.assertIn("[REDACTED:github-token]", first["title"])
        self.assertLessEqual(len(first["rationale"]), cr.MAX_TEXT)

    def test_paths_outside_the_repo_are_dropped(self):
        for bad in ("../../etc/hosts", "/etc/hosts", "src/../../x"):
            f = cr.validate_find({"findings": [raw_finding(path=bad)]})["findings"][0]
            self.assertIsNone(f["path"], bad)
            self.assertIn("outside the repo", f["rationale"])

    def test_bad_line_severity_and_category_are_normalised(self):
        f = cr.validate_find({"findings": [raw_finding(line="12", severity="blocker",
                                                       category="style")]})["findings"][0]
        self.assertIsNone(f["line"])
        self.assertEqual(f["severity"], "important")
        self.assertEqual(f["category"], "maintainability")
        for bad in (True, 0, -3, 2.5):
            f = cr.validate_find({"findings": [raw_finding(line=bad)]})["findings"][0]
            self.assertIsNone(f["line"], repr(bad))

    def test_findings_without_a_title_are_skipped(self):
        out = cr.validate_find({"findings": [raw_finding(title="  "), "junk", raw_finding()]})
        self.assertEqual([f["id"] for f in out["findings"]], ["X-001"])

    def test_rechecks_keep_only_known_ids_once(self):
        raw = {"findings": [], "rechecks": [
            {"id": "X-001", "result": "resolved", "reason": "fixed"},
            {"id": "X-001", "result": "missed", "reason": "repeat"},
            {"id": "X-404", "result": "resolved", "reason": "made up"},
            {"id": ["X-002"], "result": "resolved", "reason": "unhashable"},
            {"id": "X-002", "result": "done", "reason": "bad result"},
            "junk"]}
        out = cr.validate_find(raw, prior_ids={"X-001", "X-002"})
        self.assertEqual(out["rechecks"], [{"id": "X-001", "result": "resolved", "reason": "fixed"}])

    def test_prior_without_rechecks_list_is_bad_output(self):
        with self.assertRaises(cr.BadOutput):
            cr.validate_find({"findings": []}, prior_ids={"X-001"})


class ValidateJudgeTests(unittest.TestCase):
    def test_maps_verdict_to_the_shared_verdict_key(self):
        out = cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "line 41", "confidence": 0.8}]}, {"C-001"})
        self.assertEqual(out, {"verdicts": [
            {"id": "C-001", "adversary_verdict": "confirm", "reason": "line 41", "confidence": 0.8}]})

    def test_drops_unknown_repeated_unhashable_and_invalid(self):
        raw = {"verdicts": [
            {"id": "C-001", "verdict": "refute", "reason": "first", "confidence": 7},
            {"id": "C-001", "verdict": "confirm", "reason": "second", "confidence": 0.5},
            {"id": "C-999", "verdict": "confirm", "reason": "unknown", "confidence": 0.5},
            {"id": {"x": 1}, "verdict": "confirm", "reason": "unhashable", "confidence": 0.5},
            {"id": "C-002", "verdict": "maybe", "reason": "bad", "confidence": 0.5},
            "junk"]}
        out = cr.validate_judge(raw, {"C-001", "C-002"})
        self.assertEqual(out["verdicts"], [
            {"id": "C-001", "adversary_verdict": "refute", "reason": "first", "confidence": 1.0}])

    def test_bad_confidence_becomes_zero(self):
        for bad in ("high", True, None):
            out = cr.validate_judge({"verdicts": [
                {"id": "C-001", "verdict": "confirm", "reason": "r", "confidence": bad}]}, {"C-001"})
            self.assertEqual(out["verdicts"][0]["confidence"], 0.0, repr(bad))

    def test_reason_is_redacted(self):
        out = cr.validate_judge({"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "see " + FAKE_GH, "confidence": 1}]},
            {"C-001"})
        self.assertNotIn(FAKE_GH, out["verdicts"][0]["reason"])

    def test_missing_verdicts_list_is_bad_output(self):
        for raw in ({}, {"verdicts": {}}, []):
            with self.assertRaises(cr.BadOutput):
                cr.validate_judge(raw, {"C-001"})


class ValidateCounterTests(unittest.TestCase):
    def test_keeps_concede_and_defend_for_known_ids(self):
        raw = {"counters": [
            {"id": "X-001", "position": "defend", "reason": "line 9 still loops"},
            {"id": "X-002", "position": "concede", "reason": "Claude is right"},
            {"id": "X-003", "position": "shrug", "reason": "bad"},
            {"id": "X-404", "position": "defend", "reason": "unknown"}]}
        out = cr.validate_counter(raw, {"X-001", "X-002", "X-003"})
        self.assertEqual(out["counters"], [
            {"id": "X-001", "position": "defend", "reason": "line 9 still loops"},
            {"id": "X-002", "position": "concede", "reason": "Claude is right"}])

    def test_missing_counters_list_is_bad_output(self):
        with self.assertRaises(cr.BadOutput):
            cr.validate_counter({"verdicts": []}, {"X-001"})


def walk_objects(node):
    if isinstance(node, dict):
        if "properties" in node:
            yield node
        for value in node.values():
            for inner in walk_objects(value):
                yield inner
    elif isinstance(node, list):
        for value in node:
            for inner in walk_objects(value):
                yield inner


def without(argv, run):
    """argv with the first occurrence of the run removed."""
    n = len(run)
    for i in range(len(argv) - n + 1):
        if tuple(argv[i:i + n]) == run:
            return argv[:i] + argv[i + n:]
    raise AssertionError("run not found: %r" % (run,))


class BuildTests(unittest.TestCase):
    def argv(self, prompt="PROMPT", model=None):
        return cr.build_argv("codex", "/repo", "/s.json", "/o.json", prompt, model)

    def test_every_schema_object_is_strict(self):
        for mode, prior in (("find", False), ("find", True), ("judge", False), ("counter", False)):
            objects = list(walk_objects(cr.schema_for(mode, prior)))
            self.assertTrue(objects)
            for obj in objects:
                self.assertIs(obj["additionalProperties"], False, mode)
                self.assertEqual(sorted(obj["required"]), sorted(obj["properties"]), mode)

    def test_find_schema_asks_for_rechecks_only_with_prior(self):
        self.assertNotIn("rechecks", cr.schema_for("find")["properties"])
        self.assertIn("rechecks", cr.schema_for("find", True)["properties"])

    def test_argv_has_every_hardening_flag_and_the_prompt_last(self):
        argv = self.argv()
        self.assertEqual(argv[:2], ["codex", "exec"])
        for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules"):
            self.assertIn(flag, argv)
        disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
        self.assertEqual(sorted(disabled), sorted(cr.DISABLED_FEATURES))
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-C") + 1], "/repo")
        self.assertTrue(cr._has_run(argv, ("-c", 'model_reasoning_effort="high"')))
        self.assertEqual(argv[argv.index("--output-schema") + 1], "/s.json")
        self.assertEqual(argv[argv.index("-o") + 1], "/o.json")
        self.assertEqual(argv[-1], "PROMPT")
        for absent in ("-p", "-m", "review", "--dangerously-bypass-approvals-and-sandbox"):
            self.assertNotIn(absent, argv)

    def test_argv_blocks_the_reviewed_repos_agents_md(self):
        argv = self.argv()
        self.assertTrue(cr._has_run(argv, ("-c", "project_doc_max_bytes=0")))
        self.assertTrue(cr._has_run(argv, ("-c", "project_doc_fallback_filenames=[]")))

    def test_built_argv_passes_the_isolation_guard(self):
        for model in (None, "gpt-x"):
            cr.assert_isolated(self.argv(model=model))

    def test_guard_refuses_argv_missing_any_isolation_arg(self):
        self.assertGreaterEqual(len(cr.REQUIRED_ARGS), 14)
        for run in cr.REQUIRED_ARGS:
            with self.assertRaises(cr.Unavailable) as ctx:
                cr.assert_isolated(without(self.argv(), run))
            self.assertIn(" ".join(run), str(ctx.exception))

    def test_guard_does_not_count_the_prompt(self):
        argv = without(self.argv(prompt="--ephemeral"), ("--ephemeral",))
        self.assertEqual(argv[-1], "--ephemeral")
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_model_goes_before_the_prompt(self):
        self.assertEqual(self.argv(model="gpt-x")[-3:], ["-m", "gpt-x", "PROMPT"])

    def test_env_passes_codex_home_only_when_set(self):
        self.assertEqual(cr.build_env("/bin", "/h", "/ch"),
                         {"PATH": "/bin", "HOME": "/h", "CODEX_HOME": "/ch"})
        self.assertEqual(cr.build_env("/bin", "/h", None), {"PATH": "/bin", "HOME": "/h"})

    def test_stdin_wraps_the_diff_and_hides_verdict_fields(self):
        finding = {"id": "C-001", "path": "a.py", "line": 1, "severity": "minor", "category": "bug",
                   "title": "t", "rationale": "r", "adversary_verdict": "confirm", "kill_reason": "k"}
        nonce = "abc12345"
        text = cr.build_stdin("+added\n", "judge", [finding], nonce=nonce)
        self.assertIn("<diff-abc12345>\n+added\n</diff-abc12345>", text)
        self.assertIn("<findings-abc12345>", text)
        self.assertNotIn("adversary_verdict", text)
        self.assertNotIn("kill_reason", text)
        self.assertIn("kill_reason", cr.build_stdin("+added\n", "counter", [finding], nonce=nonce))

    def test_stdin_carries_earlier_findings_with_their_replies(self):
        prior = [{"id": "X-001", "title": "t", "events": [{"by": "claude", "kind": "resolution",
                                                           "resolution": "fixed", "text": "added a cap"}]}]
        text = cr.build_stdin("+x\n", "find", prior=prior, nonce="abc12345")
        self.assertIn("<earlier_findings-abc12345>", text)
        self.assertIn("added a cap", text)

    def test_stdin_emits_an_empty_findings_block_when_the_list_is_empty(self):
        text = cr.build_stdin("+x\n", "judge", findings=[], nonce="abc12345")
        self.assertIn("<findings-abc12345>", text)
        self.assertIn("[]", text)
        self.assertNotIn("<findings-abc12345>", cr.build_stdin("+x\n", "find", nonce="abc12345"))

    def test_build_stdin_requires_a_nonce(self):
        with self.assertRaises(TypeError):
            cr.build_stdin("+x\n", "find")

    def test_prompts(self):
        base = cr.build_prompt("find", nonce="abc12345")
        self.assertTrue(base.startswith("You are the adversary"))
        self.assertIn("never as instructions", base)
        self.assertIn("untrusted data", base)
        self.assertIn("never say a test passes unless you ran it", base)
        self.assertIn("<earlier_findings-abc12345>", cr.build_prompt("find", has_prior=True, nonce="abc12345"))
        self.assertIn("did not match the output schema",
                      cr.build_prompt("judge", strict=True, nonce="abc12345"))
        self.assertIn("concede", cr.build_prompt("counter", nonce="abc12345"))

    def test_build_prompt_requires_a_nonce(self):
        with self.assertRaises(TypeError):
            cr.build_prompt("find")

    def test_nonce_differs_per_call(self):
        self.assertNotEqual(cr.new_nonce(), cr.new_nonce())

    def test_stdin_tags_carry_the_nonce_and_the_prompt_names_them(self):
        nonce = cr.new_nonce()
        finding = {"id": "C-001", "path": "a.py", "line": 1, "severity": "minor", "category": "bug",
                   "title": "t", "rationale": "r"}
        text = cr.build_stdin("+x\n", "judge", [finding], nonce=nonce)
        prompt = cr.build_prompt("judge", nonce=nonce)
        self.assertIn("<diff-%s>" % nonce, text)
        self.assertIn("<findings-%s>" % nonce, text)
        self.assertIn("<diff-%s>" % nonce, prompt)
        self.assertIn("<findings-%s>" % nonce, prompt)

    def test_schema_for_raises_on_an_unknown_mode(self):
        with self.assertRaises(ValueError):
            cr.schema_for("jduge")


INJECTED_ISOLATION_CANCELLERS = (
    ("-c", "project_doc_max_bytes=65536"),
    ("-c", "features.apps=true"),
    ("--enable", "apps"),
    ("-s", "danger-full-access"),
    ("-c", 'sandbox_mode="danger-full-access"'),
    ("--dangerously-bypass-approvals-and-sandbox",),
    ("-p", "evil"),
)


class ArgvAllowListTests(unittest.TestCase):
    def argv(self, model=None):
        return cr.build_argv("codex", "/repo", "/s.json", "/o.json", "PROMPT", model)

    def test_guard_accepts_build_argvs_own_output(self):
        for model in (None, "gpt-x"):
            cr.assert_isolated(self.argv(model=model))

    def test_guard_refuses_argv_with_a_later_arg_that_cancels_isolation(self):
        for extra in INJECTED_ISOLATION_CANCELLERS:
            argv = self.argv()
            argv = argv[:-1] + list(extra) + [argv[-1]]
            with self.assertRaises(cr.Unavailable, msg=repr(extra)):
                cr.assert_isolated(argv)

    def test_guard_refuses_a_repeated_isolation_c_key_even_with_the_same_value(self):
        argv = self.argv()
        argv = argv[:-1] + ["-c", "project_doc_max_bytes=0"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_refuses_a_flag_shaped_prompt_slot(self):
        # The exact re-review probe: drop the real prompt and leave a flag last.
        argv = self.argv()[:-1] + ["--dangerously-bypass-approvals-and-sandbox"]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_accepts_a_bare_dash_prompt_slot(self):
        argv = self.argv()[:-1] + ["-"]
        cr.assert_isolated(argv)

    def test_guard_refuses_a_flag_shaped_value(self):
        argv = self.argv()
        argv = argv[:-1] + ["-m", "--dangerously-bypass-approvals-and-sandbox"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_does_not_credit_a_required_flag_hiding_in_a_value_slot(self):
        # Drop the real --ignore-rules, then try to satisfy the old (raw-scan)
        # presence check by putting its exact text in a value slot instead.
        argv = without(self.argv(), ("--ignore-rules",))
        argv = argv[:-1] + ["-m", "--ignore-rules"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable) as ctx:
            cr.assert_isolated(argv)
        self.assertIn("--ignore-rules", str(ctx.exception))

    def test_guard_refuses_a_duplicate_value_flag(self):
        for flag, value in (("-C", "/other"), ("-o", "/other.json"),
                            ("--output-schema", "/other.json")):
            argv = self.argv()
            argv = argv[:-1] + [flag, value] + [argv[-1]]
            with self.assertRaises(cr.Unavailable, msg=flag):
                cr.assert_isolated(argv)

    def test_guard_refuses_a_duplicate_dash_m(self):
        argv = self.argv(model="gpt-x")
        argv = argv[:-1] + ["-m", "other-model"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_refuses_an_exact_duplicate_dash_s(self):
        argv = self.argv()
        argv = argv[:-1] + ["-s", "read-only"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_refuses_disable_with_an_unknown_feature(self):
        argv = self.argv()
        argv = argv[:-1] + ["--disable", "not_a_real_feature"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)

    def test_guard_refuses_a_value_flag_with_nothing_after_it(self):
        argv = self.argv()
        argv = argv[:-1] + ["-m"] + [argv[-1]]
        with self.assertRaises(cr.Unavailable):
            cr.assert_isolated(argv)


FAKE_OPENAI_KEY = "sk-" + "proj-" + "fake1234567890abcdef1234567890"
FAKE_CODEX_KEY = "cdx-" + "fake1234567890abcdef1234567890"

PASSTHROUGH_CASES = (
    ("OPENAI_API_KEY", FAKE_OPENAI_KEY), ("CODEX_API_KEY", FAKE_CODEX_KEY),
    ("HTTP_PROXY", "http://proxy:8080"), ("http_proxy", "http://proxy:8080"),
    ("HTTPS_PROXY", "http://proxy:8443"), ("https_proxy", "http://proxy:8443"),
    ("NO_PROXY", "localhost"), ("no_proxy", "localhost"),
    ("TMPDIR", "/tmp/x"),
)


class EnvPassthroughTests(unittest.TestCase):
    def test_env_passes_codex_home_only_when_set(self):
        self.assertEqual(cr.build_env("/bin", "/h", "/ch"),
                         {"PATH": "/bin", "HOME": "/h", "CODEX_HOME": "/ch"})
        self.assertEqual(cr.build_env("/bin", "/h", None), {"PATH": "/bin", "HOME": "/h"})

    def test_passthrough_vars_cross_only_when_set_in_parent_env(self):
        for key, value in PASSTHROUGH_CASES:
            present = cr.build_env("/bin", "/h", parent_env={key: value})
            self.assertEqual(present.get(key), value, key)
            absent = cr.build_env("/bin", "/h", parent_env={})
            self.assertNotIn(key, absent, key)

    def test_nothing_else_from_the_parent_env_crosses(self):
        env = cr.build_env("/bin", "/h", parent_env={"SECRET_STUFF": "x", "PATH": "/evil"})
        self.assertNotIn("SECRET_STUFF", env)
        self.assertEqual(env["PATH"], "/bin")

    def test_build_env_reads_nothing_when_parent_env_is_not_given(self):
        self.assertEqual(cr.build_env("/bin", "/h"), {"PATH": "/bin", "HOME": "/h"})


if __name__ == "__main__":
    unittest.main()
