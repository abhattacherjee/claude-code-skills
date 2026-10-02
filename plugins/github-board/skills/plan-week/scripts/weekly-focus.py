#!/usr/bin/env python3
"""Cross-repo "Weekly Focus" GitHub Project for abhattacherjee.

Script: ~/.claude/skills/weekly-focus/scripts/weekly-focus.py
launchd runs `sync` at 07:00 and 18:00. The skill (/weekly-focus, or a question like
"what do I work on next") is the normal way to use this.

  weekly-focus.py sync [--json]   create the board if missing, add (as Focus=Next) every open
                                  issue in each active repo's current milestone, plus
                                  P1/security issues from any milestone. Work already in
                                  progress (a Status of In progress / In review on any of your
                                  boards, or an open PR that closes the issue) is pulled in as
                                  Focus=This week with Status=In Progress, and reported as
                                  unplanned when it is outside the plan. Reports what started,
                                  what is new since Monday and what closed since Monday.
                                  Focus of other existing items is never changed.
                                  Exits 3 without writing anything when the GitHub GraphQL
                                  budget is under MIN_BUDGET (skipped, not a failure).
  weekly-focus.py set FOCUS REPO#N...
                                  set Focus (This week / Next / Later) on those issues
                                  (adds them if needed). `pick` = `set "This week"`.
  weekly-focus.py show [--json]   print open items by Focus and Lane, with milestone;
                                  flags This week items outside their repo's current milestone
                                  and in-progress items outside the plan (unplanned)

"Current milestone" = the lowest-versioned open milestone that still has open issues
(titles starting with a version: v0.6, V1.2, 0.4, v2.0 — ...). Backlog/theme milestones, and any
milestone whose title or description says "paused", never count. Frozen repos are skipped
by sync. Edit FROZEN to thaw one.
"""
import datetime
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

OWNER = "abhattacherjee"
TITLE = "Weekly Focus"
FROZEN = {
    "tiny-vacation-agent", "wealth-management", "knowledge-base-ui", "marauders-map",
    "prime-plays-ui-demo", "local-llm", "agents-monorepo", "obsidian-wiki", "spec-docs",
}
# Issues pulled in even though their repo is frozen.
ALWAYS = {"tiny-vacation-agent#951"}
TOOLING = {
    "claude-code-config", "obsidian-brain", "claude-code-skills", "cc-token-router",
    "harden-repo", "git-flow", "codex-config", "cc-telemetry-dashboard",
}
SEASON = {"fantasy-football-advisor"}
FIELDS = {
    "Focus": ["This week", "Next", "Later"],
    "Lane": ["Security", "Product", "Season", "Tooling"],
}
IN_PROGRESS_STATUSES = {"in progress", "in review"}
GH_TIMEOUT = 120
GH_RETRY_DELAY = 3
STALE_DAYS = 21          # a board card counts as in progress only if its issue moved this recently
MIN_BUDGET = 300         # sync skips (exit 3) when fewer GraphQL points than this are left
EXIT_SKIPPED = 3
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")
VERSIONED = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")
README = f"""Cross-repo weekly plan. Per-repo boards stay the source of truth for their lifecycle.

Rules:
- This week takes work only from each repo's current milestone (the lowest-versioned open
  milestone with open issues). `show` flags any This week item outside it.
- Security may jump ahead. Move that issue into the current milestone so it ships in the
  next release. Key rotations with no code change are the exception.
- At most 3 repos per week besides Security. Everything else stays Next or Later.

- Work already in progress (Status In progress / In review on any of your boards, or an open PR
  that closes the issue) is pulled in automatically. It is marked unplanned when it is outside
  the plan, and never hidden or demoted.

Weekly rhythm (10-20h):
- launchd runs `~/.claude/skills/weekly-focus/scripts/weekly-focus.py sync` at 07:00 and 18:00.
- Ask the skill (`/weekly-focus`, or "what do I work on next") for the next item; plan the week
  on Monday, 30 min: clear the Security lane, pick the week.
- Tue-Wed: one product repo.
- Thu: one tooling milestone (one only).
- Fri: fantasy-football-advisor (in season) + releases.

Frozen (not synced; issues kept open): {", ".join(sorted(FROZEN))}.
"""


class GhError(RuntimeError):
    pass


RATE_RE = re.compile(r"rate limit|RATE_LIMIT", re.I)


