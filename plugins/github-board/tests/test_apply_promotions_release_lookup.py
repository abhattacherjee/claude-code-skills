"""Release lookup: page correctly, and never cache a failure as an empty list.

`gh api --paginate` applies `--jq` to EACH PAGE separately, so a sort inside the
--jq filter only orders within a page. GitHub returns releases newest-first, so
the loop walked the newest page before any older one and stamped the issue with a
too-new tag -- breaking the script's own "oldest containing release" contract.

And a failed listing must not be cached as `[]`: that suppresses the release
comment for every remaining item in the repo and reports it as "no release
contains <sha>", which asserts a fact never established.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts" / "apply-promotions.sh"
SHA = "abc123"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="apply-promotions.sh requires jq"
)

# Newest-first, one release per page -- exactly how the REST API returns them.
_PAGE_NEW = '[{"tag_name":"v2.0.0","html_url":"u2","published_at":"2026-02-01T00:00:00Z","draft":false}]'
_PAGE_OLD = '[{"tag_name":"v1.0.0","html_url":"u1","published_at":"2026-01-01T00:00:00Z","draft":false}]'

# The stub must model the behaviour under test: `gh api --paginate` applies --jq
# to EACH PAGE SEPARATELY. A stub that ignored --jq made the bug invisible --
# re-introducing the per-page filter left the test green, because the script's
# own combine step still sorted the unfiltered pages correctly.
_PAGINATED_RELEASES = """
      _jq=""; _prev=""
      for _a in "$@"; do [ "$_prev" = "--jq" ] && _jq="$_a"; _prev="$_a"; done
      for _p in '%s' '%s'; do
        if [ -n "$_jq" ]; then printf '%%s' "$_p" | jq "$_jq"; else printf '%%s\\n' "$_p"; fi
      done
      exit 0""" % (_PAGE_NEW, _PAGE_OLD)

# The stub models both axes `gh auth status` has: --active picks one account
# WITHIN a host, --hostname picks the host. Without --hostname, gh reports every
# known host, which is the fail-open the tests below pin.
_STUB = """#!/usr/bin/env bash
if [ "$1 $2" = "auth status" ]; then
  _host=""; _prev=""; _active=0
  for _a in "$@"; do
    [ "$_prev" = "--hostname" ] && _host="$_a"
    [ "$_a" = "--active" ] && _active=1
    _prev="$_a"
  done
  case "$_host" in
%(per_host_cases)s
    "") printf '%%s\\n' %(all_hosts)s ;;
    *)  echo "You are not logged into any accounts on $_host" ;;
  esac
  exit 0
