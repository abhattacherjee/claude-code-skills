"""apply-promotions.sh must not report a zero-row run as a clean, in-sync board.

The per-item loop is fed by a process substitution, so a jq projection error
emits ZERO rows: the loop body never runs, every counter stays 0, and the script
prints "Promotions: 0 ok, 0 failed" and exits 0. That reads as "the board was
already in sync" when in fact nothing was even attempted -- with a non-zero
candidate count sitting right above it in the same output.

--dry-run + --no-release-comment keeps these tests entirely offline: neither
path touches `gh`. The --release-tag tests do: a `merged` item looks up its release
milestone (#203). They run with a `gh` stub that fails every call, so no test
reaches GitHub; a failed milestone list is non-fatal.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts" / "apply-promotions.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="apply-promotions.sh requires jq"
)


def _offline_env(tmp_path):
    """PATH with a `gh` that logs each call and fails it, so nothing reaches GitHub."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text('#!/usr/bin/env bash\necho "$*" >> "$GH_LOG"\n'
                  'echo "offline stub" >&2\nexit 1\n')
    gh.chmod(0o755)
    return dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                GH_LOG=str(tmp_path / "gh.log"))


def _only_milestone_reads(tmp_path):
    log = tmp_path / "gh.log"
    calls = log.read_text().splitlines() if log.exists() else []
    return all(c.startswith("api repos/o/r/milestones?") for c in calls)


def _candidate(item_id, number, title="a title"):
    return {
        "itemId": item_id,
        "number": number,
        "title": title,
        "status": "Dev Complete",
        "url": f"https://github.com/o/r/issues/{number}",
        "repo": "o/r",
        "promoteClass": "nopr",
        "mergedPRs": [],
    }


def _run(tmp_path, candidates, *extra):
    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status", "doneOptionId": "opt_done"},
        "candidates": candidates,
    }))
    return subprocess.run(
        ["bash", str(SCRIPT), str(path), "--dry-run", "--no-release-comment", *extra],
        capture_output=True, text=True, cwd=str(tmp_path),
    )


def test_projection_failure_is_not_reported_as_an_in_sync_board(tmp_path):
    # `mergedPRs` as a string makes the projection's map() error out, so it emits
    # nothing at all -- the shape of any jq failure over this input. (A non-string
    # title no longer errors: the projection now runs every field through
    # `clean`, which tostring's it.)
    bad = _candidate("PVTI_1", 1)
    bad["mergedPRs"] = "not-a-list"
    done = _run(tmp_path, [bad, _candidate("PVTI_2", 2)])

    assert done.returncode != 0, (
        "a run that touched nothing exited 0 -- indistinguishable from a board "
        "that was already in sync"
    )
    assert "NOT in sync" in done.stderr
    assert "processed 0 of 2" in done.stderr


def test_partial_projection_failure_is_detected(tmp_path):
    """Rows already flushed before the jq error must not look like the whole set."""
    bad = _candidate("PVTI_2", 2)
    bad["mergedPRs"] = "not-a-list"
    done = _run(tmp_path, [_candidate("PVTI_1", 1), bad])

    assert done.returncode != 0
    assert "processed 1 of 2" in done.stderr


def test_healthy_run_reconciles_and_exits_zero(tmp_path):
    """Negative control: the guard must not fire on a well-formed input."""
    done = _run(tmp_path, [_candidate("PVTI_1", 1), _candidate("PVTI_2", 2)])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Promotions: 2 ok, 0 failed" in done.stdout
    assert "NOT in sync" not in done.stderr


def test_duplicate_item_rows_do_not_trip_the_reconciliation(tmp_path):
    """The projection dedups by itemId, so the expected row count must too.

    Two candidates pointing at one board item is a legitimate input (an issue and
    its PR can share a card); comparing against the raw candidate count instead of
    the distinct-itemId count would fail a healthy run.
    """
    done = _run(tmp_path, [_candidate("PVTI_1", 1), _candidate("PVTI_1", 2)])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Promotions: 1 ok, 0 failed" in done.stdout


def test_null_and_empty_item_ids_do_not_false_trip_the_reconciliation(tmp_path):
    """`@tsv` renders a null itemId as an empty column and awk collapses both.

    Counting null and "" as two distinct expected rows would report a fully
    successful run as an out-of-sync board.
    """
    a, b = _candidate(None, 1), _candidate("", 2)
    done = _run(tmp_path, [a, b])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Promotions: 1 ok, 0 failed" in done.stdout


