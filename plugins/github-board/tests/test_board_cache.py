"""Board discovery cache for promote-shipped and move-card (#146)."""
import json
import os
import subprocess
import sys
import time

import pytest

from gbtest import SKILLS_DIR, gh_calls, install_fake_gh, load_lib

PROMOTE = SKILLS_DIR / "promote-shipped" / "scripts"
MOVE = SKILLS_DIR / "move-card" / "scripts" / "board-move.sh"
AUTH = {"match": ["auth", "status"],
        "stdout": "github.com\n  - Token scopes: 'project', 'read:org', 'repo'\n"}
PROMOTE_KEY = ("promote-boards", "octo-user", "app")
BOARDS_KEY = ("move-boards", "octo-user", "app")
STATUS_KEY = ("move-status", "octo-user", "app", "7")
BOARD = {"id": "PVT_1", "title": "Board", "number": 7,
         "url": "https://github.com/users/octo-user/projects/7", "closed": False}


def run(tmp_path, script, routes, *args, **env):
    log = tmp_path / "gh.log"
    log.unlink(missing_ok=True)
    e = dict(os.environ, GB_PYTHON=sys.executable, **install_fake_gh(tmp_path / "bin", routes, log))
    e.update(env)
    r = subprocess.run(["bash", str(script), *args], env=e, capture_output=True, text=True, timeout=60)
    return r, gh_calls(log)


def graphql_calls(calls, needle=""):
    return [c for c in calls if c[:2] == ["api", "graphql"] and needle in " ".join(c)]


def discover_routes(nodes):
    return [AUTH, {"match": ["api", "graphql"],
                   "stdout": json.dumps({"data": {"repository": {"projectsV2": {"nodes": nodes}}}})}]


# ---- discover-boards.sh ---------------------------------------------------------

def test_discover_boards_reuses_its_cache(tmp_path):
    routes = discover_routes([BOARD])
    r1, c1 = run(tmp_path, PROMOTE / "discover-boards.sh", routes, "octo-user", "app", "--json")
    r2, c2 = run(tmp_path, PROMOTE / "discover-boards.sh", routes, "octo-user", "app", "--json")
    assert r1.returncode == r2.returncode == 0
    assert len(graphql_calls(c1)) == 1 and graphql_calls(c2) == []
    assert json.loads(r1.stdout) == json.loads(r2.stdout)
    assert json.loads(r2.stdout)["boards"][0]["id"] == "PVT_1"


def test_discover_boards_still_checks_the_scope_on_a_cache_hit(tmp_path):
    run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]), "octo-user", "app", "--json")
    no_scope = [{"match": ["auth", "status"], "stdout": "  - Token scopes: 'repo'\n"}]
    r, _ = run(tmp_path, PROMOTE / "discover-boards.sh", no_scope, "octo-user", "app", "--json")
    assert r.returncode == 3


def test_an_empty_board_list_is_not_cached(tmp_path):
    routes = discover_routes([])
    run(tmp_path, PROMOTE / "discover-boards.sh", routes, "octo-user", "app", "--json")
    _, calls = run(tmp_path, PROMOTE / "discover-boards.sh", routes, "octo-user", "app", "--json")
    assert len(graphql_calls(calls)) == 1


def test_an_entry_older_than_7_days_is_refetched(tmp_path):
    load_lib().cache_put(PROMOTE_KEY,
                         {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, title="Old")]},
                         now=time.time() - 8 * 86400)
    r, calls = run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]), "octo-user", "app", "--json")
    assert len(graphql_calls(calls)) == 1 and json.loads(r.stdout)["boards"][0]["title"] == "Board"


def test_discover_no_cache_never_reads_or_writes(tmp_path):
    gbc = load_lib()
    gbc.cache_put(PROMOTE_KEY,
                  {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, title="Cached")]})
    r, calls = run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]),
                   "octo-user", "app", "--json", "--no-cache")
    assert json.loads(r.stdout)["boards"][0]["title"] == "Board"
    assert gbc.cache_get(PROMOTE_KEY)["boards"][0]["title"] == "Cached"


# ---- inventory-board.sh -----------------------------------------------------------

def test_inventory_drops_a_cached_board_list_naming_a_stale_id(tmp_path):
    gbc = load_lib()
    gbc.cache_put(PROMOTE_KEY,
                  {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, id="PVT_gone")]})
    gone = {"data": {"node": None}, "errors": [{"type": "NOT_FOUND",
            "message": "Could not resolve to a node with the global id of 'PVT_gone'"}]}
    r, _ = run(tmp_path, PROMOTE / "inventory-board.sh", [AUTH, {"match": ["api", "graphql"], "stdout": json.dumps(gone)}],
               "--board-id", "PVT_gone")
    assert r.returncode == 4
    assert "re-run discover-boards.sh" in r.stderr
    assert gbc.cache_get(PROMOTE_KEY) is None


# ---- board-move.sh ------------------------------------------------------------------

