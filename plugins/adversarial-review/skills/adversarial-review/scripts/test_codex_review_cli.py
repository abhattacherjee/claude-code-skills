"""CLI tests for codex-review.sh against the stub codex. No real Codex call is
made, and no test reads or writes a real ~/.codex or ~/.cache: HOME, CODEX_HOME
and XDG_CACHE_HOME are temp dirs. The Harness puts a `python3` symlink to the
interpreter running these tests first on PATH, so the wrapper runs
codex_review.py under that same interpreter (3.9 when run by /usr/bin/python3)."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_review as cr  # noqa: E402
from test_ensure_codex import install_stub  # noqa: E402

WRAPPER = HERE / "codex-review.sh"
MODULE = HERE / "codex_review.py"
FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
DIFF = "diff --git a/src/a.py b/src/a.py\n+retry()\n"
ONE_FINDING = {"findings": [{"path": "src/a.py", "line": 2, "severity": "important",
                             "category": "bug", "title": "Retry never stops", "rationale": "No cap."}]}
NONCED_DIFF_TAG = re.compile(r"<diff-([0-9a-f]{8})>")
# Keys the stub's own launch adds (bash's exec wrapper, macOS, Python's locale
# coercion); they were not in the env codex-review passed.
LAUNCH_NOISE = {"PWD", "OLDPWD", "SHLVL", "_", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}


def wait_dead(pid, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def kill_quietly(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class Harness:
    def __init__(self, test, exec_actions=None, login=0, stamp=True, **state):
        self.dir = Path(tempfile.mkdtemp(prefix="codex-cli-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        install_stub(self.bin)
        # The wrapper runs `python3` from PATH: make that the interpreter under test.
        os.symlink(sys.executable, str(self.bin / "python3"))
        self.codex_home = self.dir / "codex-home"   # no credentials; the stub needs none
        self.codex_home.mkdir()
        self.cache = self.dir / "cache"
        fields = cr.stamp_fields(str(self.bin / "codex"), "0.155.1", str(self.codex_home))
        self.stamp = Path(cr.stamp_path(fields, str(self.cache)))
        if stamp:
            cr.write_stamp(str(self.stamp), fields)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self.diff = self.dir / "change.diff"
        self.diff.write_text(DIFF)
        self.out = self.dir / "out.json"
        state.update({"login": login, "exec": exec_actions or [{"out": ONE_FINDING}]})
        (self.home / "codex-stub.json").write_text(json.dumps(state))
        self.env = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "HOME": str(self.home),
                    "CODEX_HOME": str(self.codex_home), "XDG_CACHE_HOME": str(self.cache),
                    "TMPDIR": str(self.dir), "PYTHONDONTWRITEBYTECODE": "1",
                    "LEAK_CANARY": "leak", "GH_TOKEN": FAKE_GH}

    def argv(self, *args):
        return ["bash", str(WRAPPER), "--diff", str(self.diff), "--repo", str(self.repo),
                "--out", str(self.out)] + [str(a) for a in args]

    def run(self, *args):
        return subprocess.run(self.argv(*args), capture_output=True, text=True, env=self.env,
                              timeout=90, stdin=subprocess.DEVNULL)

    def self_test(self):
        return subprocess.run(["bash", str(WRAPPER), "--self-test"], capture_output=True, text=True,
                              env=self.env, timeout=90, stdin=subprocess.DEVNULL)

    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data))
        return path

    def calls(self):
        log = self.home / "codex-stub.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def exec_calls(self):
        return [c for c in self.calls() if c["argv"][:1] == ["exec"] and not c["canary"]]

    def canary_calls(self):
        return [c for c in self.calls() if c["argv"][:1] == ["exec"] and c["canary"]]

    def gate(self, codex=None, codex_home="default", force=False):
        """Run ensure_isolation in-process against the stub; return how many canary
        runs it made."""
        codex = str(codex or self.bin / "codex")
        home = str(self.codex_home) if codex_home == "default" else codex_home
        env = cr.build_env(self.env["PATH"], str(self.home), home)
        before = len(self.canary_calls())
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.cache)}):
            cr.ensure_isolation(codex, env, 30, force=force)
        return len(self.canary_calls()) - before

    def set_state(self, **changes):
        path = self.home / "codex-stub.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def result(self):
        return json.loads(self.out.read_text())

    def leftovers(self):
        return [p.name for p in self.dir.iterdir() if p.name.startswith("codex-adv-")]


def env_keys(call):
    """The env keys codex-review passed to the stub, sorted."""
    return sorted(set(call["env"]) - LAUNCH_NOISE)


def shared_nonce(call):
    """The nonce on the call's stdin tags, if the prompt names the same tag."""
    match = NONCED_DIFF_TAG.search(call["stdin"])
    if not match:
        return None
    return match.group(1) if ("<diff-%s>" % match.group(1)) in call["argv"][-1] else None


