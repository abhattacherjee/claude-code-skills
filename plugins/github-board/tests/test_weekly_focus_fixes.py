"""weekly-focus.py: owner logins compare case-insensitively; a cut-short search is never silent."""
import datetime
import json
import re
import subprocess

import pytest

from test_weekly_focus import _load


@pytest.fixture
def wf():
    return _load()


def test_issue_key_matches_the_owner_login_case_insensitively(wf):
    c = {"number": 7, "state": "OPEN", "repository": {"name": "app", "owner": {"login": "Octo-User"}}}
    assert wf._issue_key(c) == "app#7"


def test_issue_key_still_refuses_another_owner(wf):
    c = {"number": 7, "state": "OPEN", "repository": {"name": "app", "owner": {"login": "octo-other"}}}
    assert wf._issue_key(c) is None


def test_board_items_keeps_a_card_whose_owner_differs_only_in_case(wf, monkeypatch, capsys):
    node = {"id": "I1", "content": {"number": 3, "title": "t", "state": "OPEN",
                                    "repository": {"name": "app", "owner": {"login": "OCTO-user"}}}}
    monkeypatch.setattr(wf, "gql", lambda *a, **k: [node])
    monkeypatch.setattr(wf, "_cached", lambda key, read: read())
    items = wf.board_items(5)
    assert list(items) == ["app#3"]
    assert "not owned by" not in capsys.readouterr().err


def _search_gh(wf, monkeypatch, total, nodes):
    """gh() answers a search query the way `--paginate --jq` would: one JSON value per line.
    The count row is supplied only when the query= text selects issueCount, as GitHub would."""
    seen = []

    def fake(*args, parse=True, **kw):
        seen.append(args)
        asks = any(a.startswith("query=") and "issueCount" in a for a in args)
        rows = ([{"__issueCount": total}] if asks else []) + nodes
        return "\n".join(json.dumps(r) for r in rows)
    monkeypatch.setattr(wf, "gh", fake)
    return seen


def _closed(n):
    return {"id": f"I_{n}", "number": n, "closedAt": "2026-09-29T12:00:00Z",
            "repository": {"name": "app"}}


def test_a_truncated_closed_issue_search_warns(wf, monkeypatch, capsys):
    import datetime
    seen = _search_gh(wf, monkeypatch, 1500, [_closed(1), _closed(2)])
    assert set(wf.closed_since(datetime.date(2026, 9, 28))) == {"app#1", "app#2"}
    err = capsys.readouterr().err
    assert "1500" in err and "only 2" in err
    assert any(a.startswith("query=") and "issueCount" in a for a in seen[0])  # the query asks for the total


def test_a_complete_search_does_not_warn(wf, monkeypatch, capsys):
    import datetime
    _search_gh(wf, monkeypatch, 2, [_closed(1), _closed(2)])
    wf.closed_since(datetime.date(2026, 9, 28))
    assert capsys.readouterr().err == ""


def test_the_search_cap_warns_even_when_the_count_matches(wf, monkeypatch, capsys):
    import datetime
    _search_gh(wf, monkeypatch, 1000, [_closed(i) for i in range(1, 1001)])
    wf.closed_since(datetime.date(2026, 9, 28))
    assert "1000" in capsys.readouterr().err


def test_a_truncated_open_issue_search_warns(wf, monkeypatch, capsys):
    issue = {"number": 1, "createdAt": "x", "url": "u", "repository": {"name": "app"},
             "milestone": None, "labels": {"nodes": []}}
    _search_gh(wf, monkeypatch, 1200, [issue])
    assert list(wf.open_issues()) == ["app#1"]
    assert "1200" in capsys.readouterr().err


def test_a_truncated_pr_search_warns(wf, monkeypatch, capsys):
    _search_gh(wf, monkeypatch, 1200, [{"closingIssuesReferences": {"nodes": []}}])
    assert wf.pr_linked() == set()
    assert "1200" in capsys.readouterr().err


