"""apply-plan.sh writes milestones through REST by number (#203).

`gh issue edit --milestone <title>` cannot assign a closed milestone, so every write is
`gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`. `closed_moves` fixes the
milestone of a closed issue without a rationale or a comment. A failed write prints gh's
error and makes the run exit 1. Every `gh` call here is a stub on PATH.
"""
import json
import os
import shutil
import subprocess

import pytest

from gbtest import SKILLS_DIR

APPLY_PLAN = SKILLS_DIR / "plan-milestones" / "scripts" / "apply-plan.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")

MILESTONES = [{"title": "v0.5", "number": 5, "state": "closed"},
              {"title": "v0.6", "number": 6, "state": "open"}]

# Logs every call. The milestone list comes from $MS_JSON. PATCH fails when the issue
# number is in $PATCH_FAIL. POST prints $POST_NUMBER, or fails when it is empty.
# `issue comment` appends its stdin body to $BODY_LOG.
_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
case "$*" in
  "api -X PATCH repos/"*"/issues/"*)
    n="${4##*/}"
    for f in ${PATCH_FAIL:-}; do
      [ "$f" = "$n" ] && { echo "HTTP 422: Validation Failed (https://docs.github.com)" >&2; exit 1; }
    done
    echo '{"number":'"$n"'}'; exit 0 ;;
  "api repos/"*"/milestones -X POST"*)
    [ -n "${POST_NUMBER:-}" ] || { echo "HTTP 403: Resource not accessible" >&2; exit 1; }
    echo "$POST_NUMBER"; exit 0 ;;
  "api repos/"*"/milestones?"*)
    cat "$MS_JSON"; exit 0 ;;
  "issue comment"*)
    { cat; echo; echo "----"; } >> "$BODY_LOG"; exit 0 ;;