@pytest.mark.parametrize("empty_field, shifted_into", [
    pytest.param("repo", "promoteClass", id="null-repo"),
    pytest.param("status", "title", id="null-status"),
    pytest.param("url", "status", id="null-url"),
])
def test_an_empty_column_does_not_shift_every_later_field(tmp_path, empty_field,
                                                          shifted_into):
    """A null field must not move the columns after it.

    The row was `@tsv` read with `IFS=$'\t'`. Tab is IFS WHITESPACE, so runs of
    it fold and an EMPTY column disappears: emitting 8 columns never helped when
    one of them was empty. `repo` and `status` are `// null` by construction, so a
    single null shifted promoteClass into the merge-SHA slot and a shipped
    ("merged") item took the no-merged-PR branch -- posting "closed as completed
    with zero linked pull requests" on an issue that shipped via a merged PR.
    Correct URL, no failure signal, invisible to the row-count reconciliation.
    """
    cand = _candidate("PVTI_1", 7)
    cand["promoteClass"] = "merged"
    cand["mergedPRs"] = [{"number": 8, "baseRefName": "main", "repo": "o/r",
                          "mergeCommitOid": "abc123", "inMain": "yes"}]
    cand[empty_field] = None
    if empty_field == "repo":
        # A PR repo that differs from the candidate's is now refused as cross-repo, so null
        # both to keep this test about column shifting.
        cand["mergedPRs"][0]["repo"] = None

    # --release-tag skips the release lookup, so the preview prints a comment
    # label with no `gh` involved. Without --no-release-comment, which would
    # suppress the very label this asserts on.
    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status", "doneOptionId": "opt_done"},
        "candidates": [cand],
    }))
    done = subprocess.run(
        ["bash", str(SCRIPT), str(path), "--dry-run", "--release-tag", "v1.0.0"],
        capture_output=True, text=True, cwd=str(tmp_path), env=_offline_env(tmp_path))
    assert _only_milestone_reads(tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    # The preview names what it would comment. With the columns shifted, a merged
    # item is described as a no-merged-PR note instead.
    assert "no-merged-PR note" not in done.stdout, (
        f"a null {empty_field} shifted {shifted_into} into the next column: "
        f"a shipped item would be annotated as a no-PR closure\n{done.stdout}"
    )
    assert "v1.0.0 (forced)" in done.stdout, (
        f"the merged item lost its release label\n{done.stdout}"
    )
    assert "Promotions: 1 ok" in done.stdout


@pytest.mark.parametrize("hostile_title, why", [
    pytest.param("before\x1fafter", "a literal unit separator: the delimiter itself",
                 id="title-contains-the-separator"),
    pytest.param("line one\nline two", "a newline, which would end the row early",
                 id="title-contains-a-newline"),
    pytest.param("carriage\rreturn", "a CR", id="title-contains-a-cr"),
])
def test_a_hostile_field_value_cannot_split_a_row(tmp_path, hostile_title, why):
    """`clean` must scrub the delimiter, not just the characters that used to break rows.

    The separator rework replaced tab with the unit separator, and the scrubber
    kept guarding only CR/LF -- so a value containing the NEW delimiter split the
    row and shifted every later column, reopening the class the rework closed.
    Low exploitability (0x1F is not typeable and will not appear in a GitHub
    title) but "no realistic input contains this" is the same reasoning that made
    @tsv's fixed column count look safe.
    """
    cand = _candidate("PVTI_1", 7)
    cand["promoteClass"] = "merged"
    cand["title"] = hostile_title
    cand["mergedPRs"] = [{"number": 8, "baseRefName": "main", "repo": "o/r",
                          "mergeCommitOid": "abc123", "inMain": "yes"}]

    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status", "doneOptionId": "opt_done"},
        "candidates": [cand],
    }))
    done = subprocess.run(
        ["bash", str(SCRIPT), str(path), "--dry-run", "--release-tag", "v1.0.0"],
        capture_output=True, text=True, cwd=str(tmp_path), env=_offline_env(tmp_path))
    assert _only_milestone_reads(tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Promotions: 1 ok" in done.stdout, f"{why}: row count changed\n{done.stdout}"
    assert "v1.0.0 (forced)" in done.stdout, (
        f"{why}: the columns shifted, so a shipped item lost its release label"
        f"\n{done.stdout}"
    )
    assert "no-merged-PR note" not in done.stdout


def test_candidates_that_are_not_objects_are_rejected_with_a_diagnosis(tmp_path):
    """The row count is compared with `-ne`; an empty count is a bash error, not a
    verdict. A malformed candidates array must say so instead."""
    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "P", "title": "B", "number": 1},
        "statusField": {"id": "F", "doneOptionId": "D"},
        "candidates": [_candidate("PVTI_1", 1), 5],
    }))
    done = subprocess.run(
        ["bash", str(SCRIPT), str(path), "--dry-run", "--no-release-comment"],
        capture_output=True, text=True, cwd=str(tmp_path))

    assert done.returncode == 2, done.stdout + done.stderr
    assert "not a list of objects" in done.stderr


def test_missing_status_field_id_is_rejected_before_any_mutation(tmp_path):
    """A null statusField.id would reach the mutation as the literal "null"."""
    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"name": "Status", "doneOptionId": "opt_done"},
        "candidates": [_candidate("PVTI_1", 1)],
    }))
    done = subprocess.run(
        ["bash", str(SCRIPT), str(path), "--apply"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )

    assert done.returncode == 2
    assert "missing statusField.id" in done.stderr