def _range_search_gh(wf, monkeypatch, nodes, probe_count=None, raise_on_probe=None,
                     raise_on_fetch=False, range_drop=(), range_override=None, exc=None):
    """A range-aware fake gh. Probes and range fetches must keep the first query's search
    terms and add a created: range. raise_on_probe=N raises GhError on the Nth probe;
    raise_on_fetch raises on a range fetch; exc swaps the exception raised (default GhError);
    a call without --paginate returns one page (100 rows); range_drop leaves those numbers out of range
    fetches; range_override swaps a node (by id) in range fetches."""
    seen = []
    state = {"base": None, "probes": 0}

    def fake(*args, parse=True, **kw):
        seen.append(args)
        query = next(a for a in args if a.startswith("query="))
        terms = re.search(r'search\(query:"([^"]*)"', query)[1]
        dates = re.search(r"created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", query)
        if state["base"] is None:
            assert not dates
            state["base"] = terms
        assert re.sub(r" created:\S+", "", terms) == state["base"]
        matches = nodes
        if dates:
            start, end = dates.groups()
            matches = [n for n in nodes if start <= n["createdAt"][:10] <= end]
        assert parse is False
        if "first:1){issueCount}" in query:
            assert args == ("api", "graphql", "-f", query, "--jq", ".data.search.issueCount")
            assert dates and ",type:ISSUE," in query
            state["probes"] += 1
            if state["probes"] == raise_on_probe:
                raise (exc or wf.GhError)("probe boom")
            return str(len(matches) if probe_count is None else probe_count)
        if dates:
            if raise_on_fetch:
                raise (exc or wf.GhError)("fetch boom")
            matches = [(range_override or {}).get(n["id"], n) for n in matches
                       if n.get("number") not in range_drop]
        if not re.search(r"\.\.\. on (Issue|PullRequest)\{id ", query):
            matches = [{k: v for k, v in n.items() if k != "id"} for n in matches]   # id not selected
        page = 1000 if "--paginate" in args else 100   # one page without --paginate
        rows = [{"__issueCount": len(matches)}] + matches[:page]
        return "\n".join(json.dumps(row) for row in rows)

    monkeypatch.setattr(wf, "gh", fake)
    return seen


def _open_issue(n, day):
    return {"id": f"I_{n}", "number": n, "createdAt": f"{day}T12:00:00Z", "url": "u",
            "repository": {"name": "app"}, "milestone": None, "labels": {"nodes": []}}


def _creation_day(n):
    return datetime.date(2023, 1, 1) + datetime.timedelta(days=n % 730)


def test_an_open_issue_search_over_the_cap_reads_every_issue(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1114)]
    _range_search_gh(wf, monkeypatch, issues)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1114)}
    assert capsys.readouterr().err == ""


def test_a_search_under_the_cap_makes_one_call(wf, monkeypatch, capsys):
    start = datetime.date(2026, 9, 28)
    issues = [dict(_closed(n), createdAt=f"{_creation_day(n)}T12:00:00Z") for n in range(1, 901)]
    seen = _range_search_gh(wf, monkeypatch, issues)
    assert len(wf.closed_since(start)) == 900
    query = wf.CLOSED_Q % (wf.OWNER, "2026-09-27")
    assert seen == [("api", "graphql", "--paginate", "-f", f"query={query}",
                     "--jq", ".data.search | ({__issueCount: .issueCount}, .nodes[])")]
    assert capsys.readouterr().err == ""


def test_one_day_over_the_cap_warns_and_stops(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(0)) for n in range(1, 1201)]
    seen = _range_search_gh(wf, monkeypatch, issues)
    assert len(wf.open_issues()) == 1000
    err = capsys.readouterr().err
    assert "1200" in err and "only 1000" in err
    assert 0 < sum(args[-1] == ".data.search.issueCount" for args in seen) <= wf.SPLIT_MAX_PROBES
    assert "split stopped" not in err


def test_the_split_stops_at_the_probe_budget(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    seen = _range_search_gh(wf, monkeypatch, issues, probe_count=5000)
    wf.open_issues()
    assert sum(args[-1] == ".data.search.issueCount" for args in seen) == wf.SPLIT_MAX_PROBES
    err = capsys.readouterr().err
    assert "matched 1200 but only" in err
    assert f"split stopped after {wf.SPLIT_MAX_PROBES} probes" in err


def test_an_incomplete_split_keeps_what_the_first_search_read(wf, monkeypatch, capsys):
    # Every probe says 5000, so the split spends its budget and reads nothing. The 1,000
    # issues the first, unsplit search returned must not be thrown away (found live: 0 read).
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, probe_count=5000)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1001)}
    assert "matched 1200 but only 1000 were read" in capsys.readouterr().err


