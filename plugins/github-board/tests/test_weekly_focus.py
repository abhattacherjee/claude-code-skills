"""Tests for skills/weekly-focus/scripts/weekly-focus.py (#213, #214).

The module is loaded by path. Its `gh` function (and, for `show`, the
functions built on it) is replaced with fakes, so no test ever runs the real
`gh` or touches the network.
"""
import datetime
import importlib.util
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "plan-week" / "scripts" / "weekly-focus.py"


def _load(path: Path = SCRIPT, stub_gh=True):
    spec = importlib.util.spec_from_file_location("weekly_focus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def _no_gh(*a, **k):
        raise AssertionError(f"real gh called: {a}")

    if stub_gh:
        mod.gh = _no_gh
    return mod


@pytest.fixture
def wf():
    return _load()


def _ms(title, open_issues=1, description=None):
    return {"title": title, "open_issues": open_issues, "description": description}


def _current(wf, monkeypatch, milestones_by_repo):
    def fake_gh(*args, **kw):
        repo = args[1].split("/")[2]
        return milestones_by_repo[repo]
    monkeypatch.setattr(wf, "gh", fake_gh)
    return wf.current_milestones(set(milestones_by_repo))


# ---- current_milestones ---------------------------------------------------

def test_lowest_numeric_version_wins_not_string_order(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("v0.10"), _ms("v0.6")]})
    assert cur == {"r": "v0.6"}


def test_capital_v_and_bare_version_titles_count(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {
        "a": [_ms("V1.3"), _ms("V1.2")],
        "b": [_ms("0.5"), _ms("0.4")],
    })
    assert cur == {"a": "V1.2", "b": "0.4"}


def test_version_title_with_suffix_counts(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("v2.1"), _ms("v2.0 — Sleeper")]})
    assert cur == {"r": "v2.0 — Sleeper"}


def test_milestone_with_no_open_issues_is_skipped(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("v0.1", open_issues=0), _ms("v0.2")]})
    assert cur == {"r": "v0.2"}


@pytest.mark.parametrize("title", [
    "Backlog",
    "Backlog — x (paused)",
    "R0 — Foundation",
    "Design system migration — techno-ds v3",
])
def test_non_version_titles_are_never_current(wf, monkeypatch, title):
    cur = _current(wf, monkeypatch, {"r": [_ms(title)]})
    assert cur == {}


def test_paused_in_title_is_skipped_case_insensitively(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("v0.1 (PAUSED)"), _ms("v0.2")]})
    assert cur == {"r": "v0.2"}


def test_paused_in_description_is_skipped(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("v0.1", description="On hold, Paused for now"), _ms("v0.2")]})
    assert cur == {"r": "v0.2"}


def test_repo_with_no_qualifying_milestone_has_no_key(wf, monkeypatch):
    cur = _current(wf, monkeypatch, {"r": [_ms("Backlog")], "s": [_ms("v1.0")]})
    assert "r" not in cur
    assert cur == {"s": "v1.0"}


# ---- candidates -----------------------------------------------------------

def _issue(repo, labels=(), milestone=None):
    return {"repo": repo, "labels": list(labels), "milestone": milestone}


def _keys(wf, issues, current):
    return [k for k, _ in wf.candidates(issues, current)]


def test_frozen_repo_p1_issue_is_excluded(wf):
    issues = {"marauders-map#1": _issue("marauders-map", ["P1-high"], "v1.0")}
    assert _keys(wf, issues, {"marauders-map": "v1.0"}) == []


def test_always_issue_is_included_even_though_repo_is_frozen(wf):
    issues = {"tiny-vacation-agent#951": _issue("tiny-vacation-agent")}
    assert _keys(wf, issues, {}) == ["tiny-vacation-agent#951"]


@pytest.mark.parametrize("label", ["P1-high", "priority: P1", "security"])
def test_hot_label_is_included_from_a_non_current_milestone(wf, label):
    issues = {"app#1": _issue("app", [label], "v9.9")}
    assert _keys(wf, issues, {"app": "v1.0"}) == ["app#1"]


def test_hot_label_is_included_with_no_milestone(wf):
    issues = {"app#1": _issue("app", ["P1-high"], None)}
    assert _keys(wf, issues, {}) == ["app#1"]


def test_p2_issue_in_current_milestone_is_included(wf):
    issues = {"app#1": _issue("app", ["P2-medium"], "v1.0")}
    assert _keys(wf, issues, {"app": "v1.0"}) == ["app#1"]


def test_p2_issue_in_non_current_milestone_is_excluded(wf):
    issues = {"app#1": _issue("app", ["P2-medium"], "v2.0")}
    assert _keys(wf, issues, {"app": "v1.0"}) == []


def test_issue_without_milestone_is_excluded_unless_hot(wf):
    issues = {
        "app#1": _issue("app", ["P2-medium"], None),
        "app#2": _issue("app", ["security"], None),
    }
    assert _keys(wf, issues, {"app": "v1.0"}) == ["app#2"]


# ---- lane_for -------------------------------------------------------------

def test_security_label_gives_security_lane_even_in_the_season_repo(wf):
    assert wf.lane_for("fantasy-football-advisor", ["Security"]) == "Security"


def test_season_repo_gives_season_lane(wf):
    assert wf.lane_for("fantasy-football-advisor", ["bug"]) == "Season"


def test_tooling_repo_gives_tooling_lane(wf):
    assert wf.lane_for("claude-code-config", []) == "Tooling"


def test_other_repo_gives_product_lane(wf):
    assert wf.lane_for("some-app", []) == "Product"


# ---- show -----------------------------------------------------------------

def test_show_flags_only_this_week_items_outside_the_current_milestone(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "URL36"})
    monkeypatch.setattr(wf, "open_issues", lambda: {
        "app#1": _issue("app", [], "v2.0"),            # this week, not current
        "app#2": _issue("app", [], "v1.0"),            # this week, current
        "marauders-map#3": _issue("marauders-map", [], "v9.0"),  # this week, frozen
        "app#4": _issue("app", [], "v2.0"),            # next, not current
        "app#5": _issue("app", [], "v2.0"),            # done
    })
    monkeypatch.setattr(wf, "current_milestones", lambda repos: {"app": "v1.0"})
    monkeypatch.setattr(wf, "board_items", lambda num: {
        "app#1": {"focus": "This week", "lane": "Product", "title": "t1"},
        "app#2": {"focus": "This week", "lane": "Product", "title": "t2"},
        "marauders-map#3": {"focus": "This week", "lane": "Product", "title": "t3"},
        "app#4": {"focus": "Next", "lane": "Product", "title": "t4"},
        "app#5": {"focus": "This week", "lane": "Product", "title": "t5", "status": "Done"},
    })
    wf.show()
    out = capsys.readouterr().out.splitlines()
    lines = {}
    for key in ("app#1", "app#2", "marauders-map#3", "app#4", "app#5"):
        hit = [l for l in out if f" {key} " in l]
        if hit:
            lines[key] = hit[0]
    assert set(lines) == {"app#1", "app#2", "marauders-map#3", "app#4"}
    assert "app#5" not in lines
    assert lines["app#1"].endswith("<- not current (v1.0)")
    assert "<- not current" not in lines["app#2"]
    assert "<- not current" not in lines["marauders-map#3"]
    assert "<- not current" not in lines["app#4"]


