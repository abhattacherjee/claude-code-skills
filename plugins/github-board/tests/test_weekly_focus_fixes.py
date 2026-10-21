"""weekly-focus.py: owner logins compare case-insensitively; a cut-short search is never silent."""
import json

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
    """gh() answers a search query the way `--paginate --jq` would: one JSON value per line."""
    seen = []

    def fake(*args, parse=True, **kw):
        seen.append(args)
        rows = [{"__issueCount": total}] + nodes
        return "\n".join(json.dumps(r) for r in rows)
    monkeypatch.setattr(wf, "gh", fake)
    return seen


def _closed(n):
    return {"number": n, "closedAt": "2026-09-29T12:00:00Z", "repository": {"name": "app"}}


def test_a_truncated_closed_issue_search_warns(wf, monkeypatch, capsys):
    import datetime
    seen = _search_gh(wf, monkeypatch, 1500, [_closed(1), _closed(2)])
    assert wf.closed_since(datetime.date(2026, 9, 28)) == {"app#1", "app#2"}
    err = capsys.readouterr().err
    assert "1500" in err and "only 2" in err
    assert "issueCount" in " ".join(seen[0])      # the query asks for the total


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
