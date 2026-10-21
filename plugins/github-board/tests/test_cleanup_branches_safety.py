"""prune-branches must not delete on a failed lookup, and must group/match exactly.

Covers: a failed open-PR lookup is not "0 open PRs"; a squash-merged branch is force-deleted
only when its tip is the merged PR's head commit; root Dependabot deps group by bare name; the
exact PR URL is found anywhere in an issue body.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parent.parent / "skills" / "prune-branches" / "scripts"
          / "cleanup-branches.sh")

pytestmark = pytest.mark.skipif(shutil.which("jq") is None or shutil.which("git") is None,
                                reason="needs jq and git")

_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
jqf=""; prev=""
for a in "$@"; do
  [ "$prev" = "--jq" ] && jqf="$a"; [ "$prev" = "-q" ] && jqf="$a"; prev="$a"
done
out() { if [ -n "$jqf" ]; then printf '%s' "$1" | jq -r "$jqf"; else printf '%s\n' "$1"; fi; }
case "$1 $2" in
  "repo view") out '{"nameWithOwner":"octo/app"}'; exit 0 ;;
  "pr list")
    case "$*" in
      *app/dependabot*) printf '%s\n' "${PRS:-}"; exit 0 ;;
      *"--state open"*) [ "${OPEN_RC:-0}" != 0 ] && exit "$OPEN_RC"; out '[]'; exit 0 ;;
      *"--state all"*) [ "${ALL_RC:-0}" != 0 ] && exit "$ALL_RC"; out "${ALL_JSON:-[]}"; exit 0 ;;
    esac
    out '[]'; exit 0 ;;
  "issue list") out "${PR_ISSUES:-[]}"; exit 0 ;;
  "pr close") exit 0 ;;
  "api repos"*) exit 0 ;;
esac
exit 1
'''


def _git(*a, cwd=None):
    return subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=t", *a], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def _setup(tmp_path):
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    _git("clone", "-q", str(origin), str(repo))
    _git("checkout", "-q", "-b", "main", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    _git("push", "-q", "origin", "main", cwd=repo)
    return repo


def _run(tmp_path, repo, **env_extra):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(_STUB)
    (bindir / "gh").chmod(0o755)
    log = tmp_path / "gh.log"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log),
               XDG_CONFIG_HOME=str(tmp_path / "xdg-config"), **env_extra)
    done = subprocess.run(["bash", str(SCRIPT), "--delete"], capture_output=True, text=True,
                          env=env, cwd=str(repo), timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return done, calls


def _gone_branch(tmp_path, repo):
    """A local branch 'feat' with one commit whose remote branch was deleted."""
    _git("checkout", "-q", "-b", "feat", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "work", cwd=repo)
    _git("push", "-q", "-u", "origin", "feat", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    _git("push", "-q", "origin", "--delete", "feat", cwd=repo)
    _git("fetch", "-q", "--prune", cwd=repo)
    return _git("rev-parse", "feat", cwd=repo)


def _branches(repo):
    return _git("branch", "--format=%(refname:short)", cwd=repo).split()


def test_unknown_argument_exits_with_usage_error():
    done = subprocess.run(["bash", str(SCRIPT), "--delet"], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 2
    assert "Unknown argument: --delet" in done.stderr
    assert "Usage: cleanup-branches.sh" in done.stderr
    assert not done.stdout


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_exits_successfully(flag):
    done = subprocess.run(["bash", str(SCRIPT), flag], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0
    assert "Usage: cleanup-branches.sh" in done.stdout
    assert not done.stderr


def test_failed_open_pr_lookup_does_not_queue_a_temp_branch_for_deletion(tmp_path):
    repo = _setup(tmp_path)
    _git("push", "-q", "origin", "main:temp-x", cwd=repo)
    done, calls = _run(tmp_path, repo, OPEN_RC="1")
    assert not [c for c in calls if "-X DELETE" in c], done.stdout + done.stderr
    assert "ORPHAN" not in done.stdout
    assert "temp-x" in done.stderr


def test_orphan_temp_branch_is_still_deleted_when_the_lookup_says_zero(tmp_path):
    repo = _setup(tmp_path)
    _git("push", "-q", "origin", "main:temp-x", cwd=repo)
    done, calls = _run(tmp_path, repo)
    assert [c for c in calls if "-X DELETE" in c], done.stdout + done.stderr


def test_squash_merged_branch_with_extra_local_commits_is_kept(tmp_path):
    repo = _setup(tmp_path)
    tip = _gone_branch(tmp_path, repo)
    merged_head = "0" * 40  # the PR merged an older head than the local tip
    done, _ = _run(tmp_path, repo,
                   ALL_JSON=json.dumps([{"state": "MERGED", "headRefOid": merged_head}]))
    assert "feat" in _branches(repo), done.stdout + done.stderr
    assert "Deleted local" not in done.stdout
    assert tip


def test_squash_merged_branch_is_deleted_when_the_tip_is_the_merged_head(tmp_path):
    repo = _setup(tmp_path)
    tip = _gone_branch(tmp_path, repo)
    done, _ = _run(tmp_path, repo,
                   ALL_JSON=json.dumps([{"state": "MERGED", "headRefOid": tip}]))
    assert "feat" not in _branches(repo), done.stdout + done.stderr


def test_squash_merged_branch_is_kept_when_the_pr_lookup_fails(tmp_path):
    repo = _setup(tmp_path)
    _gone_branch(tmp_path, repo)
    done, _ = _run(tmp_path, repo, ALL_RC="1")
    assert "feat" in _branches(repo), done.stdout + done.stderr


def test_root_dependabot_versions_group_by_name_and_supersede(tmp_path):
    repo = _setup(tmp_path)
    prs = ("12|dependabot/npm_and_yarn/lodash-4.17.21|Bump lodash\n"
           "13|dependabot/npm_and_yarn/lodash-4.17.22|Bump lodash")
    done, calls = _run(tmp_path, repo, PRS=prs)
    closes = [c for c in calls if c.startswith("pr close")]
    assert len(closes) == 1 and closes[0].startswith("pr close 12"), done.stdout + done.stderr


def test_exact_pr_url_is_found_after_a_longer_url_with_the_same_prefix(tmp_path):
    repo = _setup(tmp_path)
    issue = {"number": 79, "title": "t", "state": "OPEN",
             "body": "see https://github.com/octo/app/pull/123 and https://github.com/octo/app/pull/12",
             "author": {"login": "octo", "is_bot": False}}
    done, calls = _run(tmp_path, repo,
                       PRS="12|dependabot/npm_and_yarn/lodash-4.17.21|Bump lodash",
                       PR_ISSUES=json.dumps([issue]))
    assert [c for c in calls if c.startswith("pr close 12")], done.stdout + done.stderr