# ---- fake gh (canned JSON by argv; never the real gh) ---------------------

def _fake_gh(monkeypatch, wf, *, projects, items_by_project=None, prs=None, closed=None,
             calls=None):
    """Route gh() by argv. GraphQL results come back as one JSON object per line (--jq form)."""
    items_by_project = items_by_project or {}

    def fake(*args, parse=True, **kw):
        if calls is not None:
            calls.append(args)
        if args[:2] == ("api", "graphql"):
            query = next(a for a in args if a.startswith("query="))
            if "projectsV2" in query:
                rows = projects
            elif "node(id" in query:
                pid = next(a for a in args if a.startswith("id="))[3:]
                rows = items_by_project.get(pid, [])
            elif "is:pr" in query:
                rows = prs or []
            elif "is:closed" in query:
                rows = closed or []
            else:
                raise AssertionError(f"unexpected query {query}")
            return "\n".join(json.dumps(r) for r in rows)
        raise AssertionError(f"unexpected gh call {args}")
    monkeypatch.setattr(wf, "gh", fake)


def _proj(pid, title, closed=False):
    return {"id": pid, "title": title, "closed": closed}


def _node(status, number, repo="app", owner="abhattacherjee", state="OPEN", updated=None):
    n = {"content": {"number": number, "state": state, "updatedAt": updated or _iso(1),
                     "repository": {"name": repo, "owner": {"login": owner}}}}
    n["fieldValueByName"] = {"name": status} if status else None
    return n


# ---- gh() -----------------------------------------------------------------

def test_gh_passes_a_120_second_timeout(monkeypatch):
    wf = _load(stub_gh=False)
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    wf.gh("project", "list")
    assert seen["timeout"] == 120


def _tz(monkeypatch, name):
    monkeypatch.setenv("TZ", name)
    time.tzset()


@pytest.fixture(autouse=True)
def _restore_tz():
    old = os.environ.get("TZ")
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _iso(days_ago):
    d = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- board_in_progress ----------------------------------------------------

def test_board_in_progress_status_names(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[_proj("P1", "App board")], items_by_project={"P1": [
        _node("In Progress", 1), _node("In review", 2), _node("In Review", 3),
        _node("Todo", 4), _node("Done", 5), _node(None, 6)]})
    assert wf.board_in_progress(set())[0] == {"app#1", "app#2", "app#3"}


def test_board_in_progress_ignores_closed_issues_and_foreign_owners(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[_proj("P1", "App board")], items_by_project={"P1": [
        _node("In Progress", 1, state="CLOSED"),
        _node("In Progress", 2, owner="someone-else"),
        {"fieldValueByName": {"name": "In Progress"}, "content": {}},  # PR / draft item
        _node("In Progress", 3)]})
    assert wf.board_in_progress(set())[0] == {"app#3"}


def test_board_in_progress_skips_weekly_focus_template_and_closed_projects(wf, monkeypatch):
    rows = [_node("In Progress", 1)]
    _fake_gh(monkeypatch, wf, projects=[
        _proj("W", "Weekly Focus"), _proj("T", "TEMPLATE — Standard Repo Board"),
        _proj("C", "Old board", closed=True), _proj("P", "Real board")],
        items_by_project={"W": [_node("In Progress", 10)], "T": [_node("In Progress", 11)],
                          "C": [_node("In Progress", 12)], "P": rows})
    assert wf.board_in_progress(set())[0] == {"app#1"}


# ---- pr_linked ------------------------------------------------------------

def test_pr_linked_returns_open_owned_closing_issues(wf, monkeypatch):
    def ref(n, state="OPEN", owner="abhattacherjee", repo="app"):
        return {"number": n, "state": state, "repository": {"name": repo, "owner": {"login": owner}}}
    _fake_gh(monkeypatch, wf, projects=[], prs=[
        {"closingIssuesReferences": {"nodes": [ref(1), ref(2, state="CLOSED"), ref(3, owner="x")]}},
        {"closingIssuesReferences": {"nodes": [ref(4, repo="other")]}},
        {"closingIssuesReferences": {"nodes": []}},
        {}])
    assert wf.pr_linked() == {"app#1", "other#4"}


def _pr(body, repo="claude-code-config", owner="abhattacherjee", refs=()):
    return {"body": body, "repository": {"name": repo, "owner": {"login": owner}},
            "closingIssuesReferences": {"nodes": list(refs)}}


def test_pr_into_develop_links_its_issue_from_the_body(wf, monkeypatch):
    # Live repro (#217): PR #218 targets develop, so GitHub leaves
    # closingIssuesReferences empty even though the body says "Closes #217".
    _fake_gh(monkeypatch, wf, projects=[], prs=[_pr("fix\n\nCloses #217\n")])
    assert wf.pr_linked(open_keys={"claude-code-config#217"}) == {"claude-code-config#217"}


def test_body_closing_keywords_and_forms(wf):
    body = ("Fixes #1. resolved #2, Close: #3\ncloses abhattacherjee/other#4\n"
            "Closes someone/else#5\nRefs #6, closing #7, see #8, issue #9")
    assert wf.body_closing_keys(_pr(body, repo="app")) == {"app#1", "app#2", "app#3", "other#4"}


def test_body_links_count_only_for_open_owned_issues(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[], prs=[_pr("Closes #1\nCloses #2")])
    assert wf.pr_linked(open_keys={"claude-code-config#1"}) == {"claude-code-config#1"}


def test_body_links_are_skipped_without_open_keys(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[], prs=[_pr("Closes #1")])
    assert wf.pr_linked() == set()


def test_pr_in_a_foreign_repo_does_not_link_by_body(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[], prs=[_pr("Closes #1", repo="app", owner="someone")])
    assert wf.pr_linked(open_keys={"app#1"}) == set()


def test_keyword_and_reference_on_different_lines_do_not_link(wf):
    # Review #218: \s let "fix" at a line end pair with "#5" on the next line.
    assert wf.body_closing_keys(_pr("we still need to fix\n\n#5 is related", repo="app")) == set()


