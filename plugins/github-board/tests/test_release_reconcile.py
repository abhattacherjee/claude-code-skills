"""plan-milestones step 0: release-reconcile.sh checks every closed issue's milestone (#204).

Each test builds a real git repo under tmp_path: squash commits on develop, a release merge
on main tagged v0.5.0, and more squash commits after the tag. `origin` is a bare repo under
tmp_path, reached through a url.<path>.insteadOf rewrite of https://github.com/o/r.git, so
the script sees the GitHub URL and `git fetch --tags origin` stays offline. HOME and the git
system config are isolated, so no user git config applies. Every gh call is a stub.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from gbtest import SKILLS_DIR

SCRIPTS = SKILLS_DIR / "plan-milestones" / "scripts"
RECONCILE = SCRIPTS / "release-reconcile.sh"
APPLY_PLAN = SCRIPTS / "apply-plan.sh"
URL = "https://github.com/o/r.git"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None or shutil.which("git") is None,
                                reason="needs jq and git")

MILESTONES = [{"title": "v0.4", "number": 4, "state": "closed"},
              {"title": "v0.5", "number": 5, "state": "closed"},
              {"title": "v0.6", "number": 6, "state": "open"},
              {"title": "Observability", "number": 7, "state": "open"},
              {"title": "v0.7", "number": 8, "state": "open"}]
V05 = {"number": 5, "title": "v0.5"}
V06 = {"number": 6, "title": "v0.6"}
OBS = {"number": 7, "title": "Observability"}

# The fake gh answers from $FIX (a JSON file) and logs argv to $GH_LOG, one JSON list a line.
# $FAIL_PR_LIST=<base> fails that list, $EMPTY_PR_LIST=<base> prints nothing for it,
# $FAIL_ISSUE=<n> fails that issue read, $FAIL_MS=1 fails the milestone list. An issue that
# is not in the fixture fails the way gh does for an unknown number. It answers what the call
# asks for, as GitHub does: `pr list` returns only the --json fields named; an issue has
# stateReason only when the query names it, and unmerged linked PRs only with
# includeClosedPrs:true (every unmerged PR in these fixtures is closed).
FAKE_GH = r'''
import json, os, sys
a = sys.argv[1:]
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
fix = json.load(open(os.environ["FIX"]))
def val(flag):
    return a[a.index(flag) + 1] if flag in a else None
if a[:2] == ["repo", "view"]:
    print(fix.get("default", "main")); sys.exit(0)
if a[:2] == ["pr", "list"]:
    base = val("--base")
    if os.environ.get("FAIL_PR_LIST") == base:
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
    if os.environ.get("EMPTY_PR_LIST") == base:
        sys.exit(0)
    fields = val("--json").split(",")
    print(json.dumps([{k: v for k, v in p.items() if k in fields}
                      for p in fix["prs"] if p["baseRefName"] == base])); sys.exit(0)
if a[:2] == ["api", "graphql"]:
    num = [x for x in a if x.startswith("num=")][0][4:]
    if os.environ.get("FAIL_ISSUE") == num:
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
    if num in fix["issues"] and fix["issues"][num] is None:
        print(json.dumps({"data": {"repository": {"issueOrPullRequest": None}}})); sys.exit(0)
    node = fix["issues"].get(num)
    if node is None:
        sys.stderr.write("GraphQL: Could not resolve to an issue or pull request with the "
                         "number of %s. (repository.issueOrPullRequest)\n" % num); sys.exit(1)
    query = [x for x in a if x.startswith("query=")][0]
    node = dict(node)
    if "stateReason" not in query:
        node.pop("stateReason", None)
    links = node.get("closedByPullRequestsReferences")
    if links is not None:
        if "closedByPullRequestsReferences" not in query:
            node.pop("closedByPullRequestsReferences")
        elif "includeClosedPrs:true" not in query:
            node["closedByPullRequestsReferences"] = {
                "nodes": [x for x in links["nodes"] if x["merged"]]}
    print(json.dumps({"data": {"repository": {"issueOrPullRequest": node}}})); sys.exit(0)
if a[0] == "api" and "/milestones?" in a[1]:
    if os.environ.get("FAIL_MS"):
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
    print(json.dumps(fix["milestones"])); sys.exit(0)
if a[0] == "api" and "/issues/" in a[1] and "--jq" in a:
    node = fix["issues"][a[1].rsplit("/", 1)[1]]
    print(node["state"].lower()); sys.exit(0)
sys.stderr.write("fake gh: no route for %s\n" % a); sys.exit(97)
'''


def issue(n, milestone=None, state="CLOSED", reason="COMPLETED", linked=(), typename="Issue"):
    return {"__typename": typename, "number": n, "state": state, "stateReason": reason,
            "milestone": milestone,
            "closedByPullRequestsReferences": {"nodes": [{"number": p, "merged": m}
                                                         for p, m in linked]}}


class Repo:
    """A throwaway repo: `seed` builds history, `origin.git` is bare, `work` is the checkout."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1",
                        GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
                        # Only local transports: a URL that slips past the insteadOf rewrite
                        # (a mutant that skips the host check) fails here, never on a network.
                        GIT_ALLOW_PROTOCOL="file")
        for k in ("GIT_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG", "GIT_WORK_TREE", "GH_HOST"):
            self.env.pop(k, None)
        self.clock = 1_700_000_000
        self.seed = tmp_path / "seed"
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        self.sha = {}
        self.git(tmp_path, "init", "-q", str(self.seed))
        self.git(self.seed, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(self.seed, "commit", "-q", "--allow-empty", "-m", "init")
        self.git(self.seed, "branch", "develop")

    def git(self, cwd, *args):
        # Every commit, merge and tag is one minute after the last, so "merged before the
        # last tag" never rests on two events in the same second.
        if args and args[0] in ("commit", "merge", "tag"):
            self.clock += 60
            self.env["GIT_AUTHOR_DATE"] = self.env["GIT_COMMITTER_DATE"] = f"@{self.clock} +0000"
        return subprocess.run(["git", *args], cwd=str(cwd), env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def squash(self, pr, message=None):
        """One squash commit on develop for PR `pr`; returns its sha."""
        self.git(self.seed, "checkout", "-q", "develop")
        self.git(self.seed, "commit", "-q", "--allow-empty", "-m", message or f"change (#{pr})")
        self.sha[pr] = self.git(self.seed, "rev-parse", "HEAD")
        return self.sha[pr]

    def release(self, tag="v0.5.0"):
        self.git(self.seed, "checkout", "-q", "main")
        self.git(self.seed, "merge", "-q", "--no-ff", "develop", "-m", f"Merge release {tag}")
        self.git(self.seed, "tag", "-a", tag, "-m", tag)

    def publish(self, depth=None):
        self.git(self.tmp, "init", "-q", "--bare", str(self.origin))
        self.git(self.seed, "push", "-q", str(self.origin), "main", "develop", "--tags")
        clone = ["clone", "-q"] + (["--depth", str(depth), "--no-single-branch",
                                    f"file://{self.origin}"] if depth else [str(self.origin)])
        self.git(self.tmp, *clone, str(self.work))
        self.git(self.work, "remote", "set-url", "origin", URL)
        self.git(self.work, "config", f"url.{self.origin}.insteadOf", URL)


def pr(n, body, sha, base="develop"):
    return {"number": n, "body": body, "mergeCommit": {"oid": sha}, "baseRefName": base}


def run(repo, fix, *args, cwd=None, **env):
    bindir = repo.tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text("#!" + sys.executable + "\n" + FAKE_GH)
    (bindir / "gh").chmod(0o755)
    fixfile = repo.tmp / "fix.json"
    fixfile.write_text(json.dumps(fix))
    log = repo.tmp / "gh.log"
    log.unlink(missing_ok=True)
    e = dict(repo.env, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FIX=str(fixfile),
             GH_LOG=str(log), GB_PYTHON=sys.executable)
    e.update(env)
    r = subprocess.run(["bash", str(RECONCILE), *args], cwd=str(cwd or repo.work), env=e,
                       capture_output=True, text=True, timeout=120)
    calls = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    return r, calls


def lines(r, prefix):
    return [ln for ln in r.stdout.splitlines() if ln.startswith(prefix)]


# ---- the 2026-10-04 shape ------------------------------------------------------------

def shape(tmp_path):
    """Before v0.5.0: #10 (right), #11 (in a later milestone), #12 (not planned).
    After it: #20-#25 in the closed v0.5, #26 in a themed milestone, #27 in none, #28 right,
    #29 still open."""
    repo = Repo(tmp_path)
    prs, issues = [], {}
    for n, ms, reason in [(10, V05, "COMPLETED"), (11, V06, "COMPLETED"), (12, V06, "NOT_PLANNED")]:
        prs.append(pr(100 + n, f"Closes #{n}", repo.squash(100 + n)))
        issues[str(n)] = issue(n, ms, reason=reason)
    repo.release()
    after = [(20 + i, V05) for i in range(6)] + [(26, OBS), (27, None), (28, V06)]
    for n, ms in after:
        prs.append(pr(100 + n, f"fixes: #{n}\n\nmore text", repo.squash(100 + n)))
        issues[str(n)] = issue(n, ms)
    prs.append(pr(129, "Resolves https://github.com/o/r/issues/29", repo.squash(129)))
    issues["29"] = issue(29, None, state="OPEN", reason=None)
    repo.publish()
    return repo, {"default": "main", "prs": prs, "issues": issues, "milestones": MILESTONES}


EXPECTED_MOVES = ([{"issue": 11, "to": "v0.5"}] + [{"issue": n, "to": "v0.6"} for n in range(20, 28)])


def test_the_2026_10_04_shape_lists_exactly_these_mismatches(tmp_path):
    repo, fix = shape(tmp_path)
    out = tmp_path / "plan.json"
    r, calls = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    got = lines(r, "MISMATCH")
    assert [ln.split(":")[0] for ln in got] == [f"MISMATCH #{m['issue']}" for m in EXPECTED_MOVES]
    by = {int(ln.split("#")[1].split(":")[0]): ln for ln in got}
    assert by[11] == f"MISMATCH #11: PR #111, commit {repo.sha[111][:7]}, in v0.5.0: v0.6 -> v0.5"
    assert by[20] == f"MISMATCH #20: PR #120, commit {repo.sha[120][:7]}, after v0.5.0: v0.5 -> v0.6"
    assert by[26].endswith("after v0.5.0: Observability -> v0.6")
    assert by[27].endswith("after v0.5.0: none -> v0.6")
    assert r.stdout.splitlines()[-1] == "release check: 11 issues checked, 9 mismatches, 0 flagged"
    assert json.loads(out.read_text()) == {"repo": "o/r", "closed_moves": EXPECTED_MOVES}
    # The not-planned #12 and the open #29 are never checked.
    assert "#12:" not in r.stdout and "#29:" not in r.stdout
    assert "lowest open version" in r.stderr


def test_the_json_output_dry_runs_clean_through_apply_plan(tmp_path):
    repo, fix = shape(tmp_path)
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 0, r.stderr
    e = dict(repo.env, PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
             FIX=str(tmp_path / "fix.json"), GH_LOG=str(tmp_path / "gh2.log"))
    ap = subprocess.run(["bash", str(APPLY_PLAN), "--plan", str(out)], env=e,
                        capture_output=True, text=True, timeout=60)
    assert ap.returncode == 0, ap.stdout + ap.stderr
    assert "FIX    #11 -> v0.5 [closed milestone]  (closed_moves: no comment)" in ap.stdout
    assert ap.stdout.count("FIX    #") == 9
    assert "(nothing written)" in ap.stdout


def test_a_clean_run_prints_the_summary_line(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    repo.release()
    prs.append(pr(120, "Closes #20", repo.squash(120)))
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES,
           "issues": {"10": issue(10, V05), "20": issue(20, V06)}}
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == []
    assert r.stdout.splitlines()[-1] == "release check: 2 issues checked, 0 mismatches, 0 flagged"
    assert json.loads(out.read_text()) == {"repo": "o/r", "closed_moves": []}


def test_merged_prs_are_read_for_develop_and_the_default_branch(tmp_path):
    repo, fix = shape(tmp_path)
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    lists = [c for c in calls if c[:2] == ["pr", "list"]]
    assert sorted(c[c.index("--base") + 1] for c in lists) == ["develop", "main"]
    for c in lists:
        assert c[c.index("--state") + 1] == "merged" and c[c.index("--limit") + 1] == "1000"
        assert c[c.index("--repo") + 1] == "o/r"


# ---- the checkout ------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://github.com/other/thing.git", "/some/local/path",
                                 "git@github.com:o/r-fork.git", "https://gitlab.com/o/r.git",
                                 "git@gitlab.com:o/r.git", "ssh://git@evil.example/o/r",
                                 "file:///o/r", "https://github.com.evil.example/o/r"])