esac
echo "unexpected gh call: $*" >&2
exit 1
'''


def _run(tmp_path, plan, *args, milestones=None, patch_fail="", post_number=""):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(_STUB)
    gh.chmod(0o755)
    ms = tmp_path / "ms.json"
    ms.write_text(json.dumps(MILESTONES if milestones is None else milestones))
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(dict({"repo": "O/R"}, **plan)))
    log = tmp_path / "gh.log"
    bodies = tmp_path / "bodies.log"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log),
               MS_JSON=str(ms), PATCH_FAIL=patch_fail, POST_NUMBER=post_number,
               BODY_LOG=str(bodies))
    r = subprocess.run(["bash", str(APPLY_PLAN), "--plan", str(plan_path), *args],
                       capture_output=True, text=True, env=env, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls, (bodies.read_text() if bodies.exists() else "")


def _patches(calls):
    return [c for c in calls if c.startswith("api -X PATCH")]


def test_move_into_closed_milestone_uses_rest_by_number(tmp_path):
    r, calls, _ = _run(tmp_path, {"moves": [
        {"issue": 11, "to": "v0.5", "rationale": "shipped inside v0.5.0"}]}, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/O/R/issues/11 -F milestone=5" in calls
    assert not [c for c in calls if c.startswith("issue edit")]


def test_moves_still_post_their_rationale_comment(tmp_path):
    r, calls, bodies = _run(tmp_path, {"moves": [
        {"issue": 11, "to": "v0.6", "rationale": "belongs with the v0.6 theme"}]}, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.index("api -X PATCH repos/O/R/issues/11 -F milestone=6") < \
        calls.index("issue comment 11 --repo O/R --body-file -")
    assert "belongs with the v0.6 theme" in bodies


def test_rationale_newlines_survive_into_the_comment(tmp_path):
    # @tsv wrote a newline as the two characters \n, so the comment showed a backslash.
    r, _, bodies = _run(tmp_path, {"moves": [
        {"issue": 11, "to": "v0.6", "rationale": "line one\nline two\twith a tab"}]},
        "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "line one\nline two\twith a tab" in bodies, repr(bodies)
    assert "\\n" not in bodies


def test_closed_moves_need_no_rationale_and_post_no_comment(tmp_path):
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 181, "to": "v0.6"}]}, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/O/R/issues/181 -F milestone=6" in calls
    assert not [c for c in calls if c.startswith("issue comment")]


def test_closed_moves_unknown_target_is_refused(tmp_path):
    # The valid entry proves the refusal comes before ANY write, not per issue.
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 182, "to": "v0.6"},
                                                   {"issue": 181, "to": "v9.9"}]}, "--apply")
    assert r.returncode != 0
    assert "v9.9" in r.stderr
    assert _patches(calls) == []


def test_dry_run_lists_closed_moves(tmp_path):
    r, calls, _ = _run(tmp_path, {
        "moves": [{"issue": 11, "to": "v0.6", "rationale": "belongs with the v0.6 theme"}],
        "closed_moves": [{"issue": 181, "to": "v0.5"}]})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MOVE   #11 -> v0.6" in r.stdout
    lines = [ln for ln in r.stdout.splitlines() if "#181" in ln]
    assert lines and "v0.5" in lines[0] and "MOVE" not in lines[0], r.stdout
    assert "closed milestone" in lines[0], "the dry run hides that the target is closed"
    assert _patches(calls) == []


def test_failed_write_prints_error_and_exits_1(tmp_path):
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 181, "to": "v0.6"},
                                                   {"issue": 182, "to": "v0.6"}]},
                       "--apply", patch_fail="181")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "422" in r.stdout + r.stderr
    assert "#181" in r.stderr
    # One failure does not stop the rest of the plan.
    assert "api -X PATCH repos/O/R/issues/182 -F milestone=6" in calls


def test_failed_move_posts_no_rationale_comment(tmp_path):
    r, calls, _ = _run(tmp_path, {"moves": [
        {"issue": 11, "to": "v0.6", "rationale": "belongs with the v0.6 theme"}]},
        "--apply", patch_fail="11")
    assert r.returncode == 1
    assert not [c for c in calls if c.startswith("issue comment")]


def test_ambiguous_title_is_refused(tmp_path):
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 181, "to": "v0.5"}]}, "--apply",
                       milestones=[{"title": "v0.5", "number": 5, "state": "closed"},
                                   {"title": "v0.5", "number": 9, "state": "open"}])
    assert r.returncode != 0
    assert "v0.5" in r.stderr and "ambiguous" in r.stderr.lower()
    assert _patches(calls) == []


def test_created_milestone_number_comes_from_the_post_response(tmp_path):
    r, calls, _ = _run(tmp_path, {
        "create_milestones": [{"title": "v0.7", "description": "Theme: next"}],
        "moves": [{"issue": 11, "to": "v0.7", "rationale": "belongs with the v0.7 theme"}]},
        "--apply", post_number="7")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/O/R/issues/11 -F milestone=7" in calls


def test_failed_create_fails_its_moves_and_exits_1(tmp_path):
    r, calls, _ = _run(tmp_path, {
        "create_milestones": [{"title": "v0.7", "description": "Theme: next"}],
        "moves": [{"issue": 11, "to": "v0.7", "rationale": "belongs with the v0.7 theme"},
                  {"issue": 12, "to": "v0.6", "rationale": "belongs with the v0.6 theme"}]},
        "--apply")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "403" in r.stderr
    assert not [c for c in calls if "issues/11" in c]
    assert "api -X PATCH repos/O/R/issues/12 -F milestone=6" in calls


@pytest.mark.parametrize("entry", [
    pytest.param({"issue": "11/lock", "to": "v0.6"}, id="path-in-issue"),
    pytest.param({"issue": 0, "to": "v0.6"}, id="zero"),
    pytest.param({"issue": 1.5, "to": "v0.6"}, id="fraction"),
    pytest.param({"issue": 11}, id="no-target"),
    pytest.param({"issue": 11, "to": ""}, id="empty-target"),
])
def test_malformed_entry_is_refused_before_any_write(tmp_path, entry):
    r, calls, _ = _run(tmp_path, {"closed_moves": [entry]}, "--apply")
    assert r.returncode == 1, r.stdout + r.stderr
    assert _patches(calls) == []


def test_issue_listed_twice_is_refused(tmp_path):
    r, calls, _ = _run(tmp_path, {
        "moves": [{"issue": 11, "to": "v0.6", "rationale": "belongs with the v0.6 theme"}],
        "closed_moves": [{"issue": 11, "to": "v0.5"}]}, "--apply")
    assert r.returncode == 1
    assert "#11" in r.stderr and "more than once" in r.stderr
    assert _patches(calls) == []


def test_malformed_repo_is_refused(tmp_path):
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 1, "to": "v0.6"}]}, "--apply",
                       "--repo", "O/R/issues/2")
    assert r.returncode == 1
    assert calls == []


def test_milestone_without_a_number_is_refused(tmp_path):
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 181, "to": "v0.5"}]}, "--apply",
                       milestones=[{"title": "v0.5", "state": "closed"}])
    assert r.returncode == 1
    assert "no number" in r.stderr
    assert _patches(calls) == []


def test_move_without_a_real_rationale_is_refused(tmp_path):
    r, calls, _ = _run(tmp_path, {"moves": [{"issue": 11, "to": "v0.6", "rationale": "short"}]},
                       "--apply")
    assert r.returncode == 1
    assert "rationale" in r.stderr
    assert _patches(calls) == []


@pytest.mark.parametrize("flag", ["--plan", "--repo"])
def test_flag_without_a_value_is_a_usage_error(tmp_path, flag):
    # `shift 2` with one argument left failed under set -e: exit 1, no message.
    r, calls, _ = _run(tmp_path, {"closed_moves": [{"issue": 1, "to": "v0.6"}]}, flag)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "needs a value" in r.stderr
    assert calls == []