FIELD = {"id": "F1", "name": "Status", "options": [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "In Progress"}]}
CONTENT = {"data": {"repository": {"issue": {"id": "I_1", "projectItems": {
    "nodes": [{"id": "ITEM1", "project": {"number": 7}}]}}}}}
STALE = "GraphQL: Could not resolve to a node with the global id of 'PVT_old' (updateProjectV2ItemFieldValue)\n"


def move_routes(new_pid_fails=False):
    return [
        AUTH,
        {"match": ["updateProjectV2ItemFieldValue", "pid=PVT_old"], "stderr": STALE, "rc": 1},
        {"match": ["updateProjectV2ItemFieldValue", "pid=PVT_new"],
         **({"stderr": STALE.replace("PVT_old", "PVT_new"), "rc": 1} if new_pid_fails else {"stdout": "ITEM1\n"})},
        {"match": ["projectsV2(first:100)"], "stdout": json.dumps([{"number": 7, "title": "Board", "closed": False}])},
        {"match": ["projectV2(number:$p){id}"], "stdout": "PVT_new\n"},
        {"match": ["fields(first:50)"], "stdout": json.dumps(FIELD)},
        {"match": ["projectItems(first:100)"], "stdout": json.dumps(CONTENT)},
    ]


ARGS = ("--issue", "5", "--to", "In Progress", "--repo", "octo-user/app")


def updates(calls):
    return graphql_calls(calls, "updateProjectV2ItemFieldValue")


def test_board_move_reuses_cached_board_and_status(tmp_path):
    r1, c1 = run(tmp_path, MOVE, move_routes(), *ARGS)
    r2, c2 = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r1.returncode == r2.returncode == 0, r1.stderr + r2.stderr
    assert graphql_calls(c1, "fields(first:50)") and not graphql_calls(c2, "fields(first:50)")
    assert not graphql_calls(c2, "projectsV2(first:100)")
    assert 'Moved issue #5 -> "In Progress"' in r2.stdout


def _seed_stale():
    gbc = load_lib()
    gbc.cache_put(BOARDS_KEY, [{"number": 7, "title": "Board", "closed": False}])
    gbc.cache_put(STATUS_KEY, {"pid": "PVT_old", "field": FIELD})
    return gbc


def test_board_move_refetches_once_after_a_stale_id(tmp_path):
    gbc = _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r.returncode == 0, r.stderr
    assert "look stale" in r.stderr and 'Moved issue #5 -> "In Progress"' in r.stdout
    assert len(updates(calls)) == 2
    assert gbc.cache_get(STATUS_KEY)["pid"] == "PVT_new"


def test_board_move_does_not_loop_when_the_refetch_also_fails(tmp_path):
    _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(new_pid_fails=True), *ARGS)
    assert r.returncode == 1 and len(updates(calls)) == 2


def test_board_move_no_cache_never_reads_or_writes(tmp_path):
    gbc = _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS, "--no-cache")
    assert r.returncode == 0 and len(updates(calls)) == 1
    assert gbc.cache_get(STATUS_KEY)["pid"] == "PVT_old"


# ---- added during implementation ------------------------------------------------

def test_board_move_refetches_when_the_target_column_is_missing_from_the_cache(tmp_path):
    # A Status column added after the cache was written must not be unreachable for 7 days.
    gbc = load_lib()
    gbc.cache_put(BOARDS_KEY, [{"number": 7, "title": "Board", "closed": False}])
    old_field = {"id": "F1", "name": "Status", "options": [{"id": "o1", "name": "Todo"}]}
    gbc.cache_put(STATUS_KEY, {"pid": "PVT_new", "field": old_field})
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r.returncode == 0, r.stderr
    assert "look stale" in r.stderr and 'Moved issue #5 -> "In Progress"' in r.stdout
    assert len(updates(calls)) == 1
    assert [o["name"] for o in gbc.cache_get(STATUS_KEY)["field"]["options"]] == \
        ["Todo", "In Progress"]


def test_board_move_refetches_on_any_mutation_error_with_cached_ids(tmp_path):
    # A stale option id fails with text that names no node; it still gets one fresh retry.
    gbc = _seed_stale()
    routes = move_routes()
    routes[1] = {"match": ["updateProjectV2ItemFieldValue", "pid=PVT_old"],
                 "stderr": "GraphQL: The single select option Id does not belong to the field\n", "rc": 1}
    r, calls = run(tmp_path, MOVE, routes, *ARGS)
    assert r.returncode == 0, r.stderr
    assert len(updates(calls)) == 2
    assert gbc.cache_get(STATUS_KEY)["pid"] == "PVT_new"


def test_board_move_without_cached_ids_never_refetches(tmp_path):
    routes = move_routes(new_pid_fails=True)
    r, calls = run(tmp_path, MOVE, routes, *ARGS)
    assert r.returncode == 1 and len(updates(calls)) == 1 and "look stale" not in r.stderr