def _local_hm(ts):
    d = _parse_ts(ts)
    return d.astimezone().strftime("%H:%M") if d else "unknown"


def _reset_hint():
    """Local reset time of the GraphQL budget, or None. Best effort: never raises, never retries."""
    try:
        out = subprocess.run(["gh", "api", "graphql", "-f", "query=query{rateLimit{resetAt}}",
                              "--jq", ".data.rateLimit.resetAt"], check=True, capture_output=True,
                             text=True, timeout=20).stdout.strip()
        return _local_hm(out) if _parse_ts(out) else None
    except Exception:
        return None


def gh(*args, parse=True):
    """Run gh. One retry after GH_RETRY_DELAY s on a non-zero exit (not on timeout).

    A rate-limit failure is never retried: it raises GhError("GitHub GraphQL rate limit
    exhausted ..."). `gh project ...` reports an exhausted budget as "unknown owner type",
    so that text is treated the same way.
    """
    for attempt in (1, 2):
        try:
            out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                                 timeout=GH_TIMEOUT).stdout
            break
        except subprocess.CalledProcessError as e:
            err = " ".join((e.stderr or "").split())
            body = " ".join((e.stdout or "").split()) if isinstance(e.stdout, str) else ""
            probable = args[:1] == ("project",) and "unknown owner type" in err.lower()
            if RATE_RE.search(err) or RATE_RE.search(body) or probable:
                reset = _reset_hint()
                msg = "GitHub GraphQL rate limit exhausted"
                if reset:
                    msg += f", resets {reset}"
                if probable:
                    msg += " (gh said 'unknown owner type', which it prints when out of budget)"
                raise GhError(f"{msg}: gh {' '.join(args[:2])}") from e
            if attempt == 1:
                time.sleep(GH_RETRY_DELAY)
                continue
            raise GhError(f"gh {' '.join(args[:2])} failed (exit {e.returncode}): {err}") from e
    return json.loads(out) if parse else out


def rate_limit():
    """{remaining, used, resetAt} of the GraphQL budget. Raises GhError."""
    return gh("api", "graphql", "-f", "query=query{rateLimit{remaining used resetAt}}",
              "--jq", ".data.rateLimit")


def _safe_rate_limit():
    try:
        return rate_limit()
    except (GhError, subprocess.SubprocessError, OSError, ValueError):
        return None


_CACHE = {}


def _cached(key, fn):
    """Per-process memo: each board read happens once per command."""
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


PROJECTS_Q = (
    'query($endCursor:String){user(login:"%s"){projectsV2(first:100,after:$endCursor){'
    "pageInfo{hasNextPage endCursor} nodes{id number title url closed}}}}") % OWNER
FIELDS_Q = (
    'query{user(login:"%s"){projectV2(number:%%d){fields(first:100){nodes{'
    "... on ProjectV2SingleSelectField{id name options{id name}} ... on ProjectV2Field{id name}}}}}}") % OWNER