def test_keywords_in_code_and_comments_do_not_link(wf):
    # Codex X-001 on #218: GitHub ignores these, so must we.
    body = ("<!-- Closes #1 -->\n```\nCloses #217\n```\n~~~\nfixes #3\n~~~\n"
            "run `closes #7` to see\nCloses #9")
    assert wf.body_closing_keys(_pr(body, repo="app")) == {"app#9"}


def test_full_issue_url_links(wf):
    body = "Closes https://github.com/abhattacherjee/other/issues/5"
    assert wf.body_closing_keys(_pr(body, repo="app")) == {"other#5"}


def test_owner_is_compared_case_insensitively(wf):
    assert wf.body_closing_keys(_pr("Closes Abhattacherjee/app#4", repo="x")) == {"app#4"}


def test_pr_linked_returns_the_open_issues_own_repo_spelling(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[], prs=[_pr("Closes abhattacherjee/App#4")])
    assert wf.pr_linked(open_keys={"app#4"}) == {"app#4"}


def test_sync_passes_open_issue_keys_to_in_progress_detection(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, current={"app": "v1.0"},
          issues={"app#1": _iss("app", "v1.0"), "app#2": _iss("app", "v2.0")}, in_progress=set())
    seen = {}

    def fake(open_keys=None):
        seen["open_keys"] = open_keys
        return set(), [], []
    monkeypatch.setattr(wf, "in_progress_keys", fake)
    _sync_json(wf, capsys)
    assert seen["open_keys"] == {"app#1", "app#2"}


# ---- week_start -----------------------------------------------------------

def test_week_start_monday_returns_itself(wf):
    mon = datetime.date(2026, 9, 28)
    assert mon.weekday() == 0
    assert wf.week_start(mon) == mon


def test_week_start_sunday_is_six_days_earlier(wf):
    sun = datetime.date(2026, 10, 4)
    assert sun.weekday() == 6
    assert wf.week_start(sun) == datetime.date(2026, 9, 28)


def test_week_start_midweek(wf):
    assert wf.week_start(datetime.date(2026, 9, 30)) == datetime.date(2026, 9, 28)


# ---- sync: in-progress promotion and change report ------------------------

class Board:
    """Records set_opt/add calls on a fake board."""

    def __init__(self, wf, monkeypatch, *, items, issues, current, in_progress, closed=(),
                 stale=(), failed=(), rate=({"remaining": 5000, "used": 100},
                                             {"remaining": 4924, "used": 176})):
        self.items = items
        self.rate_calls = 0
        rates = list(rate)

        def fake_rate():
            self.rate_calls += 1
            if not rates:
                raise wf.GhError("no rateLimit")
            return rates.pop(0)
        monkeypatch.setattr(wf, "rate_limit", fake_rate)
        self.sets = []
        self.adds = []
        fields = {"Focus": {"id": "F", "opts": {"This week": "tw", "Next": "nx", "Later": "lt"}},
                  "Lane": {"id": "L", "opts": {"Product": "pr", "Tooling": "tl", "Security": "sc", "Season": "se"}},
                  "Status": {"id": "S", "opts": {"Todo": "td", "In Progress": "ip", "Done": "dn"}}}
        monkeypatch.setattr(wf, "find_or_create_project",
                            lambda: {"number": 36, "id": "PID", "url": "URL36"})
        monkeypatch.setattr(wf, "write_readme", lambda n: None)
        monkeypatch.setattr(wf, "ensure_fields", lambda n: fields)
        monkeypatch.setattr(wf, "board_items", lambda n: self._board())
        monkeypatch.setattr(wf, "open_issues", lambda: issues)
        monkeypatch.setattr(wf, "current_milestones", lambda repos: current)
        monkeypatch.setattr(wf, "in_progress_keys", lambda open_keys=None: (set(in_progress), list(stale), list(failed)))
        monkeypatch.setattr(wf, "closed_since", lambda start: set(closed))
        monkeypatch.setattr(wf, "week_start", lambda today=None: datetime.date(2026, 9, 28))

        def fake_add(num, pid, flds, key, labels, focus):
            self.adds.append((key, focus))
            self.items[key] = {"id": f"id-{key}", "focus": focus, "status": "Todo",
                               "lane": wf.lane_for(key.split("#")[0], labels)}
            return f"id-{key}"

        def fake_set(pid, item_id, field, opt):
            self.sets.append((item_id, field["id"], opt))
        monkeypatch.setattr(wf, "add", fake_add)
        monkeypatch.setattr(wf, "set_opt", fake_set)

    def _board(self):
        out = {k: dict(v) for k, v in self.items.items()}
        for v in out.values():
            v.setdefault("lane", "Product")     # tests that care about Lane set it explicitly
        return out


def _iss(repo, milestone, created="2026-01-01T00:00:00Z", labels=()):
    return {"repo": repo, "labels": list(labels), "milestone": milestone,
            "created": created, "url": f"https://x/{repo}"}


def _sync_json(wf, capsys):
    wf.sync(as_json=True)
    return json.loads(capsys.readouterr().out)


def test_sync_adds_missing_in_progress_item_as_this_week_and_in_progress(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch, items={}, issues={"app#1": _iss("app", "v9.0")},
              current={"app": "v1.0"}, in_progress={"app#1"})   # not a candidate: only in-progress adds it
    out = _sync_json(wf, capsys)
    assert b.adds == [("app#1", "This week")]
    assert ("id-app#1", "S", "In Progress") in b.sets
    assert out["started"] == ["app#1"]
    assert out["unplanned"] == ["app#1"]     # v9.0 is not the current milestone
    assert out["added"] == ["app#1"]


def test_sync_promotes_existing_item_focus_and_status(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "Later", "status": "Todo"}},
              issues={"app#1": _iss("app", "v1.0")}, current={"app": "v1.0"},
              in_progress={"app#1"})
    out = _sync_json(wf, capsys)
    assert ("i1", "F", "This week") in b.sets
    assert ("i1", "S", "In Progress") in b.sets
    assert out["started"] == ["app#1"]
    assert b.adds == []


def test_sync_started_excludes_items_already_in_progress(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "This week", "status": "In Progress"},
                     "app#2": {"id": "i2", "focus": "Next", "status": "Todo"}},
              issues={"app#1": _iss("app", "v1.0"), "app#2": _iss("app", "v1.0")},
              current={"app": "v1.0"}, in_progress={"app#1", "app#2"})
    out = _sync_json(wf, capsys)
    assert out["started"] == ["app#2"]
    assert not [s for s in b.sets if s[0] == "i1"]   # nothing rewritten for the settled item


