# Review Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save every model exchange from `adversarial-review` and `deep-review` on the PR, round by round, as inline threads plus one summary review per round.

**Architecture:** A pure module `audit_record.py` validates a round record and renders every comment body. A CLI `pr-audit.py` does the GitHub I/O through `gh`, finds earlier threads by a hidden marker (so it keeps no local state), and falls back to a local markdown file. `sink.sh` (adversarial-review) and `deep-review/SKILL.md` call it.

**Tech Stack:** Python 3 standard library only, bash, `gh` CLI (REST + GraphQL), `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-24-review-audit-trail-and-codex-adversary-design.md`, Part 1. Part 2 (Codex adversary) gets its own plan after this one ships.

## Global Constraints

- Round record schema string: `audit-round/v1`.
- `head_sha`, `prev_head_sha` and a fixed event's `sha`: 40 lowercase hex characters.
- Finding id pattern: `^[A-Z][A-Z0-9]{0,3}-\d{3,}$`. Run id pattern: `^[A-Za-z0-9._-]{1,64}$`.
- Marker: `<!-- audit:v1 run=<run_id> finding=<id> event=<round>.<index> -->`; thread opener is index 0.
- Summary marker: `<!-- audit:v1 run=<run_id> summary round=<round> part=<n> -->`.
- Comment body cap: 60,000 characters (GitHub limit 65,536).
- Reviews are always `event: COMMENT`. Never `APPROVE` or `REQUEST_CHANGES`.
- `pr-audit.py` exit codes: 0 ok, 1 some posts failed, 2 usage error or invalid record.
- `sink.sh` exit codes: 0 ok, 1 error, 2 usage, 4 report delivered but audit trail incomplete.
- No new dependencies. Python standard library only.
- Paths below are relative to the repo root. `AR` = `plugins/adversarial-review/skills/adversarial-review`.
- Run every test file with `PYTHONDONTWRITEBYTECODE=1`.

## Review Focus

1. **A PR where the same finding id appears in two different runs.** A reasonable person expects a new run to open new threads, not reply into last week's thread. Pinned by `test_other_run_ids_open_new_threads` in Task 5.
2. **A rationale containing a fenced code block or a `|` character.** Expect the thread body to render and the summary table to stay intact (the summary holds no free text). Pinned by `test_pipe_in_title_does_not_break_table` in Task 3.
3. **`gh` present but the PR number wrong (404).** Expect exit 1 with a clear "could not read PR" line, not a traceback. Pinned by `test_unknown_pr_exits_1_cleanly` in Task 5.
4. **A record whose `events` repeat an event already posted, with the round number reused after a crash.** Expect the posted events to be skipped and only missing ones posted. Pinned by `test_partial_rerun_posts_only_missing` in Task 5.
5. **A token split across a line break or embedded in a URL (`https://x:ghp_…@github.com`).** Expect the URL form redacted. The split form is out of scope and documented. Pinned by `test_token_inside_url_is_redacted` in Task 2.

---

### Task 1: Round record validation and markers

**Files:**
- Create: `AR/scripts/audit_record.py`
- Test: `AR/scripts/test_audit_record.py`

**Interfaces:**
- Produces: `SCHEMA: str`, `MAX_BODY: int`, `class RecordError(ValueError)`, `validate(rec: dict) -> None` (raises `RecordError` listing every problem), `marker(run_id: str, finding_id: str, rnd: int, index: int) -> str`, `summary_marker(run_id: str, rnd: int, part: int) -> str`, `parse_marker(body: str | None) -> dict | None` (keys `run`, `finding`, `round`, `index`, `marker`).

- [ ] **Step 1: Write the failing tests**

Create `AR/scripts/test_audit_record.py`:

```python
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
            ar.validate(record(head="abc123"))
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audit_record'`.

- [ ] **Step 3: Write the implementation**

Create `AR/scripts/audit_record.py`:

```python
"""audit_record.py — pure helpers for the review audit trail.

Validates a round record (schema audit-round/v1), redacts secrets, truncates
long bodies, and renders the comment bodies pr-audit.py posts. No I/O here,
so every function can be tested directly.
"""
import re
from collections import Counter

SCHEMA = "audit-round/v1"
MAX_BODY = 60000
SKILLS = {"adversarial-review", "deep-review"}
ADVERSARIES = {"codex", "gemini", "claude-only"}
MODELS = {"claude", "codex", "gemini"}
SEVERITIES = {"critical", "important", "minor"}
STATUSES = {"survivor", "rejected", "unconfirmed"}
TAG = {"claude": "Claude", "codex": "Codex", "gemini": "Gemini"}

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
FINDING_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{0,3}-\d{3,}$")
MARKER_RE = re.compile(
    r"<!-- audit:v1 run=(?P<run>[A-Za-z0-9._-]{1,64}) "
    r"finding=(?P<finding>[A-Z][A-Z0-9]{0,3}-\d{3,}) "
    r"event=(?P<round>\d+)\.(?P<index>\d+) -->"
)


class RecordError(ValueError):
    """The round record does not match audit-round/v1."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _event_problems(where, ev):
    if not isinstance(ev, dict):
        return [f"{where} must be an object"]
    problems = []
    if ev.get("by") not in MODELS:
        problems.append(f"{where}.by must be one of {sorted(MODELS)}")
    if not isinstance(ev.get("text"), str):
        problems.append(f"{where}.text must be a string")
    kind = ev.get("kind")
    if kind == "verdict":
        if ev.get("verdict") not in ("confirm", "refute"):
            problems.append(f"{where}.verdict must be confirm or refute")
    elif kind == "counter":
        pass
    elif kind == "resolution":
        if ev.get("resolution") not in ("fixed", "pushback", "deferred"):
            problems.append(f"{where}.resolution must be fixed, pushback or deferred")
        if "sha" in ev and not SHA_RE.match(str(ev["sha"])):
            problems.append(f"{where}.sha must be a 40-char lowercase hex SHA")
    elif kind == "recheck":
        if ev.get("result") not in ("resolved", "partly", "missed"):
            problems.append(f"{where}.result must be resolved, partly or missed")
    else:
        problems.append(f"{where}.kind must be verdict, counter, resolution or recheck")
    return problems


def validate(rec):
    """Raise RecordError listing every problem with the record."""
    if not isinstance(rec, dict):
        raise RecordError("record must be a JSON object")
    problems = []
    if rec.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}")
    if not RUN_ID_RE.match(str(rec.get("run_id", ""))):
        problems.append("run_id must match [A-Za-z0-9._-]{1,64}")
    if rec.get("skill") not in SKILLS:
        problems.append(f"skill must be one of {sorted(SKILLS)}")
    if not isinstance(rec.get("phase"), str) or not rec.get("phase"):
        problems.append("phase must be a non-empty string")
    if not _is_int(rec.get("round")) or rec["round"] < 1:
        problems.append("round must be an integer >= 1")
    if rec.get("adversary") not in ADVERSARIES:
        problems.append(f"adversary must be one of {sorted(ADVERSARIES)}")
    if not SHA_RE.match(str(rec.get("head_sha", ""))):
        problems.append("head_sha must be a 40-char lowercase hex SHA")
    prev = rec.get("prev_head_sha")
    if prev is not None and not SHA_RE.match(str(prev)):
        problems.append("prev_head_sha must be null or a 40-char lowercase hex SHA")
    findings = rec.get("findings")
    if not isinstance(findings, list):
        problems.append("findings must be a list")
        findings = []
    seen = set()
    for i, f in enumerate(findings):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            problems.append(f"{where} must be an object")
            continue
        fid = str(f.get("id", ""))
        if not FINDING_ID_RE.match(fid):
            problems.append(f"{where}.id must look like X-001")
        elif fid in seen:
            problems.append(f"{where}.id {fid} is duplicated")
        seen.add(fid)
        if f.get("origin") not in MODELS:
            problems.append(f"{where}.origin must be one of {sorted(MODELS)}")
        if f.get("severity") not in SEVERITIES:
            problems.append(f"{where}.severity must be one of {sorted(SEVERITIES)}")
        if f.get("status") not in STATUSES:
            problems.append(f"{where}.status must be one of {sorted(STATUSES)}")
        for key in ("title", "category", "rationale"):
            if not isinstance(f.get(key), str):
                problems.append(f"{where}.{key} must be a string")
        if isinstance(f.get("title"), str) and not f["title"].strip():
            problems.append(f"{where}.title must not be empty")
        path = f.get("path")
        if path is not None and (not isinstance(path, str) or not path):
            problems.append(f"{where}.path must be null or a non-empty string")
        line = f.get("line")
        if line is not None and (not _is_int(line) or line < 1):
            problems.append(f"{where}.line must be null or an integer >= 1")
        events = f.get("events")
        if not isinstance(events, list):
            problems.append(f"{where}.events must be a list")
        else:
            for j, ev in enumerate(events):
                problems.extend(_event_problems(f"{where}.events[{j}]", ev))
    if problems:
        raise RecordError("; ".join(problems))


def marker(run_id, finding_id, rnd, index):
    return f"<!-- audit:v1 run={run_id} finding={finding_id} event={rnd}.{index} -->"


def summary_marker(run_id, rnd, part):
    return f"<!-- audit:v1 run={run_id} summary round={rnd} part={part} -->"


def parse_marker(body):
    match = MARKER_RE.search(body or "")
    if not match:
        return None
    return {
        "run": match["run"], "finding": match["finding"],
        "round": int(match["round"]), "index": int(match["index"]),
        "marker": match.group(0),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: 11 tests, all PASS.

- [ ] **Step 5: Negative control**

Temporarily change `SHA_RE` to `re.compile(r"^[0-9a-f]{7,40}$")`. Run the tests. Expected: `test_short_head_sha_is_rejected` FAILS. Revert the change and rerun: all PASS.

- [ ] **Step 6: Commit**

```bash
git add AR/scripts/audit_record.py AR/scripts/test_audit_record.py
git commit -m "feat(adversarial-review): validate audit round records and markers (#135)"
```

### Task 2: Redaction and truncation

**Files:**
- Modify: `AR/scripts/audit_record.py` (append)
- Test: `AR/scripts/test_audit_record.py` (append a class)

**Interfaces:**
- Consumes: `MAX_BODY` from Task 1.
- Produces: `redact(text: str) -> tuple[str, Counter]`, `truncate(text: str, limit: int = MAX_BODY) -> str`, `finalize(content: str, mark: str) -> tuple[str, Counter]` (redact, then truncate so that content + newline + marker fits `MAX_BODY`, then append the marker).

- [ ] **Step 1: Write the failing tests**

Append to `AR/scripts/test_audit_record.py`, above the `if __name__` line:

```python
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

    def test_private_key_block_is_redacted(self):
        block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
        text, counts = ar.redact(f"x\n{block}\ny")
        self.assertNotIn("MIIEow", text)
        self.assertEqual(counts["private-key"], 1)

    def test_aws_and_jwt_are_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlLXZhbHVl"
        text, counts = ar.redact(f"AKIAABCDEFGHIJKLMNOP {jwt}")
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
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: the 9 new tests FAIL with `AttributeError: module 'audit_record' has no attribute 'redact'` (or `truncate`/`finalize`).

