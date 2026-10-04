"""Tests for `pr-audit.py recheck`: the adversary's re-checks become recheck events."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_pr_audit import SHA2, SHA3, Harness, ev, finding, record  # noqa: E402


def fix_round(adversary="codex"):
    return record([finding("X-003", events=[ev("resolution", resolution="fixed", sha=SHA2,
                                                 text="added a cap")]),
                   finding("X-004", events=[ev("resolution", resolution="fixed", sha=SHA2,
                                                 text="guarded")])],
                  rnd=4, head=SHA2, phase="phase2-fix", adversary=adversary)


NEW = {"id": "X-005", "origin": "codex", "path": "src/b.py", "line": 7, "severity": "minor",
       "category": "perf", "title": "Scan twice", "rationale": "Loop in a loop."}


class RecheckTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.prior = self.h.write(fix_round(), "round-4.json")
        self.out = self.h.dir / "round-5.json"

    def recheck(self, data, rnd=5, prior=None):
        path = self.h.write(data, "recheck.json")
        res = self.h.run("recheck", "--prior", prior or self.prior, "--rechecks", path,
                         "--round", rnd, "--head-sha", SHA3, "--out", self.out)
        rec = json.loads(self.out.read_text()) if res.returncode == 0 else None
        return res, rec

    def raw_recheck(self, path_or_dict, rnd=5, prior=None):
        """Like recheck(), but skips writing through self.h.write when a raw path is
        already on disk (for a non-JSON or missing --rechecks file)."""
        path = self.h.write(path_or_dict, "recheck.json") if isinstance(path_or_dict, dict) \
            else path_or_dict
        return self.h.run("recheck", "--prior", prior or self.prior, "--rechecks", path,
                          "--round", rnd, "--head-sha", SHA3, "--out", self.out)

    def test_rechecks_become_adversary_events_on_the_earlier_findings(self):
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((rec["phase"], rec["round"], rec["run_id"]), ("phase2-recheck", 5, "ar-test-1"))
        self.assertEqual((rec["prev_head_sha"], rec["head_sha"], rec["adversary"]), (SHA2, SHA3, "codex"))
        f = rec["findings"][0]
        self.assertEqual((f["id"], f["title"], f["status"]), ("X-003", "Retry loop never resets the backoff", "survivor"))
        self.assertEqual(f["events"], [{"by": "codex", "kind": "recheck", "result": "resolved",
                                        "text": "cap is there"}])
        self.assertIn("no re-check for X-004", res.stderr)

    def test_unknown_repeated_and_unhashable_ids_are_skipped(self):
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "partly", "reason": "one path left"},
            {"id": "X-003", "result": "resolved", "reason": "repeat"},
            {"id": "X-404", "result": "resolved", "reason": "made up"},
            {"id": ["X-004"], "result": "resolved", "reason": "unhashable"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([(f["id"], [e["result"] for e in f["events"]]) for f in rec["findings"]],
                         [("X-003", ["partly"]), ("X-004", [])])
        self.assertIn("X-404", res.stderr)
        self.assertIn("unchecked=1", res.stderr)

    def test_new_findings_are_added_unconfirmed(self):
        res, rec = self.recheck({"adversary": "codex", "findings": [NEW], "rechecks": []})
        self.assertEqual(res.returncode, 0, res.stderr)
        f = rec["findings"][-1]
        self.assertEqual((f["id"], f["origin"], f["status"], f["events"]), ("X-005", "codex", "unconfirmed", []))
        self.assertEqual([g["id"] for g in rec["findings"]], ["X-003", "X-004", "X-005"])

    def test_new_finding_reusing_an_earlier_id_exits_2(self):
        clash = dict(NEW, id="X-003")
        res, _ = self.recheck({"adversary": "codex", "findings": [clash], "rechecks": []})
        self.assertEqual(res.returncode, 2)
        self.assertIn("--id-start", res.stderr)

    def test_round_must_come_after_the_prior_round(self):
        res, _ = self.recheck({"adversary": "codex", "findings": [], "rechecks": []}, rnd=4)
        self.assertEqual(res.returncode, 2)
        self.assertIn("must come after", res.stderr)

    def test_missing_rechecks_list_exits_2(self):
        res, _ = self.recheck({"findings": []})
        self.assertEqual(res.returncode, 2)
        self.assertIn("rechecks", res.stderr)

    def test_resolved_recheck_closes_only_that_thread_on_the_pr(self):
        self.assertEqual(self.h.post(fix_round(), "round-4.json").returncode, 0)
        self.assertEqual(self.h.resolves(), [])
        replies_before = len(self.h.posted("reply"))
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"},
            {"id": "X-004", "result": "partly", "reason": "one path left"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        post = self.h.post(rec, "round-5.json")
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(len(self.h.resolves()), 1)
        self.assertEqual(len(self.h.posted("reply")), replies_before + 2)

    # --- fix round 1: recheck rounds are Codex-only, and the rechecks file must
    # name the same adversary as the prior it re-checks (review Important 1) ---

    def test_gemini_prior_is_rejected(self):
        # The rechecks file's own "adversary" matches the prior's, so only the
        # Codex-only guard (not the provenance guard) can reject this.
        prior = self.h.write(fix_round("gemini"), "round-4-gemini.json")
        res, _ = self.recheck({"adversary": "gemini", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]}, prior=prior)
        self.assertEqual(res.returncode, 2)
        self.assertIn("Codex-only", res.stderr)
        self.assertIn("gemini", res.stderr)
        self.assertFalse(self.out.exists())

    def test_claude_only_prior_is_rejected(self):
        # Same as above: the rechecks file's "adversary" matches the prior's
        # "claude-only", so only the Codex-only guard can reject this.
        prior = self.h.write(fix_round("claude-only"), "round-4-claude.json")
        res, _ = self.recheck({"adversary": "claude-only", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "ok"}]}, prior=prior)
        self.assertEqual(res.returncode, 2)
        self.assertIn("Codex-only", res.stderr)
        self.assertIn("claude-only", res.stderr)
        self.assertFalse(self.out.exists())

    def test_reviewers_hand_written_probe_on_a_gemini_prior_is_rejected(self):
        # The exact probe from the review: a hand-written {"rechecks": [...]} file
        # with no provenance, run against a gemini prior, must not be trusted as a
        # Codex re-check and must not close any thread Gemini never agreed to close.
        prior = self.h.write(fix_round("gemini"), "round-4-gemini-probe.json")
        path = self.h.write({"rechecks": [{"id": "X-003", "result": "resolved"}]}, "probe.json")
        res = self.h.run("recheck", "--prior", prior, "--rechecks", path,
                         "--round", "5", "--head-sha", SHA3, "--out", self.out)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(self.out.exists())

    def test_rechecks_file_adversary_mismatch_is_rejected(self):
        res, _ = self.recheck({"adversary": "gemini", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not match", res.stderr)
        self.assertIn("codex", res.stderr)
        self.assertIn("gemini", res.stderr)
        self.assertFalse(self.out.exists())

    def test_rechecks_file_missing_adversary_is_rejected(self):
        res, _ = self.recheck({"findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not match", res.stderr)
        self.assertFalse(self.out.exists())

    # --- Minor 4: an unreadable/non-JSON --rechecks file, and an invalid re-check
    # `result` value, both exit 2 ---

    def test_non_json_rechecks_file_exits_2(self):
        path = self.h.dir / "bad.json"
        path.write_text("not json")
        res = self.raw_recheck(path)
        self.assertEqual(res.returncode, 2)
        self.assertIn("cannot read", res.stderr)
        self.assertFalse(self.out.exists())

    def test_unreadable_rechecks_file_exits_2(self):
        path = self.h.dir / "does-not-exist.json"
        res = self.raw_recheck(path)
        self.assertEqual(res.returncode, 2)
        self.assertIn("cannot read", res.stderr)
        self.assertFalse(self.out.exists())

    def test_invalid_recheck_result_exits_2(self):
        res, _ = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "kinda", "reason": "eh"}]})
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not make a valid record", res.stderr)
        self.assertFalse(self.out.exists())

    def test_an_unwritable_out_path_exits_2_with_a_message(self):
        # Final review, minor 5: open(--out) was unguarded, so a bad path crashed
        # into run()'s catch-all (exit 3) instead of saying what went wrong.
        self.out = self.h.dir / "missing-dir" / "round-5.json"
        res, _ = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("cannot write --out", res.stderr)
        self.assertIn("missing-dir", res.stderr)
        self.assertNotIn("unexpected error", res.stderr)
        self.assertFalse(self.out.exists())

    # --- deep-review X-001: a prior finding Codex did not re-check must stay in the
    # record (so Step 2.6 cannot converge without it) and be counted as unchecked ---

    def test_an_omitted_prior_finding_is_carried_over_with_no_events(self):
        prior = json.loads(Path(self.prior).read_text())
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([f["id"] for f in rec["findings"]], ["X-003", "X-004"])
        carried = rec["findings"][1]
        expected = dict(prior["findings"][1], events=[])
        self.assertEqual(carried, expected)
        self.assertIn("unchecked=1", res.stderr)
        self.assertIn("X-004", res.stderr.split("unchecked=1", 1)[1].splitlines()[0])
        self.assertIn("1 unchecked", res.stdout)

    def test_every_omitted_prior_finding_is_counted(self):
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": []})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([(f["id"], f["events"]) for f in rec["findings"]],
                         [("X-003", []), ("X-004", [])])
        line = [ln for ln in res.stderr.splitlines() if "unchecked=" in ln]
        self.assertEqual(len(line), 1, res.stderr)
        self.assertIn("unchecked=2", line[0])
        self.assertIn("X-003", line[0])
        self.assertIn("X-004", line[0])

    def test_a_full_recheck_reports_unchecked_0_and_carries_nothing(self):
        # Negative control: when Codex re-checks every prior finding, nothing is
        # carried over and the count is 0.
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"},
            {"id": "X-004", "result": "missed", "reason": "no guard"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(all(f["events"] for f in rec["findings"]))
        self.assertIn("unchecked=0", res.stderr)
        self.assertNotIn("unchecked=1", res.stderr)
        self.assertIn("0 unchecked", res.stdout)

    def test_a_carried_over_finding_keeps_its_thread_open_on_the_pr(self):
        self.assertEqual(self.h.post(fix_round(), "round-4.json").returncode, 0)
        replies_before = len(self.h.posted("reply"))
        res, rec = self.recheck({"adversary": "codex", "findings": [], "rechecks": [
            {"id": "X-003", "result": "resolved", "reason": "cap is there"}]})
        self.assertEqual(res.returncode, 0, res.stderr)
        post = self.h.post(rec, "round-5.json")
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(len(self.h.resolves()), 1)  # X-003 only
        self.assertEqual(len(self.h.posted("reply")), replies_before + 1)  # no reply on X-004


if __name__ == "__main__":
    unittest.main()