def test_sync_unplanned_for_frozen_and_not_current_only(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, current={"app": "v1.0"},
          issues={"app#1": _iss("app", "v2.0"),                # not current
                  "app#2": _iss("app", "v1.0"),                # planned
                  "marauders-map#3": _iss("marauders-map", "v1.0"),   # frozen
                  "app#4": _iss("app", None)},                 # no milestone
          in_progress={"app#1", "app#2", "marauders-map#3", "app#4"})
    out = _sync_json(wf, capsys)
    assert out["unplanned"] == ["app#1", "app#4", "marauders-map#3"]
    assert "app#2" not in out["unplanned"]


def test_sync_never_changes_focus_of_items_that_are_not_in_progress(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "Later", "status": "Todo"},
                     "app#2": {"id": "i2", "focus": "Next", "status": "Todo"},
                     "app#3": {"id": "i3", "focus": "Later", "status": "In Progress"}},
              issues={f"app#{n}": _iss("app", "v1.0") for n in (1, 2, 3)},
              current={"app": "v1.0"}, in_progress={"app#3"})
    _sync_json(wf, capsys)
    touched = {s[0] for s in b.sets}
    assert "i1" not in touched and "i2" not in touched
    assert ("i3", "F", "This week") in b.sets      # in progress, so promoted


def test_sync_change_report_new_and_closed_since_monday(wf, monkeypatch, capsys):
    _tz(monkeypatch, "UTC")
    Board(wf, monkeypatch,
          items={"app#1": {"id": "i1", "focus": "Next", "status": "Todo"},
                 "app#2": {"id": "i2", "focus": "Next", "status": "Todo"},
                 "app#3": {"id": "i3", "focus": "Next", "status": "Todo"}},
          issues={"app#1": _iss("app", "v1.0", created="2026-09-28T00:00:01Z"),   # Monday: new
                  "app#2": _iss("app", "v1.0", created="2026-09-27T23:59:59Z"),   # Sunday: old
                  "app#3": _iss("app", "v1.0", created="2026-09-30T10:00:00Z")},  # new
          current={"app": "v1.0"}, in_progress=set(),
          closed={"app#3", "app#2", "other#9"})   # other#9 is not on the board
    out = _sync_json(wf, capsys)
    assert out["new_since_monday"] == ["app#1", "app#3"]
    assert out["closed_since_monday"] == ["app#2", "app#3"]


def test_sync_json_shape_and_human_output(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, issues={"app#1": _iss("app", "v1.0")},
          current={"app": "v1.0"}, in_progress=set())
    wf.sync()
    text = capsys.readouterr().out
    assert "current  app" in text and "added 1: app#1" in text and "URL36" in text
    out = _sync_json(wf, capsys)
    assert set(out) == {"url", "current", "added", "started", "stopped", "stale_in_progress",
                        "lane_changed", "focus_filled", "unplanned", "new_since_monday", "closed_since_monday",
                        "done_this_week", "graphql_cost"}
    assert out["url"] == "URL36" and out["current"] == {"app": "v1.0"}


# ---- show --json ----------------------------------------------------------

def test_show_json_field_values(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "URL36"})
    monkeypatch.setattr(wf, "open_issues", lambda: {
        "app#1": _iss("app", "v2.0"),
        "app#2": _iss("app", "v1.0"),
        "marauders-map#3": _iss("marauders-map", "v9.0"),
        "app#4": _iss("app", "v1.0"),
        "app#5": _iss("app", "v1.0"),
    })
    monkeypatch.setattr(wf, "current_milestones", lambda repos: {"app": "v1.0"})
    monkeypatch.setattr(wf, "board_items", lambda num: {
        "app#1": {"focus": "This week", "lane": "Product", "status": "In Progress", "title": "t1"},
        "app#2": {"focus": "This week", "lane": "Product", "status": "Todo", "title": "t2"},
        "marauders-map#3": {"focus": "Next", "lane": "Product", "status": "In Progress", "title": "t3"},
        "app#4": {"focus": "This week", "lane": "Tooling", "title": "t4"},
        "app#5": {"focus": "This week", "lane": "Product", "status": "Done", "title": "t5"},
    })
    monkeypatch.setattr(wf, "week_start", lambda today=None: datetime.date(2026, 9, 28))
    wf.show(as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert data["url"] == "URL36" and data["week_start"] == "2026-09-28"
    by = {i["key"]: i for i in data["items"]}
    assert set(by) == {"app#1", "app#2", "marauders-map#3", "app#4"}   # Done is dropped
    a1 = by["app#1"]
    assert (a1["repo"], a1["number"], a1["url"], a1["title"]) == ("app", 1, "https://x/app", "t1")
    assert (a1["focus"], a1["lane"], a1["status"]) == ("This week", "Product", "In Progress")
    assert (a1["milestone"], a1["current_milestone"]) == ("v2.0", "v1.0")
    assert a1["in_progress"] and a1["not_current"] and a1["unplanned"] and not a1["frozen"]
    a2 = by["app#2"]
    assert not (a2["in_progress"] or a2["not_current"] or a2["unplanned"])
    m3 = by["marauders-map#3"]     # frozen + in progress: unplanned, but not a not_current flag
    assert m3["frozen"] and m3["unplanned"] and not m3["not_current"]
    assert by["app#4"]["status"] == "" and not by["app#4"]["in_progress"]


def test_show_human_marks_unplanned_rows(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "URL36"})
    monkeypatch.setattr(wf, "open_issues", lambda: {"app#1": _iss("app", "v2.0"),
                                                    "app#2": _iss("app", "v1.0")})
    monkeypatch.setattr(wf, "current_milestones", lambda repos: {"app": "v1.0"})
    monkeypatch.setattr(wf, "board_items", lambda num: {
        "app#1": {"focus": "Next", "lane": "Product", "status": "In Progress", "title": "a"},
        "app#2": {"focus": "Next", "lane": "Product", "status": "In Progress", "title": "b"}})
    wf.show()
    out = capsys.readouterr().out.splitlines()
    assert [l for l in out if " app#1 " in l][0].endswith("<- unplanned (in progress)")
    assert "unplanned" not in [l for l in out if " app#2 " in l][0]


# ---- set / pick -----------------------------------------------------------

def test_set_rejects_unknown_focus_with_exit_2(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project",
                        lambda: (_ for _ in ()).throw(AssertionError("must not reach the board")))
    with pytest.raises(SystemExit) as e:
        wf.set_focus("Someday", ["app#1"])
    assert e.value.code == 2
    assert "Someday" in capsys.readouterr().err


def test_set_updates_existing_and_pick_is_alias_for_this_week(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch, items={"app#1": {"id": "i1", "focus": "Next", "status": "Todo"}},
              issues={}, current={}, in_progress=set())
    wf.set_focus("Later", ["app#1"])
    assert ("i1", "F", "Later") in b.sets
    wf.pick(["app#1"])
    assert ("i1", "F", "This week") in b.sets


# ---- stale in-progress cards ----------------------------------------------