class AvailabilityTests(unittest.TestCase):
    def test_logged_out_exits_3_without_running_exec(self):
        h = Harness(self, login=1)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("ADVERSARY_UNAVAILABLE", res.stderr)
        self.assertIn("not logged in", res.stderr)
        self.assertEqual(h.exec_calls() + h.canary_calls(), [])

    def test_login_check_runs_with_the_same_scrubbed_env_as_the_review(self):
        h = Harness(self)
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        [login] = [c for c in h.calls() if c["argv"][:2] == ["login", "status"]]
        [review] = h.exec_calls()
        self.assertNotIn("LEAK_CANARY", login["env"])
        self.assertEqual(login["env"], review["env"])

    def test_missing_codex_exits_3(self):
        h = Harness(self)
        (h.bin / "codex").unlink()
        dirs = [d for d in os.environ["PATH"].split(os.pathsep)
                if d and not os.path.exists(os.path.join(d, "codex"))]
        h.env["PATH"] = os.pathsep.join([str(h.bin)] + dirs)
        res = subprocess.run([sys.executable, str(MODULE), "--diff", str(h.diff), "--mode", "find"],
                             capture_output=True, text=True, env=h.env, timeout=60)
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("not found", res.stderr)

    def test_nonzero_exit_is_unavailable_without_retry(self):
        h = Harness(self, exec_actions=[{"exit": 1, "stderr": "stream error: 503"}])
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3)
        self.assertIn("stream error: 503", res.stderr)
        self.assertEqual(len(h.exec_calls()), 1)

    def test_timeout_exits_3_and_kills_the_process_group(self):
        h = Harness(self, exec_actions=[{"sleep": 30, "spawn_child": True, "out": ONE_FINDING}])
        start = time.time()
        res = h.run("--mode", "find", "--timeout", "2")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("timed out", res.stderr)
        self.assertLess(time.time() - start, 20)
        pid = int((h.home / "child.pid").read_text())
        self.assertTrue(wait_dead(pid), "the stub's child process survived the timeout")
        self.assertEqual(h.leftovers(), [])


