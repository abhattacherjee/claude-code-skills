"""The shared milestone helper in lib/config.py (#204).

`next-release-milestone` picks the milestone that merged work belongs to: the one named in
`milestones.next_release["O/R"]`, else the open milestone with the lowest version. It sorts
by version, never by milestone number. `milestone-for-tag` maps a release tag to its
milestone with PR A's rules (#203). Both read the list with
`gh api repos/O/R/milestones?state=all&per_page=100 --paginate`; a failed, empty or
malformed reply exits 2 and is never read as "no milestones". Every gh call is a stub.
"""
import json
import os
import subprocess
import sys

import pytest

from gbtest import LIB, cfg_copy, gh_calls, install_fake_gh, write_config

CONFIG_PY = LIB / "config.py"
CONFIG_SH = LIB / "config.sh"
FALLBACK_NOTE = "next-release milestone: v4.1 (lowest open version; set milestones.next_release to choose)"


def ms(title, number, state="open"):
    return {"title": title, "number": number, "state": state}


# This repo's real shape: v4.2 was created first (#9), v4.1 later (#13).
REPO_SHAPE = [ms("v4.0", 15, "closed"), ms("v4.2", 9), ms("v4.1", 13), ms("Backlog", 2)]


def list_route(pages=None, rc=0, stdout=None, stderr=""):
    """The milestone list. Pages print back to back, as an older gh does with --paginate."""
    if stdout is None:
        stdout = "".join(json.dumps(p) + "\n" for p in (pages if pages is not None else [REPO_SHAPE]))
    return {"match": ["repos/o/r/milestones?state=all&per_page=100", "--paginate"],
            "stdout": stdout, "stderr": stderr, "rc": rc}


def tags_route(pages=None, rc=0, stdout=None, stderr=""):
    """The repo's tags (gh api repos/O/R/tags --paginate). No tags by default."""
    if stdout is None:
        stdout = "".join(json.dumps([{"name": n} for n in p]) + "\n" for p in (pages or [[]]))
    return {"match": ["repos/o/r/tags", "--paginate"], "stdout": stdout, "stderr": stderr, "rc": rc}


def tag_calls(calls):
    return [c for c in calls if "repos/o/r/tags" in c]


def run(tmp_path, *args, routes=None, config=None):
    if config is not None:
        write_config(tmp_path / "xdg-config", config)
    log = tmp_path / "gh.log"
    log.unlink(missing_ok=True)
    routes = list(routes) if routes is not None else [list_route()]
    if not any("repos/o/r/tags" in r["match"] for r in routes):
        routes.append(tags_route())
    env = dict(os.environ, **install_fake_gh(tmp_path / "bin", routes, log))
    r = subprocess.run([sys.executable, str(CONFIG_PY), *args], env=env, capture_output=True,
                       text=True, timeout=60)
    return r, gh_calls(log)


def nr(tmp_path, repo="o/r", **kw):
    return run(tmp_path, "next-release-milestone", "--repo", repo, **kw)


def mft(tmp_path, tag, repo="o/r", **kw):
    return run(tmp_path, "milestone-for-tag", "--repo", repo, "--tag", tag, **kw)


def cfg_with(next_release=None, **sections):
    c = cfg_copy()
    if next_release is not None:
        c["milestones"] = {"next_release": next_release}
    c.update(sections)
    return c


# ---- next-release-milestone ------------------------------------------------------------

def test_the_config_wins_over_the_lowest_version(tmp_path):
    r, calls = nr(tmp_path, config=cfg_with({"o/r": "v4.2"}))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "9\tv4.2\n"
    assert "lowest open version" not in r.stderr
    assert len(calls) == 2 and len(tag_calls(calls)) == 1


def test_a_config_key_matches_the_repo_in_any_case(tmp_path):
    upper = [dict(list_route(), match=["repos/O/R/milestones?state=all"]),
             dict(tags_route(), match=["repos/O/R/tags"])]
    r, _ = nr(tmp_path, repo="O/R", config=cfg_with({"o/r": "v4.2"}), routes=upper)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "9\tv4.2\n"


def test_a_config_entry_for_another_repo_is_not_used(tmp_path):
    r, _ = nr(tmp_path, config=cfg_with({"o/other": "v4.2"}))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "13\tv4.1\n"


@pytest.mark.parametrize("pick,why", [("v9.9", "no milestone titled"), ("v4.0", "is closed")])
def test_a_configured_title_that_is_missing_or_closed_warns_and_sets_nothing(tmp_path, pick, why):
    # An explicit choice that is wrong is an error the user sees, never a silent fallback.
    r, _ = nr(tmp_path, config=cfg_with({"o/r": pick}))
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert why in r.stderr and pick in r.stderr and "milestones.next_release" in r.stderr
    assert "lowest open version" not in r.stderr