def test_a_checkout_of_another_repo_or_host_is_refused_before_any_fetch(tmp_path, url):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "tag", "-d", "v0.5.0")
    repo.git(repo.work, "remote", "set-url", "origin", url)
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 2
    assert "not o/r on github.com" in r.stderr
    assert calls == []
    # The refusal comes before git fetch: the deleted tag is still missing.
    assert repo.git(repo.work, "tag", "--list") == ""


def test_the_refusal_comes_before_a_fetch_that_would_work(tmp_path):
    # The wrong repo's URL is reachable here (rewritten to the local origin), so a script that
    # fetched first would bring the deleted tag back.
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "tag", "-d", "v0.5.0")
    fork = "https://github.com/o/r-fork.git"
    repo.git(repo.work, "remote", "set-url", "origin", fork)
    repo.git(repo.work, "config", f"url.{repo.origin}.insteadOf", fork)
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 2 and calls == []
    assert repo.git(repo.work, "tag", "--list") == ""


@pytest.mark.parametrize("url", ["git@github.com:o/r.git", "ssh://git@github.com/O/R",
                                 "https://github.com/o/r/", "github.com:o/r.git",
                                 "ssh://git@github.com:22/o/r.git", "https://GitHub.com/o/r"])
def test_every_url_form_of_the_right_repo_is_accepted(tmp_path, url):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "remote", "set-url", "origin", url)
    r, _ = run(repo, fix, "--repo", "o/r", "--no-fetch")
    assert r.returncode == 0, r.stderr