class OutputTests(unittest.TestCase):
    def test_schema_valid_output_is_written_with_codex_ids(self):
        h = Harness(self)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(h.result()["adversary"], "codex")
        [f] = h.result()["findings"]
        self.assertEqual((f["id"], f["origin"], f["path"], f["line"]), ("X-001", "codex", "src/a.py", 2))
        self.assertIsNone(f["adversary_verdict"])
        self.assertEqual(len(h.exec_calls()), 1)
        self.assertEqual(h.exec_calls()[0]["schema"], cr.schema_for("find"))

    def test_invalid_json_retries_once_with_the_strict_prompt_then_exits_3(self):
        h = Harness(self, exec_actions=[{"out": "not json"}])
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3)
        self.assertIn("after one retry", res.stderr)
        calls = h.exec_calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("did not match the output schema", calls[0]["argv"][-1])
        self.assertIn("did not match the output schema", calls[1]["argv"][-1])

    def test_invalid_then_valid_succeeds(self):
        h = Harness(self, exec_actions=[{"out": {"wrong": []}}, {"out": ONE_FINDING}])
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.exec_calls()), 2)

    def test_judge_maps_verdicts_and_drops_unknown_ids(self):
        h = Harness(self, exec_actions=[{"out": {"verdicts": [
            {"id": "C-001", "verdict": "confirm", "reason": "line 2", "confidence": 0.9},
            {"id": "C-999", "verdict": "refute", "reason": "made up", "confidence": 0.9}]}}])
        findings = h.write("claude.json", {"findings": [{"id": "C-001", "title": "t", "rationale": "r"}]})
        res = h.run("--mode", "judge", "--findings", findings)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(h.result(), {"adversary": "codex", "verdicts": [
            {"id": "C-001", "adversary_verdict": "confirm", "reason": "line 2", "confidence": 0.9}]})
        self.assertIn("<findings-", h.exec_calls()[0]["stdin"])

    def test_counter_mode(self):
        h = Harness(self, exec_actions=[{"out": {"counters": [
            {"id": "X-001", "position": "defend", "reason": "line 2 still loops"}]}}])
        findings = h.write("refuted.json", {"findings": [
            {"id": "X-001", "title": "t", "rationale": "r", "kill_reason": "handled"}]})
        res = h.run("--mode", "counter", "--findings", findings)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(h.result()["adversary"], "codex")
        self.assertEqual(h.result()["counters"][0]["position"], "defend")
        self.assertIn("handled", h.exec_calls()[0]["stdin"])

    def test_find_with_prior_rechecks_earlier_findings(self):
        h = Harness(self, exec_actions=[{"out": {
            "findings": ONE_FINDING["findings"],
            "rechecks": [{"id": "X-001", "result": "resolved", "reason": "cap is there"}]}}])
        prior = h.write("round-3.json", {"findings": [{
            "id": "X-001", "title": "Retry never stops", "rationale": "No cap.",
            "events": [{"by": "claude", "kind": "resolution", "resolution": "fixed",
                        "text": "added a cap"}]}]})
        res = h.run("--mode", "find", "--prior", prior, "--id-start", "2")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = h.result()
        self.assertEqual(out["adversary"], "codex")
        self.assertEqual(out["findings"][0]["id"], "X-002")
        self.assertEqual(out["rechecks"], [{"id": "X-001", "result": "resolved", "reason": "cap is there"}])
        call = h.exec_calls()[0]
        self.assertIn("rechecks", call["schema"]["properties"])
        self.assertIn("<earlier_findings-", call["stdin"])
        self.assertIn("added a cap", call["stdin"])

    def test_prompt_and_stdin_share_one_fresh_nonce_per_call(self):
        h = Harness(self, exec_actions=[{"out": "not json"}, {"out": ONE_FINDING}])
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        nonces = [shared_nonce(c) for c in h.exec_calls()]
        self.assertEqual(len(nonces), 2)
        self.assertNotIn(None, nonces)
        self.assertNotEqual(nonces[0], nonces[1])

    def test_usage_errors_exit_2(self):
        h = Harness(self)
        self.assertEqual(h.run("--mode", "judge").returncode, 2)
        self.assertEqual(h.run("--mode", "judge", "--findings", h.diff, "--prior", h.diff).returncode, 2)
        self.assertEqual(h.run("--mode", "find", "--id-start", "0").returncode, 2)
        self.assertEqual(h.run("--mode", "find", "--timeout", "0").returncode, 2)
        self.assertEqual(h.run("--mode", "nope").returncode, 2)
        self.assertEqual(h.run().returncode, 2)

    def test_help_exits_0(self):
        h = Harness(self)
        res = subprocess.run(["bash", str(WRAPPER), "--help"], capture_output=True, text=True,
                             env=h.env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("--self-test", res.stdout)

    def test_missing_diff_exits_1(self):
        h = Harness(self)
        h.diff.unlink()
        self.assertEqual(h.run("--mode", "find").returncode, 1)


class FixRoundOneTests(unittest.TestCase):
    def test_grandchildren_are_killed_after_a_normal_exit(self):
        h = Harness(self, exec_actions=[{"spawn_child": True, "out": ONE_FINDING}])
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 0, res.stderr)
        pid = int((h.home / "child.pid").read_text())
        self.assertTrue(wait_dead(pid), "the stub's child outlived a normal exit")

    def test_a_timed_out_run_is_reaped_even_when_an_escaped_child_holds_stderr(self):
        d = Path(tempfile.mkdtemp(prefix="codex-cli-test-"))
        self.addCleanup(shutil.rmtree, d, True)
        script, pidfile = d / "escape.py", d / "escaped.pid"
        script.write_text(
            "import subprocess, sys, time\n"
            "p = subprocess.Popen(['sleep', '30'], start_new_session=True)\n"
            "open(sys.argv[1], 'w').write(str(p.pid))\n"
            "time.sleep(30)\n")

        def kill_escaped():
            try:
                os.kill(int(pidfile.read_text()), 9)
            except (OSError, ValueError):
                pass
        self.addCleanup(kill_escaped)
        made = []
        real = subprocess.Popen

        class Recording(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                made.append(self)

        with mock.patch.object(cr.subprocess, "Popen", Recording), \
                mock.patch.object(cr, "POST_KILL_WAIT", 1):
            with self.assertRaises(cr.Unavailable):
                cr.run_codex([sys.executable, str(script), str(pidfile)], None, b"", 2)
        [proc] = made
        self.assertIsNotNone(proc.returncode, "the killed codex process was never reaped")
        self.assertTrue(proc.stderr.closed)

    def test_a_stamp_removed_during_the_review_discards_the_result(self):
        h = Harness(self)
        h.set_state(exec=[{"delete": str(h.stamp), "out": ONE_FINDING}])
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("stamp", res.stderr)
        self.assertFalse(h.out.exists())

    def test_an_unwritable_out_file_exits_1_with_the_result_on_stdout(self):
        h = Harness(self)
        bad = h.dir / "missing-dir" / "out.json"
        res = subprocess.run(["bash", str(WRAPPER), "--diff", str(h.diff), "--repo", str(h.repo),
                              "--out", str(bad), "--mode", "find"], capture_output=True, text=True,
                             env=h.env, timeout=90, stdin=subprocess.DEVNULL)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("cannot write --out", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(json.loads(res.stdout)["findings"][0]["id"], "X-001")

    def test_judge_and_counter_with_no_usable_findings_skip_codex(self):
        h = Harness(self)
        empty = h.write("empty.json", {"findings": [{"id": 7}, {"title": "no id"}]})
        for mode, key in (("judge", "verdicts"), ("counter", "counters")):
            res = h.run("--mode", mode, "--findings", empty)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(h.result(), {"adversary": "codex", key: []})
        self.assertEqual([c for c in h.calls() if c["argv"][:1] == ["exec"]], [])

    def test_the_canary_git_repo_ignores_the_users_git_config_and_templates(self):
        h = Harness(self, stamp=False)
        template = h.dir / "git-template"
        (template / "hooks").mkdir(parents=True)
        (template / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        (h.home / ".gitconfig").write_text(
            "[init]\n\tdefaultBranch = leaked-branch\n\ttemplateDir = %s\n" % template)
        self.assertEqual(h.self_test().returncode, 0)
        [call] = h.canary_calls()
        self.assertEqual(call["git_hooks"], [])
        self.assertNotIn("leaked-branch", call["git_head"])


class StampWriteTests(unittest.TestCase):
    def test_an_unwritable_cache_dir_is_unavailable_with_its_path(self):
        h = Harness(self, stamp=False)
        blocker = h.dir / "cache-is-a-file"
        blocker.write_text("not a dir\n")
        h.env["XDG_CACHE_HOME"] = str(blocker)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("ADVERSARY_UNAVAILABLE", res.stderr)
        self.assertIn(str(blocker), res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(h.exec_calls(), [])


class CanaryAnswerTests(unittest.TestCase):
    def test_a_canary_with_no_answer_is_not_stamped(self):
        h = Harness(self, stamp=False, canary_answer="none")
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("no valid answer", res.stderr)
        self.assertFalse(h.stamp.exists())
        self.assertEqual(h.exec_calls(), [])

    def test_a_canary_token_on_stdout_only_is_a_leak(self):
        h = Harness(self, stamp=False, canary_answer="stdout_token")
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("isolation canary leaked", res.stderr)
        self.assertIn("AGENTS.md", res.stderr)
        self.assertFalse(h.stamp.exists())


    def test_a_canary_that_exits_non_zero_with_a_valid_answer_is_not_stamped(self):
        # Final review, minor 6: the answer alone is valid, so only the exit-code
        # check stops this canary from being stamped.
        h = Harness(self, stamp=False, canary_exit=1)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("the isolation self-test could not run: codex exec exited 1", res.stderr)
        self.assertEqual(len(h.canary_calls()), 1)
        self.assertFalse(h.stamp.exists())
        self.assertEqual(h.exec_calls(), [])


class SignalTests(unittest.TestCase):
    """Final review, minor 2: Codex runs in its own session, so a TERM or INT sent to
    the wrapper alone never reaches it. The wrapper must kill Codex's whole process
    group and remove its temp dir before it exits."""

    def interrupt(self, sig, stamp=True):
        h = Harness(self, stamp=stamp,
                    exec_actions=[{"sleep": 30, "spawn_child": True, "out": ONE_FINDING}])
        proc = subprocess.Popen(h.argv("--mode", "find", "--timeout", "60"), env=h.env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        pid_file = h.home / "child.pid"
        end = time.time() + 30
        while not pid_file.exists() and time.time() < end:
            time.sleep(0.1)
        self.assertTrue(pid_file.exists(), "the stub never started")
        time.sleep(0.3)
        self.assertEqual(len(h.leftovers()), 1, "the run's temp dir should exist mid-run")
        child = int(pid_file.read_text())
        self.addCleanup(kill_quietly, child)   # a failing run must not leave it behind
        proc.send_signal(sig)
        _, err = proc.communicate(timeout=30)
        return h, proc.returncode, err, child

    def check(self, sig):
        h, rc, err, child = self.interrupt(sig)
        self.assertEqual(rc, 128 + sig, err)
        self.assertIn("interrupted", err)
        self.assertNotIn("Traceback", err)
        self.assertTrue(wait_dead(child), "Codex's process group survived the signal")
        self.assertEqual(h.leftovers(), [])
        self.assertFalse(h.out.exists())

    def test_term_kills_the_codex_group_and_removes_the_temp_dir(self):
        self.check(signal.SIGTERM)

    def test_int_kills_the_codex_group_and_removes_the_temp_dir(self):
        self.check(signal.SIGINT)


class StampKeyTests(unittest.TestCase):
    def test_a_matching_stamp_skips_the_canary(self):
        h = Harness(self)
        self.assertEqual(h.gate(), 0)

    def test_a_changed_isolation_recipe_reruns_the_canary(self):
        h = Harness(self)
        with mock.patch.object(cr, "CANARY_SCHEMA", cr.CANARY_SCHEMA + 1):
            self.assertEqual(h.gate(), 1)
            self.assertEqual(h.gate(), 0)
        self.assertEqual(h.gate(), 0)   # the original recipe's stamp still stands

    def test_the_recipe_hash_covers_each_component(self):
        base = cr.recipe_hash()
        changes = {
            "CANARY_SCHEMA": cr.CANARY_SCHEMA + 1,
            "CANARY_SURFACES": cr.CANARY_SURFACES + ("extra",),
            "DISABLED_FEATURES": cr.DISABLED_FEATURES + ("extra",),
            "PASSTHROUGH_ENV": cr.PASSTHROUGH_ENV + ("EXTRA",),
            "REQUIRED_ARGS": cr.REQUIRED_ARGS + (("--extra",),),
            "ISOLATION_OVERRIDES": cr.ISOLATION_OVERRIDES + ("extra=1",),
        }
        # Pin the argv template so each named entry has to carry its own change.
        fixed = cr.build_argv("<codex>", "<repo>", "<schema>", "<out>", "<prompt>")
        with mock.patch.object(cr, "build_argv", lambda *a, **k: list(fixed)):
            pinned = cr.recipe_hash()
            self.assertEqual(pinned, base)
            for name, value in changes.items():
                with mock.patch.object(cr, name, value):
                    self.assertNotEqual(cr.recipe_hash(), pinned, name)
        with mock.patch.object(cr, "build_argv", lambda *a, **k: fixed + ["--extra"]):
            self.assertNotEqual(cr.recipe_hash(), base, "argv_template")
        self.assertEqual(cr.recipe_hash(), base)

    def test_changed_binary_bytes_rerun_the_canary(self):
        h = Harness(self)
        with open(str(h.bin / "codex"), "a") as fh:
            fh.write("# changed\n")
        self.assertEqual(h.gate(), 1)

    def test_a_different_binary_path_reruns_the_canary(self):
        h = Harness(self)
        other = h.dir / "bin2"
        other.mkdir()
        shutil.copy2(str(h.bin / "codex"), str(other / "codex"))
        self.assertEqual(h.gate(codex=other / "codex"), 1)

    def test_a_different_codex_home_reruns_the_canary(self):
        h = Harness(self)
        self.assertEqual(h.gate(codex_home=str(h.dir)), 1)

    def test_a_new_codex_version_reruns_the_canary(self):
        h = Harness(self)
        h.set_state(version="codex-cli 0.156.0")
        self.assertEqual(h.gate(), 1)

    def test_a_corrupt_or_mismatched_stamp_reruns_the_canary(self):
        h = Harness(self)
        h.stamp.write_text("passed\n")
        self.assertEqual(h.gate(), 1)
        data = json.loads(h.stamp.read_text())
        data["codex_sha256"] = "0" * 64
        h.stamp.write_text(json.dumps(data))
        self.assertEqual(h.gate(), 1)

    def test_a_failed_stamp_write_leaves_the_old_stamp_whole(self):
        h = Harness(self)
        before = h.stamp.read_text()
        fields = json.loads(before)
        with mock.patch.object(cr.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                cr.write_stamp(str(h.stamp), fields)
        self.assertEqual(h.stamp.read_text(), before)
        self.assertEqual(sorted(p.name for p in h.stamp.parent.iterdir()), [h.stamp.name])


class LoadFindingsTests(unittest.TestCase):
    def test_entries_without_a_string_id_are_dropped(self):
        d = Path(tempfile.mkdtemp(prefix="codex-cli-test-"))
        self.addCleanup(shutil.rmtree, d, True)
        path = d / "f.json"
        path.write_text(json.dumps({"findings": [{"id": "C-001"}, {"id": 7}, {"id": ""}, "x", {}]}))
        self.assertEqual(cr.load_findings(str(path)), [{"id": "C-001"}])
        path.write_text(json.dumps([{"id": "C-002"}]))
        self.assertEqual(cr.load_findings(str(path)), [{"id": "C-002"}])
        path.write_text(json.dumps({"no": "list"}))
        with self.assertRaises(cr.InputError):
            cr.load_findings(str(path))


class LockdownTests(unittest.TestCase):
    def test_exec_runs_with_every_hardening_flag(self):
        h = Harness(self)
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        argv = h.exec_calls()[0]["argv"]
        for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules"):
            self.assertIn(flag, argv)
        self.assertIn("project_doc_max_bytes=0", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-C") + 1], str(h.repo))
        self.assertTrue(argv[-1].startswith("You are the adversary"))

    def test_codex_gets_only_path_home_codex_home_and_the_passthrough_list(self):
        h = Harness(self)
        h.env["OPENAI_API_KEY"] = "sk-" + "stub"
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        call = h.exec_calls()[0]
        self.assertEqual(env_keys(call), ["CODEX_HOME", "HOME", "OPENAI_API_KEY", "PATH", "TMPDIR"])
        self.assertEqual(call["codex_home"], str(h.codex_home))

    def test_the_users_codex_home_is_used_as_is_and_left_untouched(self):
        h = Harness(self)
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        self.assertEqual(os.listdir(str(h.codex_home)), [])
        self.assertEqual(h.leftovers(), [])

    def test_no_codex_home_is_invented_when_the_caller_has_none(self):
        h = Harness(self)
        del h.env["CODEX_HOME"]
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        self.assertNotIn("CODEX_HOME", h.exec_calls()[0]["env"])

    def test_callers_stdin_is_not_passed_to_codex(self):
        h = Harness(self)
        proc = subprocess.Popen(h.argv("--mode", "find", "--timeout", "20"), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=h.env)
        try:
            rc = proc.wait(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                pipe.close()
        self.assertEqual(rc, 0)
        self.assertIn("<diff-", h.exec_calls()[0]["stdin"])
        self.assertIn("+retry()", h.exec_calls()[0]["stdin"])

    def test_run_isolated_refuses_an_argv_that_fails_the_guard(self):
        real = cr.build_argv

        def weakened(*args, **kwargs):
            return [a for a in real(*args, **kwargs) if a != "--ephemeral"]

        with mock.patch.object(cr, "build_argv", weakened), \
                mock.patch.object(cr, "run_codex") as run:
            with self.assertRaises(cr.Unavailable) as ctx:
                cr._run_isolated("codex", "/repo", "/s.json", "/o.json", "prompt", b"", {}, 5)
        self.assertIn("--ephemeral", str(ctx.exception))
        run.assert_not_called()


class IsolationGateTests(unittest.TestCase):
    def test_first_run_on_a_new_version_runs_the_canary_then_reviews(self):
        h = Harness(self, stamp=False)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 0, res.stderr)
        execs = [c for c in h.calls() if c["argv"][:1] == ["exec"]]
        self.assertEqual([c["canary"] for c in execs], [True, False])
        self.assertTrue(h.stamp.exists())

    def test_a_stamp_skips_the_canary(self):
        h = Harness(self)
        self.assertEqual(h.run("--mode", "find").returncode, 0)
        self.assertEqual(h.canary_calls(), [])

    def test_project_config_leak_refuses_to_run(self):
        h = Harness(self, stamp=False, load_project_config=True)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3)
        self.assertIn("isolation canary leaked", res.stderr)
        self.assertIn(".codex/config.toml", res.stderr)
        self.assertEqual(h.exec_calls(), [])
        self.assertFalse(h.stamp.exists())

    def test_agents_md_leak_refuses_and_removes_the_stamp(self):
        h = Harness(self, ignore_doc_override=True)
        res = h.self_test()
        self.assertEqual(res.returncode, 3)
        self.assertIn("AGENTS.md", res.stderr)
        self.assertFalse(h.stamp.exists())
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3)
        self.assertIn("isolation canary leaked", res.stderr)
        self.assertEqual(h.exec_calls(), [])

    def test_repo_skill_leak_refuses_to_run(self):
        h = Harness(self, stamp=False, load_repo_skills=True)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("isolation canary leaked", res.stderr)
        self.assertIn(".agents/skills", res.stderr)
        self.assertEqual(h.exec_calls(), [])
        self.assertFalse(h.stamp.exists())

    def test_repo_mcp_leak_refuses_to_run(self):
        h = Harness(self, stamp=False, load_repo_mcp=True)
        res = h.run("--mode", "find")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("isolation canary leaked", res.stderr)
        self.assertIn(".mcp.json", res.stderr)
        self.assertEqual(h.exec_calls(), [])
        self.assertFalse(h.stamp.exists())

    def test_self_test_passes_and_writes_the_stamp(self):
        h = Harness(self, stamp=False)
        res = h.self_test()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("isolation self-test passed on Codex 0.155.1", res.stdout)
        self.assertTrue(h.stamp.exists())
        self.assertEqual(h.exec_calls(), [])

    def test_the_canary_runs_isolated_and_leaves_nothing_behind(self):
        h = Harness(self, stamp=False)
        self.assertEqual(h.self_test().returncode, 0)
        [call] = h.canary_calls()
        cr.assert_isolated(["codex"] + call["argv"])   # the stub logs argv without argv[0]
        self.assertIsNotNone(shared_nonce(call))
        self.assertEqual(env_keys(call), ["CODEX_HOME", "HOME", "PATH", "TMPDIR"])
        self.assertEqual(h.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
