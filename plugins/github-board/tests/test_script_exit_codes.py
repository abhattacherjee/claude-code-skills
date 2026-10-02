"""The exit-code headers must match what the scripts actually do.

A wrong exit-code header is worse than none: a caller branches on it. These
headers were derived by reading each script's exits, so this pins that reading
and catches the next person who adds an exit without updating the header.

Only paths reachable without network or auth are exercised here; the auth exit
(apply-promotions 3) is covered by test_apply_promotions_release_lookup.py.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="requires jq")


def run(script, *args, **kw):
    return subprocess.run(["bash", str(SCRIPTS / script), *args],
                          capture_output=True, text=True, **kw)


@pytest.mark.parametrize("script", ["apply-promotions.sh", "find-promotable.sh",
                                    "discover-boards.sh", "inventory-board.sh"])
def test_help_exits_zero(script):
    assert run(script, "--help").returncode == 0


@pytest.mark.parametrize("script, args", [
    ("apply-promotions.sh", ["/nonexistent.json", "--dry-run"]),
    ("apply-promotions.sh", ["/nonexistent.json"]),            # too few args
    ("apply-promotions.sh", ["/nonexistent.json", "--bogus"]),
    ("find-promotable.sh", ["/nonexistent.json"]),
    ("find-promotable.sh", []),                                 # too few args
    ("discover-boards.sh", ["owner"]),                          # too few args
    ("inventory-board.sh", ["--board-id"]),                     # flag w/o value
])
def test_usage_and_unreadable_input_exit_two(script, args):
    assert run(script, *args).returncode == 2


def test_find_promotable_exits_five_without_a_done_option(tmp_path):
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"project": {}, "statusField": {}, "items": []}))
    done = run("find-promotable.sh", str(inv))
    assert done.returncode == 5
    assert "no Done option ID" in done.stderr


@pytest.mark.parametrize("args, code", [
    (["full-run"], 0),
    (["--help"], 0),
    (["bogus-workflow"], 1),
    ([], 1),
])
def test_task_manifest_exit_codes(args, code):
    assert run("task-manifest.sh", *args).returncode == code


def test_apply_promotions_exits_one_when_the_projection_drops_rows(tmp_path):
    """The documented exit 1 for "board NOT in sync", not just for failed writes."""
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({
        "project": {"id": "P", "title": "B", "number": 1},
        "statusField": {"id": "F", "doneOptionId": "D"},
        "candidates": [
            {"itemId": "I1", "number": 1, "title": "t",
             "status": "s", "url": "u", "repo": "o/r", "promoteClass": "nopr",
             "mergedPRs": "not-a-list"},
        ],
    }))
    done = run("apply-promotions.sh", str(cand), "--dry-run", "--no-release-comment")
    assert done.returncode == 1
    assert "NOT in sync" in done.stderr