fi
if [ "$1" = "api" ]; then
  case "$2" in
    */releases) %(releases)s ;;
    */compare/*) %(compare)s ;;
    graphql) echo '{"data":{}}'; exit 0 ;;
  esac
fi
exit 1
"""


def _sh_lines(lines):
    """Render a list of output lines as single-quoted shell words.

    Refuses an empty list on purpose: it would render as `printf '%s\\n' ''`,
    i.e. a blank line, which the script reads as "scopes unreadable" and takes the
    warn-and-proceed path. A fixture that silently produces the state under test
    from a MISTAKE is how a scope test passes while proving nothing -- so make it
    an error and force the caller to say `active=["Token scopes: none"]` when it
    actually wants that state.
    """
    if not lines:
        raise ValueError("empty auth-status output would fake the "
                         "'scopes unreadable' path; pass the lines explicitly")
    return " ".join("'" + ln.replace("'", "'\\''") + "'" for ln in lines)


def _stub_gh(tmp_path, releases, scopes="'project'", active=None, all_hosts=None,
             per_host=None, compare='echo "ahead"; exit 0'):
    """Model `gh auth status` output.

    active     lines for the active account on the DEFAULT host (github.com)
    per_host   {hostname: [lines]} when a test needs different hosts to differ
    all_hosts  lines printed when no --hostname is passed (every known host)
    """
    if active is None:
        active = ["  - Token scopes: 'gist', 'repo', %s" % scopes]
    if per_host is None:
        per_host = {"github.com": active}
    if all_hosts is None:
        all_hosts = active
    # Each host block honours --active too, so BOTH axes are modelled: a host can
    # have several accounts and only the active one is the one that will be used.
    # Without this the --active flag would be unpinned -- removing it from the
    # script would leave every test green.
    def _block(host, spec):
        if isinstance(spec, dict):
            act, allacc = spec["active"], spec["all"]
        else:
            act = allacc = spec
        return ("    %s)\n"
                "      if [ \"$_active\" = \"1\" ]; then printf '%%s\\n' %s\n"
                "      else printf '%%s\\n' %s; fi ;;"
                % (host, _sh_lines(act), _sh_lines(allacc)))
    cases = "\n".join(_block(h, s) for h, s in per_host.items())
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(_STUB % {"releases": releases,
                           "per_host_cases": cases,
                           "compare": compare,
                           "all_hosts": _sh_lines(all_hosts)})
    gh.chmod(0o755)
    return bindir


def _candidate(item_id, number):
    return {
        "itemId": item_id, "number": number, "title": "shipped thing",
        "status": "Dev Complete", "url": f"https://github.com/o/r/issues/{number}",
        "repo": "o/r", "promoteClass": "merged",
        "mergedPRs": [{"number": 8, "baseRefName": "develop",
                       "mergeCommitOid": SHA, "repo": "o/r", "inMain": "yes"}],
    }


def _run(tmp_path, bindir, *args, candidates=None):
    path = tmp_path / "cand.json"
    path.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status", "doneOptionId": "opt_done"},
        "candidates": candidates or [_candidate("PVTI_1", 7)],
    }))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(["bash", str(SCRIPT), str(path), *args],
                          capture_output=True, text=True, env=env, cwd=str(tmp_path))


def test_oldest_containing_release_wins_across_pages(tmp_path):
    bindir = _stub_gh(tmp_path, _PAGINATED_RELEASES)
    done = _run(tmp_path, bindir, "--dry-run")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "v1.0.0 (auto-detected)" in done.stdout, (
        "picked a release from the first page only -- --paginate sorts per page"
    )
    assert "v2.0.0" not in done.stdout


def test_failed_compare_does_not_claim_the_next_release(tmp_path):
    """A failed compare is not "this release does not contain the commit".

    The list is walked oldest-first, so falling through on error means one
    transient 5xx on the TRUE container lets the next, newer release answer
    `ahead` -- stamping the issue with a too-new tag. That is the same wrong-tag
    outcome the pagination fix exists to prevent, arriving through the error path.
    """
    bindir = _stub_gh(tmp_path, _PAGINATED_RELEASES,
                      compare='echo "gh: HTTP 502" >&2; exit 1')
    done = _run(tmp_path, bindir, "--dry-run")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "v1.0.0" not in done.stdout and "v2.0.0" not in done.stdout, (
        f"claimed a release tag despite being unable to compare\n{done.stdout}"
    )
    assert "WARN: compare failed" in done.stderr
    assert "UNAVAILABLE" in done.stdout
    assert "no release contains" not in done.stdout


def test_an_unavailable_verdict_is_not_cached(tmp_path):
    """A transient compare failure must not suppress the tag for the whole run.

    The per-(repo,sha) cache exists to avoid re-asking. Storing "unavailable" in
    it would turn one 5xx into a run-wide silence, which is why the sentinel
    returns before the `tee`. Here the compare fails once and then recovers; the
    second item, same repo and SHA, must still get its tag.
    """
    counter = tmp_path / "compare-calls"
    bindir = _stub_gh(
        tmp_path, _PAGINATED_RELEASES,
        compare=(f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); '
                 f'echo "$n" > "{counter}"; '
                 f'if [ "$n" = "1" ]; then echo "gh: HTTP 502" >&2; exit 1; fi; '
                 f'echo "ahead"; exit 0'),
    )
    done = _run(tmp_path, bindir, "--dry-run",
                candidates=[_candidate("PVTI_1", 7), _candidate("PVTI_2", 8)])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WARN: compare failed" in done.stderr
    assert "v1.0.0 (auto-detected)" in done.stdout, (
        f"the recovered lookup was suppressed by a cached failure\n{done.stdout}"
    )


def test_failed_release_listing_is_visible_not_cached_as_empty(tmp_path):
    bindir = _stub_gh(tmp_path, 'echo "gh: HTTP 401: Bad credentials" >&2; exit 1')
    done = _run(tmp_path, bindir, "--dry-run")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WARN: could not list releases" in done.stderr
    assert "UNAVAILABLE" in done.stdout
    assert "no release contains" not in done.stdout, (
        "an API failure was reported as a checked-and-empty result"
    )


def test_apply_requires_the_write_capable_project_scope(tmp_path):
    """A read-only token must be rejected BEFORE the first mutation, not N times."""
    bindir = _stub_gh(tmp_path, "exit 1", scopes="'read:project'")
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 3
    assert "lacks the write-capable 'project' scope" in done.stderr


def test_scope_check_reads_only_the_active_account(tmp_path):
    """N1: a scope held by ANOTHER account on the same host must not count.

    One host can hold several accounts and `gh auth status` prints a "Token
    scopes" line for each, so a grep over the unfiltered output passes when any
    of them has `project`. Only the ACTIVE account is the one that will be used.
    (The sibling host case is `test_scope_check_is_pinned_to_the_target_host`.)
    """
    bindir = _stub_gh(
        tmp_path, "exit 1",
        per_host={"github.com": {
            # the account in use is read-only; a second account on the SAME host
            # can write, and without --active gh reports both.
            "active": ["github.com", "  - Active account: true",
                       "  - Token scopes: 'read:project', 'repo'"],
            "all": ["github.com", "  - Active account: true",
                    "  - Token scopes: 'read:project', 'repo'",
                    "  - Active account: false",
                    "  - Token scopes: 'project', 'repo'"],
        }},
        all_hosts=["github.com", "  - Token scopes: 'read:project', 'repo'"],
    )
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 3, (
        "a scope held on a DIFFERENT host satisfied the gate for this one"
    )
    assert "lacks the write-capable 'project' scope" in done.stderr


def test_scope_check_is_pinned_to_the_target_host(tmp_path):
    """N10: --active alone does not cut the report down to ONE host.

    `gh auth status` reports "on each known GitHub host", so --active picks the
    active account WITHIN each host and still prints them all. The mutation runs
    against $GH_HOST (default github.com), so the scope must be read from that
    host alone. Here github.com is read-only and a GHES host is write-capable.
    """
    bindir = _stub_gh(
        tmp_path, "exit 1",
        per_host={"github.com": ["github.com", "  - Token scopes: 'read:project', 'repo'"],
                  "ghe.example.com": ["ghe.example.com", "  - Token scopes: 'project', 'repo'"]},
        all_hosts=["github.com", "  - Token scopes: 'read:project', 'repo'",
                   "ghe.example.com", "  - Token scopes: 'project', 'repo'"],
    )
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 3, (
        "a scope held on a DIFFERENT host satisfied the gate for the host the "
        "mutation actually targets"
    )
    assert "lacks the write-capable 'project' scope" in done.stderr


def test_no_login_on_the_target_host_warns_rather_than_hard_fails(tmp_path):
    """No account on that host prints no scopes line, so it must warn, not exit 3."""
    bindir = _stub_gh(tmp_path, "exit 1", per_host={"other.example.com": ["x"]},
                      all_hosts=["x"])
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 0, done.stderr
    assert "UNVERIFIED" in done.stderr


@pytest.mark.parametrize("scopes_line, label", [
    ("  - Token scopes: none", "fine-grained PAT reports no OAuth scopes"),
    ("  - Token scopes: 'none'", "quoted none"),
    (None, "no scopes line at all (bare GH_TOKEN)"),
])
def test_unreadable_scopes_warn_and_proceed(tmp_path, scopes_line, label):
    """N2: "no scopes reported" is UNKNOWN, not "scope absent".

    A fine-grained PAT carries permissions rather than OAuth scopes and reports
    `none`; a bare GH_TOKEN often prints no scopes line. Both can be fully
    Projects-write capable, so hard-failing blocks a valid setup — and the
    `gh auth refresh` remediation is a dead end for a PAT. The run must proceed
    and let the first real mutation surface any actual permission error.
    """
    lines = ["github.com"] + ([scopes_line] if scopes_line else [])
    bindir = _stub_gh(tmp_path, "exit 1", active=lines)
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 0, f"{label}: blocked a possibly-valid token\n{done.stderr}"
    assert "UNVERIFIED" in done.stderr
    assert "gh auth refresh" not in done.stderr, (
        "offered an OAuth-only remedy to a token that may not be an OAuth login"
    )


def test_reported_scopes_without_project_still_hard_fail(tmp_path):
    """Control for the above: the warn path must not swallow a real read-only token."""
    bindir = _stub_gh(tmp_path, "exit 1", scopes="'read:project'")
    done = _run(tmp_path, bindir, "--apply", "--no-release-comment")

    assert done.returncode == 3
    assert "Projects" in done.stderr, "no PAT-specific remediation offered"


def test_dry_run_does_not_require_the_write_scope(tmp_path):
    """Negative control: preview writes nothing, so it must stay usable read-only."""
    bindir = _stub_gh(tmp_path, "exit 1", scopes="'read:project'")
    done = _run(tmp_path, bindir, "--dry-run", "--no-release-comment")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "would: Dev Complete" in done.stdout