BOARD_ITEMS_Q = (
    'query($endCursor:String){user(login:"%s"){projectV2(number:%%d){items(first:100,after:$endCursor){'
    "pageInfo{hasNextPage endCursor} nodes{id "
    'focus:fieldValueByName(name:"Focus"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    'lane:fieldValueByName(name:"Lane"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    'status:fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    "content{... on Issue{number title state repository{name owner{login}}}}}}}}}") % OWNER


def list_projects():
    """OWNER's open user projects as [{id, number, title, url, closed}] (one lean query)."""
    def read():
        raw = gh("api", "graphql", "--paginate", "-f", f"query={PROJECTS_Q}",
                 "--jq", ".data.user.projectsV2.nodes[]", parse=False)
        return [p for p in (json.loads(l) for l in raw.splitlines() if l.strip())
                if not p.get("closed")]
    return _cached("projects", read)


def find_or_create_project():
    def find():
        for p in list_projects():
            if p["title"] == TITLE:
                return p
        return gh("project", "create", "--owner", OWNER, "--title", TITLE, "--format", "json")
    return _cached("project", find)


def write_readme(num):
    gh("project", "edit", str(num), "--owner", OWNER, "--readme", README,
       "--description", "Cross-repo weekly focus", "--format", "json")


def field_map(num):
    raw = gh("api", "graphql", "-f", f"query={FIELDS_Q % int(num)}",
             "--jq", ".data.user.projectV2.fields.nodes[]", parse=False)
    fields = (json.loads(l) for l in raw.splitlines() if l.strip())
    return {f["name"]: f for f in fields if f.get("name")}


def ensure_fields(num):
    def read():
        have = field_map(num)
        created = False
        for name, opts in FIELDS.items():
            if name not in have:
                gh("project", "field-create", str(num), "--owner", OWNER, "--name", name,
                   "--data-type", "SINGLE_SELECT", "--single-select-options", ",".join(opts),
                   "--format", "json")
                created = True
        if created:
            have = field_map(num)
        out = {n: {"id": have[n]["id"], "opts": {o["name"]: o["id"] for o in have[n]["options"]}}
               for n in FIELDS}
        if "Status" in have:
            out["Status"] = {"id": have["Status"]["id"],
                             "opts": {o["name"]: o["id"] for o in have["Status"]["options"]}}
        return out
    return _cached(("fields", num), read)


def board_items(num):
    """{repo#N: {id, focus, lane, status, title, content}} for the board's issues (lean query)."""
    def read():
        nodes = gql(BOARD_ITEMS_Q % int(num), ".data.user.projectV2.items.nodes[]")
        out = {}
        for n in nodes:
            c = n.get("content") or {}
            r = c.get("repository") or {}
            repo = r.get("name")
            if not (repo and c.get("number")):
                continue
            owner = (r.get("owner") or {}).get("login")
            if owner != OWNER:
                print(f"weekly-focus: warning: skipping card {owner}/{repo}#{c['number']} "
                      f"(not owned by {OWNER})", file=sys.stderr)
                continue
            out[f'{repo}#{c["number"]}'] = {
                "id": n["id"],
                "focus": (n.get("focus") or {}).get("name"),
                "lane": (n.get("lane") or {}).get("name"),
                "status": (n.get("status") or {}).get("name"),
                "title": c.get("title") or "",
                "content": {"number": c["number"], "state": c.get("state"), "repository": repo},
            }
        return out
    return _cached(("items", num), read)


def set_opt(pid, item_id, field, opt):
    gh("project", "item-edit", "--project-id", pid, "--id", item_id, "--field-id", field["id"],
       "--single-select-option-id", field["opts"][opt], parse=False)


def lane_for(repo, labels):
    if any("security" in l.lower() for l in labels):
        return "Security"
    if repo in SEASON:
        return "Season"
    return "Tooling" if repo in TOOLING else "Product"


def add(num, pid, fields, key, labels, focus):
    repo, n = key.split("#")
    url = f"https://github.com/{OWNER}/{repo}/issues/{n}"
    item = gh("project", "item-add", str(num), "--owner", OWNER, "--url", url, "--format", "json")
    set_opt(pid, item["id"], fields["Lane"], lane_for(repo, labels))
    set_opt(pid, item["id"], fields["Focus"], focus)
    return item["id"]


def open_issues():
    q = ("query($endCursor:String){search(query:\"user:%s is:issue is:open\",type:ISSUE,first:100,"
         "after:$endCursor){pageInfo{hasNextPage endCursor} nodes{... on Issue{number "
         "createdAt url repository{name} milestone{title} labels(first:20){nodes{name}}}}}}") % OWNER
    raw = gh("api", "graphql", "--paginate", "-f", f"query={q}", "--jq", ".data.search.nodes[]",
             parse=False)
    out = {}
    for line in raw.splitlines():
        i = json.loads(line)
        repo = i["repository"]["name"]
        out[f'{repo}#{i["number"]}'] = {
            "repo": repo,
            "labels": [l["name"] for l in i["labels"]["nodes"]],
            "milestone": (i.get("milestone") or {}).get("title"),
            "created": i.get("createdAt") or "",
            "url": i.get("url") or "",
        }
    return out


def gql(query, jq, **variables):
    """Run a paginated GraphQL query; return the parsed nodes `jq` selects."""
    args = ["api", "graphql", "--paginate", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    raw = gh(*args, "--jq", jq, parse=False)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def _issue_key(c):
    """repo#N for an OPEN issue owned by OWNER, else None."""
    repo = c.get("repository") or {}
    if not c.get("number") or c.get("state") != "OPEN":
        return None
    if (repo.get("owner") or {}).get("login") != OWNER:
        return None
    return f'{repo["name"]}#{c["number"]}'


PROJECT_ITEMS_Q = (
    "query($id:ID!,$endCursor:String){node(id:$id){... on ProjectV2{items(first:100,"
    "after:$endCursor){pageInfo{hasNextPage endCursor} nodes{fieldValueByName(name:\"Status\"){"
    "... on ProjectV2ItemFieldSingleSelectValue{name}} content{... on Issue{number state updatedAt "
    "repository{name owner{login}}}}}}}}}")
PR_LINKED_Q = (
    "query($endCursor:String){search(query:\"is:pr is:open author:%s\",type:ISSUE,first:100,"
    "after:$endCursor){pageInfo{hasNextPage endCursor} nodes{... on PullRequest{body "
    "repository{name owner{login}} "
    "closingIssuesReferences(first:20){nodes{number state repository{name owner{login}}}}}}}}") % OWNER
# GitHub fills closingIssuesReferences only for PRs into the default branch. Feature PRs
# target develop, so the closing keywords are read from the PR body too.
# Keyword and reference must sit on one line ([ \t], not \s). GitHub also accepts the
# full issue URL. Code and HTML comments are stripped first, as GitHub ignores them.
CLOSING_RE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)[ \t]*:?[ \t]+"
    r"(?:(?:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+))?#|"
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/)(\d+)\b")
NON_TEXT_RE = re.compile(r"<!--.*?-->|```.*?```|~~~.*?~~~|`[^`\n]*`", re.S)
CLOSED_Q = (
    "query($endCursor:String){search(query:\"user:%s is:issue is:closed closed:>=%s\",type:ISSUE,"
    "first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{... on Issue{number closedAt "
    "repository{name}}}}}")


def _parse_ts(ts):
    """UTC ISO timestamp -> aware datetime, or None."""
    try:
        return datetime.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def local_date(ts):
    """Local calendar date of a UTC ISO timestamp (None if unparsable)."""
    d = _parse_ts(ts)
    return d.astimezone().date() if d and d.tzinfo else (d.date() if d else None)


def _scan_board(p):
    """[(key, issue updatedAt)] for open issues at In progress / In review on one board."""
    rows = []
    for n in gql(PROJECT_ITEMS_Q, ".data.node.items.nodes[]", id=p["id"]):
        status = ((n.get("fieldValueByName") or {}).get("name") or "").lower()
        c = n.get("content") or {}
        key = _issue_key(c)
        if key and status in IN_PROGRESS_STATUSES:
            rows.append((key, c.get("updatedAt") or ""))
    return rows


def board_in_progress(pr_keys=None, now=None):
    """Scan OWNER's other boards for cards at In progress / In review.

    Returns (keys, stale, failed). A card counts only if its issue was updated within
    STALE_DAYS or an open PR closes it (pr_keys); older ones go to `stale` as
    [{key, board, updated}]. `failed` names boards that could not be read.
    """
    pr_keys = pr_linked() if pr_keys is None else pr_keys
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=STALE_DAYS)
    boards = [p for p in list_projects()
              if not p.get("closed") and p.get("title", "") != TITLE
              and not p.get("title", "").startswith("TEMPLATE")]
    keys, stale, failed = set(), {}, []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [(p, ex.submit(_scan_board, p)) for p in boards]
        for p, f in futs:
            title = p.get("title", "")
            try:
                rows = f.result()
            except Exception as e:  # one bad board must not abort the sync
                failed.append(title)
                print(f"warning: could not read board {title!r}: {e}", file=sys.stderr)
                continue
            for key, updated in rows:
                ts = _parse_ts(updated)
                if key in pr_keys or ts is None or ts >= cutoff:
                    keys.add(key)
                else:
                    stale.setdefault(key, {"key": key, "board": title, "updated": updated[:10]})
    stale_list = [v for k, v in sorted(stale.items()) if k not in keys]
    return keys, stale_list, failed


