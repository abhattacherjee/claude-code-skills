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


FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


class RedactTests(unittest.TestCase):
    def test_github_token_is_redacted(self):
        text, counts = ar.redact(f"token is {FAKE_GH} here")
        self.assertNotIn(FAKE_GH, text)
        self.assertIn("[REDACTED:github-token]", text)
        self.assertEqual(counts["github-token"], 1)

    def test_token_inside_url_is_redacted(self):
        text, _ = ar.redact(f"https://x:{FAKE_GH}@github.com/o/r.git")
        self.assertNotIn(FAKE_GH, text)

    def test_anthropic_key_is_not_counted_as_openai(self):
        _, counts = ar.redact("sk-ant-" + "a" * 30)
        self.assertEqual(counts["anthropic-key"], 1)
        self.assertEqual(counts["openai-key"], 0)

    def test_pem_key_block_is_redacted(self):
        pk = "PRIVATE" + " KEY"
        block = f"-----BEGIN RSA {pk}-----\nMIIEow\n-----END RSA {pk}-----"
        text, counts = ar.redact(f"x\n{block}\ny")
        self.assertNotIn("MIIEow", text)
        self.assertEqual(counts["private-key"], 1)

    def test_aws_and_jwt_are_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlLXZhbHVl"
        text, counts = ar.redact(f'{"AKIA" + "ABCDEFGHIJKLMNOP"} {jwt}')
        self.assertEqual(counts["aws-key-id"], 1)
        self.assertEqual(counts["jwt"], 1)
        self.assertNotIn(jwt, text)

    def test_ordinary_text_is_untouched(self):
        text, counts = ar.redact("skip-list sk- is fine; eyJ alone too")
        self.assertEqual(text, "skip-list sk- is fine; eyJ alone too")
        self.assertEqual(sum(counts.values()), 0)


