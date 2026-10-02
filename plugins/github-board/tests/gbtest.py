"""Shared helpers for the github-board tests. Not a test module.

TEST_CFG uses invented names only (octo-user, season-repo, tool-a, frozen-repo) so the
plugin carries no real user's values. Its lane rules have the same shape as the pre-#146
weekly-focus constants: a Security label rule, a one-repo Season lane, a Tooling lane,
default Product.
"""
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Optional

PLUGIN = Path(__file__).resolve().parent.parent
LIB = PLUGIN / "lib"
SKILLS_DIR = PLUGIN / "skills"
WEEKLY_FOCUS = SKILLS_DIR / "plan-week" / "scripts" / "weekly-focus.py"

TEST_CFG = {
    "version": 1,
    "owner": "octo-user",
    "plan_week": {
        "board_title": "Weekly Focus",
        "lanes": [
            {"name": "Security", "labels_containing": ["security"]},
            {"name": "Season", "repos": ["season-repo"]},
            {"name": "Tooling", "repos": ["tool-a", "tool-b"]},
        ],
        "default_lane": "Product",
        "schedule": {"mon": ["Security"], "tue": ["Product"], "wed": ["Product"],
                     "thu": ["Tooling"], "fri": ["Season"], "sat": [], "sun": []},
        "frozen": ["frozen-repo"],
        "always": ["frozen-repo#951"],
        "capacity": {"max_repos_besides_security": 3, "hours": [10, 20]},
        "launchd": {"enabled": True, "times": ["07:00", "18:00"],
                    "label_prefix": "dev.example.plan-week"},
    },
    "create_board": {"template_owner": "octo-user", "template_number": 31},
}


def cfg_copy() -> dict:
    return copy.deepcopy(TEST_CFG)


def write_config(config_home: Path, data) -> Path:
    """Write data (a dict, or raw text) as <config_home>/github-board/config.json."""
    path = Path(config_home) / "github-board" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_lib():
    return _load(LIB / "config.py", "github_board_config_under_test")


def load_weekly_focus(cfg: Optional[dict] = None, stub_gh: bool = True):
    """weekly-focus.py as a fresh module. cfg (if given) is applied with apply_config()."""
    mod = _load(WEEKLY_FOCUS, "weekly_focus_under_test")
    if cfg is not None:
        mod.apply_config(copy.deepcopy(cfg))
    if stub_gh:
        def _no_gh(*a, **k):
            raise AssertionError(f"real gh called: {a}")
        mod.gh = _no_gh
    return mod


FAKE_GH = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
with open(os.environ["FAKE_GH_ROUTES"]) as f:
    routes = json.load(f)
joined = " ".join(args)
for r in routes:
    if all(s in joined for s in r["match"]):
        sys.stdout.write(r.get("stdout", ""))
        sys.stderr.write(r.get("stderr", ""))
        sys.exit(r.get("rc", 0))
sys.stderr.write("fake gh: no route for: " + joined + "\n")
sys.exit(97)
'''


def install_fake_gh(bindir: Path, routes: list, log: Path) -> dict:
    """A fake `gh` on PATH. routes: [{"match": [substrings], "stdout", "stderr", "rc"}], first
    match wins (substrings are matched against the space-joined argv). Returns env vars."""
    bindir.mkdir(parents=True, exist_ok=True)
    gh = bindir / "gh"
    gh.write_text("#!" + sys.executable + "\n" + FAKE_GH)
    gh.chmod(0o755)
    routes_file = bindir / "gh-routes.json"
    routes_file.write_text(json.dumps(routes))
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_ROUTES": str(routes_file), "FAKE_GH_LOG": str(log)}


def gh_calls(log: Path) -> list:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