def body_closing_keys(pr):
    """repo#N for each closing keyword in a PR body that points at an OWNER repo."""
    repo = pr.get("repository") or {}
    owner, name = (repo.get("owner") or {}).get("login"), repo.get("name")
    keys = set()
    text = NON_TEXT_RE.sub(" ", pr.get("body") or "")
    for m in CLOSING_RE.finditer(text):
        o = m.group(1) or m.group(3) or owner
        r = m.group(2) or m.group(4) or name
        if o and r and o.lower() == OWNER.lower():
            keys.add(f"{r}#{m.group(5)}")
    return keys


def pr_linked(open_keys=None):
    """Open issues that one of OWNER's open PRs closes.

    Uses GitHub's closing references and the closing keywords in the PR body. Body
    matches carry no state, so they count only when they are in open_keys (all of
    OWNER's open issues); with open_keys None they are skipped.
    """
    keys = set()
    for pr in gql(PR_LINKED_Q, ".data.search.nodes[]"):
        for c in ((pr.get("closingIssuesReferences") or {}).get("nodes") or []):
            key = _issue_key(c)
            if key:
                keys.add(key)
        if open_keys is not None:
            # Match case-insensitively, but return the issue's own spelling of the repo.
            canon = {k.lower(): k for k in open_keys}
            keys |= {canon[k.lower()] for k in body_closing_keys(pr) if k.lower() in canon}
    return keys


