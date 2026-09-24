"""Unit tests for audit_record.py (pure functions, no I/O)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_record as ar  # noqa: E402

SHA1 = "1" * 40
SHA2 = "2" * 40


def finding(fid="X-001", **over):
    f = {
        "id": fid, "origin": "codex", "path": "src/a.py", "line": 41,
        "severity": "important", "category": "bug",
        "title": "Retry loop never resets the backoff",
        "rationale": "The delay doubles forever.",
        "status": "survivor", "events": [],
    }
    f.update(over)
    return f


def record(findings=None, rnd=1, head=SHA1, prev=None, **over):
    r = {
        "schema": "audit-round/v1", "run_id": "ar-test-1", "skill": "deep-review",
        "phase": "phase2", "round": rnd, "adversary": "codex",
        "head_sha": head, "prev_head_sha": prev,
        "findings": [finding()] if findings is None else findings,
    }
    r.update(over)
    return r


class ValidateTests(unittest.TestCase):
    def test_valid_record_passes(self):
        ar.validate(record())

    def test_short_head_sha_is_rejected(self):
        with self.assertRaises(ar.RecordError) as cm:
            ar.validate(record(head="abc1234"))
        self.assertIn("head_sha", str(cm.exception))

    def test_every_problem_is_listed(self):
        bad = record(findings=[finding(fid="bad", severity="huge", status="maybe")])
        del bad["phase"]
        with self.assertRaises(ar.RecordError) as cm:
            ar.validate(bad)
        msg = str(cm.exception)
        for needle in ("phase", ".id", ".severity", ".status"):
            self.assertIn(needle, msg)

    def test_duplicate_finding_ids_are_rejected(self):
        with self.assertRaises(ar.RecordError) as cm:
            ar.validate(record(findings=[finding(), finding()]))
        self.assertIn("duplicated", str(cm.exception))

    def test_event_kinds_are_checked(self):
        f = finding(events=[{"by": "claude", "kind": "shrug", "text": ""}])
        with self.assertRaises(ar.RecordError):
            ar.validate(record(findings=[f]))

    def test_fixed_without_sha_is_allowed_but_bad_sha_is_not(self):
        ok = finding(events=[{"by": "claude", "kind": "resolution", "resolution": "fixed", "text": "done"}])
        ar.validate(record(findings=[ok]))
        bad = copy.deepcopy(ok)
        bad["events"][0]["sha"] = "abc"
        with self.assertRaises(ar.RecordError):
            ar.validate(record(findings=[bad]))

    def test_phase1_ids_are_accepted(self):
        ar.validate(record(findings=[finding(fid="R-001")]))

    def test_bool_round_is_rejected(self):
        with self.assertRaises(ar.RecordError):
            ar.validate(record(rnd=True))


class MarkerTests(unittest.TestCase):
    def test_marker_round_trips(self):
        m = ar.marker("ar-test-1", "X-003", 2, 4)
        self.assertEqual(m, "<!-- audit:v1 run=ar-test-1 finding=X-003 event=2.4 -->")
        parsed = ar.parse_marker("some text\n" + m)
        self.assertEqual(parsed["run"], "ar-test-1")
        self.assertEqual(parsed["finding"], "X-003")
        self.assertEqual((parsed["round"], parsed["index"]), (2, 4))
        self.assertEqual(parsed["marker"], m)

    def test_no_marker_returns_none(self):
        self.assertIsNone(ar.parse_marker("plain comment"))
        self.assertIsNone(ar.parse_marker(None))

    def test_summary_marker_is_not_a_finding_marker(self):
        self.assertIsNone(ar.parse_marker(ar.summary_marker("ar-test-1", 2, 1)))


if __name__ == "__main__":
    unittest.main()