def test_stale_board_card_is_not_in_progress_and_is_reported(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[_proj("P1", "App board")], items_by_project={"P1": [
        _node("In Progress", 1, updated=_iso(22)),      # stale
        _node("In Progress", 2, updated=_iso(20)),      # fresh
        _node("In Progress", 3, updated=_iso(60))]})    # stale but an open PR closes it
    keys, stale, failed = wf.board_in_progress({"app#3"})
    assert keys == {"app#2", "app#3"} and failed == []
    assert [(c["key"], c["board"]) for c in stale] == [("app#1", "App board")]
    assert stale[0]["updated"] == _iso(22)[:10]


def test_stale_on_one_board_but_fresh_on_another_is_in_progress(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[_proj("P1", "A"), _proj("P2", "B")], items_by_project={
        "P1": [_node("In Progress", 1, updated=_iso(50))],
        "P2": [_node("In review", 1, updated=_iso(2))]})
    keys, stale, _ = wf.board_in_progress(set())
    assert keys == {"app#1"} and stale == []


def test_in_progress_keys_treats_pr_link_as_fresh(wf, monkeypatch):
    _fake_gh(monkeypatch, wf, projects=[_proj("P1", "App board")],
             items_by_project={"P1": [_node("In Progress", 1, updated=_iso(90))]},
             prs=[{"closingIssuesReferences": {"nodes": [
                 {"number": 1, "state": "OPEN",
                  "repository": {"name": "app", "owner": {"login": "abhattacherjee"}}}]}}])
    keys, stale, _ = wf.in_progress_keys()
    assert keys == {"app#1"} and stale == []


def test_stale_days_is_21(wf):
    assert wf.STALE_DAYS == 21


def test_sync_reports_stale_cards_without_promoting_them(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch, items={"app#1": {"id": "i1", "focus": "Next", "status": "Todo"}},
              issues={"app#1": _iss("app", "v1.0")}, current={"app": "v1.0"}, in_progress=set(),
              stale=[{"key": "app#1", "board": "App board", "updated": "2026-08-01"}])
    out = _sync_json(wf, capsys)
    assert out["stale_in_progress"] == [{"key": "app#1", "board": "App board",
                                         "updated": "2026-08-01"}]
    assert out["started"] == [] and b.sets == []
    wf.sync()
    assert "move the card back on App board" in capsys.readouterr().out


# ---- parallel scan and failing boards -------------------------------------

def test_one_failing_board_does_not_abort_the_scan(wf, monkeypatch, capsys):
    def fake(*args, parse=True, **kw):
        query = next(a for a in args if a.startswith("query="))
        if "projectsV2" in query:
            return "\n".join(json.dumps(p) for p in [_proj("P1", "Good"), _proj("P2", "Broken")])
        assert "node(id" in query
        if "id=P2" in args:
            raise wf.GhError("gh api graphql failed (exit 1): boom")
        return json.dumps(_node("In Progress", 7))
    monkeypatch.setattr(wf, "gh", fake)
    keys, stale, failed = wf.board_in_progress(set())
    assert keys == {"app#7"} and failed == ["Broken"]
    assert "Broken" in capsys.readouterr().err


def test_sync_with_a_failed_board_finishes_then_exits_1_and_skips_the_reset(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "This week", "status": "In Progress"}},
              issues={"app#1": _iss("app", "v1.0")}, current={"app": "v1.0"},
              in_progress=set(), failed=["Broken"])
    with pytest.raises(SystemExit) as e:
        wf.sync(as_json=True)
    assert e.value.code == 1
    cap = capsys.readouterr()
    assert json.loads(cap.out)["stopped"] == []      # the sync output is still complete
    assert "Broken" in cap.err and "weekly-focus: error" in cap.err
    assert b.sets == []       # the failed board's work must not look stopped


def test_board_scan_runs_boards_in_parallel(wf, monkeypatch):
    import threading
    barrier = threading.Barrier(3, timeout=5)

    def fake(*args, parse=True, **kw):
        if "projectsV2" in next(a for a in args if a.startswith("query=")):
            return "\n".join(json.dumps(_proj(f"P{i}", f"B{i}")) for i in range(3))
        barrier.wait()          # only passes if all 3 boards are scanned at the same time
        return ""
    monkeypatch.setattr(wf, "gh", fake)
    assert wf.board_in_progress(set()) == (set(), [], [])


# ---- sticky In Progress ---------------------------------------------------

def test_sync_resets_stopped_cards_to_todo_and_leaves_focus_alone(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "This week", "status": "In Progress"},
                     "app#2": {"id": "i2", "focus": "Later", "status": "In Progress"},
                     "app#3": {"id": "i3", "focus": "Next", "status": "Todo"},
                     "app#4": {"id": "i4", "focus": "Next", "status": "In Progress"}},
              issues={"app#1": _iss("app", "v1.0"), "app#2": _iss("app", "v1.0"),
                      "app#3": _iss("app", "v1.0")},      # app#4 is closed: not an open issue
              current={"app": "v1.0"}, in_progress={"app#2"})
    out = _sync_json(wf, capsys)
    assert out["stopped"] == ["app#1"]
    assert [x for x in b.sets if x[0] == "i1"] == [("i1", "S", "Todo")]   # only Status, never Focus
    assert not [x for x in b.sets if x[0] in ("i3", "i4")]
    wf.sync()
    assert "stopped 1: app#1" in capsys.readouterr().out


# ---- done_this_week -------------------------------------------------------

def test_sync_done_this_week_is_closed_items_with_focus_this_week(wf, monkeypatch, capsys):
    Board(wf, monkeypatch,
          items={"app#1": {"id": "i1", "focus": "This week", "status": "Done"},
                 "app#2": {"id": "i2", "focus": "Next", "status": "Done"},
                 "app#3": {"id": "i3", "focus": "This week", "status": "Todo"}},
          issues={"app#3": _iss("app", "v1.0")}, current={"app": "v1.0"}, in_progress=set(),
          closed={"app#1", "app#2"})
    out = _sync_json(wf, capsys)
    assert out["closed_since_monday"] == ["app#1", "app#2"]
    assert out["done_this_week"] == ["app#1"]


# ---- local dates ----------------------------------------------------------

def test_new_since_monday_uses_the_local_date(wf, monkeypatch, capsys):
    _tz(monkeypatch, "America/Los_Angeles")     # UTC-7 in September
    Board(wf, monkeypatch,
          items={"app#1": {"id": "i1", "focus": "Next", "status": "Todo"},
                 "app#2": {"id": "i2", "focus": "Next", "status": "Todo"}},
          issues={"app#1": _iss("app", "v1.0", created="2026-09-29T02:00:00Z"),   # Mon 19:00 local
                  "app#2": _iss("app", "v1.0", created="2026-09-28T05:00:00Z")},  # Sun 22:00 local
          current={"app": "v1.0"}, in_progress=set())
    assert _sync_json(wf, capsys)["new_since_monday"] == ["app#1"]


