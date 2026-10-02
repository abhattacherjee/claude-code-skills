"""A failed or paged list read must never look like an empty, successful one.

X-004: backfill-issues.sh read `gh issue list` / `gh pr list` through process substitution,
whose exit status `set -e` never sees. A 401 printed "Backfilled 0 items" and exited 0.

X-005: apply-plan.sh used `gh api --paginate --jq '[.[].title]'`, which applies the filter per
page and prints one array per page; `jq --argjson` then failed on the second array once a repo
had more than 100 milestones.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gbtest import SKILLS_DIR

BACKFILL = SKILLS_DIR / "create-board" / "scripts" / "backfill-issues.sh"
APPLY_PLAN = SKILLS_DIR / "plan-milestones" / "scripts" / "apply-plan.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def _stub(tmp_path, body):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\necho \"$*\" >> \"$GH_LOG\"\n" + body + "\n")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    return dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log)), log


# ---- X-004: backfill-issues.sh ------------------------------------------------------

BACKFILL_ARGS = ["--project", "3", "--target-owner", "octo", "--repo", "octo/app"]


@pytest.mark.parametrize("failing,extra", [("issue list", []), ("pr list", ["--include-prs"])])
def test_backfill_fails_when_a_list_read_fails(tmp_path, failing, extra):
    env, log = _stub(tmp_path, f'''
case "$1 $2" in
  "{failing}") echo "HTTP 401: Bad credentials" >&2; exit 1 ;;
  "issue list"|"pr list") exit 0 ;;
esac
exit 1''')
    r = subprocess.run(["bash", str(BACKFILL), *BACKFILL_ARGS, *extra], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Backfilled 0 items" not in r.stdout
    assert "could not list" in r.stderr


def test_backfill_with_an_empty_repo_still_exits_0(tmp_path):
    env, _ = _stub(tmp_path, 'case "$1 $2" in "issue list") exit 0 ;; esac; exit 1')
    r = subprocess.run(["bash", str(BACKFILL), *BACKFILL_ARGS], capture_output=True, text=True,
                       env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "No items found to backfill." in r.stdout


# ---- X-005: apply-plan.sh -----------------------------------------------------------

PAGES = [[{"title": f"m{i}"} for i in range(100)], [{"title": "v3.7"}]]

# gh applies --jq to each page separately. Without --jq, gh 2.x merges array pages into one
# array (MERGE=1); older versions print the pages back to back (MERGE=0). Both must work.
_MILESTONE_STUB = r'''
jqf=""; prev=""
for a in "$@"; do [ "$prev" = "--jq" ] && jqf="$a"; prev="$a"; done
case "$1 $2" in
  "api repos/octo/app/milestones"*)
    [ -n "${MS_FAIL:-}" ] && { echo "HTTP 502" >&2; exit 1; }
    if [ -n "$jqf" ]; then
      jq -c '.[]' "$PAGES" | while IFS= read -r page; do printf '%s' "$page" | jq -c "$jqf"; done
    elif [ "$MERGE" = 1 ]; then jq -c 'add' "$PAGES"
    else jq -c '.[]' "$PAGES"; fi
    exit 0 ;;
esac
exit 1'''


def _apply_plan(tmp_path, merge="1", fail=False):
    env, log = _stub(tmp_path, _MILESTONE_STUB)
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps(PAGES))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"repo": "octo/app", "moves": [
        {"issue": 5, "to": "v3.7", "rationale": "belongs with the v3.7 theme"}]}))
    env.update(PAGES=str(pages), MERGE=merge)
    if fail:
        env["MS_FAIL"] = "1"
    return subprocess.run(["bash", str(APPLY_PLAN), "--plan", str(plan)], capture_output=True,
                          text=True, env=env, timeout=60)


@pytest.mark.parametrize("merge", ["1", "0"])
def test_apply_plan_sees_a_milestone_on_the_second_page(tmp_path, merge):
    r = _apply_plan(tmp_path, merge)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MOVE   #5 -> v3.7" in r.stdout


def test_apply_plan_stops_when_the_milestone_list_cannot_be_read(tmp_path):
    r = _apply_plan(tmp_path, fail=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not list milestones" in r.stderr