def test_gh_host_names_the_only_accepted_host(tmp_path):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "remote", "set-url", "origin", "https://ghe.example.com/o/r.git")
    r, _ = run(repo, fix, "--repo", "o/r", "--no-fetch", GH_HOST="ghe.example.com")
    assert r.returncode == 0, r.stderr
    repo.git(repo.work, "remote", "set-url", "origin", URL)
    r, calls = run(repo, fix, "--repo", "o/r", "--no-fetch", GH_HOST="ghe.example.com")
    assert r.returncode == 2 and calls == []


def test_outside_a_git_checkout_exits_2(tmp_path):
    repo, fix = shape(tmp_path)
    elsewhere = tmp_path / "plain"
    elsewhere.mkdir()
    r, calls = run(repo, fix, "--repo", "o/r", cwd=elsewhere, GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert r.returncode == 2 and calls == []
    assert "not inside a git checkout" in r.stderr


def test_tags_missing_locally_are_fetched_first(tmp_path):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "tag", "-d", "v0.5.0")
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert len(lines(r, "MISMATCH")) == 9
    assert repo.git(repo.work, "tag", "--list") == "v0.5.0"


def test_no_fetch_skips_the_fetch(tmp_path):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "tag", "-d", "v0.5.0")
    r, _ = run(repo, fix, "--repo", "o/r", "--no-fetch")
    assert r.returncode == 0, r.stderr
    assert repo.git(repo.work, "tag", "--list") == ""
    assert "no release tag" in r.stderr