- [ ] **Step 3: Implement**

Append to `AR/scripts/audit_record.py`:

```python
SECRET_PATTERNS = [
    ("github-token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"sk-(?!ant-)[A-Za-z0-9_-]{20,}")),
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]
TRUNC_NOTE = "\n\n… truncated ({n} chars); full record in the run dir"


def redact(text):
    """Replace known secret formats with [REDACTED:<type>]. Returns (text, counts)."""
    counts = Counter()
    for name, rx in SECRET_PATTERNS:
        text, n = rx.subn(f"[REDACTED:{name}]", text)
        if n:
            counts[name] += n
    return text, counts


def truncate(text, limit=MAX_BODY):
    """Cut text at a line boundary so the result, note included, fits in limit."""
    if len(text) <= limit:
        return text
    room = limit - 100
    cut = text.rfind("\n", 0, room)
    if cut <= 0:
        cut = room
    return text[:cut] + TRUNC_NOTE.format(n=len(text) - cut)


def finalize(content, mark):
    """Redact, truncate to leave room for the marker, then append the marker."""
    body, counts = redact(content)
    body = truncate(body, MAX_BODY - len(mark) - 1)
    return body + "\n" + mark, counts
```

- [ ] **Step 4: Run to verify all pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: 20 tests, all PASS.

- [ ] **Step 5: Negative control**

Temporarily delete the `("github-token", …)` entry from `SECRET_PATTERNS`. Run the tests. Expected: `test_github_token_is_redacted` and `test_token_inside_url_is_redacted` FAIL. Restore it and rerun: all PASS.

- [ ] **Step 6: Commit**

```bash
git add AR/scripts/audit_record.py AR/scripts/test_audit_record.py
git commit -m "feat(adversarial-review): redact secrets and cap comment size in the audit trail (#135)"
```

### Task 3: Rendering bodies, outcomes and the round summary

**Files:**
- Modify: `AR/scripts/audit_record.py` (append)
- Test: `AR/scripts/test_audit_record.py` (append a class)

**Interfaces:**
- Consumes: `TAG`, `redact`, `truncate`, `summary_marker`, `MAX_BODY`.
- Produces:
  - `opener_content(rec: dict, f: dict) -> str`
  - `event_content(rec: dict, ev: dict) -> str`
  - `should_resolve(f: dict) -> bool`
  - `outcome(f: dict) -> str` (one of `refuted`, `re-check: <result>`, `fixed`, `pushback`, `deferred`, `confirmed`, `unconfirmed`)
  - `summary_bodies(rec: dict, rows: list[dict], redacted: int, failures: int, details: str = "", limit: int = MAX_BODY) -> list[str]`, where each row is `{"id", "severity", "origin", "outcome", "new": bool, "thread": str | None, "note": str | None}`
  - `no_thread_details(rec: dict, findings: list[dict]) -> tuple[str, Counter]`
  - `markdown(rec: dict) -> tuple[str, Counter]`

- [ ] **Step 1: Write the failing tests**

Append to `AR/scripts/test_audit_record.py`, above the `if __name__` line:

```python
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
        self.assertTrue(ar.should_resolve(finding(status="rejected")))
        fixed = finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])
        self.assertFalse(ar.should_resolve(fixed))
        rechecked = finding(events=[ev("recheck", by="codex", result="resolved")])
        self.assertTrue(ar.should_resolve(rechecked))
        missed = finding(events=[ev("recheck", by="codex", result="missed")])
        self.assertFalse(ar.should_resolve(missed))

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
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: the 8 new tests FAIL with `AttributeError` (`opener_content`, `summary_bodies`, …).

- [ ] **Step 3: Implement**

Append to `AR/scripts/audit_record.py`:

```python
def _sha7(sha):
    return sha[:7]


def opener_content(rec, f):
    return (
        f"**[{TAG[f['origin']]}] [{f['severity']}] {f['category']}** — {f['title']}\n\n"
        f"{f['rationale']}\n\n"
        f"Round {rec['round']} · {rec['phase']} · reviewed at `{_sha7(rec['head_sha'])}`"
    )


def event_content(rec, ev):
    kind = ev["kind"]
    if kind == "verdict":
        head = f"verdict: {ev['verdict']}"
    elif kind == "counter":
        head = "counter"
    elif kind == "resolution":
        if ev["resolution"] == "fixed":
            head = f"fixed in `{_sha7(ev['sha'])}`" if ev.get("sha") else "fixed (not yet committed)"
        else:
            head = ev["resolution"]
    else:
        head = f"re-check: {ev['result']}"
    return (
        f"**[{TAG[ev['by']]}] {head}** — {ev['text']}\n\n"
        f"Round {rec['round']} · reviewed at `{_sha7(rec['head_sha'])}`"
    )


def should_resolve(f):
    """Refuted findings close at once. Others close only on an adversary re-check."""
    if f["status"] == "rejected":
        return True
    return any(e["kind"] == "recheck" and e.get("result") == "resolved" for e in f["events"])


def outcome(f):
    if f["status"] == "rejected":
        return "refuted"
    for e in reversed(f["events"]):
        if e["kind"] == "recheck":
            return f"re-check: {e['result']}"
        if e["kind"] == "resolution":
            return e["resolution"]
    return "confirmed" if f["status"] == "survivor" else "unconfirmed"


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def summary_bodies(rec, rows, redacted, failures, details="", limit=MAX_BODY):
    prev = rec.get("prev_head_sha")
    prev_txt = f" (previous `{_sha7(prev)}`)" if prev else ""
    title = f"**{rec['skill']} · {rec['phase']} · Round {rec['round']}"
    tail = f"** · adversary: {rec['adversary']} · reviewed `{_sha7(rec['head_sha'])}`{prev_txt}"
    counts = Counter(r["outcome"] for r in rows)
    parts = [f"{sum(1 for r in rows if r['new'])} new"] + [f"{n} {k}" for k, n in sorted(counts.items())]
    count_line = f"{len(rows)} findings: " + " · ".join(parts)
    table_head = "| id | severity | origin | this round | thread |\n|---|---|---|---|---|"
    lines = []
    for r in rows:
        link = f"[thread]({r['thread']})" if r["thread"] else f"no thread: {_cell(r['note'] or 'unknown')}"
        lines.append(f"| {_cell(r['id'])} | {_cell(r['severity'])} | {_cell(r['origin'])} | "
                     f"{_cell(r['outcome'])} | {link} |")
    footer = f"Redacted: {redacted} · Posting failures: {failures}"
    fixed = len(title) + len(tail) + len(count_line) + len(table_head) + len(footer) + 200
    budget = limit - fixed
    chunks = [[]]
    size = 0
    for ln in lines:
        if chunks[-1] and size + len(ln) + 1 > budget:
            chunks.append([])
            size = 0
        chunks[-1].append(ln)
        size += len(ln) + 1
    n = len(chunks)
    bodies = []
    for i, chunk in enumerate(chunks, 1):
        numbered = f" ({i}/{n})" if n > 1 else ""
        body = "\n".join([title + numbered + tail, count_line, "", table_head, *chunk, "", footer])
        mark = summary_marker(rec["run_id"], rec["round"], i)
        if i == n and details:
            room = limit - len(body) - len(mark) - 4
            if room > 200:
                body += "\n\n" + truncate(details, room)
        body, _ = redact(body)
        bodies.append(body + "\n" + mark)
    return bodies


def _quote(text):
    return "> " + text.replace("\n", "\n> ")


def no_thread_details(rec, findings):
    if not findings:
        return "", Counter()
    parts = ["<details><summary>Findings with no inline thread</summary>", ""]
    for f in findings:
        parts.append(f"**{f['id']}** · " + opener_content(rec, f))
        for e in f["events"]:
            parts.append(_quote(event_content(rec, e)))
        parts.append("")
    parts.append("</details>")
    return redact("\n".join(parts))


def markdown(rec):
    prev = rec.get("prev_head_sha")
    prev_txt = f" (previous `{_sha7(prev)}`)" if prev else ""
    lines = [
        f"## {rec['skill']} · {rec['phase']} · Round {rec['round']}", "",
        f"Adversary: {rec['adversary']} · reviewed `{_sha7(rec['head_sha'])}`{prev_txt}", "",
    ]
    for f in rec["findings"]:
        where = f" · `{f['path']}:{f['line']}`" if f.get("path") and f.get("line") else (
            f" · `{f['path']}`" if f.get("path") else "")
        lines += [f"### {f['id']} · {outcome(f)}{where}", "", opener_content(rec, f), ""]
        for e in f["events"]:
            lines += [_quote(event_content(rec, e)), ""]
    return redact("\n".join(lines))
```

- [ ] **Step 4: Run to verify all pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_audit_record -v`
Expected: 28 tests, all PASS.

- [ ] **Step 5: Negative control**

Temporarily make `should_resolve` return `True` whenever any `resolution` event says `fixed`. Run the tests. Expected: `test_resolution_rules` FAILS. Revert and rerun: all PASS.

- [ ] **Step 6: Commit**

```bash
git add AR/scripts/audit_record.py AR/scripts/test_audit_record.py
git commit -m "feat(adversarial-review): render audit threads, outcomes and round summaries (#135)"
```

### Task 4: `gh` stub, `pr-audit.py` skeleton, `local` mode and fallbacks

**Files:**
- Create: `AR/scripts/fixtures/gh_stub.py`
- Create: `AR/scripts/pr-audit.py`
- Test: `AR/scripts/test_pr_audit.py`

**Interfaces:**
- Consumes: `audit_record.validate`, `RecordError`, `markdown`.
- Produces:
  - CLI `pr-audit.py local --record FILE --out FILE`: appends `markdown(rec)` to `--out`, exit 0.
  - CLI `pr-audit.py post --pr N --record FILE [--repo O/R] [--fallback-out FILE]`: in this task only the invalid-record exit 2 and the gh-not-ready fallback to local work. Task 5 fills in posting.
  - Python: `class GhError(RuntimeError)` with `.status`, `gh(args: list[str], payload: dict | None = None) -> str`, `gh_ready() -> bool`, `load_record(path) -> dict` (exits 2), `write_local(rec, out) -> None`, `default_local_out() -> str`.
  - Test harness `Harness` in `test_pr_audit.py`, reused by Task 5 and Task 6.
- Stub state keys (JSON at `$GH_STUB_STATE`): `auth` (bool), `repo`, `comments`, `reviews`, `resolved`, `reject_inline` (list of `[path, line]`), `reject_file` (list of paths), `fail` (list of `comment|reply|review|resolve|read`), `next_id`. Calls are logged to `$GH_STUB_LOG` as `{"argv": [...], "input": <json or null>}`.

- [ ] **Step 1: Create the `gh` stub**

Create `AR/scripts/fixtures/gh_stub.py`:

