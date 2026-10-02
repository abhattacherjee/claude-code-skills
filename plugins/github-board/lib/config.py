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

Exit codes: 0 ok; 1 cache miss; 2 invalid config, payload or usage (the key is named), or the
config path is a dangling symlink; 3 init refused because the config already holds a different
value (pass --force); 4 no config file, or no section yet for the skill asking (run its init).
Standard library only; Python 3.9+.
"""
import argparse
import hashlib
import json
import os
import re
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
    except ConfigError as e:
        print(f"github-board: error: {e}", file=sys.stderr)
        return e.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