def in_progress_keys(open_keys=None):
    """(keys, stale, failed): work in progress, stale board cards, boards that failed to read."""
    pr = pr_linked(open_keys)
    keys, stale, failed = board_in_progress(pr)
    return keys | pr, stale, failed


def week_start(today=None):
    """Date of the most recent Monday (today, if today is Monday)."""
    today = today or datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


def closed_since(start):
    # `closed:` filters on the UTC date, so ask from a day earlier and filter on the local date.
    q = CLOSED_Q % (OWNER, (start - datetime.timedelta(days=1)).isoformat())
    out = set()
    for n in gql(q, ".data.search.nodes[]"):
        day = local_date(n.get("closedAt"))
        if day is None or day >= start:
            out.add(f'{n["repository"]["name"]}#{n["number"]}')
    return out


def out_of_plan(repo, milestone, current):
    return repo in FROZEN or (milestone or "-") != current.get(repo)


def current_milestones(repos):
    cur = {}
    for repo in sorted(repos):
        best = None
        for m in gh("api", f"repos/{OWNER}/{repo}/milestones?state=open&per_page=100"):
            v = VERSIONED.match(m["title"])
            paused = "paused" in (m["title"] + " " + (m.get("description") or "")).lower()
            if v and m["open_issues"] > 0 and not paused:
                ver = tuple(int(x) for x in v.group(1).split("."))
                if best is None or ver < best[0]:
                    best = (ver, m["title"])
        if best:
            cur[repo] = best[1]
    return cur


def candidates(issues, current):
    for key, i in issues.items():
        repo = i["repo"]
        low = [l.lower() for l in i["labels"]]
        hot = any(l.startswith("p1") or l == "priority: p1" or "security" in l for l in low)
        in_current = i["milestone"] is not None and i["milestone"] == current.get(repo)
        if key in ALWAYS or (repo not in FROZEN and (hot or in_current)):
            yield key, i["labels"]


def refresh_lanes(pid, fields, have, issues):
    """Fill an empty Lane, and lift an item to Security once it gains a security label.

    Any other non-empty Lane is left alone (no downgrade, no overwrite of a hand-set lane).
    Returns [{key, from, to}].
    """
    changed = []
    for key, it in sorted(have.items()):
        if key not in issues:
            continue
        cur = it.get("lane") or ""
        labels = issues[key]["labels"]
        if not cur:
            new = lane_for(issues[key]["repo"], labels)
        elif cur != "Security" and any("security" in l.lower() for l in labels):
            new = "Security"
        else:
            continue
        if new not in fields["Lane"]["opts"]:
            print(f"warning: board has no Lane option {new!r} ({key})", file=sys.stderr)
            continue
        set_opt(pid, it["id"], fields["Lane"], new)
        changed.append({"key": key, "from": cur, "to": new})
    return changed


def _skip_low_budget():
    """Exit 3 (nothing written) if fewer than MIN_BUDGET GraphQL points are left.

    Returns the preflight rateLimit dict (None if it could not be read).
    """
    try:
        rl = rate_limit()
    except GhError as e:
        if RATE_RE.search(str(e)):
            rl = {"remaining": 0, "resetAt": None}
        else:
            return None
    remaining = rl.get("remaining")
    if isinstance(remaining, int) and remaining < MIN_BUDGET:
        print(f"weekly-focus: skipped: GraphQL budget low ({remaining} left, resets "
              f"{_local_hm(rl.get('resetAt'))})", file=sys.stderr)
        sys.exit(EXIT_SKIPPED)
    return rl


def _graphql_cost(before):
    after = _safe_rate_limit()
    try:
        return int(after["used"]) - int(before["used"])
    except (TypeError, KeyError, ValueError):
        return None


