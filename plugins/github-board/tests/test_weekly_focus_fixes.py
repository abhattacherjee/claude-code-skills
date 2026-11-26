"""weekly-focus.py: owner logins compare case-insensitively; a cut-short search is never silent."""
import datetime
import json
import re

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
    return {"number": n, "closedAt": "2026-09-29T12:00:00Z", "repository": {"name": "app"}}


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


def _range_search_gh(wf, monkeypatch, nodes, probe_count=None):
    seen = []

    def fake(*args, parse=True, **kw):
        seen.append(args)
        query = next(a for a in args if a.startswith("query="))
        dates = re.search(r"created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", query)
        matches = nodes
        if dates:
            start, end = dates.groups()
            matches = [n for n in nodes if start <= n["createdAt"][:10] <= end]
        assert parse is False
        if "first:1){issueCount}" in query:
            assert args == ("api", "graphql", "-f", query, "--jq", ".data.search.issueCount")
            assert dates and ",type:ISSUE," in query
            return str(len(matches) if probe_count is None else probe_count)
        rows = [{"__issueCount": len(matches)}] + matches[:1000]
        return "\n".join(json.dumps(row) for row in rows)

    monkeypatch.setattr(wf, "gh", fake)
    return seen


def _open_issue(n, day):
    return {"number": n, "createdAt": f"{day}T12:00:00Z", "url": "u",
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


def test_closed_and_pr_searches_split_too(wf, monkeypatch, capsys):
    issues = [dict(_closed(n), createdAt=f"{_creation_day(n)}T12:00:00Z") for n in range(1, 1114)]
    expected = {f"app#{n}" for n in range(1, 1114)}
    _range_search_gh(wf, monkeypatch, issues)
    assert set(wf.closed_since(datetime.date(2026, 9, 28))) == expected

    prs = [{"createdAt": issue["createdAt"], "closingIssuesReferences": {"nodes": [
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