class TruncateTests(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(ar.truncate("abc", 100), "abc")

    def test_long_text_is_cut_at_a_line_and_noted(self):
        text = ("line of text\n" * 1000)
        out = ar.truncate(text, 500)
        self.assertLessEqual(len(out), 500)
        self.assertIn("truncated", out)
        self.assertTrue(out.split("\n\n… truncated")[0].endswith("line of text"))

    def test_finalize_keeps_marker_and_fits(self):
        mark = ar.marker("ar-test-1", "X-001", 1, 0)
        body, _ = ar.finalize("x" * 70000, mark)
        self.assertLessEqual(len(body), ar.MAX_BODY)
        self.assertTrue(body.endswith(mark))
        self.assertIn("truncated", body)


def ev(kind, by="claude", text="because", **kw):
    e = {"by": by, "kind": kind, "text": text}
    e.update(kw)
    return e


class RenderTests(unittest.TestCase):
    def test_opener_tags_origin_and_severity(self):
        body = ar.opener_content(record(), finding())
        self.assertTrue(body.startswith("**[Codex] [important] bug** — Retry loop"))
        self.assertIn("Round 1 · phase2 · reviewed at `1111111`", body)

    def test_event_heads(self):
        rec = record()
        cases = [
            (ev("verdict", verdict="refute"), "**[Claude] verdict: refute** — because"),
            (ev("counter", by="codex"), "**[Codex] counter** — because"),
            (ev("resolution", resolution="fixed", sha=SHA2), "**[Claude] fixed in `2222222`**"),
            (ev("resolution", resolution="fixed"), "**[Claude] fixed (not yet committed)**"),
            (ev("resolution", resolution="pushback"), "**[Claude] pushback**"),
            (ev("recheck", by="codex", result="partly"), "**[Codex] re-check: partly**"),
        ]
        for event, head in cases:
            self.assertTrue(ar.event_content(rec, event).startswith(head), head)

    def test_resolution_rules(self):
        rec = record()
        self.assertTrue(ar.should_resolve(finding(status="rejected"), rec))
        fixed = finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])
        self.assertFalse(ar.should_resolve(fixed, rec))
        rechecked = finding(events=[ev("recheck", by="codex", result="resolved")])
        self.assertTrue(ar.should_resolve(rechecked, rec))
        missed = finding(events=[ev("recheck", by="codex", result="missed")])
        self.assertFalse(ar.should_resolve(missed, rec))

    def test_resolution_requires_latest_adversary_recheck(self):
        rec = record()
        rec_claude_only = record(adversary="claude-only")
        self.assertTrue(ar.should_resolve(finding(events=[ev("recheck", by="codex", result="resolved")]), rec))
        self.assertFalse(ar.should_resolve(finding(events=[ev("recheck", by="claude", result="resolved")]), rec))
        self.assertFalse(ar.should_resolve(finding(events=[ev("recheck", by="codex", result="resolved"), ev("recheck", by="codex", result="missed")]), rec))
        self.assertTrue(ar.should_resolve(finding(events=[ev("recheck", by="claude", result="resolved")]), rec_claude_only))
        self.assertFalse(ar.should_resolve(finding(events=[ev("resolution", resolution="pushback")]), rec))

    def test_outcomes(self):
        self.assertEqual(ar.outcome(finding(status="rejected")), "refuted")
        self.assertEqual(ar.outcome(finding()), "confirmed")
        self.assertEqual(ar.outcome(finding(status="unconfirmed")), "unconfirmed")
        f = finding(events=[ev("resolution", resolution="fixed"), ev("recheck", by="codex", result="resolved")])
        self.assertEqual(ar.outcome(f), "re-check: resolved")

    def test_summary_single_part(self):
        rows = [{"id": "X-001", "severity": "important", "origin": "codex", "outcome": "confirmed",
                 "new": True, "thread": "https://t/1", "note": None},
                {"id": "X-002", "severity": "minor", "origin": "codex", "outcome": "refuted",
                 "new": True, "thread": None, "note": "no path"}]
        bodies = ar.summary_bodies(record(prev=SHA2), rows, redacted=1, failures=0)
        self.assertEqual(len(bodies), 1)
        b = bodies[0]
        self.assertIn("**deep-review · phase2 · Round 1** · adversary: codex · reviewed `1111111` (previous `2222222`)", b)
        self.assertIn("2 findings: 2 new · 1 confirmed · 1 refuted", b)
        self.assertIn("| X-001 | important | codex | confirmed | [thread](https://t/1) |", b)
        self.assertIn("| X-002 | minor | codex | refuted | no thread: no path |", b)
        self.assertIn("Redacted: 1 · Posting failures: 0", b)
        self.assertTrue(b.endswith(ar.summary_marker("ar-test-1", 1, 1)))

    def test_summary_splits_and_numbers_parts(self):
        rows = [{"id": f"X-{i:03d}", "severity": "minor", "origin": "codex", "outcome": "confirmed",
                 "new": False, "thread": f"https://github.com/o/r/pull/7#discussion_r{i}", "note": None}
                for i in range(1, 101)]
        bodies = ar.summary_bodies(record(), rows, 0, 0, limit=3000)
        self.assertGreater(len(bodies), 1)
        n = len(bodies)
        for i, b in enumerate(bodies, 1):
            self.assertLessEqual(len(b), 3000)
            self.assertIn(f"Round 1 ({i}/{n})**", b)
            self.assertTrue(b.endswith(ar.summary_marker("ar-test-1", 1, i)))
        self.assertEqual(sum(b.count("| X-") for b in bodies), 100)

    def test_pipe_in_title_does_not_break_table(self):
        rows = [{"id": "X-001", "severity": "minor", "origin": "codex", "outcome": "confirmed",
                 "new": True, "thread": None, "note": "a|b"}]
        b = ar.summary_bodies(record(), rows, 0, 0)[0]
        self.assertIn("no thread: a\\|b |", b)

    def test_summary_redacts_notes_before_sizing(self):
        rows = [{"id": "X-001", "severity": "minor", "origin": "codex", "outcome": "confirmed",
                 "new": True, "thread": None, "note": f"secret {FAKE_GH} here"}]
        limit = 3000
        bodies = ar.summary_bodies(record(), rows, 0, 0, limit=limit)
        for b in bodies:
            self.assertNotIn(FAKE_GH, b)
            self.assertLessEqual(len(b), limit)

    def test_no_room_for_details_leaves_a_note_instead_of_silent_drop(self):
        rows = [{"id": "X-001", "severity": "minor", "origin": "codex", "outcome": "confirmed",
                 "new": True, "thread": "https://t/1", "note": None}]
        details = "x" * 5000
        bodies = ar.summary_bodies(record(), rows, 0, 0, details=details, limit=450)
        b = bodies[-1]
        self.assertLessEqual(len(b), 450)
        self.assertIn(
            "Details for findings with no thread were too long to include; they are in the run dir.",
            b)
        self.assertNotIn("x" * 50, b)

    def test_no_thread_details_and_markdown(self):
        f = finding(path=None, events=[ev("verdict", verdict="confirm")])
        details, _ = ar.no_thread_details(record(findings=[f]), [f])
        self.assertIn("<details>", details)
        self.assertIn("**X-001** · **[Codex] [important] bug**", details)
        self.assertIn("> **[Claude] verdict: confirm**", details)
        md, _ = ar.markdown(record(findings=[f]))
        self.assertIn("## deep-review · phase2 · Round 1", md)
        self.assertIn(ar.opener_content(record(findings=[f]), f), md)
        self.assertNotIn("<!-- audit:v1", md)


class TrailingLineTests(unittest.TestCase):
    def test_marker_on_last_line(self):
        mark = "<!-- audit:v1 run=ar-test-1 finding=X-001 event=1.0 -->"
        self.assertEqual(ar.trailing_line(f"a\n\n{mark}\n\n"), mark)

    def test_empty_body_returns_empty_string(self):
        self.assertEqual(ar.trailing_line(""), "")

    def test_none_body_returns_empty_string(self):
        self.assertEqual(ar.trailing_line(None), "")

    def test_body_with_only_whitespace_returns_empty_string(self):
        self.assertEqual(ar.trailing_line("  \n\n  \t"), "")


if __name__ == "__main__":
    unittest.main()