def sync(as_json=False):
    before = _skip_low_budget()
    p = find_or_create_project()
    num, pid = p["number"], p["id"]
    write_readme(num)
    fields = ensure_fields(num)
    have = board_items(num)
    issues = open_issues()
    current = current_milestones({i["repo"] for i in issues.values()} - FROZEN)
    added = []
    for key, labels in candidates(issues, current):
        if key not in have:
            item_id = add(num, pid, fields, key, labels, "Next")
            added.append(key)
            have[key] = {"id": item_id, "focus": "Next", "status": None, "title": "",
                         "lane": lane_for(key.split("#")[0], labels)}

    lane_changed = refresh_lanes(pid, fields, have, issues)

    # A card whose Focus update failed after item-add has no Focus and would never be retried.
    focus_filled = []
    for key, labels in candidates(issues, current):
        it = have.get(key)
        if it is not None and key not in added and not it.get("focus"):
            set_opt(pid, it["id"], fields["Focus"], "Next")
            it["focus"] = "Next"
            focus_filled.append(key)

    # Work already in progress: pull onto the board as This week / In Progress.
    started = []
    in_prog, stale_cards, failed_boards = in_progress_keys(set(issues))
    for key in sorted(in_prog):
        it = have.get(key)
        if it is None:
            labels = issues.get(key, {}).get("labels", [])
            item_id = add(num, pid, fields, key, labels, "This week")
            added.append(key)
            it = {"id": item_id, "focus": "This week", "status": None}
        elif it.get("focus") != "This week":
            set_opt(pid, it["id"], fields["Focus"], "This week")
        if it.get("status") != "In Progress":
            started.append(key)
            if "In Progress" in fields.get("Status", {}).get("opts", {}):
                set_opt(pid, it["id"], fields["Status"], "In Progress")
            else:
                print(f"warning: board has no Status option 'In Progress' ({key})", file=sys.stderr)
    # Sticky In Progress: a card that is no longer in progress goes back to Todo (Focus stays).
    # Skipped when a board could not be read, since its work would look stopped.
    stopped = []
    if not failed_boards:
        for key, it in sorted(have.items()):
            if key in issues and key not in in_prog and it.get("status") == "In Progress":
                stopped.append(key)
                if "Todo" in fields.get("Status", {}).get("opts", {}):
                    set_opt(pid, it["id"], fields["Status"], "Todo")
                else:
                    print(f"warning: board has no Status option 'Todo' ({key})", file=sys.stderr)
    unplanned = [k for k in started
                 if out_of_plan(k.split("#")[0], issues.get(k, {}).get("milestone"), current)]

    start = week_start()
    board_open = set(have) | set(added)
    new_since = sorted(k for k in board_open
                       if k in issues and (local_date(issues[k]["created"]) or datetime.date.min) >= start)
    closed = sorted(closed_since(start) & board_open)
    done_this_week = [k for k in closed if (have.get(k) or {}).get("focus") == "This week"]
    cost = _graphql_cost(before)

    if as_json:
        print(json.dumps({"url": p["url"], "current": current, "added": added, "started": started,
                          "stopped": stopped, "lane_changed": lane_changed,
                          "focus_filled": focus_filled, "stale_in_progress": stale_cards,
                          "unplanned": unplanned, "new_since_monday": new_since,
                          "closed_since_monday": closed, "done_this_week": done_this_week,
                          "graphql_cost": cost},
                         indent=2))
        return _finish_sync(failed_boards)
    for repo, title in current.items():
        print(f"current  {repo:26} {title}")
    print(f"{p['url']}\nadded {len(added)}: {' '.join(added) or '-'}")
    print(f"started {len(started)}: {' '.join(started) or '-'}")
    print(f"focus filled {len(focus_filled)}: {' '.join(focus_filled) or '-'}")
    print(f"stopped {len(stopped)}: {' '.join(stopped) or '-'}")
    print(f"lane changed {len(lane_changed)}: "
          f"{' '.join(c['key'] + ' ' + (c['from'] or '-') + '->' + c['to'] for c in lane_changed) or '-'}")
    for c in stale_cards:
        print(f"stale in progress: {c['key']} (last updated {c['updated']}) - "
              f"move the card back on {c['board']}")
    print(f"unplanned {len(unplanned)}: {' '.join(unplanned) or '-'}")
    print(f"new since {start} {len(new_since)}: {' '.join(new_since) or '-'}")
    print(f"closed since {start} {len(closed)}: {' '.join(closed) or '-'}")
    print(f"done this week {len(done_this_week)}: {' '.join(done_this_week) or '-'}")
    print("graphql cost: " + (f"{cost} points" if cost is not None else "unknown"))
    _finish_sync(failed_boards)