def test_discover_boards_rejects_an_unknown_argument(tmp_path):
    r, calls = run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]),
                   "octo-user", "app", "--jsno")
    assert r.returncode == 2 and graphql_calls(calls) == []


def test_board_move_cache_does_not_mix_up_dashed_owner_and_repo(tmp_path):
    # owner `octo-user` + repo `app` must not be served the entry of owner `octo` + `user-app`.
    gbc = load_lib()
    gbc.cache_put(("move-boards", "octo", "user-app"), [{"number": 9, "title": "Other", "closed": False}])
    gbc.cache_put(("move-status", "octo", "user-app", "9"), {"pid": "PVT_other", "field": FIELD})
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r.returncode == 0, r.stderr
    assert graphql_calls(calls, "projectsV2(first:100)"), "served another repo's board list"
    assert not graphql_calls(calls, "PVT_other")


# ---- round-1 fixes: C2 (no refetch on rate limit / scope), R1 (refetch before die/add),
# ---- R3 (-f for String! variables)

@pytest.mark.parametrize("err", [
    "GraphQL: API rate limit exceeded for user ID 1. (RATE_LIMITED)\n",
    "GraphQL: Your token has not been granted the required scopes to execute this query.\n",
])
def test_board_move_never_refetches_on_a_rate_limit_or_scope_error(tmp_path, err):
    gbc = _seed_stale()
    routes = move_routes()
    routes[1] = {"match": ["updateProjectV2ItemFieldValue", "pid=PVT_old"], "stderr": err, "rc": 1}
    r, calls = run(tmp_path, MOVE, routes, *ARGS)
    assert r.returncode == 1 and len(updates(calls)) == 1, r.stderr
    assert "look stale" not in r.stderr
    assert gbc.cache_get(STATUS_KEY)["pid"] == "PVT_old"        # not dropped either


def _seed_wrong_board():
    # The cached board list names board 9; the card really sits on board 7.
    gbc = load_lib()
    gbc.cache_put(BOARDS_KEY, [{"number": 9, "title": "Old", "closed": False}])
    gbc.cache_put(("move-status", "octo-user", "app", "9"), {"pid": "PVT_nine", "field": FIELD})
    return gbc


def test_board_move_refetches_before_saying_the_card_is_not_on_the_board(tmp_path):
    _seed_wrong_board()
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r.returncode == 0, r.stderr
    assert "look stale" in r.stderr and 'Moved issue #5 -> "In Progress"' in r.stdout


def test_board_move_add_never_adds_to_a_cached_board_without_refetching(tmp_path):
    _seed_wrong_board()
    routes = move_routes()
    routes.insert(1, {"match": ["addProjectV2ItemById"], "stdout": "ITEM_ADDED\n"})
    r, calls = run(tmp_path, MOVE, routes, *ARGS, "--add")
    assert r.returncode == 0, r.stderr
    assert graphql_calls(calls, "addProjectV2ItemById") == [], "added the card to the stale cached board"
    assert 'Moved issue #5 -> "In Progress"' in r.stdout


def test_board_move_sends_owner_and_repo_as_strings(tmp_path):
    # -F does type inference: an all-numeric owner or repo would go out as an Int.
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS, "--no-cache")
    assert r.returncode == 0, r.stderr
    for c in graphql_calls(calls):
        for i, a in enumerate(c):
            if a.startswith(("o=", "n=")):
                assert c[i - 1] == "-f", c


# C-005: a board number from the cached board list that no longer resolves (the board was
# deleted; inventory-board.sh dropped the move-status entry but not move-boards) refetches the
# list once instead of dying on every run until the entry ages out.
@pytest.mark.parametrize("gone", [
    pytest.param({"stdout": ""}, id="empty-id"),
    pytest.param({"stderr": "GraphQL: Could not resolve to a ProjectV2 with the number 9.\n", "rc": 1},
                 id="graphql-error"),
])
def test_a_cached_board_number_that_no_longer_resolves_refetches_once(tmp_path, gone):
    gbc = load_lib()
    gbc.cache_put(BOARDS_KEY, [{"number": 9, "title": "Deleted", "closed": False}])
    routes = move_routes()
    routes.insert(1, {"match": ["projectV2(number:$p){id}", "p=9"], **gone})
    r, calls = run(tmp_path, MOVE, routes, *ARGS)
    assert r.returncode == 0, r.stderr
    assert 'Moved issue #5 -> "In Progress" on octo-user/app board #7' in r.stdout
    assert len(graphql_calls(calls, "projectsV2(first:100)")) == 1
    assert gbc.cache_get(BOARDS_KEY)[0]["number"] == 7


def test_an_explicit_board_number_that_does_not_resolve_still_dies(tmp_path):
    routes = move_routes()
    routes.insert(1, {"match": ["projectV2(number:$p){id}", "p=9"], "stdout": ""})
    r, calls = run(tmp_path, MOVE, routes, *ARGS, "--project", "9")
    assert r.returncode != 0 and "board #9 not found" in r.stderr
    assert not graphql_calls(calls, "projectsV2(first:100)")