def test_closed_since_filters_on_the_local_close_date(wf, monkeypatch):
    _tz(monkeypatch, "America/Los_Angeles")
    seen = []
    _fake_gh(monkeypatch, wf, projects=[], calls=seen, closed=[
        {"number": 1, "closedAt": "2026-09-29T02:00:00Z", "repository": {"name": "app"}},   # Mon local
        {"number": 2, "closedAt": "2026-09-28T05:00:00Z", "repository": {"name": "app"}}])  # Sun local
    assert wf.closed_since(datetime.date(2026, 9, 28)) == {"app#1"}
    assert "closed:>=2026-09-27" in " ".join(seen[0])     # asked from a day earlier


# ---- gh() retry and errors ------------------------------------------------

def test_gh_retries_once_after_3s_then_succeeds(monkeypatch):
    wf = _load(stub_gh=False)
    sleeps, n = [], []
    monkeypatch.setattr(wf.time, "sleep", sleeps.append)

    def fake_run(cmd, **kw):
        n.append(1)
        if len(n) == 1:
            raise subprocess.CalledProcessError(1, cmd, stderr="flaky")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": 1}', stderr="")
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    assert wf.gh("project", "list") == {"ok": 1}
    assert len(n) == 2 and sleeps == [3]


def test_gh_final_failure_names_the_subcommand_and_stderr(monkeypatch):
    wf = _load(stub_gh=False)
    monkeypatch.setattr(wf.time, "sleep", lambda s: None)

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="  HTTP 502\nbad gateway \n")
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as e:
        wf.gh("project", "item-list", "36")
    assert "project item-list" in str(e.value) and "HTTP 502 bad gateway" in str(e.value)


def test_gh_does_not_retry_a_timeout(monkeypatch):
    wf = _load(stub_gh=False)
    n = []

    def fake_run(cmd, **kw):
        n.append(1)
        raise subprocess.TimeoutExpired(cmd, 120)
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        wf.gh("project", "list")
    assert len(n) == 1


def test_script_prints_one_error_line_and_no_traceback():
    # Runs the real script with a fake `gh` first on PATH; nothing reaches GitHub.
    import stat
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "gh"
        fake.write_text('#!/bin/sh\necho "HTTP 401 bad credentials" >&2\nexit 1\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        code = ("import runpy,sys,time;time.sleep=lambda s:None;"
                f"sys.argv=['weekly-focus.py','show'];runpy.run_path({str(SCRIPT)!r},run_name='__main__')")
        r = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=60,
                           env={"PATH": f"{d}:{os.environ['PATH']}"})
    assert r.returncode == 1
    assert r.stderr.startswith("weekly-focus: error: gh api graphql failed")
    assert "HTTP 401 bad credentials" in r.stderr
    assert "Traceback" not in r.stderr and len(r.stderr.strip().splitlines()) == 1


# ---- lean board reads (no gh project list / field-list / item-list) --------

def _item_node(iid, number, repo="app", focus="Next", lane="Product", status="Todo", title="t",
               owner="abhattacherjee"):
    return {"id": iid, "focus": {"name": focus} if focus else None,
            "lane": {"name": lane} if lane else None,
            "status": {"name": status} if status else None,
            "content": {"number": number, "title": title, "state": "OPEN",
                        "repository": {"name": repo, "owner": {"login": owner}}}}


def test_board_items_uses_one_lean_graphql_query_and_keeps_the_old_shape(wf, monkeypatch):
    seen = []

    def fake(*args, parse=True, **kw):
        seen.append(args)
        rows = [_item_node("a", 1, focus="This week", status="In Progress", title="one"),
                _item_node("b", 2, focus=None, lane=None, status=None),
                {"id": "pr", "content": {}},                        # PR / draft: skipped
                {"id": "d", "content": {"title": "draft"}}]
        return "\n".join(json.dumps(r) for r in rows)
    monkeypatch.setattr(wf, "gh", fake)
    items = wf.board_items(36)
    assert len(seen) == 1 and seen[0][:3] == ("api", "graphql", "--paginate")
    q = next(a for a in seen[0] if a.startswith("query="))
    assert "projectV2(number:36)" in q and "fieldValueByName" in q
    assert set(items) == {"app#1", "app#2"}
    assert items["app#1"] == {"id": "a", "focus": "This week", "lane": "Product",
                              "status": "In Progress", "title": "one",
                              "content": {"number": 1, "state": "OPEN", "repository": "app"}}
    assert (items["app#2"]["focus"], items["app#2"]["lane"], items["app#2"]["status"]) == (None,) * 3


def test_no_read_goes_through_gh_project_list_field_list_or_item_list(wf, monkeypatch):
    calls = []

    def fake(*args, parse=True, **kw):
        calls.append(args)
        query = next((a for a in args if a.startswith("query=")), "")
        if "projectsV2" in query:
            return json.dumps(_proj("PID", "Weekly Focus") | {"number": 36, "url": "U"})
        if "fields(" in query:
            return "\n".join(json.dumps(f) for f in [
                {"id": "F", "name": "Focus", "options": [{"id": "1", "name": "This week"}]},
                {"id": "L", "name": "Lane", "options": [{"id": "2", "name": "Product"}]},
                {"id": "S", "name": "Status", "options": [{"id": "3", "name": "Todo"}]},
                {"id": "T", "name": "Title"}])
        return "\n".join(json.dumps(_item_node("a", 1)) for _ in range(1))
    monkeypatch.setattr(wf, "gh", fake)
    p = wf.find_or_create_project()
    fields = wf.ensure_fields(p["number"])
    wf.board_items(p["number"])
    assert p["number"] == 36 and fields["Focus"] == {"id": "F", "opts": {"This week": "1"}}
    assert fields["Status"]["opts"] == {"Todo": "3"}
    assert not [c for c in calls if c[0] == "project"]
    assert all(c[:2] == ("api", "graphql") for c in calls)


def test_board_reads_run_once_per_process(wf, monkeypatch):
    calls = []

    def fake(*args, parse=True, **kw):
        calls.append(args)
        query = next(a for a in args if a.startswith("query="))
        if "projectsV2" in query:
            return json.dumps({"id": "P", "number": 36, "title": "Weekly Focus", "url": "U"})
        if "fields(" in query:
            return "\n".join(json.dumps(f) for f in [
                {"id": "F", "name": "Focus", "options": []}, {"id": "L", "name": "Lane", "options": []}])
        return json.dumps(_item_node("a", 1))
    monkeypatch.setattr(wf, "gh", fake)
    for _ in range(3):
        wf.find_or_create_project()
        wf.ensure_fields(36)
        wf.board_items(36)
    wf.board_in_progress(set())          # reuses the project list too
    assert len([c for c in calls if "projectsV2" in " ".join(c)]) == 1
    assert len(calls) == 3      # project list, fields, items: once each