def _finish_sync(failed_boards):
    if failed_boards:
        print("weekly-focus: error: sync finished but could not read board(s): "
              + ", ".join(failed_boards), file=sys.stderr)
        sys.exit(1)


def set_focus(focus, keys):
    if focus not in FIELDS["Focus"] or not keys:
        print(f"usage: set <{'|'.join(FIELDS['Focus'])}> repo#N...  (got Focus={focus!r}, {keys})",
              file=sys.stderr)
        sys.exit(2)
    bad = [k for k in keys if not KEY_RE.match(k)]
    if bad:
        print(f"weekly-focus: bad issue key(s) {bad}: expected repo#N, e.g. app#12", file=sys.stderr)
        sys.exit(2)
    p = find_or_create_project()
    num, pid = p["number"], p["id"]
    fields = ensure_fields(num)
    have = board_items(num)
    for key in keys:
        if key in have:
            set_opt(pid, have[key]["id"], fields["Focus"], focus)
        else:
            repo, n = key.split("#")
            labels = [l["name"] for l in gh("issue", "view", n, "--repo", f"{OWNER}/{repo}",
                                              "--json", "labels")["labels"]]
            add(num, pid, fields, key, labels, focus)
        print(f"{focus}:", key)


def pick(keys):
    set_focus("This week", keys)


def priority(labels):
    """1-4 from P1..P4 / "priority: pN" labels (lowest number wins), else None."""
    found = [int(m.group(1)) for l in labels
             if (m := re.match(r"^(?:priority:\s*)?p([1-4])(?!\d)", l.strip().lower()))]
    return min(found) if found else None


def show_items(p):
    issues = open_issues()
    current = current_milestones({i["repo"] for i in issues.values()} - FROZEN)
    out = []
    for k, it in board_items(p["number"]).items():
        if it.get("status") == "Done" or k not in issues:
            continue
        repo, raw_ms = issues[k]["repo"], issues[k]["milestone"]
        frozen = repo in FROZEN
        focus = it.get("focus") or ""
        in_prog = it.get("status") == "In Progress"
        off = out_of_plan(repo, raw_ms, current)
        labels = issues[k]["labels"]
        out.append({
            "key": k, "repo": repo, "number": int(k.split("#")[1]), "url": issues[k].get("url", ""),
            "title": it.get("title", ""), "focus": focus, "lane": it.get("lane") or "",
            "status": it.get("status") or "", "milestone": raw_ms,
            "current_milestone": current.get(repo), "labels": labels, "priority": priority(labels),
            "in_current": raw_ms is not None and raw_ms == current.get(repo),
            "frozen": frozen, "in_progress": in_prog,
            "not_current": focus == "This week" and off and not frozen,
            "unplanned": in_prog and off,
        })
    return out


def show(as_json=False):
    p = find_or_create_project()
    items = show_items(p)
    if as_json:
        print(json.dumps({"url": p["url"], "week_start": week_start().isoformat(), "items": items},
                         indent=2))
        return
    order = {"This week": 0, "Next": 1, "Later": 2}
    for it in sorted(items, key=lambda r: (order.get(r["focus"], 3), r["lane"] or "-", r["key"])):
        flag = ""
        if it["not_current"]:
            flag += f"  <- not current ({it['current_milestone'] or 'none'})"
        if it["unplanned"]:
            flag += "  <- unplanned (in progress)"
        print(f"{it['focus'] or '-':10} {it['lane'] or '-':9} {it['key']:32} "
              f"{(it['milestone'] or '-')[:22]:22} {it['title'][:60]}{flag}")
    print(p["url"])


def main(argv):
    args = [a for a in argv if a != "--json"]
    as_json = "--json" in argv
    cmd = args[0] if args else "show"
    if cmd == "sync":
        sync(as_json)
    elif cmd == "set":
        set_focus(args[1] if len(args) > 1 else "", args[2:])
    elif cmd == "pick":
        pick(args[1:])
    elif cmd == "show":
        show(as_json)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (GhError, subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        print(f"weekly-focus: error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
        sys.exit(1)