def test_a_failed_fetch_exits_1(tmp_path):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "config", f"url.{tmp_path / 'gone.git'}.insteadOf", URL)
    repo.git(repo.work, "config", "--unset", f"url.{repo.origin}.insteadOf")
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 1
    assert "git fetch --tags origin failed" in r.stderr
    assert not [c for c in calls if c[:2] == ["api", "graphql"]]


def test_a_shallow_clone_is_refused(tmp_path):
    # A shallow clone can hold a merge commit yet miss the history that ties it to its tag,
    # so a shipped issue reads as "after the last tag". Refuse rather than guess.
    repo, fix = shape(tmp_path)
    shutil.rmtree(repo.work)
    repo.git(tmp_path, "clone", "-q", "--depth", "3", "--no-single-branch",
             f"file://{repo.origin}", str(repo.work))
    repo.git(repo.work, "remote", "set-url", "origin", URL)
    repo.git(repo.work, "config", f"url.file://{repo.origin}.insteadOf", URL)
    out = tmp_path / "plan.json"
    r, calls = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 2
    assert "shallow clone: run git fetch --unshallow origin, then re-run" in r.stderr
    assert calls == [] and lines(r, "MISMATCH") == [] and not out.exists()


# ---- the step-5 flag: closed through an abandoned PR -----------------------------------

def test_a_closed_issue_whose_only_linked_pr_never_merged_is_flagged(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(140, "Fixes #40", repo.squash(140)),
           pr(144, "Fixes #44", repo.squash(144))]
    repo.squash(0, "fix the thing\n\nCloses #42")
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {
        "40": issue(40, V05, linked=[(41, False)]),
        "42": issue(42, V05, linked=[(43, False), (45, False)]),
        "44": issue(44, V05, linked=[(44, True), (46, False)])}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    flags = lines(r, "FLAG")
    assert flags == [
        "FLAG #40: closed with only unmerged linked PR(s) #41, but merged PR #140 names it",
        f"FLAG #42: closed with only unmerged linked PR(s) #43 #45, but commit {repo.sha[0][:7]} "
        "on develop names it"]
    # #40 and #44 had their milestones checked; #42, named only by a commit, had not.
    assert r.stdout.splitlines()[-1] == ("release check: 2 issues checked, 0 mismatches, "
                                         "2 flagged, 1 named only by a commit")