def test_the_lowest_open_version_wins_over_the_lowest_number(tmp_path):
    r, _ = nr(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "13\tv4.1\n"
    assert FALLBACK_NOTE in r.stderr


def test_without_a_config_file_the_fallback_runs(tmp_path):
    # No config at all is the common case, not an error.
    r, _ = nr(tmp_path)
    assert r.returncode == 0 and r.stdout == "13\tv4.1\n"


def test_v4_10_sorts_after_v4_2(tmp_path):
    r, _ = nr(tmp_path, routes=[list_route([[ms("v4.10", 3), ms("v4.2", 20)]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "20\tv4.2\n"


def test_non_version_titles_and_closed_milestones_are_never_picked(tmp_path):
    shape = [ms("Backlog", 1), ms("Someday", 2), ms("v4.1 — Observability", 3),
             ms("v4.0", 4, "closed"), ms("v4.1.0-rc1", 5), ms("v5.0", 6)]
    r, _ = nr(tmp_path, routes=[list_route([shape])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "6\tv5.0\n"


def test_a_patch_title_sorts_after_its_minor(tmp_path):
    r, _ = nr(tmp_path, routes=[list_route([[ms("v4.1.1", 7), ms("4.1", 8)]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "8\t4.1\n"


def test_two_titles_with_the_same_version_are_ambiguous(tmp_path):
    r, _ = nr(tmp_path, routes=[list_route([[ms("v4.1", 7), ms("4.1.0", 8), ms("v4.2", 9)]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert "ambiguous" in r.stderr


def test_no_candidate_warns_and_prints_nothing(tmp_path):
    r, _ = nr(tmp_path, routes=[list_route([[ms("Backlog", 1), ms("v4.0", 2, "closed")]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert "no next-release milestone" in r.stderr


def test_the_answer_on_page_two_is_found(tmp_path):
    page1 = [ms(f"m{i}", 100 + i) for i in range(100)]
    r, _ = nr(tmp_path, routes=[list_route([page1, [ms("v4.1", 13)]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "13\tv4.1\n"


@pytest.mark.parametrize("route,why", [
    pytest.param(list_route(rc=1, stdout="", stderr="HTTP 502: Bad Gateway\n"), "502", id="gh-fails"),
    pytest.param(list_route(stdout=""), "no output", id="empty-output"),
    pytest.param(list_route(stdout='{"message": "Not Found"}\n'), 'not a list ({"message"',
                 id="object-page"),
    pytest.param(list_route(stdout="[1, 2]\n"), "not a list of milestones", id="non-object-items"),
    pytest.param(list_route(stdout='[{"title": "v4.1", "number": 13}]\n{"x"'), "not JSON",
                 id="truncated-page"),
])
@pytest.mark.parametrize("cmd", ["next", "tag"])
def test_an_unreadable_list_exits_2_never_reads_as_empty(tmp_path, route, why, cmd):
    r, _ = (nr(tmp_path, routes=[route]) if cmd == "next"
            else mft(tmp_path, "v4.0.0", routes=[route]))
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout == ""
    assert "could not list milestones for o/r" in r.stderr and why in r.stderr


def test_an_empty_list_is_a_real_answer(tmp_path):
    # gh prints [] for a repo with no milestones: that is "none", not a failure.
    r, _ = nr(tmp_path, routes=[list_route([[]])])
    assert r.returncode == 0 and r.stdout == ""


@pytest.mark.parametrize("repo", ["o", "o/r/x", "../..", "o/..", "./r", "o/r\n"])
def test_a_malformed_repo_exits_2_before_any_gh_call(tmp_path, repo):
    for r, calls in (nr(tmp_path, repo=repo), mft(tmp_path, "v4.0.0", repo=repo)):
        assert r.returncode == 2
        assert calls == []


def test_an_invalid_config_exits_2(tmp_path):
    r, calls = nr(tmp_path, config=cfg_with({"o/r": 7}))
    assert r.returncode == 2
    assert "milestones.next_release" in r.stderr
    assert calls == []


def test_the_cache_file_is_reused_and_a_failure_is_not_cached(tmp_path):
    cache = tmp_path / "ms.json"
    r, calls = run(tmp_path, "next-release-milestone", "--repo", "o/r", "--cache", str(cache),
                   routes=[list_route(rc=1, stdout="", stderr="HTTP 502\n")])
    assert r.returncode == 2 and not cache.exists()
    r, calls = run(tmp_path, "next-release-milestone", "--repo", "o/r", "--cache", str(cache))
    assert r.returncode == 0 and len(calls) == 2 and len(tag_calls(calls)) == 1 and cache.exists()
    r, calls = run(tmp_path, "milestone-for-tag", "--repo", "o/r", "--tag", "v4.0.0",
                   "--cache", str(cache))
    assert r.returncode == 0 and r.stdout == "15\tv4.0\n"
    assert calls == []


def test_the_answer_on_page_one_is_kept_when_page_two_has_more(tmp_path):
    r, _ = nr(tmp_path, routes=[list_route([[ms("v4.1", 13)], [ms("v4.2", 9), ms("Backlog", 2)]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "13\tv4.1\n"


# ---- the newest version tag bounds the fallback (round 1, item 3) ---------------------

def test_an_open_milestone_already_shipped_is_skipped(tmp_path):
    # v4.0 shipped (tag v4.0.0) but was left open: it is not the next release.
    shape = [ms("v4.0", 15), ms("v4.1", 13), ms("v4.2", 9)]
    r, calls = nr(tmp_path, routes=[list_route([shape]), tags_route([["v4.0.0", "nightly"]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "13\tv4.1\n"
    assert tag_calls(calls) == [["api", "repos/o/r/tags", "--paginate"]]


def test_a_minor_milestone_is_at_or_below_its_patch_tag(tmp_path):
    shape = [ms("v4.1", 13), ms("v4.1.1", 14), ms("v4.2", 9)]
    r, _ = nr(tmp_path, routes=[list_route([shape]), tags_route([["v4.1.0"]])])
    assert r.stdout == "14\tv4.1.1\n"


def test_the_newest_tag_is_the_highest_version_on_any_page(tmp_path):
    # Mixed prefixes, a non-version tag, and the highest on page two.
    shape = [ms("v4.2", 9), ms("v4.10", 3), ms("v4.11", 4)]
    pages = [["4.2.0", "v4.9.0", "nightly-1"], ["v4.10.0", "v4.1.0"]]
    r, _ = nr(tmp_path, routes=[list_route([shape]), tags_route(pages)])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "4\tv4.11\n"


@pytest.mark.parametrize("route,why", [
    pytest.param(tags_route(rc=1, stdout="", stderr="HTTP 502: Bad Gateway\n"), "502", id="gh-fails"),
    pytest.param(tags_route(stdout=""), "no output", id="empty-output"),
    pytest.param(tags_route(stdout='{"message": "Not Found"}\n'), "not a list", id="object-page"),
])
def test_an_unreadable_tag_list_exits_2(tmp_path, route, why):
    r, _ = nr(tmp_path, routes=[list_route(), route])
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout == ""
    assert "could not list tags for o/r" in r.stderr and why in r.stderr


def test_a_configured_title_at_or_below_the_newest_tag_warns_and_sets_nothing(tmp_path):
    r, _ = nr(tmp_path, config=cfg_with({"o/r": "v4.1"}),
              routes=[list_route(), tags_route([["v4.1.0"]])])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert "already shipped" in r.stderr and "v4.1.0" in r.stderr


def test_after_tag_replaces_the_tag_read(tmp_path):
    r, calls = run(tmp_path, "next-release-milestone", "--repo", "o/r", "--after-tag", "v4.1.0")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "9\tv4.2\n"
    assert tag_calls(calls) == []


def test_an_empty_after_tag_means_no_tags(tmp_path):
    r, calls = run(tmp_path, "next-release-milestone", "--repo", "o/r", "--after-tag", "")
    assert r.returncode == 0 and r.stdout == "13\tv4.1\n"
    assert tag_calls(calls) == []


def test_after_tag_must_be_a_version(tmp_path):
    r, calls = run(tmp_path, "next-release-milestone", "--repo", "o/r", "--after-tag", "nightly")
    assert r.returncode == 2 and calls == []


# ---- milestone-for-tag (PR A's rules, #203) --------------------------------------------

def test_a_tag_maps_to_its_closed_release_milestone(tmp_path):
    r, _ = mft(tmp_path, "v4.0.0")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "15\tv4.0\n"


def test_the_exact_patch_title_wins(tmp_path):
    r, _ = mft(tmp_path, "v3.18.1", routes=[list_route([[ms("v3.18", 20, "closed"),
                                                          ms("v3.18.1", 21, "closed")]])])
    assert r.stdout == "21\tv3.18.1\n"


def test_the_minor_title_is_the_fallback(tmp_path):
    r, _ = mft(tmp_path, "v3.18.1", routes=[list_route([[ms("v3.18", 20, "closed"),
                                                          ms("v3.18.2", 22)]])])
    assert r.stdout == "20\tv3.18\n"


@pytest.mark.parametrize("title,tag", [("4.0", "v4.0.0"), ("v4.0", "4.0.0")])
def test_the_leading_v_is_optional_on_both_sides(tmp_path, title, tag):
    r, _ = mft(tmp_path, tag, routes=[list_route([[ms(title, 15, "closed")]])])
    assert r.stdout == f"15\t{title}\n"


def test_a_two_part_tag_maps_to_the_exact_title(tmp_path):
    r, _ = mft(tmp_path, "v4.0", routes=[list_route([[ms("v4", 4), ms("v4.0", 15)]])])
    assert r.stdout == "15\tv4.0\n"


def test_two_matching_titles_are_ambiguous(tmp_path):
    r, _ = mft(tmp_path, "v4.0.0", routes=[list_route([[ms("v4.0", 15, "closed"), ms("4.0", 16)]])])
    assert r.returncode == 0
    assert r.stdout == "skip\tambiguous: v4.0 #15, 4.0 #16 for v4.0.0\n"


def test_no_matching_title_skips(tmp_path):
    r, _ = mft(tmp_path, "v9.0.0")
    assert r.returncode == 0
    assert r.stdout == "skip\tno milestone titled 9.0.0 or 9.0 for v9.0.0\n"


@pytest.mark.parametrize("tag", ["nightly-1", "v4", "v4.0.0-rc1", "v4.0.0\nx"])
def test_a_tag_not_shaped_like_a_version_skips_before_listing(tmp_path, tag):
    r, calls = mft(tmp_path, tag)
    assert r.returncode == 0
    assert r.stdout.startswith("skip\t") and "is not vX.Y.Z or vX.Y" in r.stdout
    assert calls == []


def test_a_title_with_a_tab_cannot_split_the_output(tmp_path):
    r, _ = nr(tmp_path, config=cfg_with({"o/r": "v4.1\tx"}),
              routes=[list_route([[ms("v4.1\tx", 13)]])])
    assert r.stdout == "13\tv4.1 x\n"


# ---- the config validator --------------------------------------------------------------

@pytest.mark.parametrize("section,key", [
    pytest.param({"milestones": []}, "milestones", id="section-not-a-map"),
    pytest.param({"milestones": {"next_release": "v4.1"}}, "milestones.next_release",
                 id="next-release-not-a-map"),
    pytest.param({"milestones": {"next_release": {"just-a-repo": "v4.1"}}},
                 "milestones.next_release", id="key-not-owner-repo"),
    pytest.param({"milestones": {"next_release": {"o/..": "v4.1"}}},
                 "milestones.next_release", id="key-dot-part"),
    pytest.param({"milestones": {"next_release": {"o/r": ""}}}, "milestones.next_release",
                 id="empty-title"),
    pytest.param({"milestones": {"next_release": {"o/r": "v4.1", "O/R": "v4.2"}}},
                 "milestones.next_release", id="same-repo-twice"),
    pytest.param({"move_card": {"post_merge_columns": "Dev Complete"}},
                 "move_card.post_merge_columns", id="columns-not-a-list"),
    pytest.param({"move_card": {"post_merge_columns": [""]}},
                 "move_card.post_merge_columns", id="empty-column"),
    pytest.param({"move_card": "x"}, "move_card", id="move-card-not-a-map"),
])
def test_the_validator_refuses_a_bad_section(tmp_path, section, key):
    c = cfg_copy()
    c.update(section)
    write_config(tmp_path / "xdg-config", c)
    r = subprocess.run([sys.executable, str(CONFIG_PY), "show"], capture_output=True, text=True,
                       env=dict(os.environ), timeout=30)
    assert r.returncode == 2, r.stdout
    assert key in r.stderr


def test_the_validator_accepts_good_sections(tmp_path):
    c = cfg_with({"o/r": "v4.1", "octo-user/app.js": "Next"},
                 move_card={"post_merge_columns": ["Merged", "QA"]})
    write_config(tmp_path / "xdg-config", c)
    r = subprocess.run([sys.executable, str(CONFIG_PY), "get", "move_card.post_merge_columns",
                        "--lines"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "Merged\nQA\n"


# ---- the bash wrappers -----------------------------------------------------------------

@pytest.mark.parametrize("fn,args,out", [
    ("gb_next_release", ["--repo", "o/r"], "13\tv4.1\n"),
    ("gb_milestone_for_tag", ["--repo", "o/r", "--tag", "v4.0.0"], "15\tv4.0\n"),
])
def test_the_bash_wrappers(tmp_path, fn, args, out):
    log = tmp_path / "gh.log"
    env = dict(os.environ, GB_PYTHON=sys.executable,
               **install_fake_gh(tmp_path / "bin", [list_route(), tags_route()], log))
    r = subprocess.run(["bash", "-c", f'. "{CONFIG_SH}"; {fn} "$@"', "x", *args], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == out


def test_the_bash_wrapper_passes_exit_2_through(tmp_path):
    env = dict(os.environ, GB_PYTHON=sys.executable,
               **install_fake_gh(tmp_path / "bin", [list_route(rc=1, stdout="")], tmp_path / "gh.log"))
    r = subprocess.run(["bash", "-c", f'. "{CONFIG_SH}"; gb_next_release --repo o/r; echo "rc=$?"'],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "rc=2"