def test_closed_and_pr_searches_split_too(wf, monkeypatch, capsys):
    issues = [dict(_closed(n), createdAt=f"{_creation_day(n)}T12:00:00Z") for n in range(1, 1114)]
    expected = {f"app#{n}" for n in range(1, 1114)}
    _range_search_gh(wf, monkeypatch, issues)
    assert set(wf.closed_since(datetime.date(2026, 9, 28))) == expected

    prs = [{"id": f"PR_{issue['number']}", "createdAt": issue["createdAt"], "closingIssuesReferences": {"nodes": [
        {"number": issue["number"], "state": "OPEN",
         "repository": {"name": "app", "owner": {"login": wf.OWNER}}}]}} for issue in issues]
    _range_search_gh(wf, monkeypatch, prs)
    assert wf.pr_linked() == expected
    assert capsys.readouterr().err == ""


def test_the_split_includes_the_first_github_date_and_today_utc(wf, monkeypatch, capsys):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1001)]
    issues.extend([_open_issue(1001, datetime.date(2008, 1, 1)), _open_issue(1002, today)])
    seen = _range_search_gh(wf, monkeypatch, issues)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1003)}
    assert f"created:2008-01-01..{today + datetime.timedelta(days=1)}" in seen[1][3]
    assert capsys.readouterr().err == ""


def _probed_ranges(seen):
    """(start, end) of every created: range a probe asked about."""
    out = []
    for args in seen:
        if args[-1] == ".data.search.issueCount":
            d = re.search(r"created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", args[3])
            out.append(tuple(datetime.date.fromisoformat(x) for x in d.groups()))
    return out


def test_a_gh_error_in_a_probe_keeps_the_first_search(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, raise_on_probe=3)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1001)}
    err = capsys.readouterr().err
    assert "the search split for open issues failed (probe boom); using the first 1000 results" in err
    assert "matched 1200 but only 1000 were read" in err


def test_a_gh_error_in_a_range_fetch_keeps_the_first_search(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, raise_on_fetch=True)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1001)}
    err = capsys.readouterr().err
    assert "the search split for open issues failed (fetch boom)" in err
    assert "matched 1200 but only 1000 were read" in err


def _timeout(msg):
    return subprocess.TimeoutExpired(["gh"], 60)


def test_a_timeout_in_a_probe_keeps_the_first_search(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, raise_on_probe=3, exc=_timeout)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1001)}
    err = capsys.readouterr().err
    assert "the search split for open issues failed" in err
    assert "matched 1200 but only 1000 were read" in err


def test_a_timeout_in_a_range_fetch_keeps_the_first_search(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, raise_on_fetch=True, exc=_timeout)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1001)}
    err = capsys.readouterr().err
    assert "the search split for open issues failed" in err
    assert "matched 1200 but only 1000 were read" in err


def test_a_range_fetch_paginates_past_one_page(wf, monkeypatch, capsys):
    # 150 issues share one day, so one range holds more than a page (100 rows). The split
    # reads them all only if range fetches pass --paginate.
    issues = [_open_issue(n, "2024-05-05") for n in range(1, 151)]
    issues += [_open_issue(n, _creation_day(n)) for n in range(151, 1201)]
    _range_search_gh(wf, monkeypatch, issues)
    assert len(wf.open_issues()) == 1200
    assert "were read" not in capsys.readouterr().err


def test_two_prs_with_the_same_fields_but_different_ids_both_survive(wf, monkeypatch, capsys):
    twin = {"createdAt": "2024-01-01T12:00:00Z", "body": "b", "isDraft": False,
            "repository": {"name": "app", "owner": {"login": wf.OWNER}},
            "closingIssuesReferences": {"nodes": []}}
    prs = [dict(twin, id="PR_a"), dict(twin, id="PR_b")]
    prs += [dict(twin, id=f"PR_{n}", body=str(n), createdAt=f"{_creation_day(n)}T12:00:00Z")
            for n in range(1100)]
    _range_search_gh(wf, monkeypatch, prs)
    nodes = wf.gql_search(wf.PR_LINKED_Q, "open pull requests")
    assert len(nodes) == 1102
    assert capsys.readouterr().err == ""


def test_the_selections_ask_for_the_node_id(wf):
    assert "... on PullRequest{id " in wf.PR_LINKED_Q
    assert "... on Issue{id number " in wf.CLOSED_Q


