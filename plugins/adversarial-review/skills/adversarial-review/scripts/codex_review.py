#!/usr/bin/env python3
"""codex_review.py — run Codex as the adversary in a locked-down `codex exec`.

Called through codex-review.sh (--help works on both). Modes:
  find     Codex reviews the diff and reports findings (ids X-001, ...).
           With --prior, it also re-checks earlier findings (a rechecks list).
  judge    Codex gives confirm/refute verdicts on another model's findings.
  counter  Codex concedes or defends its own findings that Claude refuted.

Codex runs with only PATH, HOME and the user's own CODEX_HOME in its
environment; with user config, rules, the reviewed repo's AGENTS.md, apps,
plugins, hooks and memories off; in a read-only sandbox; and with the diff on a
stdin pipe that is closed after writing. Every argv passes an isolation guard,
and each Codex version must pass an isolation canary before its first review.
Its output is untrusted: it is checked against the schema, capped, and redacted.

Exit codes:
  0  success
  1  error (an input file is missing or unreadable)
  2  usage error
  3  adversary unavailable (codex missing or logged out, a non-zero exit,
     a timeout, no valid output after one retry, a missing isolation flag,
     or a leaked isolation canary)
"""
import argparse
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_record as ar  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_UNAVAILABLE = 0, 1, 3
DEFAULT_TIMEOUT = 900
MAX_FINDINGS = 50
MAX_TEXT = 4000
MAX_TITLE = 200
SEVERITIES = ("critical", "important", "minor")
CATEGORIES = ("bug", "security", "perf", "convention", "maintainability")
RECHECK_RESULTS = ("resolved", "partly", "missed")
VERDICTS = ("confirm", "refute")
POSITIONS = ("concede", "defend")
# codex_hooks is a legacy feature name in the 0.155.1 binary; Task 10 checks it.
DISABLED_FEATURES = ("apps", "plugins", "remote_plugin", "memories", "multi_agent",
                     "image_generation", "view_image", "codex_hooks")


class BadOutput(ValueError):
    """Codex answered, but not in the required shape."""


class Unavailable(RuntimeError):
    """Codex cannot be used for this run."""


class InputError(RuntimeError):
    """An input file is missing or unreadable."""


def clean_text(value, limit):
    """Redact known secret formats first, then cut to limit characters."""
    text = value if isinstance(value, str) else ""
    text, _ = ar.redact(text)
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return text


def _is_line(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _clean_path(path):
    """Return (path or None, note for the rationale). Absolute paths and '..' parts are dropped."""
    if not isinstance(path, str) or not path.strip():
        return None, ""
    path = path.strip()
    if path.startswith("/") or ".." in path.split("/"):
        return None, "(path " + json.dumps(path[:200]) + " was outside the repo) "
    return path, ""


def _known(item, known_ids, seen):
    """The item's id when it is a known string id not seen before, else None."""
    if not isinstance(item, dict):
        return None
    rid = item.get("id")
    if not isinstance(rid, str) or rid not in known_ids or rid in seen:
        return None
    return rid


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def validate_find(raw, id_start=1, prior_ids=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        raise BadOutput("expected an object with a findings list")
    findings = []
    for item in raw["findings"]:
        if len(findings) >= MAX_FINDINGS:
            break
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"), MAX_TITLE)
        if not title.strip():
            continue
        path, note = _clean_path(item.get("path"))
        rationale = item.get("rationale") if isinstance(item.get("rationale"), str) else ""
        severity = item.get("severity") if item.get("severity") in SEVERITIES else "important"
        category = item.get("category") if item.get("category") in CATEGORIES else "maintainability"
        findings.append({
            "id": "X-%03d" % (id_start + len(findings)),
            "path": path,
            "line": item.get("line") if _is_line(item.get("line")) else None,
            "severity": severity, "category": category, "title": title,
            "rationale": clean_text(note + rationale, MAX_TEXT), "origin": "codex",
            "claude_verdict": None, "adversary_verdict": None, "status": None,
            "killed_by": None, "kill_reason": None,
        })
    result = {"findings": findings}
    if prior_ids is not None:
        items = raw.get("rechecks")
        if not isinstance(items, list):
            raise BadOutput("expected a rechecks list when earlier findings are given")
        rechecks, seen = [], set()
        for item in items:
            rid = _known(item, prior_ids, seen)
            if rid is None or item.get("result") not in RECHECK_RESULTS:
                continue
            seen.add(rid)
            rechecks.append({"id": rid, "result": item["result"],
                             "reason": clean_text(item.get("reason"), MAX_TEXT)})
        result["rechecks"] = rechecks
    return result


def validate_judge(raw, known_ids):
    if not isinstance(raw, dict) or not isinstance(raw.get("verdicts"), list):
        raise BadOutput("expected an object with a verdicts list")
    verdicts, seen = [], set()
    for item in raw["verdicts"]:
        rid = _known(item, known_ids, seen)
        if rid is None or item.get("verdict") not in VERDICTS:
            continue
        seen.add(rid)
        verdicts.append({"id": rid, "adversary_verdict": item["verdict"],
                         "reason": clean_text(item.get("reason"), MAX_TEXT),
                         "confidence": _confidence(item.get("confidence"))})
    return {"verdicts": verdicts}


def validate_counter(raw, known_ids):
    if not isinstance(raw, dict) or not isinstance(raw.get("counters"), list):
        raise BadOutput("expected an object with a counters list")
    counters, seen = [], set()
    for item in raw["counters"]:
        rid = _known(item, known_ids, seen)
        if rid is None or item.get("position") not in POSITIONS:
            continue
        seen.add(rid)
        counters.append({"id": rid, "position": item["position"],
                         "reason": clean_text(item.get("reason"), MAX_TEXT)})
    return {"counters": counters}
