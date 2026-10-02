"""find-promotable.sh must FAIL CLOSED when timeline PR discovery errors.

The fallback query answers "which merged PRs closed this issue?". A closed issue
with an empty answer is classified `nopr` -- a PROMOTING class -- because "closed
as completed with zero linked PRs" reads as an administrative closure. That makes
the empty array positive evidence, so an auth expiry / rate limit / network error
collapsing to `[]` would promote unreleased work and comment that it was an
administrative closure. `linkedPRCount == 0` is the NORMAL Git-Flow state, so this
is the common path, not an edge case.

The distinguishing control is the pair of tests below: the SAME fixture, with the
API succeeding-with-empty vs failing, must land in different classes.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts" / "find-promotable.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="find-promotable.sh requires jq"
)


def _inventory():
    """One board item: closed-as-completed issue, no formal linked PR, not Done."""
    return {
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {
            "id": "PVTSSF_1",
            "name": "Status",
            "options": [{"id": "opt_dev", "name": "Dev Complete"},
                        {"id": "opt_done", "name": "Done"}],
            "doneOptionId": "opt_done",
        },
        "items": [{
            "itemId": "PVTI_1",
            "status": "Dev Complete",
            "statusOptionId": "opt_dev",
            "contentType": "Issue",
            "issue": {
                "number": 42,
                "title": "an issue",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "url": "https://github.com/o/r/issues/42",
                "repo": "o/r",
                "linkedPRs": [],
            },
            "pullRequest": None,
            "draftTitle": None,
        }],
    }


def _stub_gh(tmp_path, body):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + body + "\n")
    gh.chmod(0o755)
    return bindir


def _run(tmp_path, bindir, *args):
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps(_inventory()))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(SCRIPT), str(inv), *args],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )


def test_discovery_api_failure_is_held_not_promoted(tmp_path):
    # gh fails the way an expired token / rate limit / network error does.
    bindir = _stub_gh(tmp_path, 'echo "gh: HTTP 401: Bad credentials" >&2; exit 1')
    done = _run(tmp_path, bindir)

    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["candidates"] == [], (
        "an unverifiable PR set was promoted -- an API failure must never be able "
        "to manufacture the zero-linked-PRs evidence that `nopr` promotes on"
    )
    assert [c["promoteClass"] for c in out["held"]] == ["hold-discovery-failed"]
    assert "discovery FAILED" in done.stderr


def test_discovery_api_success_with_no_prs_is_still_promoted(tmp_path):
    """Negative control: the fix must not turn every no-PR closure into a hold.

    Same fixture, same code path -- only the API's exit status differs.
    """
    bindir = _stub_gh(tmp_path, 'echo "[]"; exit 0')
    done = _run(tmp_path, bindir)

    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert [c["promoteClass"] for c in out["candidates"]] == ["nopr"]
    assert out["held"] == []


def test_malformed_issue_reference_is_held_not_treated_as_no_prs(tmp_path):
    """A repo/number we cannot even ask about is unverified, not PR-free."""
    bindir = _stub_gh(tmp_path, 'echo "[]"; exit 0')
    inv = _inventory()
    inv["items"][0]["issue"]["repo"] = None
    path = tmp_path / "inv2.json"
    path.write_text(json.dumps(inv))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    done = subprocess.run(["bash", str(SCRIPT), str(path)],
                          capture_output=True, text=True, env=env, cwd=str(tmp_path))

    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["candidates"] == []
    assert [c["promoteClass"] for c in out["held"]] == ["hold-discovery-failed"]


def test_human_output_names_the_new_class(tmp_path):
    """A class that exists in code but not in the output is undocumented behaviour."""
    bindir = _stub_gh(tmp_path, 'echo "gh: HTTP 401" >&2; exit 1')
    done = _run(tmp_path, bindir, "--human")

    assert done.returncode == 0, done.stderr
    assert "could not verify" in done.stdout
    assert "HELD BACK: 1" in done.stdout
