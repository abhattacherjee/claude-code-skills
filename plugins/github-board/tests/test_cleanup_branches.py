"""prune-branches Category 5 closes a Dependabot PR only for a real tracking issue.

The old search treated any issue matching the free text "<package> dependabot" (or a fuzzy
"PR #N" search hit) as a tracking issue and then ran `gh pr close`. A tracking issue now has
to contain the exact token `PR #<n>` (or the PR's URL) and be written by the repo owner or a
login in the config's prune_branches.tracking_issue_authors (default: none). A bot is not
trusted just for being a bot: any installed GitHub App could file such an issue.
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

PR = "12|dependabot/npm_and_yarn/lodash-4.17.21|Bump lodash from 4.17.20 to 4.17.21"

# Applies --jq like gh does. `issue list` answers by the --search text.
_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
jqf=""; search=""; prev=""
for a in "$@"; do
  [ "$prev" = "--jq" ] && jqf="$a"; [ "$prev" = "-q" ] && jqf="$a"
  [ "$prev" = "--search" ] && search="$a"; prev="$a"
done
out() { if [ -n "$jqf" ]; then printf '%s' "$1" | jq -r "$jqf"; else printf '%s\n' "$1"; fi; }
case "$1 $2" in
  "repo view") out '{"nameWithOwner":"octo/app"}'; exit 0 ;;
  "pr list")
    case "$*" in *app/dependabot*) printf '%s\n' "$PRS"; exit 0 ;; esac
    out '[]'; exit 0 ;;
  "issue list")
    case "$search" in
      *dependabot*) out "$PKG_ISSUES"; exit 0 ;;
      *) out "$PR_ISSUES"; exit 0 ;;
    esac ;;
  "pr close") exit 0 ;;
esac
exit 1
'''


def _issue(number, title, body, login, is_bot=False):
    return {"number": number, "title": title, "body": body, "state": "OPEN",
            "url": f"https://github.com/octo/app/issues/{number}",
            "author": {"login": login, "is_bot": is_bot}}


def _run(tmp_path, pr_issues, pkg_issues=(), allow=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_STUB)
    (bindir / "gh").chmod(0o755)
    log = tmp_path / "gh.log"
    cfg = tmp_path / "xdg-config"
    if allow is not None:
        (cfg / "github-board").mkdir(parents=True)
        (cfg / "github-board" / "config.json").write_text(json.dumps(
            {"version": 1, "owner": "octo", "prune_branches": {"tracking_issue_authors": allow}}))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log), PRS=PR,
               XDG_CONFIG_HOME=str(cfg),
               PR_ISSUES=json.dumps(list(pr_issues)), PKG_ISSUES=json.dumps(list(pkg_issues)))
    done = subprocess.run(["bash", str(SCRIPT), "--delete"], capture_output=True, text=True,
                          env=env, cwd=str(repo), timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return done, [c for c in calls if c.startswith("pr close")]


def test_an_issue_that_only_mentions_the_package_does_not_close_the_pr(tmp_path):
    pkg = [_issue(77, "lodash is slow", "we use lodash; dependabot keeps bumping it", "octo")]
    done, closes = _run(tmp_path, pr_issues=pkg, pkg_issues=pkg)
    assert closes == [], done.stdout
    assert "ISSUE-TRACKED" not in done.stdout


def test_an_owner_issue_naming_pr_n_closes_it_and_shows_the_match(tmp_path):
    done, closes = _run(tmp_path, [_issue(78, "Migrate lodash", "Tracks PR #12 (major bump).", "octo")])
    assert closes and closes[0].startswith("pr close 12"), done.stdout
    assert "#78" in done.stdout and "Migrate lodash" in done.stdout


def test_the_full_pr_url_counts(tmp_path):
    done, closes = _run(tmp_path, [_issue(79, "t", "see https://github.com/octo/app/pull/12.", "octo")])
    assert closes, done.stdout


def test_a_bot_authored_tracking_issue_does_not_count_by_default(tmp_path):
    done, closes = _run(tmp_path, [_issue(80, "Dependabot: PR #12", "", "app/triage-bot", True)])
    assert closes == [], done.stdout


def test_a_bot_authored_tracking_issue_counts_when_allowlisted(tmp_path):
    done, closes = _run(tmp_path, [_issue(80, "Dependabot: PR #12", "", "app/triage-bot", True)],
                        allow=["app/triage-bot"])
    assert closes, done.stdout + done.stderr
    assert "#80" in done.stdout


def test_an_allowlist_for_another_login_does_not_admit_the_bot(tmp_path):
    done, closes = _run(tmp_path, [_issue(80, "Dependabot: PR #12", "", "app/triage-bot", True)],
                        allow=["someone-else"])
    assert closes == [], done.stdout


def test_an_invalid_config_stops_before_closing_anything(tmp_path):
    done, closes = _run(tmp_path, [_issue(78, "t", "Tracks PR #12", "octo")], allow=["a b"])
    assert done.returncode == 2 and closes == [], done.stdout + done.stderr


@pytest.mark.parametrize("issue", [
    pytest.param(_issue(81, "t", "Tracks PR #12", "stranger"), id="author-not-owner-or-bot"),
    pytest.param(_issue(82, "t", "Tracks PR #123", "octo"), id="longer-number"),
    pytest.param(_issue(83, "t", "Tracks MYPR #12", "octo"), id="not-a-word-boundary"),
    pytest.param(_issue(84, "t", "see https://github.com/octo/app/pull/123", "octo"), id="longer-url"),
    pytest.param(_issue(85, "t", "Tracks pr #12", "octo"), id="lower-case-token"),
])
def test_near_misses_do_not_close_the_pr(tmp_path, issue):
    done, closes = _run(tmp_path, [issue])
    assert closes == [], done.stdout
