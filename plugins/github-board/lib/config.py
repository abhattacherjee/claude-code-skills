#!/usr/bin/env python3
"""github-board shared config (#146).

Preferences: ${XDG_CONFIG_HOME:-~/.config}/github-board/config.json. Hand-editable; written
only by `init`. Nothing falls back to built-in values when it is missing.

Metadata cache: ${XDG_CACHE_HOME:-~/.cache}/github-board/<key>.json, one file per lookup with
the time it was fetched and the key tuple it was stored under (see cache_key()). Entries are reused for 7 days. An empty lookup is never cached.
Deleting the directory is always safe.

CLI (bash scripts call it through lib/config.sh):
  config.py path                         print the config file path
  config.py show                         print the config as JSON
  config.py get KEY [--lines] [--optional]
                                         print one value (KEY is dotted: plan_week.launchd.times);
                                         --lines prints a list one item per line; --optional
                                         prints nothing (exit 0) when there is no config or key
  config.py init [--require SECTION] [--force] [--from FILE]
                                         merge a JSON payload (stdin, or FILE) into the config
  config.py classify-error               read a gh error on stdin; print rate, scope or other
  config.py cache get PART... [--max-age-days N]  print a fresh entry (exit 1 on a miss)
  config.py cache put PART...                     store stdin JSON (never fails its caller)
  config.py cache drop PART... | drop-scope PART... | drop-containing TEXT
  config.py cache key PART...                     print the file name the key tuple maps to
                                         A key is a tuple of PARTs, e.g. move-boards OWNER REPO.
  config.py next-release-milestone --repo O/R [--cache FILE]
                                         print "<number>\t<title>" of the milestone merged work
                                         belongs to: milestones.next_release["O/R"] when set,
                                         else the open milestone with the lowest version (vX.Y
                                         or vX.Y.Z, sorted by version, not number). With no
                                         candidate, or a configured title that is missing or
                                         closed, it prints nothing and warns on stderr (exit 0)
  config.py milestone-for-tag --repo O/R --tag TAG [--cache FILE]
                                         print "<number>\t<title>" of TAG's release milestone
                                         (exact vX.Y.Z title, else vX.Y; leading v optional), or
                                         "skip\t<reason>" when none, two, or TAG is no version
  Both read gh api repos/O/R/milestones?state=all&per_page=100 --paginate. --cache FILE reads
  the list from FILE when it exists, else writes the list there after a good read.

Exit codes: 0 ok; 1 cache miss; 2 invalid config, payload or usage (the key is named), the
config path is a dangling symlink, or the milestone list could not be read (failed, empty or
malformed; never read as "no milestones"); 3 init refused because the config already holds a
different value (pass --force); 4 no config file, or no section yet for the skill asking (run
its init).
Standard library only; Python 3.9+.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

VERSION = 1
CACHE_MAX_AGE_DAYS = 7
SECTIONS = ("plan_week", "create_board")
# The init command that writes each section; named when a required section is missing.
SECTION_INIT = {"plan_week": "plan-week init", "create_board": "create-board init"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
ISSUE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LABEL_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
# A user login, a bot login (`name[bot]`), or gh's `app/name` form for a GitHub App.
AUTHOR_RE = re.compile(r"^(?:app/)?[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?$")
# gh errors that a refetch can never fix: an exhausted budget and a token without the scope.
# One definition for every script (weekly-focus.py imports these; bash calls classify-error).
RATE_RE = re.compile(r"rate limit|RATE_LIMIT", re.I)
SCOPE_RE = re.compile(r"required scopes|INSUFFICIENT_SCOPES|missing required scopes?|"
                      r"lacks the project scope", re.I)
INIT_HINT = "run `plan-week init` (or `create-board init` for the board template)"
# OWNER/REPO as it goes into a REST path. A "." or ".." part is refused apart (_repo_ok).
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# A release milestone title: vX.Y or vX.Y.Z, leading v optional. [0-9], not \d, which also
# matches other scripts' digits.
VERSION_TITLE_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)(?:\.([0-9]+))?$")


class ConfigError(Exception):
    """Invalid config, payload or usage. `key` names the offending key."""
    exit_code = 2

    def __init__(self, message: str, key: Optional[str] = None):
        super().__init__(message)
        self.key = key


class ConfigMissing(ConfigError):
    exit_code = 4


class ConfigConflict(ConfigError):
    exit_code = 3


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "github-board" / "config.json"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "github-board"


# ---- validation ---------------------------------------------------------------

def _req(obj: Any, key: str, path: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise ConfigError(f"missing required key {path}", path)
    return obj[key]


def _str(v: Any, path: str, pattern=None) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{path} must be a non-empty string", path)
    # fullmatch, not match: `$` also matches before a final newline, so match() let "me\n"
    # through and it broke every GraphQL query that used it.
    if pattern is not None and not pattern.fullmatch(v):
        raise ConfigError(f"{path} has an invalid value {v!r}", path)
    return v


def _int(v: Any, path: str, minimum: int = 0) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"{path} must be a whole number >= {minimum}", path)
    return v


def _str_list(v: Any, path: str, pattern=None) -> list:
    if not isinstance(v, list):
        raise ConfigError(f"{path} must be a list", path)
    for i, item in enumerate(v):
        _str(item, f"{path}[{i}]", pattern)
    return v


def _lane_name(v: Any, path: str) -> str:
    """A lane name becomes a single-select option, and gh takes the options as one
    comma-separated list, so a ',' would split one lane into two."""
    name = _str(v, path)
    if "," in name:
        raise ConfigError(f"{path} {name!r} contains ',', which a board option name cannot", path)
    return name


def _validate_plan_week(pw: Any) -> None:
    p = "plan_week"
    if not isinstance(pw, dict):
        raise ConfigError(f"{p} must be an object", p)
    _str(_req(pw, "board_title", f"{p}.board_title"), f"{p}.board_title")
    lanes = _req(pw, "lanes", f"{p}.lanes")
    if not isinstance(lanes, list):
        raise ConfigError(f"{p}.lanes must be a list", f"{p}.lanes")
    names = []
    for i, lane in enumerate(lanes):
        lp = f"{p}.lanes[{i}]"
        name = _lane_name(_req(lane, "name", f"{lp}.name"), f"{lp}.name")
        if name in names:
            raise ConfigError(f"{lp}.name: lane {name!r} is listed twice", f"{lp}.name")
        names.append(name)
        if "labels_containing" not in lane and "repos" not in lane:
            raise ConfigError(f"{lp} needs labels_containing or repos", lp)
        if "labels_containing" in lane:
            _str_list(lane["labels_containing"], f"{lp}.labels_containing")
        if "repos" in lane:
            _str_list(lane["repos"], f"{lp}.repos")
    default = _lane_name(_req(pw, "default_lane", f"{p}.default_lane"), f"{p}.default_lane")
    if default in names:
        raise ConfigError(f"{p}.default_lane {default!r} is also a rule lane", f"{p}.default_lane")
    known = names + [default]
    schedule = _req(pw, "schedule", f"{p}.schedule")
    if schedule is not None:
        if not isinstance(schedule, dict):
            raise ConfigError(f"{p}.schedule must be an object or null", f"{p}.schedule")
        for day, day_lanes in schedule.items():
            dp = f"{p}.schedule.{day}"
            if day not in DAYS:
                raise ConfigError(f"{dp}: unknown day (use {', '.join(DAYS)})", dp)
            for lane in _str_list(day_lanes, dp):
                if lane not in known:
                    raise ConfigError(f"{dp}: unknown lane {lane!r} (lanes: {', '.join(known)})", dp)
    _str_list(_req(pw, "frozen", f"{p}.frozen"), f"{p}.frozen")
    _str_list(_req(pw, "always", f"{p}.always"), f"{p}.always", ISSUE_KEY_RE)
    cap = _req(pw, "capacity", f"{p}.capacity")
    _int(_req(cap, "max_repos_besides_security", f"{p}.capacity.max_repos_besides_security"),
         f"{p}.capacity.max_repos_besides_security")
    hours = _req(cap, "hours", f"{p}.capacity.hours")
    if (not isinstance(hours, list) or len(hours) != 2
            or any(isinstance(h, bool) or not isinstance(h, int) or h < 0 for h in hours)
            or hours[0] > hours[1]):
        raise ConfigError(f"{p}.capacity.hours must be [low, high] whole hours", f"{p}.capacity.hours")
    ld = _req(pw, "launchd", f"{p}.launchd")
    enabled = _req(ld, "enabled", f"{p}.launchd.enabled")
    if not isinstance(enabled, bool):
        raise ConfigError(f"{p}.launchd.enabled must be true or false", f"{p}.launchd.enabled")
    times = _str_list(_req(ld, "times", f"{p}.launchd.times"), f"{p}.launchd.times", TIME_RE)
    if enabled and not times:
        raise ConfigError(f"{p}.launchd.times is empty but launchd is enabled", f"{p}.launchd.times")
    _str(_req(ld, "label_prefix", f"{p}.launchd.label_prefix"), f"{p}.launchd.label_prefix",
         LABEL_PREFIX_RE)


def _validate_create_board(cb: Any) -> None:
    p = "create_board"
    if not isinstance(cb, dict):
        raise ConfigError(f"{p} must be an object", p)
    _str(_req(cb, "template_owner", f"{p}.template_owner"), f"{p}.template_owner", LOGIN_RE)
    _int(_req(cb, "template_number", f"{p}.template_number"), f"{p}.template_number", minimum=1)


def _validate_prune_branches(pb: Any) -> None:
    p = "prune_branches"
    if not isinstance(pb, dict):
        raise ConfigError(f"{p} must be an object", p)
    if "tracking_issue_authors" in pb:
        _str_list(pb["tracking_issue_authors"], f"{p}.tracking_issue_authors", AUTHOR_RE)


def _repo_ok(repo: Any) -> bool:
    return (isinstance(repo, str) and REPO_RE.fullmatch(repo) is not None
            and not any(part in (".", "..") for part in repo.split("/")))


def _validate_milestones(ms: Any) -> None:
    p = "milestones"
    if not isinstance(ms, dict):
        raise ConfigError(f"{p} must be an object", p)
    if "next_release" not in ms:
        return
    nr = ms["next_release"]
    kp = f"{p}.next_release"
    # Keyed by repo, because one config serves every repo: {"owner/repo": "v4.1"}.
    if not isinstance(nr, dict):
        raise ConfigError(f'{kp} must be an object of "owner/repo": "milestone title"', kp)
    seen = {}
    for repo, title in nr.items():
        if not _repo_ok(repo):
            raise ConfigError(f"{kp}: key {repo!r} is not owner/repo", kp)
        _str(title, f"{kp}[{repo!r}]")
        if repo.lower() in seen:
            raise ConfigError(f"{kp}: {seen[repo.lower()]!r} and {repo!r} name the same repo", kp)
        seen[repo.lower()] = repo


def _validate_move_card(mc: Any) -> None:
    p = "move_card"
    if not isinstance(mc, dict):
        raise ConfigError(f"{p} must be an object", p)
    if "post_merge_columns" in mc:
        _str_list(mc["post_merge_columns"], f"{p}.post_merge_columns")


def validate(cfg: Any, require: Iterable[str] = ()) -> dict:
    if not isinstance(cfg, dict):
        raise ConfigError("the config must be a JSON object", "<file>")
    version = _req(cfg, "version", "version")
    if version != VERSION:
        raise ConfigError(f"unknown version {version!r}: this plugin reads version {VERSION}", "version")
    _str(_req(cfg, "owner", "owner"), "owner", LOGIN_RE)
    if "plan_week" in cfg:
        _validate_plan_week(cfg["plan_week"])
    if "create_board" in cfg:
        _validate_create_board(cfg["create_board"])
    if "prune_branches" in cfg:
        _validate_prune_branches(cfg["prune_branches"])
    if "milestones" in cfg:
        _validate_milestones(cfg["milestones"])
    if "move_card" in cfg:
        _validate_move_card(cfg["move_card"])
    for section in require:
        if section not in cfg:
            # The file exists (another skill's init wrote it) but this skill is not set up yet:
            # the same "run init" state as no file at all, so exit 4, not 2.
            hint = SECTION_INIT.get(section, "init")
            raise ConfigMissing(f"{config_path()} has no {section} section yet; run `{hint}`", section)
    return cfg


def _refuse_dangling(path: Path) -> None:
    if path.is_symlink() and not path.exists():
        raise ConfigError(f"{path} is a dangling symlink (to {os.readlink(path)}); fix or remove "
                          "the link", "<file>")


def load(require: Iterable[str] = ()) -> dict:
    path = config_path()
    _refuse_dangling(path)
    if not path.exists():
        raise ConfigMissing(f"no config at {path}; {INIT_HINT}")
    try:
        cfg = json.loads(path.read_text())
    except ValueError as e:
        raise ConfigError(f"{path} is not valid JSON ({e}); fix it, or re-run init with --force", "<file>")
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}", "<file>")
    return validate(cfg, require)


def get(cfg: dict, dotted: str) -> Any:
    cur: Any = cfg
    walked = []
    for part in dotted.split("."):
        walked.append(part)
        cur = _req(cur, part, ".".join(walked))
    return cur


def read_payload(from_file: Optional[str]) -> Any:
    """The init payload from FILE, or from stdin when no --from was given at all. An empty
    --from (an unset shell variable) is an error, never a silent switch to stdin."""
    if from_file is not None and not from_file.strip():
        raise ConfigError("--from was given an empty path", "--from")
    try:
        text = Path(from_file).read_text() if from_file is not None else sys.stdin.read()
    except OSError as e:
        raise ConfigError(f"cannot read {from_file}: {e}", "--from")
    try:
        return json.loads(text)
    except ValueError as e:
        raise ConfigError(f"the init payload is not valid JSON ({e})", "<payload>")


def init_config(payload: Any, require: Optional[str] = None, force: bool = False) -> Path:
    """Merge payload's top-level keys into the config and write it.

    A key that already holds a different value is refused (ConfigConflict, exit 3) unless
    force. The merged result is validated before anything is written."""
    if not isinstance(payload, dict):
        raise ConfigError("the init payload must be a JSON object", "<payload>")
    path = config_path()
    _refuse_dangling(path)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if not isinstance(existing, dict):
                raise ValueError("not a JSON object")
        except OSError as e:
            raise ConfigError(f"cannot read {path}: {e}", "<file>")
        except ValueError:
            if not force:
                raise ConfigError(f"{path} is not valid JSON; pass --force to replace it", "<file>")
            existing = {}
    merged = dict(existing)
    for key, value in payload.items():
        if key == "version":
            continue
        if key in existing and existing[key] != value and not force:
            raise ConfigConflict(f"{path} already has a different {key}; pass --force to replace it", key)
        merged[key] = value
    merged["version"] = VERSION
    if require and require not in merged:
        # A payload without the section is a bad payload (2), not "not set up yet" (4).
        raise ConfigError(f"missing required key {require} in the init payload", require)
    validate(merged)
    # A symlinked config (a dotfiles link) is written through: the temp file goes next to the
    # link's target and replaces the target, so the link survives. Replacing the link path
    # itself would turn it into a plain file and leave the dotfile stale.
    target = path.resolve() if path.is_symlink() else path
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(merged, indent=2) + "\n")
        os.replace(tmp, target)
    except OSError as e:
        raise ConfigError(f"cannot write {path}: {e}", "<file>")
    return path


# ---- metadata cache -------------------------------------------------------------
#
# A cache key is a tuple of strings, e.g. ("move-boards", owner, repo). cache_key() turns it
# into a file name: a readable prefix plus a short hash of the JSON-encoded tuple, so no two
# tuples share a file (joining with '-' made owner `a-b` + repo `c` equal owner `a` + repo
# `b-c`). The entry stores the tuple too, and a read whose tuple differs is a miss.
# Every caller (plan-week, move-card, promote-shipped) goes through cache_key().

_cache_warned = False
_drop_warned = False


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)


def _key_tuple(key: Any) -> list:
    parts = [key] if isinstance(key, str) else list(key)
    if not parts or not all(isinstance(p, str) for p in parts):
        raise TypeError(f"a cache key is a non-empty tuple of strings, got {key!r}")
    return parts


def cache_key(key: Any) -> str:
    """The file stem for a key tuple: readable prefix + 16 hex digits of sha256(JSON tuple)."""
    parts = _key_tuple(key)
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:16]
    return f"{_safe('-'.join(parts))[:80]}-{digest}"


def _cache_file(key: Any) -> Path:
    return cache_dir() / (cache_key(key) + ".json")


def _empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == ""


def cache_get(key: Any, max_age_days: float = CACHE_MAX_AGE_DAYS, now: Optional[float] = None) -> Any:
    """The cached value; None when missing, unreadable, too old, from the future, empty, or
    stored under a different key tuple."""
    try:
        entry = json.loads(_cache_file(key).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("key") != _key_tuple(key):
        return None
    fetched = entry.get("fetched_at")
    now = time.time() if now is None else now
    if isinstance(fetched, bool) or not isinstance(fetched, (int, float)):
        return None
    if fetched > now + 300 or now - fetched > max_age_days * 86400:
        return None
    value = entry.get("value")
    return None if _empty(value) else value


def cache_put(key: Any, value: Any, now: Optional[float] = None) -> bool:
    """Store value. Never raises: an unwritable cache warns once on stderr and returns False."""
    global _cache_warned
    if _empty(value):
        return False
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = _cache_file(key)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"key": _key_tuple(key),
                                   "fetched_at": time.time() if now is None else now,
                                   "value": value}))
        os.replace(tmp, f)
        return True
    except OSError as e:
        if not _cache_warned:
            print(f"github-board: warning: metadata cache not written ({e}); carrying on without it",
                  file=sys.stderr)
            _cache_warned = True
        return False


def _unlink(f: Path) -> bool:
    """Delete one entry. A missing file is fine; any other failure warns once, because an entry
    that cannot be deleted keeps being reused (a stale id would fail every run for 7 days)."""
    global _drop_warned
    try:
        f.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        if not _drop_warned:
            print(f"github-board: warning: could not delete cache entry {f.name} ({e}); stale "
                  f"board ids may be reused for up to {CACHE_MAX_AGE_DAYS} days. Delete "
                  f"{cache_dir()} by hand to clear it.", file=sys.stderr)
            _drop_warned = True
        return False


def cache_drop(key: Any) -> None:
    _unlink(_cache_file(key))


def _entries() -> list:
    try:
        return sorted(cache_dir().glob("*.json"))
    except OSError:
        return []


def cache_drop_scope(head: Any) -> int:
    """Drop every entry whose stored key tuple starts with `head`, e.g. ("plan-week", owner).
    Matching is on whole tuple items, so owner `a` never reaches owner `a-b`."""
    head = _key_tuple(head)
    n = 0
    for f in _entries():
        try:
            stored = json.loads(f.read_text()).get("key")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(stored, list) and stored[:len(head)] == head and _unlink(f):
            n += 1
    return n


def cache_drop_containing(text: str) -> int:
    n = 0
    for f in _entries():
        try:
            hit = text in f.read_text()
        except OSError:
            continue
        if hit and _unlink(f):
            n += 1
    return n


# ---- milestones (#204) ------------------------------------------------------------
#
# The one place that decides which milestone a piece of work belongs to. move-card,
# promote-shipped (apply-promotions.sh) and plan-milestones (release-reconcile.sh) all call
# it, so the tag rules and the next-release rule cannot drift apart.

class MilestoneListError(Exception):
    """The milestone list could not be read. Never the same as an empty list."""


def _one_line(text: str, limit: int = 160) -> str:
    return " ".join(text.split())[:limit]


def _out(text: Any) -> str:
    """A title as one stdout field: a tab or newline in it would split the row."""
    return re.sub(r"[\t\r\n]", " ", str(text))


def parse_milestone_pages(text: str, repo: str) -> list:
    """gh --paginate prints one JSON array per page, merged or back to back. Every page must
    be an array of objects; anything else is a failure, never a shorter list."""
    if not text.strip():
        raise MilestoneListError(f"could not list milestones for {repo}: gh returned no output "
                                 "(it prints [] when there are none)")
    dec = json.JSONDecoder()
    pos, out = 0, []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        try:
            page, pos = dec.raw_decode(text, pos)
        except ValueError as e:
            raise MilestoneListError(f"could not list milestones for {repo}: the reply is not JSON ({e})")
        if not isinstance(page, list):
            raise MilestoneListError(f"could not list milestones for {repo}: a page is not a list "
                                     f"({_one_line(json.dumps(page))})")
        if not all(isinstance(m, dict) for m in page):
            raise MilestoneListError(f"could not list milestones for {repo}: a page is not a list of "
                                     "milestones")
        out.extend({"title": m.get("title"), "number": m.get("number"), "state": m.get("state")}
                   for m in page)
    return out


def fetch_milestones(repo: str) -> list:
    """Every milestone of repo, all states, all pages. No --jq: gh applies it per page."""
    try:
        r = subprocess.run(["gh", "api", f"repos/{repo}/milestones?state=all&per_page=100",
                            "--paginate"], capture_output=True, text=True)
    except OSError as e:
        raise MilestoneListError(f"could not list milestones for {repo}: cannot run gh ({e})")
    if r.returncode != 0:
        raise MilestoneListError(f"could not list milestones for {repo} (gh exit {r.returncode}): "
                                 f"{_one_line(r.stderr + ' ' + r.stdout)}")
    return parse_milestone_pages(r.stdout, repo)


def load_milestones(repo: str, cache: Optional[str] = None) -> list:
    """The list from the run's cache file when given and present, else from gh. A failed read
    raises and writes nothing, so a later call retries instead of reading an empty list."""
    if cache:
        try:
            cached = json.loads(Path(cache).read_text())
            if isinstance(cached, list):
                return cached
        except (OSError, ValueError):
            pass
    found = fetch_milestones(repo)
    if cache:
        try:
            tmp = Path(f"{cache}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(found))
            os.replace(tmp, cache)
        except OSError:
            pass                 # a cache must never fail its caller
    return found


def _version_key(title: Any) -> Optional[tuple]:
    m = VERSION_TITLE_RE.fullmatch(title) if isinstance(title, str) else None
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _has_number(m: dict) -> bool:
    return isinstance(m.get("number"), int) and not isinstance(m.get("number"), bool)


def _tag_levels(tag: str) -> Optional[tuple]:
    """(exact, minor) titles to try for a tag, without the leading v; minor is "" for a
    two-part tag. None when the tag is not vX.Y.Z or vX.Y."""
    core = tag[1:] if tag.startswith("v") else tag
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", core):
        return core, core.rsplit(".", 1)[0]
    if re.fullmatch(r"[0-9]+\.[0-9]+", core):
        return core, ""
    return None


def milestone_for_tag(milestones: list, tag: str) -> tuple:
    """("hit", number, title) or ("skip", reason). The rules of PR A (#203): the exact X.Y.Z
    title first, then X.Y, leading v optional on both sides; more than one match at the first
    level that has any is refused, never resolved by picking one."""
    levels = _tag_levels(tag)
    if levels is None:
        return ("skip", f"tag '{_out(tag)}' is not vX.Y.Z or vX.Y")
    exact, minor = levels

    def pick(t):
        out = []
        for m in milestones:
            title = m.get("title") or ""
            if isinstance(title, str) and (title[1:] if title.startswith("v") else title) == t:
                out.append(m)
        return out

    hits = pick(exact)
    if not hits and minor:
        hits = pick(minor)
    if len(hits) == 1 and _has_number(hits[0]):
        return ("hit", hits[0]["number"], hits[0]["title"])
    if not hits:
        return ("skip", f"no milestone titled {exact}{' or ' + minor if minor else ''} for {tag}")
    names = ", ".join(f"{_out(m.get('title'))} #{m.get('number')}" for m in hits)
    return ("skip", f"ambiguous: {names} for {tag}")


def configured_next_release(cfg: Optional[dict], repo: str) -> Optional[str]:
    """milestones.next_release[repo], with the repo matched in any case (GitHub's is)."""
    table = ((cfg or {}).get("milestones") or {}).get("next_release") or {}
    for key, title in table.items():
        if key.lower() == repo.lower():
            return title
    return None


def next_release_milestone(milestones: list, repo: str, choice: Optional[str]) -> tuple:
    """((number, title) or None, [stderr lines]). Never guesses silently: a fallback pick says
    what it picked, and a configured title that is wrong sets nothing."""
    key = f'milestones.next_release["{repo}"]'
    if choice is not None:
        same = [m for m in milestones if m.get("title") == choice]
        if not same:
            return None, [f"WARN: {key} is {choice!r}, but {repo} has no milestone titled "
                          f"{choice!r}; no next-release milestone set. Fix the config."]
        if len(same) > 1 or not _has_number(same[0]):
            return None, [f"WARN: {key} is {choice!r}, which names "
                          f"{len(same)} milestones in {repo}; no next-release milestone set."]
        if same[0].get("state") != "open":
            return None, [f"WARN: {key} is {choice!r}, but that milestone is closed; "
                          "no next-release milestone set. Fix the config."]
        return (same[0]["number"], choice), []
    versions = [(k, m) for m in milestones
                for k in [_version_key(m.get("title"))]
                if k is not None and m.get("state") == "open" and _has_number(m)]
    if not versions:
        return None, [f"WARN: {repo} has no open milestone titled vX.Y or vX.Y.Z; no next-release "
                      "milestone (set milestones.next_release to choose)."]
    low = min(k for k, _ in versions)
    tied = [m for k, m in versions if k == low]
    if len(tied) > 1:
        names = ", ".join(f"{_out(m['title'])} #{m['number']}" for m in tied)
        return None, [f"WARN: the lowest open version in {repo} is ambiguous: {names}; no "
                      "next-release milestone (set milestones.next_release to choose)."]
    pick = tied[0]
    return (pick["number"], pick["title"]), [
        f"next-release milestone: {_out(pick['title'])} (lowest open version; set "
        "milestones.next_release to choose)"]


def _milestone_cli(args) -> int:
    if not _repo_ok(args.repo):
        raise ConfigError(f"--repo must be OWNER/REPO with no . or .. part, got {args.repo!r}",
                          "--repo")
    if args.cmd == "milestone-for-tag":
        # A tag that is not a version needs no list.
        milestones = [] if _tag_levels(args.tag) is None else load_milestones(args.repo, args.cache)
        found = milestone_for_tag(milestones, args.tag)
        print(f"{found[1]}\t{_out(found[2])}" if found[0] == "hit" else f"skip\t{_out(found[1])}")
        return 0
    try:
        cfg = load()
    except ConfigMissing:
        cfg = None
    choice = configured_next_release(cfg, args.repo)
    pick, notes = next_release_milestone(load_milestones(args.repo, args.cache), args.repo, choice)
    for line in notes:
        print(line, file=sys.stderr)
    if pick is not None:
        print(f"{pick[0]}\t{_out(pick[1])}")
    return 0


# ---- CLI ------------------------------------------------------------------------

def _print_value(value: Any, lines: bool) -> None:
    if lines and isinstance(value, list):
        for item in value:
            print(item if isinstance(item, str) else json.dumps(item))
    elif isinstance(value, bool):
        print("true" if value else "false")
    elif value is None:
        print("null")
    elif isinstance(value, (str, int, float)):
        print(value)
    else:
        print(json.dumps(value))


def _cache_cli(args) -> int:
    if args.op == "key":
        print(cache_key(args.key))
    elif args.op == "get":
        value = cache_get(args.key, args.max_age_days)
        if value is None:
            return 1
        print(json.dumps(value))
    elif args.op == "put":
        try:
            value = json.loads(sys.stdin.read())
        except ValueError:
            return 0          # a cache must never fail its caller
        cache_put(args.key, value)
    elif args.op == "drop":
        cache_drop(args.key)
    elif args.op == "drop-scope":
        print(cache_drop_scope(args.key))
    elif args.op == "drop-containing":
        print(cache_drop_containing(args.text))
    return 0


def error_kind(text: str) -> str:
    """"rate", "scope" or "other" for a gh error message."""
    if RATE_RE.search(text):
        return "rate"
    if SCOPE_RE.search(text):
        return "scope"
    return "other"


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="config.py", description="github-board config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path")
    sub.add_parser("show")
    g = sub.add_parser("get")
    g.add_argument("key")
    g.add_argument("--lines", action="store_true")
    g.add_argument("--optional", action="store_true",
                   help="no config, or no such key: print nothing and exit 0")
    i = sub.add_parser("init")
    i.add_argument("--require", choices=SECTIONS)
    i.add_argument("--force", action="store_true")
    i.add_argument("--from", dest="from_file")
    sub.add_parser("classify-error", help="read a gh error on stdin; print rate, scope or other")
    c = sub.add_parser("cache")
    csub = c.add_subparsers(dest="op", required=True)
    cg = csub.add_parser("get")
    cg.add_argument("key", nargs="+")
    cg.add_argument("--max-age-days", type=float, default=CACHE_MAX_AGE_DAYS)
    for op in ("key", "put", "drop", "drop-scope"):
        csub.add_parser(op).add_argument("key", nargs="+")
    csub.add_parser("drop-containing").add_argument("text")
    nr = sub.add_parser("next-release-milestone",
                        help="print the milestone merged work belongs to (number<TAB>title)")
    nr.add_argument("--repo", required=True)
    nr.add_argument("--cache", help="read the milestone list from FILE, or write it there")
    mt = sub.add_parser("milestone-for-tag", help="print a release tag's milestone (number<TAB>title)")
    mt.add_argument("--repo", required=True)
    mt.add_argument("--tag", required=True)
    mt.add_argument("--cache", help="read the milestone list from FILE, or write it there")
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "path":
            print(config_path())
        elif args.cmd == "show":
            print(json.dumps(load(), indent=2))
        elif args.cmd == "get":
            section = args.key.split(".")[0]
            if args.optional:
                try:
                    cfg = load()
                except ConfigMissing:
                    return 0
                try:
                    value = get(cfg, args.key)
                except ConfigError:
                    return 0
                _print_value(value, args.lines)
                return 0
            cfg = load(require=(section,) if section in SECTIONS else ())
            _print_value(get(cfg, args.key), args.lines)
        elif args.cmd == "init":
            print(f"wrote {init_config(read_payload(args.from_file), args.require, args.force)}")
        elif args.cmd == "cache":
            return _cache_cli(args)
        elif args.cmd == "classify-error":
            print(error_kind(sys.stdin.read()))
        elif args.cmd in ("next-release-milestone", "milestone-for-tag"):
            return _milestone_cli(args)
    except ConfigError as e:
        print(f"github-board: error: {e}", file=sys.stderr)
        return e.exit_code
    except MilestoneListError as e:
        print(f"github-board: error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