def test_the_split_copy_wins_and_each_issue_counts_once(wf, monkeypatch, capsys):
    # The split misses 1101..1106, so it is short and the first search's rows are merged in.
    # Issue 5 changed milestone between the reads: the split's (newer) copy must win.
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    newer = dict(issues[4], milestone={"title": "v2"})
    _range_search_gh(wf, monkeypatch, issues, range_drop=range(1101, 1107),
                     range_override={"I_5": newer})
    out = wf.open_issues()
    assert out["app#5"]["milestone"] == "v2"
    assert len(out) == 1194
    assert "matched 1200 but only 1194 were read" in capsys.readouterr().err


def test_a_short_split_returns_the_union_of_both_searches(wf, monkeypatch, capsys):
    # The split reads some ranges but misses 1..50, which only the first search has.
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    _range_search_gh(wf, monkeypatch, issues, range_drop=range(1, 51))
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1201)}
    assert capsys.readouterr().err == ""
    _range_search_gh(wf, monkeypatch, issues, range_drop=list(range(1, 51)) + [1150])
    assert len(wf.open_issues()) == 1199
    assert "matched 1200 but only 1199 were read" in capsys.readouterr().err


def test_the_leaf_ranges_are_disjoint_and_cover_every_day(wf, monkeypatch, capsys):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1201)]
    seen = _range_search_gh(wf, monkeypatch, issues)
    wf.open_issues()
    leaves = []
    for start, end in _probed_ranges(seen):
        count = sum(1 for n in issues if str(start) <= n["createdAt"][:10] <= str(end))
        if count <= wf.SEARCH_CAP or start == end:
            leaves.append((start, end))
    leaves.sort()
    assert leaves[0][0] == datetime.date(2008, 1, 1)
    assert leaves[-1][1] == today + datetime.timedelta(days=1)
    for prev, nxt in zip(leaves, leaves[1:]):
        assert nxt[0] == prev[1] + datetime.timedelta(days=1)
    # The paginated range fetches must also be pairwise disjoint, each range fetched once.
    fetched = []
    for args in seen:
        d = re.search(r"created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})",
                      next(a for a in args if a.startswith("query="))) \
            if "--paginate" in args else None
        if d:
            fetched.append(tuple(datetime.date.fromisoformat(x) for x in d.groups()))
    assert fetched and len(fetched) == len(set(fetched))
    fetched.sort()
    for prev, nxt in zip(fetched, fetched[1:]):
        assert nxt[0] > prev[1]


def test_exactly_the_cap_makes_one_call_and_one_more_splits(wf, monkeypatch, capsys):
    issues = [_open_issue(n, _creation_day(n)) for n in range(1, 1001)]
    seen = _range_search_gh(wf, monkeypatch, issues)
    assert len(wf.open_issues()) == 1000
    assert len(seen) == 1
    # Deliberate: at exactly the cap the count can't tell "complete" from "cut off", so the
    # conservative warning still fires (see test_the_search_cap_warns_even_when_the_count_matches).
    assert "were read" in capsys.readouterr().err
    issues.append(_open_issue(1001, _creation_day(1001)))
    seen = _range_search_gh(wf, monkeypatch, issues)
    assert set(wf.open_issues()) == {f"app#{n}" for n in range(1, 1002)}
    assert len(_probed_ranges(seen)) >= 1
    assert "were read" not in capsys.readouterr().err


def _labelled(n_nodes, total):
    return {"number": 1, "createdAt": "x", "url": "u", "repository": {"name": "app"},
            "milestone": None,
            "labels": {"totalCount": total, "nodes": [{"name": f"l{i}"} for i in range(n_nodes)]}}


def test_an_issue_with_more_than_20_labels_warns(wf, monkeypatch, capsys):
    seen = _search_gh(wf, monkeypatch, 1, [_labelled(20, 25)])
    assert list(wf.open_issues()) == ["app#1"]
    err = capsys.readouterr().err
    assert "app#1" in err and "25 labels" in err and "only 20" in err
    assert "totalCount" in " ".join(seen[0])    # the query asks for the label total


def test_an_issue_with_20_or_fewer_labels_does_not_warn(wf, monkeypatch, capsys):
    _search_gh(wf, monkeypatch, 1, [_labelled(20, 20)])
    wf.open_issues()
    assert capsys.readouterr().err == ""