def test_ensure_fields_creates_missing_then_rereads_once(wf, monkeypatch):
    calls = []
    state = {"created": False}

    def fake(*args, parse=True, **kw):
        calls.append(args)
        if args[0] == "project":
            state["created"] = True
            return {}
        rows = [{"id": "F", "name": "Focus", "options": [{"id": "1", "name": "Next"}]},
                {"id": "S", "name": "Status", "options": []}]
        if state["created"]:
            rows.append({"id": "L", "name": "Lane", "options": [{"id": "2", "name": "Product"}]})
        return "\n".join(json.dumps(r) for r in rows)
    monkeypatch.setattr(wf, "gh", fake)
    out = wf.ensure_fields(36)
    assert out["Lane"]["opts"] == {"Product": "2"}
    assert [c[0] for c in calls] == ["api", "project", "api"]      # read, create Lane, re-read
    assert calls[1][:2] == ("project", "field-create") and "Lane" in calls[1]


def test_no_reads_via_gh_project_subcommands_in_the_source():
    src = SCRIPT.read_text()
    for banned in ('"project", "list"', '"project", "field-list"', '"project", "item-list"'):
        assert banned not in src
    for kept in ('"project", "item-add"', '"project", "item-edit"', '"project", "create"',
                 '"project", "edit"', '"project", "field-create"'):
        assert kept in src


def test_sync_does_not_reread_the_board_after_adding(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch, items={}, issues={"app#1": _iss("app", "v1.0")},
              current={"app": "v1.0"}, in_progress=set())
    reads = []
    monkeypatch.setattr(wf, "board_items", lambda n: reads.append(n) or {})
    out = _sync_json(wf, capsys)
    assert out["added"] == ["app#1"] and reads == [36]


# ---- rate limit: gh() ------------------------------------------------------

@pytest.mark.parametrize("stderr,stdout", [
    ("gh: API rate limit already exceeded for user ID 1.", ""),
    ("", '{"errors":[{"type":"RATE_LIMIT","message":"API rate limit exceeded"}]}'),
    ("HTTP 403: rate limit exceeded", ""),
])
def test_gh_rate_limit_is_not_retried_and_says_so(monkeypatch, stderr, stdout):
    wf = _load(stub_gh=False)
    sleeps, n = [], []
    monkeypatch.setattr(wf.time, "sleep", sleeps.append)

    def fake_run(cmd, **kw):
        n.append(cmd)
        if "resetAt" in " ".join(cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout="2026-09-29T20:05:00Z\n", stderr="")
        raise subprocess.CalledProcessError(1, cmd, output=stdout, stderr=stderr)
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as e:
        wf.gh("api", "graphql", "-f", "query=x")
    assert "GitHub GraphQL rate limit exhausted" in str(e.value)
    assert re.search(r"resets \d\d:\d\d", str(e.value))
    assert sleeps == [] and len([c for c in n if "resetAt" not in " ".join(c)]) == 1


def test_gh_rate_limit_without_a_reset_time_still_raises(monkeypatch):
    wf = _load(stub_gh=False)

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="rate limit already exceeded")
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as e:
        wf.gh("api", "graphql")
    assert str(e.value).startswith("GitHub GraphQL rate limit exhausted")


def test_gh_project_unknown_owner_type_is_reported_as_a_probable_rate_limit(monkeypatch):
    wf = _load(stub_gh=False)
    n = []
    monkeypatch.setattr(wf.time, "sleep", lambda s: None)

    def fake_run(cmd, **kw):
        n.append(cmd)
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="unknown owner type")
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as e:
        wf.gh("project", "item-add", "36")
    assert "rate limit exhausted" in str(e.value) and "unknown owner type" in str(e.value)
    assert len([c for c in n if c[1] == "project"]) == 1        # not retried


# ---- rate limit: sync budget preflight and cost ----------------------------

def _exhaust(wf, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("sync wrote or read the board despite a low budget")
    for name in ("find_or_create_project", "write_readme", "ensure_fields", "board_items",
                 "open_issues", "add", "set_opt", "gh"):
        monkeypatch.setattr(wf, name, boom)


def test_sync_skips_with_exit_3_when_the_budget_is_low(wf, monkeypatch, capsys):
    _tz(monkeypatch, "UTC")
    _exhaust(wf, monkeypatch)
    monkeypatch.setattr(wf, "rate_limit",
                        lambda: {"remaining": 299, "used": 4701, "resetAt": "2026-09-29T20:05:00Z"})
    with pytest.raises(SystemExit) as e:
        wf.sync(as_json=True)
    assert e.value.code == 3
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip() == "weekly-focus: skipped: GraphQL budget low (299 left, resets 20:05)"


def test_sync_runs_at_exactly_min_budget(wf, monkeypatch, capsys):
    assert wf.MIN_BUDGET == 300
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set(),
          rate=({"remaining": 300, "used": 4700}, {"remaining": 290, "used": 4710}))
    assert _sync_json(wf, capsys)["graphql_cost"] == 10


def test_sync_skips_when_the_preflight_itself_is_rate_limited(wf, monkeypatch, capsys):
    _exhaust(wf, monkeypatch)

    def limited():
        raise wf.GhError("GitHub GraphQL rate limit exhausted: gh api graphql")
    monkeypatch.setattr(wf, "rate_limit", limited)
    with pytest.raises(SystemExit) as e:
        wf.sync()
    assert e.value.code == 3
    assert "skipped: GraphQL budget low (0 left" in capsys.readouterr().err


def test_show_and_set_do_not_run_the_budget_preflight(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "rate_limit",
                        lambda: (_ for _ in ()).throw(AssertionError("preflight outside sync")))
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "U"})
    monkeypatch.setattr(wf, "open_issues", lambda: {})
    monkeypatch.setattr(wf, "current_milestones", lambda r: {})
    monkeypatch.setattr(wf, "board_items", lambda n: {})
    wf.show()


def test_sync_reports_graphql_cost_as_the_used_difference(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set(),
          rate=({"remaining": 5000, "used": 100}, {"remaining": 4880, "used": 220}))
    assert _sync_json(wf, capsys)["graphql_cost"] == 120
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set())
    wf.sync()
    assert "graphql cost: 76 points" in capsys.readouterr().out


def test_sync_graphql_cost_is_null_when_the_final_query_fails(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set(),
          rate=({"remaining": 5000, "used": 100},))
    assert _sync_json(wf, capsys)["graphql_cost"] is None
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set(),
          rate=({"remaining": 5000, "used": 100},))
    wf.sync()
    assert "graphql cost: unknown" in capsys.readouterr().out