def test_an_issue_with_no_linked_pr_is_not_flagged(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(140, "Fixes #40", repo.squash(140))]
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"40": issue(40, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert lines(r, "FLAG") == []


# ---- several PRs, and the edges -----------------------------------------------------------

def test_an_issue_named_by_two_prs_takes_the_earliest_release(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(150, "Closes #50", repo.squash(150))]
    repo.release()
    prs.append(pr(151, "follow-up, fixes #50", repo.squash(151)))
    repo.publish()
    # Listed newest first, as gh does: the order must not decide.
    fix = {"prs": prs[::-1], "milestones": MILESTONES, "issues": {"50": issue(50, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #50: PR #150, commit {repo.sha[150][:7]}, in v0.5.0: v0.6 -> v0.5"
        "; also named by PR #151 (after v0.5.0)"]


def test_an_earlier_patch_release_wins_over_a_later_one(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(160, "Closes #60", repo.squash(160))]
    repo.release("v0.5.0")
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "tag", "-a", "v0.10.0", "-m", "v0.10.0")
    repo.publish()
    ms = MILESTONES + [{"title": "v0.10", "number": 10, "state": "closed"}]
    fix = {"prs": prs, "milestones": ms, "issues": {"60": issue(60, {"number": 10, "title": "v0.10"})}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #60: PR #160, commit {repo.sha[160][:7]}, in v0.5.0: v0.10 -> v0.5"]


def test_a_tag_with_no_milestone_is_a_note_not_a_mismatch(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    repo.release("v0.9.0")
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == []
    assert "no milestone titled 0.9.0 or 0.9 for v0.9.0" in r.stdout
    assert r.stdout.splitlines()[-1] == "release check: 0 issues checked, 0 mismatches, 0 flagged"


def test_no_next_release_milestone_is_a_note(tmp_path):
    repo = Repo(tmp_path)
    repo.release()
    prs = [pr(120, "Closes #20", repo.squash(120))]
    repo.publish()
    ms = [m for m in MILESTONES if m["state"] == "closed"]
    fix = {"prs": prs, "milestones": ms, "issues": {"20": issue(20, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == []
    assert "no next-release milestone" in r.stderr
    assert "NOTE #20" in r.stdout


def test_a_reference_to_a_pr_or_a_missing_number_is_skipped(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(170, "Closes #71 and fixes #99999", repo.squash(170))]
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES,
           "issues": {"71": issue(71, None, typename="PullRequest")}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "release check: 0 issues checked, 0 mismatches, 0 flagged"
    assert "#99999" in r.stdout and "not found" in r.stdout


def test_only_this_repos_references_count(tmp_path):
    repo = Repo(tmp_path)
    body = ("Fixes other/repo#10, closes https://github.com/other/repo/issues/10, "
            "see #10, fixes o/r#11, closes https://github.com/o/r/issues/12")
    prs = [pr(180, body, repo.squash(180))]
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V06), "11": issue(11, V06), "12": issue(12, V06)}}
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    nums = sorted(x[4:] for c in calls if c[:2] == ["api", "graphql"] for x in c if x.startswith("num="))
    assert nums == ["11", "12"]


# ---- read failures and usage --------------------------------------------------------------

@pytest.mark.parametrize("env,why", [
    pytest.param({"FAIL_PR_LIST": "develop"}, "502", id="pr-list-fails"),
    pytest.param({"EMPTY_PR_LIST": "main"}, "no output", id="pr-list-empty"),
    pytest.param({"FAIL_MS": "1"}, "could not list milestones", id="milestones-fail"),
])
def test_a_failed_read_exits_1(tmp_path, env, why):
    repo, fix = shape(tmp_path)
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out), **env)
    assert r.returncode == 1, r.stdout
    assert why in r.stderr
    assert not out.exists()


def test_an_unreadable_issue_makes_the_run_incomplete(tmp_path):
    repo, fix = shape(tmp_path)
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out), FAIL_ISSUE="20")
    assert r.returncode == 1
    assert "1 issue(s) could not be checked: #20" in r.stdout + r.stderr
    assert len(lines(r, "MISMATCH")) == 8
    assert not out.exists()


def test_a_null_issue_reply_is_unreadable_not_skipped(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": None}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 1
    assert "unexpected reply" in r.stderr and "could not be checked: #10" in r.stdout


def test_a_full_page_of_merged_prs_makes_the_run_incomplete(tmp_path):
    repo = Repo(tmp_path)
    sha = repo.squash(1)
    repo.publish()
    prs = [pr(n, "", sha) for n in range(1, 1001)]
    out = tmp_path / "plan.json"
    r, _ = run(repo, {"prs": prs, "milestones": MILESTONES, "issues": {}}, "--repo", "o/r",
               "--json", str(out))
    assert r.returncode == 1
    assert "1000 merged PRs into develop" in r.stderr and "into main" not in r.stderr
    assert "past the 1000-PR limit" in r.stdout and not out.exists()


@pytest.mark.parametrize("merge_commit", [None, {}, "absent"])
def test_a_merged_pr_without_a_merge_commit_makes_the_run_incomplete(tmp_path, merge_commit):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110)), pr(111, "Closes #11", "x")]
    if merge_commit == "absent":
        del prs[1]["mergeCommit"]
    else:
        prs[1]["mergeCommit"] = merge_commit
    repo.release()
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V06), "11": issue(11, V06)}}
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 1
    assert "#111 (no merge commit)" in r.stdout and not out.exists()


def test_an_old_json_file_is_deleted_even_when_the_run_fails(tmp_path):
    repo, fix = shape(tmp_path)
    out = tmp_path / "plan.json"
    for args, env in (((), {"FAIL_MS": "1"}), (("--repo", "o"), {})):
        out.write_text('{"repo": "o/r", "closed_moves": [{"issue": 1, "to": "v0.1"}]}')
        r, _ = run(repo, fix, *(args or ("--repo", "o/r")), "--json", str(out), **env)
        assert r.returncode != 0
        assert not out.exists(), "a stale plan survived a failed run"


