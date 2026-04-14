"""CLI helpers for /emerge — thin wrappers around obsidian_utils functions.

Each function is designed to be called from a minimal ``python3 -c`` stub
in the emerge SKILL.md, keeping inline code to 2-3 lines.
"""
from __future__ import annotations

import json
import os
import sys
import time

from obsidian_utils import (
    collect_vault_corpus,
    load_config,
    upgrade_and_collect_corpus,
    write_vault_note,
)


def run_corpus(days: int = 30) -> None:
    """Upgrade unsummarized notes and collect vault corpus for /emerge.

    Prints KEY=VALUE lines for SKILL.md to parse.  Exits non-zero on error.
    """
    c = load_config()
    if not c.get("vault_path"):
        print("ERROR: vault_path not configured", file=sys.stderr)
        sys.exit(1)

    out = os.path.expanduser("~/.claude/obsidian-brain/emerge-corpus.json")

    # Cache check: reuse if < 15 min old and same window
    if os.path.isfile(out) and (time.time() - os.path.getmtime(out)) < 900:
        try:
            with open(out) as f:
                cached = json.load(f)
            if cached.get("stats", {}).get("window_days") == days:
                s = cached["stats"]
                print("VAULT=" + c["vault_path"])
                print("INS=" + c.get("insights_folder", "claude-insights"))
                print("STATUS=CACHED:" + str(s["total_notes"]) + ":0:0")
                return
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"[obsidian-brain] cache read failed, collecting fresh: {exc}", file=sys.stderr)

    status = upgrade_and_collect_corpus(
        c["vault_path"],
        c.get("sessions_folder", "claude-sessions"),
        c.get("insights_folder", "claude-insights"),
        days,
        out,
    )
    print("VAULT=" + c["vault_path"])
    print("INS=" + c.get("insights_folder", "claude-insights"))
    print("STATUS=" + status)


def run_recollect(days: int = 30) -> None:
    """Re-collect corpus after fallback upgrades (no upgrade pass).

    Prints REFRESHED:<count> for SKILL.md to parse.
    """
    import tempfile

    c = load_config()
    corpus_json = collect_vault_corpus(
        c["vault_path"],
        c.get("sessions_folder", "claude-sessions"),
        c.get("insights_folder", "claude-insights"),
        days,
    )
    out = os.path.expanduser("~/.claude/obsidian-brain/emerge-corpus.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(corpus_json)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    print("REFRESHED:" + str(json.loads(corpus_json).get("note_count", 0)))


def run_build_note() -> None:
    """Build emerge vault note from corpus + analysis.

    Prints SAVED:<path> then ---REPORT--- then the analysis body.
    Cleans up temp files on success.
    """
    import datetime
    import hashlib

    c = load_config()
    vault = c["vault_path"]
    ins = c.get("insights_folder", "claude-insights")

    corpus_path = os.path.expanduser("~/.claude/obsidian-brain/emerge-corpus.json")
    analysis_path = os.path.expanduser("~/.claude/obsidian-brain/emerge-analysis.md")

    with open(corpus_path) as f:
        corpus = json.load(f)
    with open(analysis_path) as f:
        analysis = f.read()

    today = datetime.date.today().isoformat()
    projects = sorted(
        set(
            n.get("project", "")
            for n in corpus.get("notes", [])
            if n.get("project")
        )
    )
    src = [
        "[[" + os.path.splitext(n["file"])[0] + "]]"
        for n in corpus.get("notes", [])
    ]
    tags = ["claude/emerge"] + ["claude/project/" + p for p in projects]

    fm = (
        "---\ntype: claude-emerge\ndate: " + today
        + '\ndate_range: "' + corpus.get("date_range", "")
        + '"\nprojects:\n' + "\n".join("  - " + p for p in projects)
        + "\nsource_notes:\n" + "\n".join('  - "' + s + '"' for s in src)
        + "\nnote_count: " + str(corpus.get("note_count", 0))
        + "\ntags:\n" + "\n".join("  - " + t for t in tags)
        + "\n---"
    )
    title = "# Emerge: Pattern Discovery (" + corpus.get("date_range", "") + ")"
    header = (
        "**Projects:** " + ", ".join(projects)
        + "\n**Notes analyzed:** " + str(corpus.get("note_count", 0))
    )
    body = fm + "\n\n" + title + "\n\n" + header + "\n\n" + analysis

    h = hashlib.md5(today.encode()).hexdigest()[-4:]
    filename = today + "-emerge-patterns-" + h + ".md"

    if write_vault_note(vault, ins, filename, body):
        print("SAVED:" + os.path.join(vault, ins, filename))
        print("---REPORT---")
        print(analysis)
    else:
        print("ERROR: write failed", file=sys.stderr)
        sys.exit(1)

    # Cleanup temp files
    for p in [corpus_path, analysis_path]:
        try:
            os.remove(p)
        except OSError:
            pass
