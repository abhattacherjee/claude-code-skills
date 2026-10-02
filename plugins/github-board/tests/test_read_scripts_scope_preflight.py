"""The READ scripts must scope their preflight to the host they will query.

`gh auth status` reports "on each known GitHub host" and can list several
accounts per host, so the unscoped form passed whenever ANY login held
`read:project` -- including an unrelated GHES account. The preflight then
approved a token that cannot read the target board, and the run failed later at
the GraphQL call: the exact outcome the preflight exists to prevent.

The write path was fixed for this (N1/N10) and these two were not, which is how
the check came to have two shapes in one directory. The last test in this file
pins all three call sites to one form.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts"
DISCOVER = SCRIPTS / "discover-boards.sh"
INVENTORY = SCRIPTS / "inventory-board.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="requires jq")

_META = ('{"data":{"node":{"id":"PVT_1","title":"B","number":1,"fields":{"nodes":'
         '[{"id":"F","name":"Status","options":[{"id":"D","name":"Done"}]}]}}}}')
_ITEMS = ('{"data":{"node":{"items":{"pageInfo":{"hasNextPage":false,'
          '"endCursor":null},"nodes":[]}}}}')
_BOARDS = '{"data":{"repository":{"projectsV2":{"nodes":[]}}}}'

_STUB = """#!/usr/bin/env bash
if [ "$1 $2" = "auth status" ]; then
  _host=""; _prev=""; _active=0
  for _a in "$@"; do
    [ "$_prev" = "--hostname" ] && _host="$_a"
    [ "$_a" = "--active" ] && _active=1
    _prev="$_a"
  done
  case "$_host" in
%(cases)s
    "") printf '%%s\\n' %(all_hosts)s ;;
    *)  echo "You are not logged into any accounts on $_host" ;;
  esac
  exit 0
fi
if [ "$1 $2" = "api graphql" ]; then
  for _a in "$@"; do
    case "$_a" in
      *"items(first:100"*) echo '%(items)s'; exit 0 ;;
      *"fields(first:50"*) echo '%(meta)s'; exit 0 ;;
      *"projectsV2(first:50"*) echo '%(boards)s'; exit 0 ;;
    esac
  done
fi
exit 1
"""


def _sh(lines):
    return " ".join("'" + ln.replace("'", "'\\''") + "'" for ln in lines)


def _stub_gh(tmp_path, per_host, all_hosts):
    cases = "\n".join(
        "    %s)\n      if [ \"$_active\" = \"1\" ]; then printf '%%s\\n' %s\n"
        "      else printf '%%s\\n' %s; fi ;;"
        % (host, _sh(spec["active"]), _sh(spec["all"]))
        for host, spec in per_host.items()
    )
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(_STUB % {"cases": cases, "all_hosts": _sh(all_hosts),
                           "items": _ITEMS, "meta": _META, "boards": _BOARDS})
    gh.chmod(0o755)
    return bindir


def _run(script, bindir, tmp_path):
    args = ([str(script), "owner", "repo", "--json"] if script == DISCOVER
            else [str(script), "--board-id", "PVT_1"])
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(["bash", *args], capture_output=True, text=True,
                          env=env, cwd=str(tmp_path))


SCRIPT_IDS = [pytest.param(DISCOVER, id="discover-boards"),
              pytest.param(INVENTORY, id="inventory-board")]


@pytest.mark.parametrize("script", SCRIPT_IDS)
def test_scope_on_another_host_does_not_satisfy_the_check(script, tmp_path):
    """A `read:project` held on a GHES login must not approve a github.com run."""
    bindir = _stub_gh(
        tmp_path,
        per_host={"github.com": {"active": ["github.com", "  - Token scopes: 'repo'"],
                                 "all": ["github.com", "  - Token scopes: 'repo'"]},
                  "ghe.example.com": {"active": ["  - Token scopes: 'read:project'"],
                                      "all": ["  - Token scopes: 'read:project'"]}},
        all_hosts=["github.com", "  - Token scopes: 'repo'",
                   "ghe.example.com", "  - Token scopes: 'read:project'"],
    )
    done = _run(script, bindir, tmp_path)

    assert done.returncode == 3, (
        f"{script.name}: a scope held on another host satisfied the gate\n{done.stderr}"
    )
    assert "lacks the 'read:project' scope" in done.stderr


@pytest.mark.parametrize("script", SCRIPT_IDS)
def test_scope_held_by_another_account_on_the_same_host_does_not_count(script, tmp_path):
    bindir = _stub_gh(
        tmp_path,
        per_host={"github.com": {
            "active": ["github.com", "  - Token scopes: 'repo'"],
            "all": ["github.com", "  - Token scopes: 'repo'",
                    "  - Token scopes: 'read:project'"],
        }},
        all_hosts=["github.com", "  - Token scopes: 'repo'"],
    )
    done = _run(script, bindir, tmp_path)

    assert done.returncode == 3, done.stderr
    assert "lacks the 'read:project' scope" in done.stderr


@pytest.mark.parametrize("script", SCRIPT_IDS)
def test_scope_present_on_the_target_host_passes(script, tmp_path):
    """Negative control: the scoped check must not reject a correct token."""
    bindir = _stub_gh(
        tmp_path,
        per_host={"github.com": {
            "active": ["github.com", "  - Token scopes: 'read:project', 'repo'"],
            "all": ["github.com", "  - Token scopes: 'read:project', 'repo'"],
        }},
        all_hosts=["github.com", "  - Token scopes: 'read:project', 'repo'"],
    )
    done = _run(script, bindir, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("script", SCRIPT_IDS)
def test_unreadable_scopes_warn_and_proceed(script, tmp_path):
    """A fine-grained PAT reports `none` and can still read Projects.

    Same three-way verdict as the write path: unknown is not absent, and
    `gh auth refresh` cannot fix a PAT, so hard-failing offers a remedy that
    cannot work.
    """
    bindir = _stub_gh(
        tmp_path,
        per_host={"github.com": {"active": ["github.com", "  - Token scopes: none"],
                                 "all": ["github.com", "  - Token scopes: none"]}},
        all_hosts=["github.com", "  - Token scopes: none"],
    )
    done = _run(script, bindir, tmp_path)

    assert done.returncode != 3, f"blocked a possibly-valid token\n{done.stderr}"
    assert "UNVERIFIED" in done.stderr
    assert "gh auth refresh" not in done.stderr


def test_scope_preflight_is_identical_across_scripts():
    """One form, three call sites -- checked, not left to discipline.

    A shared helper would also prevent copies drifting, but these scripts are
    documented and shipped as independently runnable entry points, and sourcing a
    sibling adds a failure mode of its own. Nor would a helper stop a NEW script
    hand-rolling its own check. This scan covers that case too: every
    `gh auth status` in the directory must carry both flags.
    """
    sites = []
    for path in sorted(SCRIPTS.glob("*.sh")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "gh auth status" in line and not line.lstrip().startswith("#"):
                sites.append((path.name, line.strip()))

    assert len(sites) == 3, f"expected 3 call sites, found {len(sites)}: {sites}"
    for name, line in sites:
        assert re.search(r'gh auth status --active --hostname "\$\{GH_HOST:-github\.com\}"',
                         line), f"{name} uses an unscoped form: {line}"
