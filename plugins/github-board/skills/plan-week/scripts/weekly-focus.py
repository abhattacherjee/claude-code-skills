#!/usr/bin/env python3
"""Cross-repo "Weekly Focus" GitHub Project, driven by the github-board config.

Script: <github-board plugin>/skills/plan-week/scripts/weekly-focus.py
Config: ${XDG_CONFIG_HOME:-~/.config}/github-board/config.json gives the owner, board title,
lanes, schedule, frozen and always lists, capacity and launchd settings.
launchd runs `sync` at the configured times. The skill (/github-board:plan-week, or a question
like "what do I work on next") is the normal way to use this.

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
  weekly-focus.py init [--force] [--from FILE]
                                  write the config from a JSON payload ({"owner", "plan_week",
                                  optional "create_board"}) on stdin, or from FILE. Refuses
                                  (exit 3) to replace a different existing section without --force.
  weekly-focus.py config          print the current config as JSON (exit 4 when there is none)
  --no-cache (any command)        never read or write the board-id cache (~/.cache/github-board)
  weekly-focus.py --help          this text (needs no config)

  --json on show also carries the config's schedule, capacity, lanes and default_lane.
  sync --json and show --json carry config_warnings: frozen or always entries that match no
  open issue (a renamed or deleted repo, or a closed issue).

Exit codes: 0 ok; 1 error; 2 usage or invalid config (names the key); 3 sync skipped
(GraphQL budget low) or init refused; 4 no config yet (run `plan-week init`).

"Current milestone" = the lowest-versioned open milestone that still has open issues
(titles starting with a version: v0.6, V1.2, 0.4, v2.0 — ...). Backlog/theme milestones, and any
milestone whose title or description says "paused", never count. Frozen repos
(plan_week.frozen) are skipped by sync. Edit the config to thaw one.
"""
import datetime
import importlib.util
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _load_github_board_lib():
    """lib/config.py of the plugin this script ships in (found from this file, never from HOME)."""
    path = Path(__file__).resolve().parents[3] / "lib" / "config.py"
    spec = importlib.util.spec_from_file_location("github_board_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gbconfig = _load_github_board_lib()

# Filled in from the github-board config by apply_config(); main() calls it. Nothing here
# carries a user's values; tests call apply_config() with their own.
CONFIG = {}
OWNER = ""
TITLE = "Weekly Focus"
FROZEN = set()
ALWAYS = set()          # repo#N pulled in even though the repo is frozen
LANES = []              # [{"name", "labels_containing"?, "repos"?}]; first match wins
DEFAULT_LANE = "Product"
SCHEDULE = None         # {"mon": [lane, ...], ...}, or None for no fixed days
CAPACITY = {"max_repos_besides_security": 3, "hours": [10, 20]}
LAUNCHD = {"enabled": False, "times": [], "label_prefix": ""}
FIELDS = {
    "Focus": ["This week", "Next", "Later"],
    "Lane": [],
}
DAY_NAMES = (("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"),
             ("sat", "Sat"), ("sun", "Sun"))
IN_PROGRESS_STATUSES = {"in progress", "in review"}
GH_TIMEOUT = 120
GH_RETRY_DELAY = 3
STALE_DAYS = 21          # a board card counts as in progress only if its issue moved this recently
MIN_BUDGET = 300         # sync skips (exit 3) when fewer GraphQL points than this are left
EXIT_SKIPPED = 3
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")
VERSIONED = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")


def board_readme():
    """The README sync writes to the board, built from the config."""
    lo, hi = CAPACITY["hours"]
    if SCHEDULE:
        days = [f"- {label}: {', '.join(SCHEDULE[key])}" for key, label in DAY_NAMES if SCHEDULE.get(key)]
    else:
        days = ["- No fixed days: Security first, then priority order."]
    if LAUNCHD.get("enabled"):
        sync_line = f"- launchd runs `weekly-focus.py sync` at {' and '.join(LAUNCHD['times'])}."
    else:
        sync_line = "- Run `weekly-focus.py sync` (or ask the skill) to refresh the board."
    return "\n".join([
        "Cross-repo weekly plan. Per-repo boards stay the source of truth for their lifecycle.",
        "",
        "Rules:",
        "- This week takes work only from each repo's current milestone (the lowest-versioned open",
        "  milestone with open issues). `show` flags any This week item outside it.",
        "- Security may jump ahead. Move that issue into the current milestone so it ships in the",
        "  next release. Key rotations with no code change are the exception.",
        f"- At most {CAPACITY['max_repos_besides_security']} repos per week besides Security. "
        "Everything else stays Next or Later.",
        "",
        "- Work already in progress (Status In progress / In review on any of your boards, or an open PR",
        "  that closes the issue) is pulled in automatically. It is marked unplanned when it is outside",
        "  the plan, and never hidden or demoted.",
        "",
        f"Weekly rhythm ({lo}-{hi}h):",
        sync_line,
        "- Ask the skill (`/github-board:plan-week`, or \"what do I work on next\") for the next item;",
        "  plan the week on its first day, 30 min: clear the Security lane, pick the week.",
        *days,
        "",
        f"Frozen (not synced; issues kept open): {', '.join(sorted(FROZEN)) or 'none'}.",
        "",
    ])


class GhError(RuntimeError):
    pass


RATE_RE = re.compile(r"rate limit|RATE_LIMIT", re.I)
SCOPE_RE = re.compile(r"required scopes|INSUFFICIENT_SCOPES|missing required scopes?|lacks the project scope", re.I)
CACHE_MODE = "use"      # "use" | "refresh" (skip reads, write fresh) | "off" (--no-cache)
_CACHE_USED = False


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
            if SCOPE_RE.search(err) or SCOPE_RE.search(body):
                raise GhError("GitHub token lacks the project scope; run "
                              f"`gh auth refresh -s read:project,project` (gh {' '.join(args[:2])}: "
                              f"{err[:200]})") from e
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


def _cache_key(name):
    return f"plan-week-{OWNER}-{name}"


def _cache_read(name):
    """A cached board lookup, or None. Records that cached ids were used this run."""
    global _CACHE_USED
    if CACHE_MODE != "use":
        return None
    value = gbconfig.cache_get(_cache_key(name))
    if value is not None:
        _CACHE_USED = True
    return value


def _cache_write(name, value):
    if CACHE_MODE != "off":
        gbconfig.cache_put(_cache_key(name), value)


def _run_with_refetch(fn):
    """Run fn. If it fails while ids from the disk cache are in use, drop the cache and run it
    once more with fresh lookups.

    Any gh failure counts, not only "Could not resolve ...": a stale Lane or Focus option id
    fails with other text, and would otherwise fail every run until the entry ages out.
    Rate-limit and missing-scope errors are never retried. Each command is idempotent
    (sync adds only what is missing; set re-sets the same Focus), so a rerun is safe.
    """
    global CACHE_MODE
    try:
        return fn()
    except GhError as e:
        msg = str(e)
        if not (_CACHE_USED and CACHE_MODE == "use") or RATE_RE.search(msg) or SCOPE_RE.search(msg):
            raise
    print("weekly-focus: cached board ids look stale; refetching once", file=sys.stderr)
    gbconfig.cache_drop_prefix(f"plan-week-{OWNER}-")
    _CACHE.clear()
    CACHE_MODE = "refresh"
    return fn()


_PROJECTS_Q = (
    'query($endCursor:String){user(login:"%s"){projectsV2(first:100,after:$endCursor){'
    "pageInfo{hasNextPage endCursor} nodes{id number title url closed}}}}")
_FIELDS_Q = (
    'query{user(login:"%s"){projectV2(number:%%d){fields(first:100){nodes{'
    "... on ProjectV2SingleSelectField{id name options{id name}} ... on ProjectV2Field{id name}}}}}}")
_BOARD_ITEMS_Q = (
    'query($endCursor:String){user(login:"%s"){projectV2(number:%%d){items(first:100,after:$endCursor){'
    "pageInfo{hasNextPage endCursor} nodes{id "
    'focus:fieldValueByName(name:"Focus"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    'lane:fieldValueByName(name:"Lane"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    'status:fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}} '
    "content{... on Issue{number title state repository{name owner{login}}}}}}}}}")
PROJECTS_Q = FIELDS_Q = BOARD_ITEMS_Q = PR_LINKED_Q = ""   # set by apply_config()


def apply_config(cfg):
    """Set this module's settings from a validated github-board config (gbconfig.load())."""
    global CONFIG, OWNER, TITLE, FROZEN, ALWAYS, LANES, DEFAULT_LANE, SCHEDULE, CAPACITY, LAUNCHD
    global PROJECTS_Q, FIELDS_Q, BOARD_ITEMS_Q, PR_LINKED_Q
    pw = cfg["plan_week"]
    CONFIG = cfg
    OWNER = cfg["owner"]
    TITLE = pw["board_title"]
    FROZEN = set(pw["frozen"])
    ALWAYS = set(pw["always"])
    LANES = [dict(lane) for lane in pw["lanes"]]
    DEFAULT_LANE = pw["default_lane"]
    SCHEDULE = pw["schedule"]
    CAPACITY = dict(pw["capacity"])
    LAUNCHD = dict(pw["launchd"])
    FIELDS["Lane"] = [lane["name"] for lane in LANES] + [DEFAULT_LANE]
    PROJECTS_Q = _PROJECTS_Q % OWNER
    FIELDS_Q = _FIELDS_Q % OWNER
    BOARD_ITEMS_Q = _BOARD_ITEMS_Q % OWNER
    PR_LINKED_Q = _PR_LINKED_Q % OWNER


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
        hit = _cache_read(f"project-{TITLE}")
        if isinstance(hit, dict) and all(k in hit for k in ("id", "number", "url")):
            return hit
        p = next((q for q in list_projects() if q["title"] == TITLE), None)
        if p is None:
            p = gh("project", "create", "--owner", OWNER, "--title", TITLE, "--format", "json")
        _cache_write(f"project-{TITLE}", {k: p.get(k) for k in ("id", "number", "url", "title")})
        return p
    return _cached("project", find)


def write_readme(num):
    gh("project", "edit", str(num), "--owner", OWNER, "--readme", board_readme(),
       "--description", "Cross-repo weekly focus", "--format", "json")


def field_map(num):
    raw = gh("api", "graphql", "-f", f"query={FIELDS_Q % int(num)}",
             "--jq", ".data.user.projectV2.fields.nodes[]", parse=False)
    fields = (json.loads(l) for l in raw.splitlines() if l.strip())
    return {f["name"]: f for f in fields if f.get("name")}


def _fields_complete(out):
    """A cached field map is usable only if it has every field and option FIELDS needs."""
    return isinstance(out, dict) and all(
        isinstance(out.get(name), dict) and all(o in out[name].get("opts", {}) for o in opts)
        for name, opts in FIELDS.items())


def ensure_fields(num):
    def read():
        hit = _cache_read(f"fields-{num}")
        if _fields_complete(hit):
            return hit
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
        _cache_write(f"fields-{num}", out)
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


def label_lane(labels):
    """The first lane whose labels_containing matches a label (case-insensitive), else None."""
    low = [l.lower() for l in labels]
    for lane in LANES:
        subs = [s.lower() for s in lane.get("labels_containing", [])]
        if any(s in l for l in low for s in subs):
            return lane["name"]
    return None


def lane_for(repo, labels):
    """First matching lane rule (a label rule or a repo list), else DEFAULT_LANE."""
    low = [l.lower() for l in labels]
    for lane in LANES:
        subs = [s.lower() for s in lane.get("labels_containing", [])]
        if any(s in l for l in low for s in subs) or repo in lane.get("repos", []):
            return lane["name"]
    return DEFAULT_LANE


def add(num, pid, fields, key, labels, focus):
    repo, n = key.split("#")
    url = f"https://github.com/{OWNER}/{repo}/issues/{n}"
    item = gh("project", "item-add", str(num), "--owner", OWNER, "--url", url, "--format", "json")
    lane = lane_for(repo, labels)
    if lane in fields["Lane"]["opts"]:
        set_opt(pid, item["id"], fields["Lane"], lane)
    else:
        print(f"warning: board has no Lane option {lane!r} ({key}); add it to the board's Lane field",
              file=sys.stderr)
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
_PR_LINKED_Q = (
    "query($endCursor:String){search(query:\"is:pr is:open author:%s\",type:ISSUE,first:100,"
    "after:$endCursor){pageInfo{hasNextPage endCursor} nodes{... on PullRequest{body "
    "repository{name owner{login}} "
    "closingIssuesReferences(first:20){nodes{number state repository{name owner{login}}}}}}}}")
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


def config_warnings(issues):
    """Config entries that match no open issue: usually a renamed or deleted repo."""
    repos = {i["repo"] for i in issues.values()}
    out = [f"frozen repo {r!r} has no open issues (renamed or deleted? check plan_week.frozen)"
           for r in sorted(FROZEN - repos)]
    out += [f"always issue {k!r} is not an open issue (closed, moved, or its repo renamed? "
            "check plan_week.always)" for k in sorted(ALWAYS - set(issues))]
    return out


def refresh_lanes(pid, fields, have, issues):
    """Fill an empty Lane, and lift an item to a label lane (e.g. Security) once it gains a matching label.

    Any other non-empty Lane is left alone (no downgrade, no overwrite of a hand-set lane).
    Returns [{key, from, to}].
    """
    changed = []
    for key, it in sorted(have.items()):
        if key not in issues:
            continue
        cur = it.get("lane") or ""
        labels = issues[key]["labels"]
        lifted = label_lane(labels)
        if not cur:
            new = lane_for(issues[key]["repo"], labels)
        elif lifted and cur != lifted:
            new = lifted
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
    warnings = config_warnings(issues)
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
                          "graphql_cost": cost, "config_warnings": warnings},
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
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
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


def show_items(p, issues=None):
    issues = open_issues() if issues is None else issues
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
    issues = open_issues()
    items = show_items(p, issues)
    warnings = config_warnings(issues)
    if as_json:
        print(json.dumps({"url": p["url"], "week_start": week_start().isoformat(),
                          "schedule": SCHEDULE, "capacity": CAPACITY,
                          "lanes": [lane["name"] for lane in LANES], "default_lane": DEFAULT_LANE,
                          "config_warnings": warnings, "items": items}, indent=2))
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
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


COMMANDS = ("sync", "set", "pick", "show", "init", "config")


def init_cmd(args):
    """init [--force] [--from FILE]: merge the payload into the config through lib/config.py."""
    force = "--force" in args
    rest = [a for a in args if a != "--force"]
    from_file = None
    if rest[:1] == ["--from"]:
        if len(rest) < 2:
            raise gbconfig.ConfigError("--from needs a file", "--from")
        from_file, rest = rest[1], rest[2:]
    if rest:
        raise gbconfig.ConfigError(f"unknown init argument(s): {' '.join(rest)}", "init")
    path = gbconfig.init_config(gbconfig.read_payload(from_file), require="plan_week", force=force)
    print(f"wrote {path}")


def main(argv):
    global CACHE_MODE
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    args = [a for a in argv if a not in ("--json", "--no-cache")]
    as_json = "--json" in argv
    if "--no-cache" in argv:
        CACHE_MODE = "off"
    cmd = args[0] if args else "show"
    if cmd not in COMMANDS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    if cmd == "init":
        init_cmd(args[1:])
        return
    apply_config(gbconfig.load(require=("plan_week",)))
    if cmd == "config":
        print(json.dumps(CONFIG, indent=2))
        return

    def run():
        if cmd == "sync":
            sync(as_json)
        elif cmd == "set":
            set_focus(args[1] if len(args) > 1 else "", args[2:])
        elif cmd == "pick":
            pick(args[1:])
        else:
            show(as_json)
    _run_with_refetch(run)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except gbconfig.ConfigError as e:
        print(f"weekly-focus: error: {e}", file=sys.stderr)
        sys.exit(e.exit_code)
    except (GhError, subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        print(f"weekly-focus: error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
        sys.exit(1)