```python
#!/usr/bin/env python3
"""Stateful stand-in for the `gh` CLI, used by the pr-audit tests.

State lives in $GH_STUB_STATE (JSON). Every call is appended to $GH_STUB_LOG as
{"argv": [...], "input": <parsed stdin JSON or null>}. It supports only the
calls pr-audit.py makes.
"""
import json
import os
import re
import sys

DEFAULT = {
    "auth": True, "repo": "octo/demo", "comments": [], "reviews": [], "resolved": [],
    "reject_inline": [], "reject_file": [], "fail": [], "next_id": 1000,
}


def load():
    path = os.environ.get("GH_STUB_STATE")
    state = json.loads(json.dumps(DEFAULT))
    if path and os.path.exists(path):
        with open(path) as fh:
            state.update(json.load(fh))
    return state


def save(state):
    path = os.environ.get("GH_STUB_STATE")
    if path:
        with open(path, "w") as fh:
            json.dump(state, fh)


def log(argv, payload):
    path = os.environ.get("GH_STUB_LOG")
    if path:
        with open(path, "a") as fh:
            fh.write(json.dumps({"argv": argv, "input": payload}) + "\n")


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def graphql(state, args):
    fields = dict(a.split("=", 1) for a in args if "=" in a)
    query = fields.get("query", "")
    if "resolveReviewThread" in query:
        if "resolve" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["resolved"].append(int(fields["id"].removeprefix("T_")))
        save(state)
        print(json.dumps({"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}))
        return
    nodes = [
        {"id": f"T_{c['id']}", "isResolved": c["id"] in state["resolved"],
         "comments": {"nodes": [{"databaseId": c["id"]}]}}
        for c in state["comments"] if c.get("in_reply_to_id") is None
    ]
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}}))


def main(argv):
    state = load()
    payload = json.loads(sys.stdin.read() or "null") if "--input" in argv else None
    log(argv, payload)
    if argv[:2] == ["auth", "status"]:
        sys.exit(0 if state["auth"] else 1)
    if argv[:2] == ["repo", "view"]:
        print(state["repo"])
        return
    if not argv or argv[0] != "api":
        die(f"gh stub: unsupported command {argv}")
    args = argv[1:]
    if args[0] == "graphql":
        graphql(state, args[1:])
        return
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    endpoint = next(a for a in args if a.startswith("repos/"))
    match = re.fullmatch(
        r"repos/[^/]+/[^/]+/pulls/(\d+)/(comments|reviews)(?:/(\d+)/replies)?",
        endpoint.split("?", 1)[0])
    if not match:
        die(f"gh stub: unsupported endpoint {endpoint}")
    pr, kind, parent = match.groups()
    if method == "GET":
        if "read" in state["fail"]:
            die("gh: Not Found (HTTP 404)")
        for item in state["comments" if kind == "comments" else "reviews"]:
            print(json.dumps({"id": item["id"], "body": item["body"], "html_url": item.get("html_url")}))
        return
    if kind == "reviews":
        if "review" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["next_id"] += 1
        state["reviews"].append({"id": state["next_id"], "body": payload["body"],
                                 "commit_id": payload.get("commit_id"), "event": payload.get("event")})
        save(state)
        print(json.dumps({"id": state["next_id"]}))
        return
    if parent:
        if "reply" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        new = {"body": payload["body"], "in_reply_to_id": int(parent)}
    else:
        if "comment" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        if payload.get("subject_type") == "file":
            if payload["path"] in state["reject_file"]:
                die("gh: Validation Failed (HTTP 422)")
        elif [payload["path"], payload.get("line")] in state["reject_inline"]:
            die("gh: Validation Failed (HTTP 422)")
        new = {k: payload.get(k) for k in ("body", "path", "line", "subject_type", "commit_id")}
        new["in_reply_to_id"] = None
    state["next_id"] += 1
    new["id"] = state["next_id"]
    new["html_url"] = f"https://github.com/{state['repo']}/pull/{pr}#discussion_r{new['id']}"
    state["comments"].append(new)
    save(state)
    print(json.dumps(new))


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 2: Write the failing tests**

Create `AR/scripts/test_pr_audit.py`:

```python
"""CLI tests for pr-audit.py against a stateful `gh` stub."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PR_AUDIT = HERE / "pr-audit.py"
STUB = HERE / "fixtures" / "gh_stub.py"
SHA1, SHA2, SHA3 = "1" * 40, "2" * 40, "3" * 40
FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


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


def record(findings, rnd=1, head=SHA1, prev=None, **over):
    r = {
        "schema": "audit-round/v1", "run_id": "ar-test-1", "skill": "deep-review",
        "phase": "phase2", "round": rnd, "adversary": "codex",
        "head_sha": head, "prev_head_sha": prev, "findings": findings,
    }
    r.update(over)
    return r


def ev(kind, by="claude", text="because", **kw):
    e = {"by": by, "kind": kind, "text": text}
    e.update(kw)
    return e


class Harness:
    def __init__(self, test, **state):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-audit-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        bindir = self.dir / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "{STUB}" "$@"\n')
        gh.chmod(0o755)
        self.state_path = self.dir / "state.json"
        self.log_path = self.dir / "log.jsonl"
        self.state_path.write_text(json.dumps(state))
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "GH_STUB_STATE": str(self.state_path), "GH_STUB_LOG": str(self.log_path),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.fallback = self.dir / "fallback.md"

    def write(self, rec, name="round.json"):
        path = self.dir / name
        path.write_text(json.dumps(rec) if isinstance(rec, dict) else rec)
        return path

    def run(self, *args):
        return subprocess.run([sys.executable, str(PR_AUDIT), *map(str, args)],
                              capture_output=True, text=True, env=self.env, cwd=self.dir)

    def post(self, rec, name="round.json"):
        return self.run("post", "--pr", "7", "--repo", "octo/demo",
                        "--record", self.write(rec, name), "--fallback-out", self.fallback)

    def calls(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def posted(self, kind):
        out = []
        for c in self.calls():
            argv = c["argv"]
            if "-X" not in argv:
                continue
            ep = next(a for a in argv if a.startswith("repos/"))
            if (kind == "thread" and ep.endswith("/comments")) or \
               (kind == "reply" and ep.endswith("/replies")) or \
               (kind == "review" and ep.endswith("/reviews")):
                out.append(c)
        return out

    def resolves(self):
        return [c for c in self.calls() if c["argv"][:2] == ["api", "graphql"]
                and any("resolveReviewThread" in a for a in c["argv"])]

    def state(self):
        return json.loads(self.state_path.read_text())


class InputTests(unittest.TestCase):
    def test_malformed_record_exits_2_and_makes_no_calls(self):
        h = Harness(self)
        res = h.run("post", "--pr", "7", "--record", h.write("{not json"))
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("invalid record", res.stderr)
        self.assertEqual(h.calls(), [])

    def test_short_head_sha_exits_2(self):
        h = Harness(self)
        res = h.post(record([finding()], head="abc1234"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("head_sha", res.stderr)
        self.assertEqual(h.calls(), [])


class LocalTests(unittest.TestCase):
    def test_local_appends_markdown_without_markers(self):
        h = Harness(self)
        out = h.dir / "branch.adversarial-review.md"
        out.write_text("# existing report\n")
        rec = record([finding(events=[ev("verdict", verdict="confirm", text="Reproduced it.")])])
        res = h.run("local", "--record", h.write(rec), "--out", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = out.read_text()
        self.assertTrue(text.startswith("# existing report\n"))
        self.assertIn("Retry loop never resets the backoff", text)
        self.assertIn("**[Claude] verdict: confirm** — Reproduced it.", text)
        self.assertNotIn("<!-- audit:v1", text)
        self.assertEqual(h.calls(), [])

    def test_post_without_auth_falls_back_to_local(self):
        h = Harness(self, auth=False)
        res = h.post(record([finding()]))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not logged in", res.stdout)
        self.assertIn("Retry loop never resets the backoff", h.fallback.read_text())
        self.assertEqual([c["argv"][:2] for c in h.calls()], [["auth", "status"]])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit -v`
Expected: 4 FAIL. The subprocess reports `can't open file '.../pr-audit.py'`, and the return codes are 2 but the `stderr` assertions fail.

- [ ] **Step 4: Implement the skeleton**

Create `AR/scripts/pr-audit.py` and make it executable (`chmod +x`):

```python
#!/usr/bin/env python3
"""pr-audit.py — save one review round's model exchange on a PR as an audit trail.

Usage:
  pr-audit.py post   --pr N --record ROUND.json [--repo OWNER/NAME] [--fallback-out FILE]
  pr-audit.py local  --record ROUND.json --out FILE
  pr-audit.py record --report-json REPORT.json --run-id ID --skill SKILL --phase PHASE
                     --round K --adversary ADV --head-sha SHA [--prev-head-sha SHA]
                     --out ROUND.json

Each finding gets one inline thread; each later event is a reply in it; each
round gets one COMMENT review with a summary table. Earlier threads are found by
a hidden marker, so no local state is kept. Without gh (or when logged out),
post writes the same content to the local markdown file instead.

Exit codes: 0 ok, 1 one or more posts failed, 2 usage error or invalid record.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_record as ar  # noqa: E402

LOCAL_SUFFIX = ".adversarial-review.md"


