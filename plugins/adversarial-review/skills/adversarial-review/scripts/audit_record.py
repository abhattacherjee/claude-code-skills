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


_PK = "PRIVATE" + " KEY"
SECRET_PATTERNS = [
    ("github-token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"sk-(?!ant-)[A-Za-z0-9_-]{20,}")),
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*" + _PK + r"-----[\s\S]*?(?:-----END [A-Z ]*" + _PK + r"-----|\Z)")),
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


def should_resolve(f, rec):
    """Refuted findings close at once. Others close only on the adversary's latest re-check."""
    if f["status"] == "rejected":
        return True
    for e in reversed(f["events"]):
        if e["kind"] == "recheck":
            return e.get("result") == "resolved" and (e["by"] == rec["adversary"] or rec["adversary"] == "claude-only")
    return False


def outcome(f):
    if f["status"] == "rejected":
        return "refuted"
    for e in reversed(f["events"]):
        if e["kind"] == "recheck":
            return f"re-check: {e['result']}"
        if e["kind"] == "resolution":
            return e["resolution"]
    return "confirmed" if f["status"] == "survivor" else "unconfirmed"


def _prev_suffix(rec):
    """Return ' (previous `<sha7>`)' or '' for prev_head_sha."""
    prev = rec.get("prev_head_sha")
    return f" (previous `{_sha7(prev)}`)" if prev else ""


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


NO_ROOM_NOTE = "Details for findings with no thread were too long to include; they are in the run dir."


def summary_bodies(rec, rows, redacted, failures, details="", limit=MAX_BODY):
    prev_txt = _prev_suffix(rec)
    title = f"**{rec['skill']} · {rec['phase']} · Round {rec['round']}"
    tail = f"** · adversary: {rec['adversary']} · reviewed `{_sha7(rec['head_sha'])}`{prev_txt}"
    counts = Counter(r["outcome"] for r in rows)
    parts = [f"{sum(1 for r in rows if r['new'])} new"] + [f"{n} {k}" for k, n in sorted(counts.items())]
    count_line = f"{len(rows)} findings: " + " · ".join(parts)
    table_head = "| id | severity | origin | this round | thread |\n|---|---|---|---|---|"
    lines = []
    for r in rows:
        note = r['note'] or 'unknown'
        note, _ = redact(note)
        link = f"[thread]({r['thread']})" if r["thread"] else f"no thread: {_cell(note)}"
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
            elif room > len(NO_ROOM_NOTE) + 4:
                body += "\n\n" + NO_ROOM_NOTE
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


def trailing_line(body):
    """Last non-empty line of a comment body, stripped ("" if none)."""
    if not body:
        return ""
    lines = body.strip().split("\n")
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def markdown(rec):
    prev_txt = _prev_suffix(rec)
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