@pytest.mark.parametrize("args", [[], ["--repo"], ["--repo", "o"], ["--repo", "o/.."],
                                  ["--repo", "o/r", "--json"], ["--repo", "o/r", "--bogus"]])
def test_usage_errors_exit_2(tmp_path, args):
    repo, fix = shape(tmp_path)
    r, calls = run(repo, fix, *args)
    assert r.returncode == 2, r.stdout + r.stderr
    assert calls == []


@pytest.mark.parametrize("bad", ["o", "o/..", "./r", "o/r/x"])
def test_a_malformed_repo_is_a_usage_error_before_the_checkout_is_read(tmp_path, bad):
    repo, fix = shape(tmp_path)
    repo.git(repo.work, "remote", "set-url", "origin", f"https://github.com/{bad}.git")
    r, calls = run(repo, fix, "--repo", bad)
    assert r.returncode == 2 and calls == []
    assert "--repo must be OWNER/REPO" in r.stderr


def _one_side(tmp_path, inside):
    repo = Repo(tmp_path)
    if inside:
        prs = [pr(110, "Closes #10", repo.squash(110))]
        repo.release()
    else:
        repo.release()
        prs = [pr(120, "Closes #20", repo.squash(120))]
    repo.publish()
    n = "10" if inside else "20"
    return repo, {"prs": prs, "milestones": MILESTONES, "issues": {n: issue(int(n), OBS)}}


@pytest.mark.parametrize("inside", [True, False], ids=["tag-milestone", "next-release"])
def test_an_unreadable_milestone_list_exits_1_on_either_path(tmp_path, inside):
    # One issue inside the tag (tag -> milestone) or one after it (next release): each path
    # must stop on its own, not rely on the other one running later.
    repo, fix = _one_side(tmp_path, inside)
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out), FAIL_MS="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not list milestones" in r.stderr
    assert lines(r, "MISMATCH") == [] and not out.exists()


def test_a_tag_that_is_not_a_version_is_ignored(tmp_path):
    repo = Repo(tmp_path)
    repo.release()
    prs = [pr(120, "Closes #20", repo.squash(120))]
    repo.git(repo.seed, "tag", "x-build")          # sorts after v0.5.0, contains the commit
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"20": issue(20, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #20: PR #120, commit {repo.sha[120][:7]}, after v0.5.0: v0.5 -> v0.6"]


# ---- the skill lists step 0 ------------------------------------------------------------------

@pytest.mark.parametrize("workflow,count", [("refocus", 7), ("audit-only", 4)])
def test_the_task_manifest_starts_with_the_release_check(workflow, count):
    r = subprocess.run(["bash", str(SCRIPTS / "task-manifest.sh"), workflow],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    tasks = json.loads(r.stdout)
    assert len(tasks) == count
    assert "release-reconcile.sh" in tasks[0]["description"]


def test_skill_md_has_step_0_and_its_task_row():
    text = (SKILLS_DIR / "plan-milestones" / "SKILL.md").read_text()
    assert "### 0. Release check (every invocation)" in text
    assert "| 0 | Check closed issues against their releases |" in text
    assert text.index("### 0. Release check") < text.index("### 1. Gather")
    assert '"${CLAUDE_SKILL_DIR}/scripts/release-reconcile.sh" --repo O/R' in text


# ---- PR #206 review round 1 -----------------------------------------------------------------

def squashed_release(repo, tag="v0.5.0"):
    """release/* squashed into main: the tag holds a new commit, not develop's history."""
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "merge", "-q", "--squash", "develop")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", f"Release {tag} (squash)")
    repo.git(repo.seed, "tag", "-a", tag, "-m", tag)


def test_a_squashed_release_leaves_work_merged_before_it_alone(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110)), pr(111, "Closes #11", repo.squash(111))]
    squashed_release(repo)
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES,
           "issues": {"10": issue(10, V05), "11": issue(11, V06)}}
    out = tmp_path / "plan.json"
    r, _ = run(repo, fix, "--repo", "o/r", "--json", str(out))
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == []
    assert lines(r, "NOTE") == [
        "NOTE #10: PR #110 merged before v0.5.0 but no tag contains it (squashed release?); "
        "milestone left as v0.5",
        "NOTE #11: PR #111 merged before v0.5.0 but no tag contains it (squashed release?); "
        "milestone left as v0.6"]
    assert r.stdout.splitlines()[-1] == "release check: 0 issues checked, 0 mismatches, 0 flagged"
    assert json.loads(out.read_text())["closed_moves"] == []