class GhError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def gh(args, payload=None):
    """Run gh and return stdout. Raise GhError with .status=422 on validation failures."""
    try:
        proc = subprocess.run(
            ["gh", *args], input=None if payload is None else json.dumps(payload),
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise GhError("gh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh timed out after 60s") from exc
    if proc.returncode != 0:
        err = proc.stderr.strip() or f"gh exited {proc.returncode}"
        raise GhError(err, 422 if "(HTTP 422)" in err else None)
    return proc.stdout


def gh_ready():
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True,
                              timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_record(path):
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        ar.validate(rec)
    except (OSError, json.JSONDecodeError, ar.RecordError) as exc:
        print(f"pr-audit: invalid record {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    return rec


def write_local(rec, out):
    text, counts = ar.markdown(rec)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write("\n" + text + "\n")
    return counts


def default_local_out():
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
    root = git("rev-parse", "--show-toplevel") or "."
    branch = (git("rev-parse", "--abbrev-ref", "HEAD") or "unknown-branch").replace("/", "-")
    return str(Path(root) / f"{branch}{LOCAL_SUFFIX}")


def cmd_local(args):
    rec = load_record(args.record)
    counts = write_local(rec, args.out)
    print(f"pr-audit: wrote round {rec['round']} to {args.out} "
          f"(redacted {sum(counts.values())})")
    return 0


def cmd_post(args):
    rec = load_record(args.record)
    if not gh_ready():
        out = args.fallback_out or default_local_out()
        print(f"pr-audit: gh is missing or not logged in; writing the audit trail to {out} instead.")
        write_local(rec, out)
        return 0
    return post_round(rec, args)


def post_round(rec, args):
    raise NotImplementedError("filled in by Task 5")


def build_parser():
    p = argparse.ArgumentParser(description="Save a review round's model exchange on a PR.")
    sub = p.add_subparsers(dest="cmd", required=True)
    post = sub.add_parser("post")
    post.add_argument("--pr", type=int, required=True)
    post.add_argument("--record", required=True)
    post.add_argument("--repo")
    post.add_argument("--fallback-out")
    local = sub.add_parser("local")
    local.add_argument("--record", required=True)
    local.add_argument("--out", required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "post":
        return cmd_post(args)
    return cmd_local(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
chmod +x AR/scripts/pr-audit.py AR/scripts/fixtures/gh_stub.py
git add AR/scripts/pr-audit.py AR/scripts/test_pr_audit.py AR/scripts/fixtures/gh_stub.py
git commit -m "feat(adversarial-review): add pr-audit.py local mode and a gh test stub (#135)"
```

### Task 5: Posting a round to the PR

**Files:**
- Modify: `AR/scripts/pr-audit.py` (replace `post_round`, add `GitHub`, `open_thread`, the GraphQL strings)
- Test: `AR/scripts/test_pr_audit.py` (append a class)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: `post_round(rec, args) -> int` (0 or 1); `class GitHub(repo: str, pr: int)` with `comments()`, `review_bodies()`, `new_thread(sha, path, line, body)`, `reply(comment_id, body)`, `review(sha, body)`, `threads() -> dict[int, tuple[str, bool]]`, `resolve(thread_id)`; `open_thread(hub, rec, f, body) -> tuple[dict | None, str | None]`.
- Output line on stdout: `pr-audit: PR #<n>: posted <p>, skipped <s> already on the PR, resolved <r>, failed <f>, redacted <x>`. Each failure goes to stderr as `pr-audit: FAILED <id> <what>: <error>`.

- [ ] **Step 1: Write the failing tests**

Append to `AR/scripts/test_pr_audit.py`, above the `if __name__` line:

```python
class PostTests(unittest.TestCase):
    def test_first_round_opens_threads_and_posts_summary(self):
        h = Harness(self)
        rec = record([finding(events=[ev("verdict", verdict="confirm")]),
                      finding("X-002", path=None, title="No location")])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        threads = h.posted("thread")
        self.assertEqual(len(threads), 1)
        body = threads[0]["input"]
        self.assertEqual(body["commit_id"], SHA1)
        self.assertEqual((body["path"], body["line"], body["side"]), ("src/a.py", 41, "RIGHT"))
        self.assertTrue(body["body"].endswith("<!-- audit:v1 run=ar-test-1 finding=X-001 event=1.0 -->"))
        self.assertEqual(len(h.posted("reply")), 1)
        reviews = h.posted("review")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["input"]["event"], "COMMENT")
        self.assertEqual(reviews[0]["input"]["commit_id"], SHA1)
        summary = reviews[0]["input"]["body"]
        self.assertIn("| X-002 | important | codex | confirmed | no thread: no path |", summary)
        self.assertIn("Findings with no inline thread", summary)
        self.assertIn("posted 3,", res.stdout)

    def test_second_round_replies_to_existing_thread(self):
        h = Harness(self)
        self.assertEqual(h.post(record([finding()])).returncode, 0)
        second = record([finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])],
                        rnd=2, head=SHA2, prev=SHA1)
        res = h.post(second, "round2.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.posted("thread")), 1)
        replies = h.posted("reply")
        self.assertEqual(len(replies), 1)
        self.assertIn("/comments/1001/replies", " ".join(replies[0]["argv"]))
        self.assertIn("fixed in `2222222`", replies[0]["input"]["body"])
        self.assertEqual(h.resolves(), [])

    def test_refuted_is_resolved_in_same_run(self):
        h = Harness(self)
        rec = record([finding(status="rejected", events=[ev("verdict", verdict="refute")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.resolves()), 1)
        self.assertEqual(h.state()["resolved"], [1001])
        self.assertIn("resolved 1,", res.stdout)

    def test_fixed_stays_open_until_recheck(self):
        h = Harness(self)
        h.post(record([finding()]))
        h.post(record([finding(events=[ev("resolution", resolution="fixed", sha=SHA2)])],
                      rnd=2, head=SHA2), "r2.json")
        self.assertEqual(h.resolves(), [])
        h.post(record([finding(events=[ev("recheck", by="codex", result="resolved")])],
                      rnd=3, head=SHA3), "r3.json")
        self.assertEqual(len(h.resolves()), 1)

    def test_422_falls_back_to_file_then_summary(self):
        h = Harness(self, reject_inline=[["src/a.py", 41], ["src/b.py", 9]], reject_file=["src/b.py"])
        rec = record([finding(), finding("X-002", path="src/b.py", line=9)])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        file_level = [c["input"] for c in h.posted("thread") if c["input"].get("subject_type") == "file"]
        self.assertEqual([c["path"] for c in file_level], ["src/a.py", "src/b.py"])
        comments = h.state()["comments"]
        self.assertEqual([c["path"] for c in comments], ["src/a.py"])
        summary = h.posted("review")[0]["input"]["body"]
        self.assertIn("| X-002 | important | codex | confirmed | no thread: GitHub rejected", summary)

    def test_rerun_posts_nothing(self):
        h = Harness(self)
        rec = record([finding(status="rejected", events=[ev("verdict", verdict="refute")])])
        h.post(rec)
        before = len(h.calls())
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        new = h.calls()[before:]
        self.assertEqual([c for c in new if "-X" in c["argv"]], [])
        self.assertIn("posted 0,", res.stdout)
        self.assertIn("skipped 3 already on the PR", res.stdout)

    def test_partial_rerun_posts_only_missing(self):
        h = Harness(self, fail=["reply"])
        rec = record([finding(events=[ev("verdict", verdict="confirm"), ev("counter", by="codex")])])
        first = h.post(rec)
        self.assertEqual(first.returncode, 1)
        state = h.state()
        state["fail"] = []
        h.state_path.write_text(json.dumps(state))
        second = h.post(rec)
        self.assertEqual(second.returncode, 0, second.stderr)
        bodies = [c["body"] for c in h.state()["comments"] if c["in_reply_to_id"]]
        self.assertEqual(len(bodies), 2)
        self.assertEqual(len(h.posted("thread")), 1)

    def test_partial_failure_exits_1_and_names_the_finding(self):
        h = Harness(self, fail=["reply"])
        rec = record([finding(events=[ev("verdict", verdict="confirm")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAILED X-001 reply 1.1", res.stderr)
        self.assertIn("failed 1,", res.stdout)
        self.assertIn("Posting failures: 1", h.posted("review")[0]["input"]["body"])

    def test_secret_is_redacted_everywhere(self):
        h = Harness(self)
        rec = record([finding(rationale=f"leaked {FAKE_GH}",
                              events=[ev("verdict", verdict="confirm", text=f"saw {FAKE_GH}")])])
        res = h.post(rec)
        self.assertEqual(res.returncode, 0, res.stderr)
        for c in h.calls():
            self.assertNotIn(FAKE_GH, json.dumps(c))
        self.assertIn("Redacted: 2", h.posted("review")[0]["input"]["body"])

    def test_oversize_rationale_is_truncated(self):
        h = Harness(self)
        res = h.post(record([finding(rationale="x" * 70000)]))
        self.assertEqual(res.returncode, 0, res.stderr)
        body = h.posted("thread")[0]["input"]["body"]
        self.assertLessEqual(len(body), 60000)
        self.assertIn("truncated", body)
        self.assertTrue(body.endswith("event=1.0 -->"))

    def test_other_run_ids_open_new_threads(self):
        h = Harness(self)
        h.post(record([finding()]))
        h.post(record([finding()], run_id="ar-test-2"), "other.json")
        self.assertEqual(len(h.posted("thread")), 2)

    def test_unknown_pr_exits_1_cleanly(self):
        h = Harness(self, fail=["read"])
        res = h.post(record([finding()]))
        self.assertEqual(res.returncode, 1)
        self.assertIn("could not read PR #7", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit -v`
Expected: the 12 new tests FAIL with `NotImplementedError: filled in by Task 5` in stderr.

- [ ] **Step 3: Implement posting**

In `AR/scripts/pr-audit.py`, replace the `post_round` stub with the following, placed after `write_local`:

```python
THREADS_QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first: 1) { nodes { databaseId } } }
      }
    }
  }
}"""
RESOLVE_MUTATION = """
mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"""


def json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class GitHub:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr
        self.base = f"repos/{repo}/pulls/{pr}"

    def comments(self):
        return json_lines(gh(["api", "--paginate", f"{self.base}/comments?per_page=100",
                              "--jq", ".[] | {id, body, html_url}"]))

    def review_bodies(self):
        return [r.get("body") or "" for r in json_lines(gh(
            ["api", "--paginate", f"{self.base}/reviews?per_page=100", "--jq", ".[] | {id, body}"]))]

    def new_thread(self, sha, path, line, body):
        payload = {"body": body, "commit_id": sha, "path": path}
        if line is None:
            payload["subject_type"] = "file"
        else:
            payload.update(line=line, side="RIGHT")
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/comments", "--input", "-"], payload))

    def reply(self, comment_id, body):
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/comments/{comment_id}/replies",
                              "--input", "-"], {"body": body}))

    def review(self, sha, body):
        return json.loads(gh(["api", "-X", "POST", f"{self.base}/reviews", "--input", "-"],
                             {"commit_id": sha, "body": body, "event": "COMMENT"}))

    def threads(self):
        """Map each thread's first comment id to (thread node id, isResolved)."""
        owner, name = self.repo.split("/", 1)
        out, after = {}, None
        while True:
            args = ["api", "graphql", "-f", f"query={THREADS_QUERY}", "-f", f"owner={owner}",
                    "-f", f"name={name}", "-F", f"pr={self.pr}"]
            if after:
                args += ["-f", f"after={after}"]
            conn = json.loads(gh(args))["data"]["repository"]["pullRequest"]["reviewThreads"]
            for node in conn["nodes"]:
                first = node["comments"]["nodes"]
                if first:
                    out[first[0]["databaseId"]] = (node["id"], node["isResolved"])
            if not conn["pageInfo"]["hasNextPage"]:
                return out
            after = conn["pageInfo"]["endCursor"]

    def resolve(self, thread_id):
        gh(["api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-f", f"id={thread_id}"])


def open_thread(hub, rec, f, body):
    """Open a thread: inline, else file-level on a 422, else none. Returns (comment, note)."""
    path, line = f.get("path"), f.get("line")
    if not path:
        return None, "no path"
    if line is not None:
        try:
            return hub.new_thread(rec["head_sha"], path, line, body), None
        except GhError as exc:
            if exc.status != 422:
                raise
    try:
        return hub.new_thread(rec["head_sha"], path, None, body), None
    except GhError as exc:
        if exc.status != 422:
            raise
        return None, "GitHub rejected the inline and file comment (422)"


def post_round(rec, args):
    try:
        repo = args.repo or gh(["repo", "view", "--json", "nameWithOwner",
                                "-q", ".nameWithOwner"]).strip()
        hub = GitHub(repo, args.pr)
        existing = hub.comments()
        review_text = "\n".join(hub.review_bodies())
    except GhError as exc:
        print(f"pr-audit: could not read PR #{args.pr}: {exc}", file=sys.stderr)
        return 1

    posted_markers, openers = set(), {}
    for c in existing:
        m = ar.parse_marker(c.get("body"))
        if m:
            posted_markers.add(m["marker"])
            if m["run"] == rec["run_id"] and m["index"] == 0:
                openers.setdefault(m["finding"], c)

    n_posted = n_skipped = n_resolved = 0
    failures, rows, no_thread = [], [], []
    redacted = Counter()
    threads = None
    for f in rec["findings"]:
        fid = f["id"]
        opener = openers.get(fid)
        is_new, note = opener is None, None
        if opener is None:
            mark = ar.marker(rec["run_id"], fid, rec["round"], 0)
            body, red = ar.finalize(ar.opener_content(rec, f), mark)
            redacted += red
            try:
                opener, note = open_thread(hub, rec, f, body)
                n_posted += opener is not None
            except GhError as exc:
                failures.append((fid, "open thread", str(exc)))
                note = "posting failed"
        elif ar.parse_marker(opener["body"])["round"] == rec["round"]:
            n_skipped += 1

        if opener is None:
            no_thread.append(f)
        else:
            for idx, event in enumerate(f["events"], start=1):
                mark = ar.marker(rec["run_id"], fid, rec["round"], idx)
                if mark in posted_markers:
                    n_skipped += 1
                    continue
                body, red = ar.finalize(ar.event_content(rec, event), mark)
                redacted += red
                try:
                    hub.reply(opener["id"], body)
                    n_posted += 1
                except GhError as exc:
                    failures.append((fid, f"reply {rec['round']}.{idx}", str(exc)))
            if ar.should_resolve(f):
                try:
                    if threads is None:
                        threads = hub.threads()
                    thread_id, done = threads.get(opener["id"], (None, True))
                    if thread_id and not done:
                        hub.resolve(thread_id)
                        n_resolved += 1
                except GhError as exc:
                    failures.append((fid, "resolve thread", str(exc)))
        rows.append({"id": fid, "severity": f["severity"], "origin": f["origin"],
                     "outcome": ar.outcome(f), "new": is_new,
                     "thread": opener.get("html_url") if opener else None, "note": note})

    details, red = ar.no_thread_details(rec, no_thread)
    redacted += red
    total_redacted = sum(redacted.values())
    for i, body in enumerate(ar.summary_bodies(rec, rows, total_redacted, len(failures), details), 1):
        if ar.summary_marker(rec["run_id"], rec["round"], i) in review_text:
            n_skipped += 1
            continue
        try:
            hub.review(rec["head_sha"], body)
            n_posted += 1
        except GhError as exc:
            failures.append(("summary", f"part {i}", str(exc)))

    print(f"pr-audit: PR #{args.pr}: posted {n_posted}, skipped {n_skipped} already on the PR, "
          f"resolved {n_resolved}, failed {len(failures)}, redacted {total_redacted}")
    for fid, what, err in failures:
        print(f"pr-audit: FAILED {fid} {what}: {err}", file=sys.stderr)
    return 1 if failures else 0
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit test_audit_record -v`
Expected: 44 tests, all PASS.

- [ ] **Step 5: Negative controls**

Run the suite after each temporary change, confirm the named test goes red, then revert:
1. In `post_round`, replace `if mark in posted_markers:` with `if False:`. Expected: `test_rerun_posts_nothing` FAILS.
2. In `open_thread`, change `if exc.status != 422:` (the first one) to `if True:`. Expected: `test_422_falls_back_to_file_then_summary` FAILS.
3. Remove the `m["run"] == rec["run_id"] and` condition. Expected: `test_other_run_ids_open_new_threads` FAILS.
4. Change `return 1 if failures else 0` to `return 0`. Expected: `test_partial_failure_exits_1_and_names_the_finding` FAILS.

After reverting all four, rerun: 44 PASS.

- [ ] **Step 6: Commit**

```bash
git add AR/scripts/pr-audit.py AR/scripts/test_pr_audit.py
git commit -m "feat(adversarial-review): post each round's model exchange to the PR (#135)"
```

### Task 6: Build a round record from adversarial-review's report

**Files:**
- Modify: `AR/scripts/synthesize.py:285-295` and `:317-327` (record `verdict_reason`)
- Modify: `AR/scripts/pr-audit.py` (add `cmd_record` and its parser)
- Test: `AR/scripts/test_pr_audit.py` (append a class)

**Interfaces:**
- Consumes: `report.json` findings with `id, origin, path, line, severity, category, title, rationale, status, claude_verdict, gemini_verdict, kill_reason`, plus the new `verdict_reason`.
- Produces: CLI `pr-audit.py record --report-json F --run-id ID --skill SKILL --phase PHASE --round K --adversary ADV --head-sha SHA [--prev-head-sha SHA] --out F`. It writes a valid `audit-round/v1` record and exits 2 if the result does not validate. The judge of a Claude finding is the adversary. The judge of any other finding is Claude. With `--adversary claude-only`, no verdict events are written.

- [ ] **Step 1: Write the failing tests**

Append to `AR/scripts/test_pr_audit.py`, above the `if __name__` line:

```python
REPORT = {"summary": {}, "findings": [
    {"id": "C-001", "origin": "claude", "path": "src/a.py", "line": 41, "severity": "important",
     "category": "bug", "title": "Off by one", "rationale": "Loop skips the last item.",
     "status": "survivor", "gemini_verdict": "confirm", "claude_verdict": None,
     "verdict_reason": "Reproduced with a 3-item list.", "kill_reason": None},
    {"id": "G-001", "origin": "gemini", "path": "", "line": "12", "severity": "minor",
     "category": "convention", "title": "Name", "rationale": None, "status": "rejected",
     "gemini_verdict": None, "claude_verdict": "refute", "verdict_reason": None,
     "kill_reason": "The name matches the module convention."},
    {"id": "C-002", "origin": "claude", "path": "src/c.py", "line": None, "severity": "minor",
     "category": None, "title": "Unjudged", "rationale": "x", "status": "unconfirmed",
     "gemini_verdict": None, "claude_verdict": None},
]}


class RecordTests(unittest.TestCase):
    def build(self, h, adversary="gemini"):
        report = h.write(json.dumps(REPORT), "report.json")
        out = h.dir / "round-1.json"
        res = h.run("record", "--report-json", report, "--run-id", "ar-20260924-1",
                    "--skill", "adversarial-review", "--phase", "review", "--round", "1",
                    "--adversary", adversary, "--head-sha", SHA1, "--out", out)
        return res, out

    def test_record_maps_verdicts_to_events(self):
        h = Harness(self)
        res, out = self.build(h)
        self.assertEqual(res.returncode, 0, res.stderr)
        rec = json.loads(out.read_text())
        by_id = {f["id"]: f for f in rec["findings"]}
        self.assertEqual(by_id["C-001"]["events"], [
            {"by": "gemini", "kind": "verdict", "verdict": "confirm",
             "text": "Reproduced with a 3-item list."}])
        self.assertEqual(by_id["G-001"]["events"][0]["by"], "claude")
        self.assertEqual(by_id["G-001"]["events"][0]["text"], "The name matches the module convention.")
        self.assertEqual((by_id["G-001"]["path"], by_id["G-001"]["line"]), (None, 12))
        self.assertEqual(by_id["G-001"]["rationale"], "")
        self.assertEqual(by_id["C-002"]["events"], [])
        self.assertEqual(by_id["C-002"]["category"], "other")

    def test_claude_only_writes_no_verdicts(self):
        h = Harness(self)
        res, out = self.build(h, adversary="claude-only")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(all(f["events"] == [] for f in json.loads(out.read_text())["findings"]))

    def test_record_output_posts_cleanly(self):
        # C-001 opens an inline thread. C-002 has a path but no line, so it opens a
        # file-level thread. G-001 has no path, so it appears in the summary only.
        h = Harness(self)
        _, out = self.build(h)
        res = h.run("post", "--pr", "7", "--repo", "octo/demo", "--record", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(h.posted("thread")), 2)
        self.assertEqual(len(h.posted("review")), 1)
```

- [ ] **Step 2: Add a synthesize check to `run-tests.sh`**

In `AR/scripts/run-tests.sh`, add this block just before the `# FINAL SUMMARY` banner:

```bash
# ====================================================================
# synthesize.py — verdict_reason recorded for every judged finding
# ====================================================================
section "synthesize.py — verdict_reason recorded for every judged finding"

VR_JSON="$TMP_DIR/vr-report.json"
run_capture VR_OUT VR_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --gemini-findings "$FIXTURES_DIR/r1_gemini_findings.json" \
  --gemini-verdicts "$FIXTURES_DIR/r2_gemini_verdicts.json" \
  --claude-verdicts "$FIXTURES_DIR/r2_claude_verdicts.json" \
  --md "$TMP_DIR/vr-report.md" \
  --json "$VR_JSON"
assert_exit_code "synthesize exits 0 for verdict_reason fixture" "0" "$VR_EXIT"
VR_CHECK="$(python3 - "$VR_JSON" <<'PYEOF'
import json, sys
fs = json.load(open(sys.argv[1]))["findings"]
judged = [f for f in fs if (f.get("gemini_verdict") or f.get("claude_verdict"))]
bad = [f["id"] for f in judged if not isinstance(f.get("verdict_reason"), str)]
print("ok" if judged and not bad else f"bad {bad} judged={len(judged)}")
PYEOF
)"
assert_eq "every judged finding carries verdict_reason" "ok" "$VR_CHECK"
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit -v` then `bash run-tests.sh | tail -5`.
Expected: the 3 `RecordTests` FAIL (argparse: `invalid choice: 'record'`), and run-tests.sh reports `FAIL: every judged finding carries verdict_reason`.

- [ ] **Step 4: Record `verdict_reason` in `synthesize.py`**

In the Claude-findings loop (around line 285), after each branch that reads `g_verdict`, set the reason. The loop body becomes:

```python
        if g_verdict is None:
            f["gemini_verdict"] = None
            f["status"] = "unconfirmed"
        elif g_verdict.get("gemini_verdict") == "confirm":
            f["gemini_verdict"] = "confirm"
            f["status"] = "survivor"
        elif g_verdict.get("gemini_verdict") == "refute":
            f["gemini_verdict"] = "refute"
            f["status"] = "rejected"
            f["killed_by"] = "gemini"
            f["kill_reason"] = g_verdict.get("reason", "")
        else:
            f["gemini_verdict"] = g_verdict.get("gemini_verdict")
            f["status"] = "unconfirmed"
        if g_verdict is not None:
            f["verdict_reason"] = g_verdict.get("reason", "") or ""
```

Make the same change in the Gemini-findings loop (around line 317), using `c_verdict`:

```python
        if c_verdict is not None:
            f["verdict_reason"] = c_verdict.get("reason", "") or ""
```

- [ ] **Step 5: Add `cmd_record` to `pr-audit.py`**

Add this function above `build_parser`:

```python
def _as_line(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value) or None
    return None


def cmd_record(args):
    try:
        with open(args.report_json, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"pr-audit: cannot read {args.report_json}: {exc}", file=sys.stderr)
        return 2
    findings = []
    for f in report.get("findings", []):
        origin = f.get("origin")
        if origin == "claude":
            judge, verdict = args.adversary, f.get("gemini_verdict")
        else:
            judge, verdict = "claude", f.get("claude_verdict")
        events = []
        if args.adversary != "claude-only" and verdict in ("confirm", "refute"):
            events.append({"by": judge, "kind": "verdict", "verdict": verdict,
                           "text": f.get("verdict_reason") or f.get("kill_reason") or ""})
        findings.append({
            "id": f.get("id"), "origin": origin, "path": f.get("path") or None,
            "line": _as_line(f.get("line")), "severity": f.get("severity"),
            "category": f.get("category") or "other", "title": f.get("title") or "(no title)",
            "rationale": f.get("rationale") or "", "status": f.get("status"), "events": events,
        })
    rec = {"schema": ar.SCHEMA, "run_id": args.run_id, "skill": args.skill, "phase": args.phase,
           "round": args.round, "adversary": args.adversary, "head_sha": args.head_sha,
           "prev_head_sha": args.prev_head_sha, "findings": findings}
    try:
        ar.validate(rec)
    except ar.RecordError as exc:
        print(f"pr-audit: report does not make a valid record: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    print(f"pr-audit: wrote {args.out} ({len(findings)} findings)")
    return 0
```

In `build_parser`, before `return p`, add:

```python
    rec = sub.add_parser("record")
    rec.add_argument("--report-json", required=True)
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--skill", required=True, choices=sorted(ar.SKILLS))
    rec.add_argument("--phase", required=True)
    rec.add_argument("--round", type=int, required=True)
    rec.add_argument("--adversary", required=True, choices=sorted(ar.ADVERSARIES))
    rec.add_argument("--head-sha", required=True)
    rec.add_argument("--prev-head-sha")
    rec.add_argument("--out", required=True)
```

In `main`, dispatch it:

```python
    if args.cmd == "record":
        return cmd_record(args)
```

- [ ] **Step 6: Run to verify they pass**

Run: `cd AR/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_pr_audit test_audit_record -v` then `bash run-tests.sh | tail -4`.
Expected: 47 unittest PASS. run-tests.sh: `All tests passed.` with 2 more passes than before (140).

- [ ] **Step 7: Commit**

```bash
git add AR/scripts/synthesize.py AR/scripts/pr-audit.py AR/scripts/test_pr_audit.py AR/scripts/run-tests.sh
git commit -m "feat(adversarial-review): build audit round records from report.json (#135)"
```

### Task 7: Route `sink.sh` PR mode through `pr-audit.py`

**Files:**
- Modify: `AR/scripts/sink.sh` (header, argument parsing, validation, delete `find_pr_review_cli` at lines 132-163, replace `deliver_pr` at lines 184-292, dispatch at 294-298)
- Modify: `AR/scripts/run-tests.sh` (add two sections before `# FINAL SUMMARY`)
- Create: `AR/scripts/fixtures/audit_round_min.json`

**Interfaces:**
- Consumes: `pr-audit.py post` and `local` (Tasks 4-5).
- Produces: `sink.sh --report-md F --report-json F --mode pr|local [--pr N] [--branch B] [--record ROUND.json] [--no-post]`. Exit 0 ok, 1 error, 2 usage, 4 report delivered but audit trail incomplete. In pr mode, `--record` is required unless `--no-post` is given.

- [ ] **Step 1: Create the record fixture**

Create `AR/scripts/fixtures/audit_round_min.json`:

```json
{
  "schema": "audit-round/v1",
  "run_id": "ar-sink-test",
  "skill": "adversarial-review",
  "phase": "review",
  "round": 1,
  "adversary": "gemini",
  "head_sha": "1111111111111111111111111111111111111111",
  "prev_head_sha": null,
  "findings": [
    {
      "id": "C-001", "origin": "claude", "path": "src/a.py", "line": 41,
      "severity": "important", "category": "bug", "title": "Off by one",
      "rationale": "Loop skips the last item.", "status": "survivor",
      "events": [{"by": "gemini", "kind": "verdict", "verdict": "confirm", "text": "Reproduced."}]
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

In `AR/scripts/run-tests.sh`, add before the `# FINAL SUMMARY` banner:

```bash
# ====================================================================
# pr-audit.py + audit_record.py — unit and CLI tests
# ====================================================================
section "pr-audit.py + audit_record.py — unit and CLI tests"

run_capture UT_OUT UT_EXIT env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s "$SCRIPT_DIR" -p 'test_*.py'
assert_exit_code "python unittest suite passes" "0" "$UT_EXIT"
[[ "$UT_EXIT" == "0" ]] || echo "$UT_OUT" | tail -30

# ====================================================================
# sink.sh — PR mode posts the audit trail through pr-audit.py
# ====================================================================
section "sink.sh — PR mode posts the audit trail through pr-audit.py"

SINK_STUB_DIR="$TMP_DIR/sink-stub"
SINK_REPO="$TMP_DIR/sink-repo"
SINK_STATE="$TMP_DIR/sink-state.json"
SINK_LOG="$TMP_DIR/sink-log.jsonl"
mkdir -p "$SINK_STUB_DIR"
printf '#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' "$FIXTURES_DIR/gh_stub.py" >"$SINK_STUB_DIR/gh"
chmod +x "$SINK_STUB_DIR/gh"
git init -q "$SINK_REPO"
printf '# report\n' >"$TMP_DIR/sink-report.md"
printf '{"findings":[]}\n' >"$TMP_DIR/sink-report.json"
SINK_RECORD="$FIXTURES_DIR/audit_round_min.json"

# Usage: sink_run OUT_VAR EXIT_VAR STATE_JSON sink-args...
# Runs sink.sh from inside a throwaway git repo so gitignore and local files land there.
sink_run() {
  local out_var="$1" exit_var="$2" state="$3"
  shift 3
  printf '%s' "$state" >"$SINK_STATE"
  rm -f "$SINK_LOG"
  run_capture "$out_var" "$exit_var" bash -c 'cd "$1" && shift && exec "$@"' _ "$SINK_REPO" \
    env PATH="$SINK_STUB_DIR:$PATH" GH_STUB_STATE="$SINK_STATE" GH_STUB_LOG="$SINK_LOG" \
    PYTHONDONTWRITEBYTECODE=1 bash "$SCRIPT_DIR/sink.sh" \
    --report-md "$TMP_DIR/sink-report.md" --report-json "$TMP_DIR/sink-report.json" "$@"
}

sink_run S_OUT S_EXIT '{}' --mode pr --pr 7 --branch feature/x --record "$SINK_RECORD"
assert_exit_code "sink pr mode posts and exits 0" "0" "$S_EXIT"
assert_contains "sink pr mode prints pr-audit counts" "pr-audit: PR #7: posted 3" "$S_OUT"
assert_contains "sink pr mode posted a summary review" "/reviews" "$(cat "$SINK_LOG" 2>/dev/null)"

sink_run S_OUT S_EXIT '{"fail":["review"]}' --mode pr --pr 7 --branch feature/x --record "$SINK_RECORD"
assert_exit_code "sink pr mode with a failed post exits 4" "4" "$S_EXIT"
assert_contains "sink says the audit trail is incomplete" "incomplete" "$S_OUT"
if echo "$S_OUT" | grep -qF "PR review comments posted"; then
  fail "sink never prints the old unconditional success line"
else
  pass "sink never prints the old unconditional success line"
fi

sink_run S_OUT S_EXIT '{}' --mode pr --pr 7 --branch feature/x --no-post
assert_exit_code "sink --no-post exits 0" "0" "$S_EXIT"
if [[ -s "$SINK_LOG" ]]; then
  fail "sink --no-post makes no gh calls" "log: $(cat "$SINK_LOG")"
else
  pass "sink --no-post makes no gh calls"
fi
assert_eq "sink --no-post writes the local report" "yes" \
  "$([[ -f "$SINK_REPO/feature-x.adversarial-review.md" ]] && echo yes || echo no)"

sink_run S_OUT S_EXIT '{}' --mode pr --pr 7 --branch feature/x
assert_exit_code "sink pr mode without --record is a usage error" "2" "$S_EXIT"

sink_run S_OUT S_EXIT '{}' --mode local --branch feature/y --record "$SINK_RECORD"
assert_exit_code "sink local mode with a record exits 0" "0" "$S_EXIT"
assert_contains "sink local mode appends the exchange" "**[Gemini] verdict: confirm**" \
  "$(cat "$SINK_REPO/feature-y.adversarial-review.md")"

assert_eq "sink.sh no longer references pr-review-cli" "0" \
  "$(grep -c 'pr-review-cli' "$SCRIPT_DIR/sink.sh" || true)"
```

- [ ] **Step 3: Run to verify the sink tests fail**

Run: `cd AR/scripts && bash run-tests.sh | tail -20`
Expected: the unittest section PASSES. The sink section FAILS: `sink.sh` rejects `--record` with `Error: unknown argument: --record` (exit 2), and the `pr-review-cli` count is not 0.

- [ ] **Step 4: Rewrite `sink.sh`**

Replace lines 1-46 (header through `usage`) with:

```bash
#!/usr/bin/env bash
# sink.sh — deliver the synthesized review report, and save the model exchange
# on the PR (pr mode) or in the local report file (local mode).
# Usage: sink.sh --report-md <md> --report-json <json> --mode <pr|local>
#                [--pr <n>] [--branch <name>] [--record <round.json>] [--no-post] [--help]
# Exit codes: 0=ok, 1=error, 2=usage, 4=report delivered but audit trail incomplete

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_MD=""
REPORT_JSON=""
MODE=""
PR_NUMBER=""
BRANCH=""
RECORD=""
NO_POST="false"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --report-md <md> --report-json <json> --mode <pr|local>
         [--pr <n>] [--branch <name>] [--record <round.json>] [--no-post] [--help]

Deliver the synthesized adversarial review report. In pr mode, also save every
model exchange on the PR through pr-audit.py: one inline thread per finding,
verdicts as replies, and one summary review.

Options:
  --report-md <file>    Path to the markdown report (required)
  --report-json <file>  Path to the structured JSON report (required)
  --mode <pr|local>     Delivery mode (required)
  --pr <number>         PR number (required in pr mode)
  --branch <name>       Branch name, used for the local output filename
  --record <file>       Round record (audit-round/v1). Required in pr mode unless --no-post.
  --no-post             Do not post to the PR; deliver as in local mode
  --help                Show this help and exit

pr mode behavior:
  Prints the report, then runs pr-audit.py post. If gh is missing or not logged
  in, pr-audit.py writes the exchange to <branch>.adversarial-review.md instead.

local mode behavior:
  Prints the report AND writes <branch>.adversarial-review.md in the repo root,
  then appends the exchange from --record if given. Ensures
  *.adversarial-review.md is gitignored.

Exit codes:
  0  Success
  1  Error
  2  Usage error
  4  Report delivered, but some audit comments failed to post (listed on stderr)
EOF
}
```

In the argument `case`, add before `--help)`:

```bash
    --record)
      [[ $# -lt 2 ]] && { echo "Error: --record requires an argument" >&2; exit 2; }
      RECORD="$2"; shift 2 ;;
    --no-post) NO_POST="true"; shift ;;
```

After the existing `if [[ "$MODE" == "pr" && -z "$PR_NUMBER" ]]` block, add:

```bash
if [[ "$MODE" == "pr" && "$NO_POST" == "false" && -z "$RECORD" ]]; then
  echo "Error: --record <round.json> is required in pr mode (or pass --no-post)" >&2
  usage >&2
  exit 2
fi
if [[ -n "$RECORD" && ! -f "$RECORD" ]]; then
  echo "Error: record not found: $RECORD" >&2
  exit 1
fi
```

Delete `find_pr_review_cli` (the comment line `# Search for pr-review-cli.sh in known locations` and the function below it).

Replace `deliver_local` and `deliver_pr` with:

```bash
# Local output file for a branch: <repo_root>/<branch with / as ->.adversarial-review.md
local_out_file() {
  local branch="$1"
  echo "$(get_repo_root)/${branch//\//-}.adversarial-review.md"
}

# ---- mode: local ----
deliver_local() {
  local repo_root output_branch
  repo_root="$(get_repo_root)"
  output_branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown-branch")}"

  echo ""
  echo "====== Adversarial PR Review Report ======"
  cat "$REPORT_MD"
  echo "=========================================="

  write_local_artifact "$repo_root" "$output_branch" "$REPORT_MD"
  if [[ -n "$RECORD" ]]; then
    python3 "$SCRIPT_DIR/pr-audit.py" local --record "$RECORD" --out "$(local_out_file "$output_branch")"
  fi
}

# ---- mode: pr ----
deliver_pr() {
  local repo_root output_branch code=0
  repo_root="$(get_repo_root)"
  output_branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "pr-$PR_NUMBER")}"

  echo ""
  echo "====== Adversarial PR Review Report (PR #$PR_NUMBER) ======"
  cat "$REPORT_MD"
  echo "============================================================"

  # pr-audit.py falls back to this file when gh is unavailable, so keep it ignored.
  ensure_gitignored "$repo_root"
  python3 "$SCRIPT_DIR/pr-audit.py" post --pr "$PR_NUMBER" --record "$RECORD" \
    --fallback-out "$(local_out_file "$output_branch")" || code=$?
  case "$code" in
    0) return 0 ;;
    1)
      echo "WARNING: the audit trail for PR #$PR_NUMBER is incomplete — some comments failed to post (listed above)." >&2
      return 4 ;;
    *)
      echo "Error: pr-audit.py could not run (exit $code)." >&2
      return 1 ;;
  esac
}
```

Replace the dispatch at the end with:

```bash
# ---- dispatch ----
case "$MODE" in
  local) deliver_local ;;
  pr)
    if [[ "$NO_POST" == "true" ]]; then
      deliver_local
    else
      deliver_pr
    fi
    ;;
esac
```

- [ ] **Step 5: Run to verify all pass**

Run: `cd AR/scripts && bash run-tests.sh | tail -6`
Expected: `All tests passed.`, with 14 more passes than after Task 6 (154 total).

- [ ] **Step 6: Negative control**

In `deliver_pr`, change `return 4 ;;` to `return 0 ;;`. Run `bash run-tests.sh | grep -E 'FAIL|Results'`. Expected: `FAIL: sink pr mode with a failed post exits 4`. Revert, rerun: all pass.

- [ ] **Step 7: Commit**

```bash
git add AR/scripts/sink.sh AR/scripts/run-tests.sh AR/scripts/fixtures/audit_round_min.json
git commit -m "fix(adversarial-review): post PR findings through pr-audit.py; stop reporting success on failure (#135)

sink.sh called pr-review-cli.sh with --pr, which that CLI rejects as an
unknown subcommand, so PR mode never posted a comment. It then printed
'PR review comments posted' regardless."
```

### Task 8: adversarial-review skill instructions, docs and version

**Files:**
- Modify: `AR/SKILL.md` (Quick Start ~20-31, Step 4 end ~251, Step 5 ~253-262, Output Locations ~300-305, See Also ~307-314, frontmatter version line 5)
- Modify: `plugins/adversarial-review/README.md:38`, `:122`
- Modify: `plugins/adversarial-review/.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json` (the `./plugins/adversarial-review` entry), `README.md` (the adversarial-review table row)
- Modify: `plugins/adversarial-review/CHANGELOG.md`, `AR/CHANGELOG.md`

**Interfaces:**
- Consumes: `pr-audit.py record` (Task 6), `sink.sh --record/--no-post` and exit 4 (Task 7).

- [ ] **Step 1: Quick Start**

In `AR/SKILL.md`, add to the Quick Start code block, after the `--force` example:

```bash
# Review without posting anything to the PR (report + local file only)
/adversarial-review --no-post
```

- [ ] **Step 2: Add Step 4b — write the round record**

Insert after the Step 4 paragraph that ends "…to the user." (line ~251) and before `### Step 5 — Sink`:

````markdown
### Step 4b — Write the round record

The round record is what `sink.sh` posts to the PR: every finding, and the opposing model's verdict with its reason. Build it from `report.json`, never by hand.

```bash
RUN_ID="ar-$(date +%Y%m%d-%H%M%S)-$$"
if [[ "$MODE" == "pr" ]]; then
  HEAD_SHA="$(gh pr view "$PR" --json headRefOid -q .headRefOid)"
else
  HEAD_SHA="$(git rev-parse HEAD)"
fi
# ADVERSARY is "gemini", or "claude-only" when Step 0 fell back to degraded mode.
$SCRIPTS/pr-audit.py record \
  --report-json "$RUN_DIR/report.json" \
  --run-id "$RUN_ID" --skill adversarial-review --phase review --round 1 \
  --adversary "$ADVERSARY" --head-sha "$HEAD_SHA" \
  --out "$RUN_DIR/round-1.json"
```

Exit 2 means `report.json` did not make a valid record. Tell the user and run Step 5 with `--no-post`.
````

- [ ] **Step 3: Update Step 5**

Replace the Step 5 code block and add the exit-code note:

````markdown
### Step 5 — Sink

```bash
$SCRIPTS/sink.sh \
  --report-md "$RUN_DIR/report.md" \
  --report-json "$RUN_DIR/report.json" \
  --mode "$MODE" \
  --record "$RUN_DIR/round-1.json" \
  [--pr "$PR"] \
  [--branch "$(git branch --show-current)"] \
  [--no-post]
```

Pass `--no-post` when the user asked for it. Relay `sink.sh`'s `pr-audit:` line to the user.

- Exit 0: delivered. In pr mode, each finding now has a thread on the PR, the opposing model's verdict is a reply, refuted findings' threads are resolved, and one summary review lists them all.
- Exit 4: the report was delivered but some audit comments failed. The failed ids are on stderr. Tell the user; rerunning Step 5 with the same record posts only what is missing.
- Exit 1 or 2: delivery failed. Show the error.

The run directory (`$RUN_DIR`) keeps `round-1.json`. Give the user its path.
````

- [ ] **Step 4: Output Locations and See Also**

Replace the `pr` row of the Output Locations table with:

```markdown
| `pr` | Terminal report; one PR thread per finding with the verdict as a reply, and one summary review, via `pr-audit.py` (falls back to the local file when `gh` is unavailable) |
```

In See Also, replace the `sink.sh` line and delete the `pr-review-loop` line:

```markdown
- `scripts/sink.sh` — output routing: terminal + local file, and the PR audit trail via `pr-audit.py`
- `scripts/pr-audit.py` — posts a round record to the PR (`post`), writes it locally (`local`), or builds it from `report.json` (`record`)
```

- [ ] **Step 5: README**

In `plugins/adversarial-review/README.md`, replace line 38 with:

```markdown
- **PR mode** (auto-detected when a PR exists for the current branch): reviews `gh pr diff`, then saves the exchange on the PR: one thread per finding, the opposing model's verdict as a reply, refuted threads resolved, and one summary review. `--no-post` skips posting.
```

Replace line 122 with:

```markdown
- `scripts/pr-audit.py` — the PR audit trail; also used by the `deep-review` plugin for every round
```

- [ ] **Step 6: Version 0.1.0 → 0.2.0**

Change `0.1.0` to `0.2.0` in: `AR/SKILL.md` frontmatter `version:`, `plugins/adversarial-review/.claude-plugin/plugin.json`, the `./plugins/adversarial-review` entry in `.claude-plugin/marketplace.json`, and the adversarial-review row of the root `README.md` table. Check nothing else still says 0.1.0 for this plugin:

Run: `grep -rn '0\.1\.0' plugins/adversarial-review .claude-plugin/marketplace.json README.md | grep -i adversarial`
Expected: no output.

- [ ] **Step 7: Changelogs**

Add at the top of both `plugins/adversarial-review/CHANGELOG.md` and `AR/CHANGELOG.md`, under the `# Changelog` title:

```markdown
## [0.2.0] - <date the PR merges>

### Added

- PR mode saves the whole exchange on the PR: one inline thread per finding (refuted ones too), the opposing model's verdict as a reply, refuted threads resolved at once, and one summary review. Secrets in model output are redacted before posting, and bodies are capped below GitHub's size limit.
- `scripts/pr-audit.py` with `post`, `local` and `record` modes, and `--no-post` on the skill and `sink.sh`.

### Fixed

- PR mode never posted anything. `sink.sh` called `pr-review-cli.sh --pr …`, which that CLI rejects as an unknown subcommand, then printed "PR review comments posted" anyway. `sink.sh` now exits 4 when any audit comment fails.
```

- [ ] **Step 8: Validate and commit**

Run: `./scripts/validate-skill.sh plugins/adversarial-review/skills/adversarial-review && ./scripts/validate-plugin.sh plugins/adversarial-review`
Expected: both `Result: PASS`.

```bash
git add plugins/adversarial-review .claude-plugin/marketplace.json README.md
git commit -m "docs(adversarial-review): document the PR audit trail; bump to 0.2.0 (#135)"
```

### Task 9: deep-review posts every round

**Files:**
- Create: `deep-review/references/audit-trail.md`
- Modify: `deep-review/SKILL.md` (Arguments 33-42, Phase 0 after step 5 ~84, Phase 1 "Each round" ~92-117, Phase 2 steps 2.1-2.5 ~153-219, Final report ~223-232, frontmatter version)
- Copy both files to `plugins/deep-review/skills/deep-review/` (the published copy must match the source byte for byte)
- Modify: version sites `deep-review/plugin-manifest.json`, `plugins/deep-review/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, root `README.md`; changelogs `deep-review/CHANGELOG.md`, `plugins/deep-review/CHANGELOG.md`, `plugins/deep-review/skills/deep-review/CHANGELOG.md`

**Interfaces:**
- Consumes: `pr-audit.py post|local` and the `audit-round/v1` schema (Tasks 1-5), `gemini-review.sh --mode find` (existing).

- [ ] **Step 1: Write the reference file**

Create `deep-review/references/audit-trail.md`:

````markdown
# Audit trail — one record per round

Every round of Phase 1 and Phase 2 is saved on the PR (or, with no PR, in the local report file) by
the adversarial-review plugin's `scripts/pr-audit.py`. You write one JSON record per round; the
script posts it. Never post comments by hand.

## Setup (Phase 0)

```bash
RUN_ID="dr-$(date +%Y%m%d-%H%M%S)-$$"
RUN_DIR="$(mktemp -d)"
AUDIT="<adversarial-review plugin dir>/skills/adversarial-review/scripts/pr-audit.py"
K=0            # round counter, shared by both phases
PREV_HEAD=null # previous round's head SHA, JSON null for the first round
```

## After each round

1. `K=$((K+1))`. Head SHA: `gh pr view "$PR" --json headRefOid -q .headRefOid` in PR mode,
   `git rev-parse HEAD` otherwise.
2. Write `$RUN_DIR/round-$K.json`:

```json
{
  "schema": "audit-round/v1", "run_id": "<RUN_ID>", "skill": "deep-review",
  "phase": "phase1 | phase2-r1 | phase2-r2 | phase2-r3 | phase2-fix",
  "round": <K>, "adversary": "gemini | codex | claude-only",
  "head_sha": "<40 hex>", "prev_head_sha": <PREV_HEAD>,
  "findings": [{
    "id": "R-001", "origin": "claude | gemini | codex",
    "path": "src/a.py or null", "line": 41,
    "severity": "critical | important | minor", "category": "bug",
    "title": "...", "rationale": "...",
    "status": "survivor | rejected | unconfirmed",
    "events": [ only THIS round's events, in order ]
  }]
}
```

   Events: `{"by": "claude|gemini|codex", "kind": "verdict", "verdict": "confirm|refute", "text": "..."}`,
   `{"by": ..., "kind": "counter", "text": "..."}`,
   `{"by": ..., "kind": "resolution", "resolution": "fixed|pushback|deferred", "sha": "<40 hex, only once committed>", "text": "..."}`,
   `{"by": ..., "kind": "recheck", "result": "resolved|partly|missed", "text": "..."}`.

3. Post it:

```bash
if [[ "$NO_POST" == "true" ]]; then :;
elif [[ -n "$PR" ]]; then python3 "$AUDIT" post --pr "$PR" --record "$RUN_DIR/round-$K.json";
else python3 "$AUDIT" local --record "$RUN_DIR/round-$K.json" --out "<branch with / as ->.adversarial-review.md"; fi
```

4. `PREV_HEAD="\"<head sha>\""`.

Exit 1 means some comments failed (listed on stderr). Note it for the final report and carry on;
rerunning the same command later posts only what is missing. Exit 2 means the record is invalid:
fix the JSON and rerun. A posting failure never stops the review.

## What goes in each record

| Round | Findings to include | Events |
|---|---|---|
| Phase 1, each round | every actionable finding raised this round, ids `R-001…` continuing across rounds; plus earlier findings being re-checked | `resolution` for each fix or pushback (`fixed` has no `sha` until the Phase 1 commit); `recheck` by the re-reviewer for findings fixed last round |
| Phase 2 R1 | all Claude (`C-`) and adversary (`G-`/`X-`) findings, `status: unconfirmed` | none |
| Phase 2 R2 | every judged finding, with its updated `status` | `verdict` by the judging model |
| Phase 2 R3 | findings whose refutation was contested | `counter` by the finding's origin, then `verdict` for the concede-or-defend answer |
| Phase 2 fix | survivors | `resolution` with the Phase 2 commit `sha` |

A refuted finding's thread is resolved at once. A fixed one stays open until a later round records
`recheck: resolved` by a model other than the author.
````

- [ ] **Step 2: Edit `deep-review/SKILL.md`**

a. Arguments block — add a line after `--max-rounds`:

```
/deep-review --no-post       # keep the audit trail local; post nothing to the PR
```

b. Phase 0 — add step 6 after step 5:

```markdown
6. **Start the audit trail.** Set up `RUN_ID`, `RUN_DIR`, `AUDIT` and the round counter as in
   `./references/audit-trail.md`. Every round below ends by writing and posting one record, so the
   PR shows each iteration: findings as threads, verdicts, counters, fixes and re-checks as replies.
```

c. Phase 1 "Each round" — add a final numbered step after step 5 ("Converge or iterate"):

```markdown
6. **Record the round** per `./references/audit-trail.md` (phase `phase1`): this round's findings
   with their `resolution` events, and `recheck` events for last round's fixes.
```

d. Step 2.1 — replace the Gemini finder bullet and its NOTE (lines 158-162) with:

```markdown
- Gemini finder — `gemini-review.sh --diff <DIFF> --mode find --out <gemini-r1.json>` (the
  adversarial-review plugin's script). It emits `{"findings":[...]}` with `origin="gemini"`.
  Exit 3 means the adversary is unavailable: follow Step 2.0's degraded path.
```

   Then append after "…respectable, valid answer.": `Record the round (phase \`phase2-r1\`).`

e. Step 2.2 — replace "(same approach R1 uses)" with "(build a prompt file with the brief and each finding)". Append after "Emit an R2 digest…": `Record the round (phase \`phase2-r2\`): each judged finding with its \`verdict\` event and updated \`status\`.`

f. Step 2.3 — append at the end of the step: `Record the round (phase \`phase2-r3\`): \`counter\` then \`verdict\` events for each contested finding.`

g. Step 2.5 — after "Push; if the repo polls CI after push, check it." add: `Then record the round (phase \`phase2-fix\`): a \`resolution\` event with the pushed commit's \`sha\` for each survivor.`

h. Final report — add a bullet:

```markdown
- Audit trail: the PR link (or local file), rounds posted, and any posting failures with the
  command to rerun them; the run directory path holding every `round-<k>.json`.
```

i. Frontmatter `version: 1.3.1` → `version: 1.4.0`.

- [ ] **Step 3: Check the stale claim is gone**

Run: `grep -n 'NO discovery\|R2-\*\*judge-only\|direct `gemini -m' deep-review/SKILL.md`
Expected: only the R2 reliability-note fallback line matches (`direct \`gemini -m gemini-2.5-pro -p "<brief + each Claude finding`). The R1 NOTE is gone.

- [ ] **Step 4: Sync the published copy**

```bash
cp deep-review/SKILL.md plugins/deep-review/skills/deep-review/SKILL.md
mkdir -p plugins/deep-review/skills/deep-review/references
cp deep-review/references/audit-trail.md plugins/deep-review/skills/deep-review/references/audit-trail.md
diff -r deep-review/references plugins/deep-review/skills/deep-review/references && diff deep-review/SKILL.md plugins/deep-review/skills/deep-review/SKILL.md && echo in-sync
```

Expected: `in-sync`.

- [ ] **Step 5: Version 1.3.1 → 1.4.0 and changelogs**

Change `1.3.1` to `1.4.0` in `deep-review/plugin-manifest.json`, `plugins/deep-review/.claude-plugin/plugin.json`, the `./plugins/deep-review` entry in `.claude-plugin/marketplace.json`, and the deep-review row of the root `README.md`.

Add to the top of all three deep-review changelogs (`deep-review/CHANGELOG.md`, `plugins/deep-review/CHANGELOG.md`, `plugins/deep-review/skills/deep-review/CHANGELOG.md`):

```markdown
## [1.4.0] - <date the PR merges>

### Added

- Every round of both phases is saved on the PR through adversarial-review's `pr-audit.py`: findings as threads, and verdicts, counters, fixes and re-checks as replies, with one summary review per round. `--no-post` keeps it local. See `references/audit-trail.md`.

### Fixed

- Phase 2 R1 told you to call `gemini` directly because `gemini-review.sh` supposedly had no `--mode find`. It does; R1 now uses it.
```

Run: `grep -rn '1\.3\.1' deep-review plugins/deep-review .claude-plugin/marketplace.json README.md | grep -v CHANGELOG`
Expected: no output.

- [ ] **Step 6: Validate and commit**

Run: `./scripts/validate-skill.sh deep-review && ./scripts/validate-plugin.sh plugins/deep-review && ./scripts/test-sync-hygiene.sh | tail -2`
Expected: both validators `Result: PASS`; `All assertions passed.`

```bash
git add deep-review plugins/deep-review .claude-plugin/marketplace.json README.md
git commit -m "feat(deep-review): save every round on the PR via pr-audit.py; bump to 1.4.0 (#135)"
```

### Task 10: Run the adversarial-review suite in CI

**Files:**
- Modify: `.github/workflows/validate-skill.yml` (append a job after `sync-hygiene`)

- [ ] **Step 1: Add the job**

Append to the `jobs:` map:

```yaml
  adversarial-review-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Unconditional, like the two harness jobs above. Before #135 this suite
      # ran only by hand, which is how sink.sh's PR mode stayed broken.
      - name: Run adversarial-review test suite
        run: bash plugins/adversarial-review/skills/adversarial-review/scripts/run-tests.sh
```

- [ ] **Step 2: Check the suite passes on Linux**

Push the branch and watch the job: `gh run watch --exit-status $(gh run list --branch feature/135-review-audit-trail-codex --limit 1 --json databaseId -q '.[0].databaseId')`
Expected: `adversarial-review-tests` passes. If a test fails only on Linux, fix the test or script in this task. Do not skip it.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/validate-skill.yml
git commit -m "ci: run the adversarial-review test suite on every PR (#135)"
```

### Task 11: Monorepo changelog, PR and a live check

**Files:**
- Modify: `CHANGELOG.md` (`[Unreleased]`)

- [ ] **Step 1: Changelog entry**

Under `## [Unreleased]` in the root `CHANGELOG.md`, add:

```markdown
### Added

- **Review audit trail on the PR (#135, part 1).** `adversarial-review` 0.1.0 -> 0.2.0 and `deep-review` 1.3.1 -> 1.4.0 save every model exchange on the PR, round by round: one inline thread per finding (refuted ones included, resolved at once), verdicts, counters, fixes and re-checks as replies, and one summary review per round. A fixed finding's thread closes only when the adversary's re-check says resolved. Secrets are redacted and bodies capped before posting. A new shared script, `pr-audit.py`, does the posting; it keeps no local state, so a rerun posts only what is missing.

### Fixed

- **`adversarial-review` PR mode never posted a comment.** `sink.sh` called `pr-review-cli.sh --pr …`, which that CLI rejects, then printed "PR review comments posted" anyway. The suite that would have caught it never ran in CI; it does now.
```

- [ ] **Step 2: Full local verification**

Run each and confirm:
- `bash plugins/adversarial-review/skills/adversarial-review/scripts/run-tests.sh | tail -3` → `All tests passed.`
- `./scripts/test-discovery-guards.sh | tail -1` and `./scripts/test-sync-hygiene.sh | tail -1` → `All assertions passed.`
- `./scripts/commit-preflight.sh` (after staging) → `PREFLIGHT PASSED`

- [ ] **Step 3: Commit and open the PR**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): review audit trail and the PR-mode fix (#135)"
git push -u origin feature/135-review-audit-trail-codex
gh pr create --base develop --title "Review audit trail on the PR (#135, part 1)" --body-file <body>
gh pr view --json baseRefName -q .baseRefName   # must print develop
```

The PR body references #135 without a closing keyword (`Part of #135`), because part 2 (Codex) is still to come.

- [ ] **Step 4: Live check on this PR (ask first)**

Ask the user before posting anything. With approval, run `/adversarial-review` on this PR. Then check on GitHub:
- one thread per finding, each ending with its `audit:v1` marker;
- verdicts as replies, and refuted threads resolved;
- one `COMMENT` summary review with working thread links;
- rerunning `sink.sh` with the same `round-1.json` prints `posted 0`.

Report what was posted, with links.