# ---- set / pick key validation --------------------------------------------

@pytest.mark.parametrize("bad", ["app", "app#", "#5", "app#x", "a b#1", "app#1;rm", "o/app#1"])
def test_set_rejects_a_malformed_key_before_any_write(wf, monkeypatch, capsys, bad):
    monkeypatch.setattr(wf, "find_or_create_project",
                        lambda: (_ for _ in ()).throw(AssertionError("must not reach the board")))
    with pytest.raises(SystemExit) as e:
        wf.set_focus("This week", ["app#1", bad])
    assert e.value.code == 2 and bad in capsys.readouterr().err


def test_pick_rejects_a_malformed_key(wf, monkeypatch):
    monkeypatch.setattr(wf, "find_or_create_project",
                        lambda: (_ for _ in ()).throw(AssertionError("must not reach the board")))
    with pytest.raises(SystemExit) as e:
        wf.pick(["nope"])
    assert e.value.code == 2


# ---- show --json: labels, priority, in_current ----------------------------

@pytest.mark.parametrize("labels,want", [
    (["P1-high"], 1), (["priority: P2"], 2), (["Priority: p3"], 3), (["P4-low", "bug"], 4),
    (["P2-medium", "P1-high"], 1), (["bug", "p10"], None), ([], None), (["prod"], None),
])
def test_priority_from_labels(wf, labels, want):
    assert wf.priority(labels) == want


def test_show_json_has_labels_priority_and_in_current_for_every_item(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "URL36"})
    monkeypatch.setattr(wf, "open_issues", lambda: {
        "app#1": _iss("app", "v1.0", labels=["P1-high", "bug"]),
        "app#2": _iss("app", "v2.0"),
        "app#3": _iss("app", None)})
    monkeypatch.setattr(wf, "current_milestones", lambda repos: {"app": "v1.0"})
    monkeypatch.setattr(wf, "board_items", lambda num: {
        "app#1": {"focus": "Next", "lane": "Product", "title": "a"},
        "app#2": {"focus": "This week", "lane": "Product", "title": "b"},
        "app#3": {"focus": "Next", "lane": "Product", "title": "c"}})
    wf.show(as_json=True)
    by = {i["key"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert (by["app#1"]["labels"], by["app#1"]["priority"], by["app#1"]["in_current"]) == \
        (["P1-high", "bug"], 1, True)
    assert (by["app#2"]["labels"], by["app#2"]["priority"], by["app#2"]["in_current"]) == ([], None, False)
    assert by["app#3"]["in_current"] is False
    assert by["app#2"]["not_current"] is True       # unchanged


# ---- lane refresh ---------------------------------------------------------

def _lane_case(wf, monkeypatch, repo, lane, labels):
    return Board(wf, monkeypatch,
                 items={f"{repo}#1": {"id": "i1", "focus": "Next", "status": "Todo", "lane": lane}},
                 issues={f"{repo}#1": _iss(repo, "v1.0", labels=labels)}, current={repo: "v1.0"},
                 in_progress=set())


def test_sync_fills_an_empty_lane(wf, monkeypatch, capsys):
    b = _lane_case(wf, monkeypatch, "claude-code-config", "", ["bug"])
    out = _sync_json(wf, capsys)
    assert b.sets == [("i1", "L", "Tooling")]
    assert out["lane_changed"] == [{"key": "claude-code-config#1", "from": "", "to": "Tooling"}]


def test_sync_lifts_a_lane_to_security_when_a_security_label_appears(wf, monkeypatch, capsys):
    b = _lane_case(wf, monkeypatch, "claude-code-config", "Tooling", ["Security"])
    out = _sync_json(wf, capsys)
    assert out["lane_changed"] == [{"key": "claude-code-config#1", "from": "Tooling",
                                    "to": "Security"}]
    assert b.sets == [("i1", "L", "Security")]


def test_sync_keeps_security_lane_after_the_label_is_removed(wf, monkeypatch, capsys):
    b = _lane_case(wf, monkeypatch, "claude-code-config", "Security", ["bug"])
    assert _sync_json(wf, capsys)["lane_changed"] == [] and b.sets == []


def test_sync_leaves_a_hand_set_lane_alone(wf, monkeypatch, capsys):
    b = _lane_case(wf, monkeypatch, "claude-code-config", "Product", ["bug"])   # repo is TOOLING
    assert _sync_json(wf, capsys)["lane_changed"] == [] and b.sets == []
    wf.sync()
    assert "lane changed 0: -" in capsys.readouterr().out


def test_sync_lane_refresh_ignores_items_whose_issue_is_not_open(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": "Next", "status": "Done", "lane": ""}},
              issues={}, current={}, in_progress=set())
    assert _sync_json(wf, capsys)["lane_changed"] == [] and b.sets == []


def test_board_items_skips_foreign_owned_card_with_warning(wf, monkeypatch, capsys):
    rows = [_item_node("x", 1, owner="someone-else"), _item_node("y", 2)]
    monkeypatch.setattr(wf, "gh", lambda *a, parse=True, **k: "\n".join(json.dumps(r) for r in rows))
    items = wf.board_items(36)
    assert set(items) == {"app#2"}
    assert "someone-else/app#1" in capsys.readouterr().err


def test_foreign_card_with_same_repo_and_number_does_not_suppress_adding(wf, monkeypatch, capsys):
    rows = [_item_node("x", 1, owner="someone-else")]
    monkeypatch.setattr(wf, "gh", lambda *a, parse=True, **k: "\n".join(json.dumps(r) for r in rows))
    have = wf.board_items(36)
    b = Board(wf, monkeypatch, items={}, issues={"app#1": _iss("app", "v1.0")},
              current={"app": "v1.0"}, in_progress=set())
    monkeypatch.setattr(wf, "board_items", lambda n: dict(have))
    out = _sync_json(wf, capsys)
    assert have == {} and out["added"] == ["app#1"] and b.adds == [("app#1", "Next")]


def test_sync_fills_empty_focus_on_candidate_but_not_a_set_one(wf, monkeypatch, capsys):
    b = Board(wf, monkeypatch,
              items={"app#1": {"id": "i1", "focus": None, "status": "Todo"},
                     "app#2": {"id": "i2", "focus": "Later", "status": "Todo"}},
              issues={f"app#{n}": _iss("app", "v1.0") for n in (1, 2)},
              current={"app": "v1.0"}, in_progress=set())
    out = _sync_json(wf, capsys)
    assert out["focus_filled"] == ["app#1"]
    assert ("i1", "F", "Next") in b.sets
    assert not [s for s in b.sets if s[0] == "i2"]