def test_after_a_squashed_release_later_work_still_mismatches(tmp_path):
    repo = Repo(tmp_path)
    repo.squash(100)
    squashed_release(repo)
    prs = [pr(120, "Closes #20", repo.squash(120))]
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"20": issue(20, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #20: PR #120, commit {repo.sha[120][:7]}, after v0.5.0: v0.5 -> v0.6"]


def test_a_lightweight_last_tag_uses_its_commit_date(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", "release")
    repo.git(repo.seed, "tag", "v0.5.0")
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [] and len(lines(r, "NOTE #10: PR #110 merged before v0.5.0")) == 1


def test_a_shipped_milestone_left_open_is_not_the_next_release(tmp_path):
    repo = Repo(tmp_path)
    repo.release()
    prs = [pr(120, "Closes #20", repo.squash(120))]
    repo.publish()
    ms = [dict(m, state="open") if m["title"] == "v0.5" else m for m in MILESTONES]
    fix = {"prs": prs, "milestones": ms, "issues": {"20": issue(20, V05)}}
    r, calls = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #20: PR #120, commit {repo.sha[120][:7]}, after v0.5.0: v0.5 -> v0.6"]
    # The local newest tag is passed in: no tag list is read from GitHub.
    assert not [c for c in calls if any("/tags" in x for x in c)]


def test_mixed_tag_prefixes_are_ordered_by_version(tmp_path):
    # git's v:refname puts "1.3.0" before "v1.2.0" and "2.0" before "v1.0".
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    for tag in ("v1.2.0", "1.3.0", "v1.10.0", "2.0"):
        repo.git(repo.seed, "checkout", "-q", "main")
        repo.git(repo.seed, "merge", "-q", "--no-ff", "develop", "-m", f"Merge {tag}")
        repo.git(repo.seed, "tag", "-a", tag, "-m", tag)
        repo.git(repo.seed, "checkout", "-q", "develop")
        repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", f"after {tag}")
    prs.append(pr(120, "Closes #20", repo.squash(120)))
    repo.publish()
    ms = MILESTONES + [{"title": "v1.2", "number": 12, "state": "closed"},
                       {"title": "v2.1", "number": 21, "state": "open"}]
    fix = {"prs": prs, "milestones": ms, "issues": {"10": issue(10, V06), "20": issue(20, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #10: PR #110, commit {repo.sha[110][:7]}, in v1.2.0: v0.6 -> v1.2",
        f"MISMATCH #20: PR #120, commit {repo.sha[120][:7]}, after 2.0: v0.6 -> v2.1"]


def test_ten_or_more_tags_rank_numerically(tmp_path):
    # v0.9 is rank 9 and v0.10 rank 10: a text sort of the ranks would put 10 first.
    repo = Repo(tmp_path)
    prs = []
    for i in range(1, 13):
        if i == 9:
            prs.append(pr(190, "Closes #50", repo.squash(190)))
        if i == 10:
            prs.append(pr(200, "Closes #50", repo.squash(200)))
        repo.release(f"v0.{i}")
    repo.publish()
    ms = MILESTONES + [{"title": "v0.9", "number": 9, "state": "closed"}]
    fix = {"prs": prs, "milestones": ms, "issues": {"50": issue(50, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #50: PR #190, commit {repo.sha[190][:7]}, in v0.9: v0.6 -> v0.9"
        "; also named by PR #200 (in v0.10)"]


def test_hotfix_with_higher_pr_number_ships_first(tmp_path):
    # #150 lands on develop after v0.5.0 (unreleased); hotfix #160 on main is tagged v0.5.1.
    repo = Repo(tmp_path)
    repo.release("v0.5.0")
    prs = [pr(150, "Closes #50", repo.squash(150))]
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", "hotfix (#160)")
    repo.sha[160] = repo.git(repo.seed, "rev-parse", "HEAD")
    repo.git(repo.seed, "tag", "-a", "v0.5.1", "-m", "v0.5.1")
    prs.append(pr(160, "Fixes #50", repo.sha[160], base="main"))
    repo.publish()
    ms = MILESTONES + [{"title": "v0.5.1", "number": 51, "state": "closed"}]
    fix = {"prs": prs, "milestones": ms, "issues": {"50": issue(50, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #50: PR #160, commit {repo.sha[160][:7]}, in v0.5.1: v0.6 -> v0.5.1"
        "; also named by PR #150 (after v0.5.1)"]


def test_tag_off_every_branch_is_fetched(tmp_path):
    # A tag pushed after the clone, on a commit no branch reaches: only --tags brings it.
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    repo.publish()
    repo.git(repo.seed, "checkout", "-q", "--detach", "develop")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", "release build")
    repo.git(repo.seed, "tag", "-a", "v0.5.0", "-m", "v0.5.0")
    repo.git(repo.seed, "push", "-q", str(repo.origin), "v0.5.0")
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert repo.git(repo.work, "tag", "--list") == "v0.5.0"
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #10: PR #110, commit {repo.sha[110][:7]}, in v0.5.0: v0.6 -> v0.5"]


def test_a_flag_names_the_branch_the_commit_is_on(tmp_path):
    repo = Repo(tmp_path)
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", "hotfix\n\nCloses #42")
    sha = repo.git(repo.seed, "rev-parse", "HEAD")
    repo.publish()
    fix = {"prs": [], "milestones": MILESTONES,
           "issues": {"42": issue(42, V05, linked=[(43, False)])}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "FLAG") == [
        f"FLAG #42: closed with only unmerged linked PR(s) #43, but commit {sha[:7]} on main names it"]


def test_without_origin_branches_commit_evidence_is_unavailable(tmp_path):
    repo, fix = shape(tmp_path)
    for b in ("develop", "main"):
        repo.git(repo.work, "update-ref", "-d", f"refs/remotes/origin/{b}")
    repo.git(repo.work, "update-ref", "-d", "refs/remotes/origin/HEAD")
    r, _ = run(repo, fix, "--repo", "o/r", "--no-fetch")
    assert r.returncode == 0, r.stderr
    assert "neither origin/develop nor origin/main exists here" in r.stderr


def test_a_merge_in_the_same_second_as_the_last_tag_counts_as_before_it(tmp_path):
    # The boundary: a squashed release tagged in the very second the PR merged. "Before or
    # at" keeps the shipped milestone; "after" would move it out.
    repo = Repo(tmp_path)
    prs = [pr(110, "Closes #10", repo.squash(110))]
    stamp = repo.git(repo.seed, "log", "-1", "--format=%ct", repo.sha[110])
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", "Release v0.5.0 (squash)")
    env = dict(repo.env, GIT_COMMITTER_DATE=f"@{stamp} +0000")
    subprocess.run(["git", "tag", "-a", "v0.5.0", "-m", "v0.5.0"], cwd=str(repo.seed), env=env,
                   check=True, capture_output=True)
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"10": issue(10, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == [] and len(lines(r, "NOTE #10: PR #110 merged before")) == 1


# ---- hotfix tags are ignored for the squash date test ---------------------------------------

def hotfix(repo, pr_num, tag):
    repo.git(repo.seed, "checkout", "-q", "main")
    repo.git(repo.seed, "commit", "-q", "--allow-empty", "-m", f"hotfix (#{pr_num})")
    repo.sha[pr_num] = repo.git(repo.seed, "rev-parse", "HEAD")
    repo.git(repo.seed, "tag", "-a", tag, "-m", tag)
    return repo.sha[pr_num]


def test_develop_work_merged_before_a_hotfix_tag_moves_to_the_next_release(tmp_path):
    # #150 merged after v0.5.0 and before hotfix v0.5.1: no tag holds it, and it is newer
    # than the newest release tag (v0.5.0), so it is unreleased work, not a squash.
    repo = Repo(tmp_path)
    repo.release("v0.5.0")
    prs = [pr(150, "Closes #50", repo.squash(150))]
    hotfix(repo, 160, "v0.5.1")
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"50": issue(50, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "NOTE") == []
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #50: PR #150, commit {repo.sha[150][:7]}, after v0.5.1: v0.5 -> v0.6"]


@pytest.mark.parametrize("tag", ["v0.6.0", "v0.6"], ids=["three-part", "two-part"])
def test_a_squashed_release_after_a_hotfix_still_gets_the_note(tmp_path, tag):
    repo = Repo(tmp_path)
    repo.release("v0.5.0")
    hotfix(repo, 160, "v0.5.1")
    prs = [pr(170, "Closes #70", repo.squash(170))]
    squashed_release(repo, tag)
    hotfix(repo, 180, f"{tag}.1" if tag == "v0.6" else "v0.6.1")
    repo.publish()
    ms = MILESTONES + [{"title": "v0.6.1", "number": 61, "state": "open"}]
    fix = {"prs": prs, "milestones": ms, "issues": {"70": issue(70, V06)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "MISMATCH") == []
    assert lines(r, "NOTE") == [
        f"NOTE #70: PR #170 merged before {tag} but no tag contains it (squashed release?); "
        "milestone left as v0.6"]


def test_with_only_hotfix_tags_no_date_test_applies(tmp_path):
    repo = Repo(tmp_path)
    prs = [pr(150, "Closes #50", repo.squash(150))]
    hotfix(repo, 160, "v0.5.1")
    repo.publish()
    fix = {"prs": prs, "milestones": MILESTONES, "issues": {"50": issue(50, V05)}}
    r, _ = run(repo, fix, "--repo", "o/r")
    assert r.returncode == 0, r.stderr
    assert lines(r, "NOTE") == []
    assert lines(r, "MISMATCH") == [
        f"MISMATCH #50: PR #150, commit {repo.sha[150][:7]}, after v0.5.1: v0.5 -> v0.6"]
