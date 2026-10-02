#!/usr/bin/env python3
"""github-board shared config (#146).

Preferences: ${XDG_CONFIG_HOME:-~/.config}/github-board/config.json. Hand-editable; written
only by `init`. Nothing falls back to built-in values when it is missing.

CLI (bash scripts call it through lib/config.sh):
  config.py path                         print the config file path
  config.py show                         print the config as JSON
  config.py get KEY [--lines]            print one value (KEY is dotted: plan_week.launchd.times);
                                         --lines prints a list one item per line
  config.py init [--require SECTION] [--force] [--from FILE]
                                         merge a JSON payload (stdin, or FILE) into the config

Exit codes: 0 ok; 2 invalid config, payload or usage (the key is named); 3 init refused
because the config already holds a different value (pass --force); 4 no config file.
Standard library only; Python 3.9+.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

VERSION = 1
SECTIONS = ("plan_week", "create_board")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
ISSUE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LABEL_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
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
    if pattern is not None and not pattern.match(v):
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
        name = _str(_req(lane, "name", f"{lp}.name"), f"{lp}.name")
        if name in names:
            raise ConfigError(f"{lp}.name: lane {name!r} is listed twice", f"{lp}.name")
        names.append(name)
        if "labels_containing" not in lane and "repos" not in lane:
            raise ConfigError(f"{lp} needs labels_containing or repos", lp)
        if "labels_containing" in lane:
            _str_list(lane["labels_containing"], f"{lp}.labels_containing")
        if "repos" in lane:
            _str_list(lane["repos"], f"{lp}.repos")
    default = _str(_req(pw, "default_lane", f"{p}.default_lane"), f"{p}.default_lane")
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


def validate(cfg: Any, require: Iterable[str] = ()) -> dict:
    if not isinstance(cfg, dict):
        raise ConfigError("the config must be a JSON object", "<file>")
    version = _req(cfg, "version", "version")
    if version != VERSION:
        raise ConfigError(f"unknown version {version!r}: this plugin reads version {VERSION}", "version")
    _str(_req(cfg, "owner", "owner"), "owner", LOGIN_RE)
    for section in require:
        _req(cfg, section, section)
    if "plan_week" in cfg:
        _validate_plan_week(cfg["plan_week"])
    if "create_board" in cfg:
        _validate_create_board(cfg["create_board"])
    return cfg


def load(require: Iterable[str] = ()) -> dict:
    path = config_path()
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
    try:
        text = Path(from_file).read_text() if from_file else sys.stdin.read()
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
    validate(merged, (require,) if require else ())
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(merged, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError as e:
        raise ConfigError(f"cannot write {path}: {e}", "<file>")
    return path


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


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="config.py", description="github-board config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path")
    sub.add_parser("show")
    g = sub.add_parser("get")
    g.add_argument("key")
    g.add_argument("--lines", action="store_true")
    i = sub.add_parser("init")
    i.add_argument("--require", choices=SECTIONS)
    i.add_argument("--force", action="store_true")
    i.add_argument("--from", dest="from_file")
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
            cfg = load(require=(section,) if section in SECTIONS else ())
            _print_value(get(cfg, args.key), args.lines)
        elif args.cmd == "init":
            print(f"wrote {init_config(read_payload(args.from_file), args.require, args.force)}")
    except ConfigError as e:
        print(f"github-board: error: {e}", file=sys.stderr)
        return e.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
