# github-board Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `/plugin install github-board@claude-code-skills` installs seven GitHub-workflow skills (short verb names) and the four agents `create-board` dispatches, with every per-user value moved out of the plugin into `~/.config/github-board/config.json`.

**Architecture:** The plugin is authored directly in `plugins/github-board/` (the `adversarial-review` pattern). A shared `lib/config.py` (plus a thin `lib/config.sh` for bash) loads and validates the per-user config and keeps a 7-day metadata cache under `~/.cache/github-board/`. `plan-week` (was `weekly-focus`) reads owner, lanes, schedule, capacity and launchd settings from the config; its launchd jobs run through a stable symlink `~/.local/share/github-board/current` so they survive plugin upgrades.

**Tech Stack:** bash, Python 3.9+ (standard library only), `gh` CLI, `jq`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-02-github-board-plugin-design.md` (issue #146). Read it before starting; this plan argues from it.

## Global Constraints

- Repo: `/Users/abhishek/dev/claude_workspace/claude-code-skills`, branch `feature/146-github-board-plugin`. All paths below are relative to the repo root. Never use a bare `cd` into a subdirectory; use absolute paths or `( cd dir && cmd )`.
- Python floor is 3.9 (CI runs `actions/setup-python` with `"3.9"`): no `match`, no `X | Y` type unions, no 3.10+ APIs. Standard library only.
- Tests run offline. `gh` is always a fake (a PATH-shimmed executable or a monkeypatched function). Nothing touches live GitHub, the real `launchctl`, the real `~/Library/LaunchAgents`, `~/.config`, `~/.cache` or `~/.local/share`. A `conftest.py` autouse fixture points `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` at `tmp_path` for every test.
- Run pytest as `python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider` (no `.pytest_cache` in the repo root).
- Skill names: `create-board`, `triage-issues`, `plan-milestones`, `plan-week`, `move-card`, `promote-shipped`, `prune-branches`. Agent names: `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier`; dispatched as `github-board:<agent>`.
- In a SKILL.md, `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` are substituted as text when the skill loads; they are not environment variables in the Bash tool. Commands spell `"${CLAUDE_SKILL_DIR}/scripts/<x>"`. Scripts find themselves and `lib/` from `BASH_SOURCE[0]` / `__file__`.
- Config path `${XDG_CONFIG_HOME:-~/.config}/github-board/config.json`; cache dir `${XDG_CACHE_HOME:-~/.cache}/github-board/`; link `${GITHUB_BOARD_LINK:-~/.local/share/github-board/current}`. Cache entries live 7 days.
- `plan-week` keeps `STATE_DIR` default `~/.local/state/weekly-focus`, `LOG_DIR` default `~/Library/Logs/weekly-focus`, the script name `weekly-focus.py`, and the board fields. Labels are `<plan_week.launchd.label_prefix>-sync` and `-watchdog`.
- Exit codes: config missing → 4 ("run `plan-week init`"); unparseable config, unknown `version`, missing or bad key → 2 naming the key; `init` refusing to replace a different existing section → 3; `install-launchd.sh` refused takeover or non-symlink link path → 3, failed `launchctl` step → 1, bad arguments or launchd disabled → 2. Everything else keeps its current exit codes.
- No plugin file may contain the author's login, the repo names from the pre-#146 `FROZEN`/`ALWAYS`/`TOOLING`/`SEASON` constants, or `com.<login>`, except CHANGELOG history and the five follow-up/marketplace repo names in the plugin's root `README.md`. The author's `init --from` seed file is never committed.
- No `~/.claude/skills/`, `$HOME/.claude/skills/`, `__HOME__/.claude/skills/` or `.claude/agents/` path in the plugin outside CHANGELOG history and the plugin root `README.md` runbook.
- Commits: one per task. Stage explicit paths only (never `git add -A`). Run `./scripts/commit-preflight.sh` as its own Bash command, then `git commit` as a separate command within 300 s (a hook checks the token). End each commit message with the attribution lines the session's system prompt gives.
- Writing style for docs, comments and commit messages: plain English, short sentences.

## Review Focus

1. **Config present, but the `gh` token lacks the `project` scope.** `plan-week` must fail at once with one line naming `gh auth refresh -s read:project,project`, never retry the call, and write nothing to the cache. Test: Task 6, `test_scope_error_is_not_retried_and_names_the_fix` and `test_scope_error_writes_no_cache`.
2. **A repo in `plan_week.frozen` or `plan_week.always` was renamed or deleted.** Sync must keep working and report the stale entry in `config_warnings` (JSON) and on stderr (human mode), so the renamed repo's issues being synced is explained. Test: Task 4, `test_sync_json_reports_config_entries_with_no_open_issue` and `test_show_json_reports_config_warnings_schedule_and_capacity`.
3. **The cache directory cannot be written** (a file in the way, a read-only disk). Every command must still succeed from live data and warn once on stderr. Test: Task 6, `test_unwritable_cache_warns_once_and_returns_false` and `test_plan_week_runs_when_the_cache_cannot_be_written`.
4. **`plan_week.schedule` names a lane that is not in `lanes` or `default_lane`** (a typo). Loading must exit 2 naming `plan_week.schedule.<day>` and the bad lane, not silently skip the day. Test: Task 3, `test_schedule_with_unknown_lane_exits_2_naming_the_day`.
5. **The link path `~/.local/share/github-board/current` exists as a real directory.** `install-launchd.sh` must refuse with exit 3 and write nothing (no `ln` into the directory, no plist); `--check` must report `NOT A LINK`. Test: Task 7, `test_link_path_that_is_a_real_directory_is_refused` and `test_check_reports_a_real_directory_at_the_link_path`.

---

## File Structure

```
plugins/github-board/
  .claude-plugin/plugin.json          plugin manifest (name, version 1.0.0, description)
  .gitignore                          __pycache__/, *.pyc, .pytest_cache/
  README.md                           skills, agents, config, cache, launchd, Phase 3/4 runbook
  CHANGELOG.md                        [1.0.0]
  LICENSE                             MIT (copied from plugins/adversarial-review/LICENSE)
  lib/
    config.py                         load/validate/init the config; metadata cache; CLI
    config.sh                         bash wrappers around config.py (sourced)
  skills/
    create-board/                     from ~/.claude/skills/create-gh-board/  (+ scripts/init-config.sh)
    triage-issues/                    from ~/.claude/skills/github-issue-triage/
    plan-milestones/                  from ~/.claude/skills/github-milestone-planning/
    plan-week/                        from claude-code-config skills/weekly-focus/
      launchd/sync.plist.template     renamed from com.<login>.weekly-focus-sync.plist.template
      launchd/watchdog.plist.template renamed from com.<login>.weekly-focus-watchdog.plist.template
    move-card/                        git mv of this repo's github-board-move/
    promote-shipped/                  from claude-code-config skills/github-release-board-promote/ (no tests/, no plugin-manifest.json)
    prune-branches/                   from ~/.claude/skills/git-branch-cleanup/
  agents/
    template-inspector.md  board-creator.md  workflow-syncer.md  board-verifier.md
  tests/
    conftest.py                       autouse XDG isolation; gb_config fixture
    gbtest.py                         TEST_CFG, write_config, load_lib, load_weekly_focus, fake gh
    test_structure.py                 Task 1
    test_paths.py                     Task 2
    test_config.py                    Task 3
    test_plan_week_config.py          Task 4 (lanes parity, schedule/capacity, warnings)
    test_plan_week_init.py            Task 5
    test_cache.py                     Task 6
    test_create_board_config.py       Task 9
    test_board_cache.py               Task 10
    test_no_personal_values.py        Task 11
    smoke-clean-home.sh               Task 11
    test_weekly_focus.py              moved from claude-code-config/tests/
    test_weekly_focus_launchd.py      moved from claude-code-config/tests/
    test_weekly_focus_skill_shell.py  moved from claude-code-config/tests/
    test_apply_promotions_reconcile.py, test_apply_promotions_release_lookup.py,
    test_find_promotable_discovery.py, test_read_scripts_scope_preflight.py,
    test_script_exit_codes.py         moved from promote-shipped's tests/
```

Also modified: `.claude-plugin/marketplace.json`, `README.md`, `CHANGELOG.md`, `.github/workflows/validate-skill.yml`, `scripts/validate-skill.sh` and its byte-identical copy `plugins/skill-publishing/skills/skill-publishing/scripts/validate-skill.sh`, skill-publishing's version files, `skill-authoring/SKILL.md`, `skill-authoring/references/task-tracking-pattern.md`, the same two under `plugins/skill-authoring/skills/skill-authoring/`, skill-authoring's version files, `plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh`. Deleted: the repo-root `github-board-move/` (by `git mv`).

Source roots used below:

```bash
REPO=/Users/abhishek/dev/claude_workspace/claude-code-skills
CCC=/Users/abhishek/dev/claude_workspace/claude-code-config
P=plugins/github-board
```

---

### Task 1: Scaffold the plugin with renamed copies of all skills, agents and tests

Verbatim copies plus renames only. Behaviour does not change in this task.

**Files:**
- Create: `plugins/github-board/{.claude-plugin/plugin.json,.gitignore,README.md,CHANGELOG.md,LICENSE}`
- Create (copies): `plugins/github-board/skills/{create-board,triage-issues,plan-milestones,plan-week,promote-shipped,prune-branches}/`, `plugins/github-board/agents/*.md`, `plugins/github-board/tests/test_weekly_focus*.py`, the five promote tests
- Move: `github-board-move/` → `plugins/github-board/skills/move-card/` (`git mv`)
- Create: `plugins/github-board/tests/{conftest.py,gbtest.py,test_structure.py}`
- Modify: `.claude-plugin/marketplace.json`, `README.md` (drop the `github-board-move` install line), `scripts/validate-skill.sh`, `plugins/skill-publishing/skills/skill-publishing/scripts/validate-skill.sh`, skill-publishing version files

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/gbtest.py` with `PLUGIN: Path`, `LIB: Path`, `SKILLS_DIR: Path`, `TEST_CFG: dict`, `write_config(config_home: Path, data) -> Path`, `load_lib() -> module`, `load_weekly_focus(cfg: Optional[dict] = None, stub_gh: bool = True) -> module`, `install_fake_gh(bindir: Path, routes: list, log: Path) -> dict` (env vars to merge), `gh_calls(log: Path) -> list[list[str]]`. `tests/conftest.py` with autouse `_isolated_xdg` and fixture `gb_config` (writes `TEST_CFG`, returns its path). `load_lib` and `load_weekly_focus` only work once Tasks 3 and 4 land; they are defined now so later tasks share one helper.

- [ ] **Step 1: Write the test helpers**

`plugins/github-board/tests/gbtest.py`:

```python
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
```

`plugins/github-board/tests/conftest.py`:

```python
import pytest

from gbtest import TEST_CFG, write_config


@pytest.fixture(autouse=True)
def _isolated_xdg(tmp_path, monkeypatch):
    """No test reads or writes the real ~/.config, ~/.cache or ~/.local/share."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("GITHUB_BOARD_LINK", str(tmp_path / "share" / "github-board" / "current"))


@pytest.fixture
def gb_config(tmp_path):
    """TEST_CFG written to the isolated config dir. Returns the file path."""
    return write_config(tmp_path / "xdg-config", TEST_CFG)
```

- [ ] **Step 2: Write the failing structure test**

`plugins/github-board/tests/test_structure.py`:

```python
"""Structure of the github-board plugin (#146): seven skills, four agents, new names only."""
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = {"create-board", "triage-issues", "plan-milestones", "plan-week", "move-card",
          "promote-shipped", "prune-branches"}
AGENTS = {"template-inspector", "board-creator", "workflow-syncer", "board-verifier"}
OLD_SKILLS = ["create-gh-board", "github-issue-triage", "github-milestone-planning",
              "weekly-focus", "github-board-move", "github-release-board-promote",
              "git-branch-cleanup"]
OLD_AGENTS = ["gh-board-template-inspector", "gh-board-creator", "gh-board-workflow-syncer",
              "gh-board-verifier"]
OLD = OLD_SKILLS + OLD_AGENTS
# A bare mention (`create-gh-board`, "spawned by create-gh-board skill") and a slash command
# (/create-gh-board). Path pieces stay out of scope: "/state/weekly-focus", "weekly-focus.py",
# "com.example.weekly-focus-sync" keep the tool's own name on purpose.
BARE = {n: re.compile(r"(?<![\w/.-])" + re.escape(n) + r"(?![\w.-])") for n in OLD}
SLASH = {n: re.compile(r"(?:^|[\s(`'\"])/" + re.escape(n) + r"(?![\w/.-])") for n in OLD}


def _frontmatter(path: Path) -> str:
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path}: no frontmatter"
    return m.group(1)


def _field(path: Path, field: str):
    m = re.search(rf"^{field}:\s*(.+?)\s*$", _frontmatter(path), re.M)
    return m.group(1).strip('"') if m else None


def test_exactly_the_seven_skills():
    assert {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()} == SKILLS


def test_exactly_the_four_agents():
    assert {p.stem for p in (PLUGIN / "agents").glob("*.md")} == AGENTS


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_name_matches_directory(skill):
    assert _field(PLUGIN / "skills" / skill / "SKILL.md", "name") == skill


@pytest.mark.parametrize("agent", sorted(AGENTS))
def test_agent_name_matches_file_and_names_create_board(agent):
    path = PLUGIN / "agents" / f"{agent}.md"
    assert _field(path, "name") == agent
    assert "spawned by create-board skill" in _field(path, "description")


def test_create_board_dispatches_all_four_agents_by_plugin_name():
    text = (PLUGIN / "skills" / "create-board" / "SKILL.md").read_text()
    dispatched = set(re.findall(r"github-board:([a-z][a-z0-9-]*)", text)) - SKILLS
    assert dispatched == AGENTS


def test_every_github_board_name_in_the_plugin_exists():
    for md in list((PLUGIN / "skills").rglob("*.md")) + list((PLUGIN / "agents").glob("*.md")):
        for name in re.findall(r"github-board:([a-z][a-z0-9-]*)", md.read_text()):
            assert name in SKILLS | AGENTS, f"{md}: github-board:{name} does not exist"


def _allowed(line: str) -> bool:
    # Trigger phrases live in description:; "was …" notes name the old name on purpose.
    return line.startswith(("description:", "name:")) or re.search(r"\bwas\b", line) is not None


def _hits(paths, names):
    out = []
    for p in paths:
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _allowed(line):
                continue
            for n in names:
                if BARE[n].search(line) or SLASH[n].search(line):
                    out.append(f"{p.relative_to(PLUGIN)}:{i}: {n}")
    return out


def test_no_old_name_in_skill_or_agent_docs():
    docs = [p for p in (PLUGIN / "skills").rglob("*.md") if p.name != "CHANGELOG.md"]
    docs += list((PLUGIN / "agents").glob("*.md"))
    assert _hits(sorted(docs), OLD) == []


def test_no_old_name_in_scripts():
    # weekly-focus stays the name of the script, its state and log dirs and its labels.
    scripts = sorted(p for p in (PLUGIN / "skills").rglob("scripts/*") if p.suffix in (".sh", ".py"))
    assert _hits(scripts, [n for n in OLD if n != "weekly-focus"]) == []


def test_no_plugin_manifest_json_inside_skills():
    assert list((PLUGIN / "skills").rglob("plugin-manifest.json")) == []


def test_marketplace_lists_the_plugin():
    import json
    rows = json.loads((PLUGIN.parent.parent / ".claude-plugin" / "marketplace.json").read_text())["plugins"]
    row = next(r for r in rows if r["name"] == "github-board")
    assert row["source"] == "./plugins/github-board"
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert row["version"] == plugin["version"] == "1.0.0"
```

- [ ] **Step 3: Run it to see it fail**

Run: `python3 -m pytest plugins/github-board/tests/test_structure.py -q -p no:cacheprovider`
Expected: FAIL / errors (`plugins/github-board/skills` does not exist).

- [ ] **Step 4: Copy the sources**

```bash
cd /Users/abhishek/dev/claude_workspace/claude-code-skills   # the repo root, not a subdirectory
CCC=/Users/abhishek/dev/claude_workspace/claude-code-config
P=plugins/github-board
mkdir -p $P/.claude-plugin $P/skills $P/agents $P/tests
cp -R ~/.claude/skills/create-gh-board          $P/skills/create-board
cp -R ~/.claude/skills/github-issue-triage      $P/skills/triage-issues
cp -R ~/.claude/skills/github-milestone-planning $P/skills/plan-milestones
cp -R ~/.claude/skills/git-branch-cleanup       $P/skills/prune-branches
cp -R $CCC/skills/weekly-focus                  $P/skills/plan-week
cp -R $CCC/skills/github-release-board-promote  $P/skills/promote-shipped
git mv github-board-move $P/skills/move-card
mv $P/skills/promote-shipped/tests/*.py $P/tests/
rmdir $P/skills/promote-shipped/tests
rm -f $P/skills/promote-shipped/plugin-manifest.json
cp $CCC/agents/gh-board-template-inspector.md $P/agents/template-inspector.md
cp $CCC/agents/gh-board-creator.md            $P/agents/board-creator.md
cp $CCC/agents/gh-board-workflow-syncer.md    $P/agents/workflow-syncer.md
cp $CCC/agents/gh-board-verifier.md           $P/agents/board-verifier.md
cp $CCC/tests/test_weekly_focus.py $CCC/tests/test_weekly_focus_launchd.py \
   $CCC/tests/test_weekly_focus_skill_shell.py $P/tests/
cp plugins/adversarial-review/LICENSE $P/LICENSE
find $P \( -name __pycache__ -o -name .DS_Store -o -name '*.pyc' \) -prune -exec rm -rf {} +
```

(The `cd` above is to the repo root, which is the session's working directory already.)

- [ ] **Step 5: Write the plugin files**

`plugins/github-board/.claude-plugin/plugin.json`:

```json
{
  "name": "github-board",
  "version": "1.0.0",
  "description": "GitHub workflow skills in one install: create-board, triage-issues, plan-milestones, plan-week, move-card, promote-shipped and prune-branches, plus the four agents create-board dispatches. Per-user settings live in ~/.config/github-board/config.json."
}
```

`plugins/github-board/.gitignore`:

```
.DS_Store
__pycache__/
*.pyc
.pytest_cache/
```

`plugins/github-board/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to the **github-board** plugin are documented here.

## [1.0.0] - 2026-10-02

### Added

- First release (#146). Seven skills under short names: `create-board` (was `create-gh-board`), `triage-issues` (was `github-issue-triage`), `plan-milestones` (was `github-milestone-planning`), `plan-week` (was `weekly-focus`), `move-card` (was `github-board-move`), `promote-shipped` (was `github-release-board-promote`) and `prune-branches` (was `git-branch-cleanup`). Four agents for `create-board`: `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier` (were `gh-board-*`).
```

`plugins/github-board/README.md` (Task 12 replaces it with the full version):

```markdown
# github-board

GitHub workflow skills in one install: create a board from a template, triage issues, plan milestones, plan the week, move cards, promote shipped work to Done, and prune stale branches.

| Skill | Was | What it does |
|---|---|---|
| `create-board` | `create-gh-board` | Copies a template ProjectV2 board onto a repo and verifies it |
| `triage-issues` | `github-issue-triage` | Audits, updates and closes open issues |
| `plan-milestones` | `github-milestone-planning` | Keeps milestones small and themed |
| `plan-week` | `weekly-focus` | Answers "what do I work on next" from a cross-repo board |
| `move-card` | `github-board-move` | Moves a card to any Status column |
| `promote-shipped` | `github-release-board-promote` | Moves shipped cards to Done after a release |
| `prune-branches` | `git-branch-cleanup` | Finds and deletes stale branches |

Agents (dispatched by `create-board` only): `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier`.
```

- [ ] **Step 6: Set frontmatter names, versions and descriptions**

Edit each SKILL.md's frontmatter to exactly the following (keep everything after the closing `---`; `create-board` keeps its `disable-model-invocation: true` line):

`skills/create-board/SKILL.md`:

```yaml
---
name: create-board
description: "Replicates a GitHub ProjectV2 board (Kanban view, Status columns, Milestone swimlanes, custom fields) onto a target repository by copying a known-good template, then verifies the copy and reports the one workflow that must be enabled by hand. Also audits existing boards for drift, read-only. Use when: (1) the user runs `/github-board:create-board <owner/repo>` or /create-gh-board (the old name of this skill), (2) the user asks to create, clone, copy, or replicate a project board across repos, (3) a new repo needs the standard board layout (Status: Todo/Up Next/In Progress/Development Complete/Done) wired up, (4) the user asks which existing boards have drifted or are missing auto-add. The template board comes from the github-board config (`create-board init`)."
disable-model-invocation: true
metadata:
  version: 3.0.0
---
```

`skills/triage-issues/SKILL.md`:

```yaml
---
name: triage-issues
description: "Reviews, triages, updates, prioritizes, and closes open GitHub issues against the current codebase state. Use when: (1) open issues have accumulated and need audit, (2) user asks to clean up or review GitHub issues, (3) after a release to close resolved issues, (4) periodic backlog grooming to identify stale or duplicate issues, (5) need to prioritize open issues by impact and effort, (6) 'github issue triage' or /github-issue-triage (the old name of this skill)."
metadata:
  version: 2.0.0
---
```

`skills/plan-milestones/SKILL.md`:

```yaml
---
name: plan-milestones
description: "Re-organises open GitHub issues across milestones so each milestone stays small, themed, and shippable, deferring the rest to a themed backlog rather than letting one milestone absorb everything. Use when: (1) a milestone keeps growing and never ships, (2) new issues land in the open milestone by default, (3) open issues have no milestone at all, (4) planning what a release actually contains, (5) the user asks to re-arrange, re-scope, or focus milestones, (6) a roadmap pivots and leaves version-numbered milestones that never shipped, (7) 'milestone planning' or /github-milestone-planning (the old name of this skill). Covers: milestone themes, accretion detection, keep/defer/backlog triage, what to do with emptied and never-shipped milestones, gh milestone mechanics."
metadata:
  version: 2.0.0
---
```

`skills/plan-week/SKILL.md`:

```yaml
---
name: plan-week
description: "Answers what to work on next from the cross-repo Weekly Focus board and plans the week. Use when: (1) 'what do I work on next' or 'what should I work on', (2) 'what's my focus this week', (3) 'plan my next week' or 'weekly plan', (4) 'weekly focus' or /weekly-focus (the old name of this skill)."
metadata:
  version: 2.0.0
---
```

`skills/move-card/SKILL.md`:

```yaml
---
name: move-card
description: "Moves a GitHub issue or PR's Project (v2) board card to a target Status column via a deterministic script (scripts/board-move.sh). Use when: (1) moving an issue to 'In Progress' when work starts, (2) moving a card to 'Development Complete'/'In Review'/'Done in develop' when its PR merges, (3) any mid-lifecycle Project v2 status change that promote-shipped (release->Done only) does not cover, (4) listing a board's available Status columns, (5) 'board move' or /github-board-move (the old name of this skill). Covers: projectsV2 board discovery, Status field/option lookup, updateProjectV2ItemFieldValue, fuzzy column matching, --add for items not yet on the board, project auth-scope checks."
metadata:
  version: 2.0.0
---
```

`skills/promote-shipped/SKILL.md`:

```yaml
---
name: promote-shipped
description: "Moves GitHub Projects (v2) board items to Done after a release or hotfix merges to main. Use when: (1) a release branch finished via Git Flow and the GitHub Release is published, (2) a hotfix shipped to main + back-merged to develop, (3) /finalize-release just completed, (4) the project board has closed issues sitting in 'Dev Complete', 'In Review', 'Done in develop', etc. whose linked PRs merged, (5) 'release board promote' or /github-release-board-promote (the old name of this skill). Discovers all Projects V2 boards linked to the repo, asks the user which board when multiple, validates each candidate (closed issue + merged PR + status != Done), shows a dry-run preview, then applies updateProjectV2ItemFieldValue. No-op when the repo has no boards. Covers: GraphQL projectsV2 discovery, status-field auto-detect, closedByPullRequestsReferences."
metadata:
  version: 2.0.0
---
```

`skills/prune-branches/SKILL.md`:

```yaml
---
name: prune-branches
description: "Audits and cleans stale git branches across local and remote. Use when: (1) repository has accumulated stale feature/hotfix/release branches after merges, (2) Dependabot PRs pile up with superseded older versions, (3) temp branches from git-flow-finish scripts linger as orphans, (4) git branch -d fails with 'not fully merged' on squash-merged branches, (5) periodic repo hygiene after multiple releases or hotfix cycles, (6) Dependabot PRs have been triaged into GitHub issues and the original PRs are stale, (7) 'branch cleanup' or /git-branch-cleanup (the old name of this skill)."
metadata:
  version: 2.0.0
---
```

Agent frontmatter (keep each `model:` line as it is):

```yaml
# agents/template-inspector.md
name: template-inspector
description: "Snapshots a GitHub ProjectV2 board's structure (fields, views, workflows) to a JSON file for downstream replication. NOT user-invocable — spawned by create-board skill in Phase 1 (was gh-board-template-inspector)."
# agents/board-creator.md
name: board-creator
description: "Copies a template ProjectV2 onto a target owner via `gh project copy` and links the new project to a target repository. NOT user-invocable — spawned by create-board skill in Phases 2 and 3 (was gh-board-creator)."
# agents/workflow-syncer.md
name: workflow-syncer
description: "Reports whether a new ProjectV2 board has the repo-scoped 'Auto-add to project' workflow, and emits the UI URL and filter needed to enable it. NOT user-invocable — spawned by create-board skill in Phase 4 (was gh-board-workflow-syncer). GitHub's public GraphQL API has no mutation to create or enable a workflow, so this agent reports only."
# agents/board-verifier.md
name: board-verifier
description: "Diffs a newly-created ProjectV2 board against the template snapshot — fields, Status options, view shape (layout, filter, columns, swimlanes) and workflows — and reports drift plus the one manual step. NOT user-invocable — spawned by create-board skill in Phase 6 (was gh-board-verifier)."
```

- [ ] **Step 7: Rename old names in bodies and scripts**

Run from the repo root. It skips `name:`/`description:` lines (done by hand above) and CHANGELOG files, and leaves `weekly-focus` alone in scripts (the script, state dir and labels keep that name).

```bash
python3 - <<'PY'
import re
from pathlib import Path

P = Path("plugins/github-board")
SKILLS = {"create-gh-board": "create-board", "github-issue-triage": "triage-issues",
          "github-milestone-planning": "plan-milestones", "weekly-focus": "plan-week",
          "github-board-move": "move-card", "github-release-board-promote": "promote-shipped",
          "git-branch-cleanup": "prune-branches"}
AGENTS = {"gh-board-template-inspector": "github-board:template-inspector",
          "gh-board-creator": "github-board:board-creator",
          "gh-board-workflow-syncer": "github-board:workflow-syncer",
          "gh-board-verifier": "github-board:board-verifier"}


def rename(line, mapping):
    for old, new in mapping.items():
        short = new.split(":")[-1]
        line = re.sub(r"((?:^|[\s(`'\"]))/" + re.escape(old) + r"(?![\w/.-])",
                      lambda m, s=short: m.group(1) + "/github-board:" + s, line)
        line = re.sub(r"(?<![\w/.-])" + re.escape(old) + r"(?![\w.-])", lambda m, n=new: n, line)
    return line


def rewrite(path, mapping):
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(l if re.match(r"(name|description):", l) else rename(l, mapping)
                            for l in lines))


both = {**SKILLS, **AGENTS}
for p in [p for p in (P / "skills").rglob("*.md") if p.name != "CHANGELOG.md"] + list((P / "agents").glob("*.md")):
    rewrite(p, both)
no_wf = {k: v for k, v in both.items() if k != "weekly-focus"}
for p in (P / "skills").rglob("scripts/*"):
    if p.suffix in (".sh", ".py"):
        rewrite(p, no_wf)
PY
git diff --stat -- plugins/github-board   # then read the diff of every changed line
```

Read the whole diff. Expected kinds of change: See Also lists and "When to use" tables now name `create-board`, `promote-shipped`, `triage-issues`, `plan-milestones`; `create-board`'s phase and registry tables say `github-board:template-inspector` etc.; `# plan-week` heading in `plan-week/README.md`; `apply-promotions.sh`'s comment footer says `promote-shipped` (its `gh-board-promote:no-merged-pr` marker is untouched); `task-manifest.sh` and `inspect-template.sh` header comments. `~/.claude/skills/<old>` paths are untouched (Task 2 handles them).

- [ ] **Step 8: Per-skill CHANGELOG entries for the major bump**

`skills/promote-shipped/CHANGELOG.md`: change the `## [Unreleased]` heading to `## [2.0.0] - 2026-10-02` and add, directly under it:

```markdown
### Changed
- **Renamed to `promote-shipped`** and moved into the `github-board` plugin (#146). Invoke it as `/github-board:promote-shipped`. The old name still matches as a trigger phrase.
```

`skills/move-card/CHANGELOG.md`: change the title line to `# Changelog — move-card`, the intro to `All notable changes to the **move-card** skill (was \`github-board-move\`) are documented here.`, and add above `## [1.0.0]`:

```markdown
## [2.0.0] - 2026-10-02

### Changed
- **Renamed to `move-card`** and moved into the `github-board` plugin (#146). Invoke it as `/github-board:move-card`. The old name still matches as a trigger phrase.
```

- [ ] **Step 9: Fix the moved tests' paths and names**

```bash
T=plugins/github-board/tests
perl -pi -e 's#parent\.parent / "scripts"#parent.parent / "skills" / "promote-shipped" / "scripts"#' \
  $T/test_apply_promotions_reconcile.py $T/test_apply_promotions_release_lookup.py \
  $T/test_find_promotable_discovery.py $T/test_read_scripts_scope_preflight.py $T/test_script_exit_codes.py
perl -pi -e 's#"skills" / "weekly-focus"#"skills" / "plan-week"#g' \
  $T/test_weekly_focus.py $T/test_weekly_focus_launchd.py $T/test_weekly_focus_skill_shell.py
perl -pi -e 's#== SKILL\.name == "weekly-focus"#== SKILL.name == "plan-week"#' $T/test_weekly_focus_launchd.py
grep -n 'parent.parent\|"plan-week"' $T/*.py
```

Expected: every promote test points at `skills/promote-shipped/scripts`; the three weekly-focus tests point at `skills/plan-week`.

- [ ] **Step 10: Make `common.sh` pass the validator**

`validate-skill.sh` fails any `scripts/*.sh` without a `#!/usr/bin/env bash` first line or without the execute bit. Insert `#!/usr/bin/env bash` as line 1 of `plugins/github-board/skills/plan-week/scripts/common.sh` (keep the existing first comment as line 2), then `chmod +x plugins/github-board/skills/plan-week/scripts/common.sh`.

- [ ] **Step 11: Let the validator accept `disable-model-invocation`**

`create-board` (copied from the installed `create-gh-board`) carries `disable-model-invocation: true`, a real Claude Code frontmatter field that `scripts/validate-skill.sh:267-277` rejects. Keep the field and widen the allow-list. In `scripts/validate-skill.sh` AND its byte-identical copy `plugins/skill-publishing/skills/skill-publishing/scripts/validate-skill.sh`, replace:

```bash
    name|description|metadata|model) ;; # allowed (model is valid for sub-agent skills)
```

with:

```bash
    name|description|metadata|model|disable-model-invocation) ;; # allowed (model: sub-agent skills; disable-model-invocation: slash-command-only skills)
```

and the failure message line with:

```bash
  fail "non-standard frontmatter fields:$NON_STANDARD (allowed: name, description, metadata, model, disable-model-invocation)"
```

Then `cmp scripts/validate-skill.sh plugins/skill-publishing/skills/skill-publishing/scripts/validate-skill.sh` must print nothing.

Bump skill-publishing to 4.5.0 (the validator is part of it): `metadata.version` in `plugins/skill-publishing/skills/skill-publishing/SKILL.md`, `"version"` in `plugins/skill-publishing/.claude-plugin/plugin.json`, its row in `.claude-plugin/marketplace.json`, its row in `README.md` (`| 4.4.0 |` → `| 4.5.0 |` on the skill-publishing line). Add to the top of both `plugins/skill-publishing/CHANGELOG.md` and `plugins/skill-publishing/skills/skill-publishing/CHANGELOG.md`, above `## [4.4.0]`:

```markdown
## [4.5.0] - 2026-10-02

### Changed

- `validate-skill.sh` accepts the `disable-model-invocation` frontmatter field, which Claude Code uses for slash-command-only skills (#146). The repo-root copy and this copy stay byte-identical. The live authoring copy at `~/.claude/skills/skill-publishing/scripts/validate-skill.sh` is outside the repo and is not changed here.
```

- [ ] **Step 12: Marketplace row and root README install line**

In `.claude-plugin/marketplace.json`, insert between the `figma-ui-designer` and `obsidian-brain` rows:

```json
    {
      "name": "github-board",
      "source": "./plugins/github-board",
      "description": "GitHub workflow skills in one install: create-board, triage-issues, plan-milestones, plan-week, move-card, promote-shipped and prune-branches, plus the four agents create-board dispatches. Per-user settings live in ~/.config/github-board/config.json.",
      "version": "1.0.0"
    },
```

Then `jq . .claude-plugin/marketplace.json >/dev/null` must succeed. In `README.md`, delete the line `cp -r /tmp/claude-code-skills/github-board-move ~/.claude/skills/github-board-move`.

- [ ] **Step 13: Run the tests and validators**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
scripts/validate-plugin.sh plugins/skill-publishing
```

Expected: all tests pass (the 216 moved tests plus the structure tests); both validators print `Result: PASS`. If `test_no_old_name_*` lists a line, rename that mention by hand (or add "was" if it is a deliberate old-name note), then re-run.

- [ ] **Step 14: Commit**

```bash
git add plugins/github-board .claude-plugin/marketplace.json README.md scripts/validate-skill.sh \
  plugins/skill-publishing/skills/skill-publishing/scripts/validate-skill.sh \
  plugins/skill-publishing/skills/skill-publishing/SKILL.md plugins/skill-publishing/.claude-plugin/plugin.json \
  plugins/skill-publishing/CHANGELOG.md plugins/skill-publishing/skills/skill-publishing/CHANGELOG.md
git status --short   # confirm github-board-move/ shows as renamed, nothing unexpected staged
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(github-board): scaffold plugin with seven renamed skills and four agents (#146)"
```

---

### Task 2: Run bundled scripts through `${CLAUDE_SKILL_DIR}`; no `~/.claude` paths

**Files:**
- Create: `plugins/github-board/tests/test_paths.py`
- Modify: all seven `skills/*/SKILL.md`, the four `agents/*.md`, `skills/plan-week/scripts/weekly-focus.py` (docstring line 4, README text line 78), `skills/plan-week/scripts/install-launchd.sh` (`render`), both `skills/plan-week/launchd/*.plist.template`, `skills/plan-week/README.md`, `tests/test_weekly_focus_skill_shell.py`, `tests/test_weekly_focus_launchd.py` (template test)

**Interfaces:**
- Consumes: Task 1 layout.
- Produces: launchd templates use `__SCRIPTS__` (rendered as `$SKILL_DIR/scripts` for now; Task 7 switches it to the stable link). Agents take a `skill_dir` input; `create-board` passes `skill_dir: ${CLAUDE_SKILL_DIR}` in every dispatch.

- [ ] **Step 1: Write the failing path test**

`plugins/github-board/tests/test_paths.py`:

```python
"""Paths (#146): SKILL.md runs bundled scripts through ${CLAUDE_SKILL_DIR}, agents through the
skill_dir they are given, and nothing in the plugin points into ~/.claude/skills or agents."""
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = sorted(p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir())
AGENTS = sorted((PLUGIN / "agents").glob("*.md"))
HOME_CLAUDE = re.compile(r"(?:~|\$HOME|\$\{HOME\}|__HOME__)/\.claude/(?:skills|agents)/")
FENCE = re.compile(r"^[ \t>]*```[^\n]*\n(.*?)^[ \t>]*```", re.S | re.M)
SCRIPT_REF = re.compile(r"(\S*)scripts/[\w.-]+\.(?:sh|py)\b")


def _plugin_files():
    for p in sorted(PLUGIN.rglob("*")):
        rel = p.relative_to(PLUGIN)
        if not p.is_file() or rel.parts[0] == "tests" or "__pycache__" in rel.parts:
            continue
        if p.name == "CHANGELOG.md" or rel == Path("README.md"):
            continue  # history, and the root README's migration runbook
        yield p, rel


def test_no_home_claude_skills_or_agents_paths():
    hits = [f"{rel}:{i}" for p, rel in _plugin_files()
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1)
            if HOME_CLAUDE.search(line)]
    assert hits == []


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_md_runs_scripts_through_claude_skill_dir(skill):
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text()
    assert "./scripts/" not in text
    bad = [m.group(0) for block in FENCE.findall(text) for m in SCRIPT_REF.finditer(block)
           if not m.group(1).endswith("${CLAUDE_SKILL_DIR}/")]
    assert bad == []


@pytest.mark.parametrize("agent", AGENTS, ids=lambda p: p.stem)
def test_agents_run_scripts_from_the_skill_dir_they_are_given(agent):
    text = agent.read_text()
    assert "`skill_dir`" in text
    bad = [m.group(0) for m in SCRIPT_REF.finditer(text) if not m.group(1).endswith("<skill_dir>/")]
    assert bad == []


def test_create_board_passes_skill_dir_to_every_dispatch():
    assert "skill_dir: ${CLAUDE_SKILL_DIR}" in (PLUGIN / "skills" / "create-board" / "SKILL.md").read_text()
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 -m pytest plugins/github-board/tests/test_paths.py -q -p no:cacheprovider`
Expected: FAIL — hits in `plan-week/SKILL.md:13`, `prune-branches/SKILL.md:18-24`, the agents, both plist templates, `weekly-focus.py:4,78`, `plan-week/README.md`; `./scripts/` in several SKILL.md files.

- [ ] **Step 3: Rewrite SKILL.md script invocations**

First the one assignment the generic rewrite would double-quote. In `skills/plan-week/SKILL.md` replace:

```bash
WF="$HOME/.claude/skills/weekly-focus/scripts/weekly-focus.py"   # path only: zsh does not word-split $WF
```

with:

```bash
WF="${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"   # path only: zsh does not word-split $WF
```

Then, from the repo root:

```bash
python3 - <<'PY'
import re
from pathlib import Path

DIR = '"${CLAUDE_SKILL_DIR}/scripts/%s"'
HOME_REF = re.compile(r"(?:~|\$HOME)/\.claude/skills/[\w-]+/scripts/([\w.-]+\.(?:sh|py))")
DOT_REF = re.compile(r'(?<![\w/"}.-])\./scripts/([\w.-]+\.(?:sh|py))')
REF = re.compile(r'(?<![\w/"}.<-])scripts/([\w.-]+\.(?:sh|py))')


def fix_block(block):
    block = HOME_REF.sub(lambda m: DIR % m.group(1), block)
    block = DOT_REF.sub(lambda m: DIR % m.group(1), block)
    return REF.sub(lambda m: DIR % m.group(1), block)


for p in sorted(Path("plugins/github-board/skills").glob("*/SKILL.md")):
    t = p.read_text()
    t = re.sub(r"(^[ \t>]*```[^\n]*\n)(.*?)(^[ \t>]*```)",
               lambda m: m.group(1) + fix_block(m.group(2)) + m.group(3), t, flags=re.S | re.M)
    t = DOT_REF.sub(lambda m: DIR % m.group(1), t)
    t = HOME_REF.sub(lambda m: DIR % m.group(1), t)
    p.write_text(t)
PY
git diff -- plugins/github-board/skills/*/SKILL.md
```

Read the diff: every fenced invocation now reads `"${CLAUDE_SKILL_DIR}/scripts/<name>" <args>`; prose mentions such as "Runs `scripts/copy-template.sh`" outside fences are unchanged. The `WF=` line must have exactly one pair of quotes.

- [ ] **Step 4: Pass `skill_dir` to the agents**

In `skills/create-board/SKILL.md`, directly under the `## Progress Tracking (MANDATORY)` phase table, add:

```markdown
Every agent dispatch passes `skill_dir: ${CLAUDE_SKILL_DIR}` plus the inputs the agent lists.
The agents run each script as `<skill_dir>/scripts/<name>`.
```

In each of the four `agents/*.md`, replace the input line ``- Skill base directory: `~/.claude/skills/create-gh-board` `` with:

```markdown
- `skill_dir`: absolute path of the create-board skill directory. Run every script as `<skill_dir>/scripts/<name>`.
```

Then make every script reference in the agents absolute through `skill_dir`:

```bash
perl -pi -e 's#~/\.claude/skills/create-gh-board/scripts/#<skill_dir>/scripts/#g; s#(?<![\w/>.-])scripts/([\w.-]+\.sh)#<skill_dir>/scripts/$1#g' \
  plugins/github-board/agents/*.md
git diff -- plugins/github-board/agents
```

Expected: e.g. `1. Run \`<skill_dir>/scripts/copy-template.sh --source-owner …\``, `` `<skill_dir>/scripts/verify-board.sh` separates structural parity…``.

- [ ] **Step 5: Script and template paths for plan-week**

`skills/plan-week/scripts/weekly-focus.py` line 4: replace `Script: ~/.claude/skills/weekly-focus/scripts/weekly-focus.py` with `Script: <github-board plugin>/skills/plan-week/scripts/weekly-focus.py`. Line 78 (inside `README`): replace ``- launchd runs `~/.claude/skills/weekly-focus/scripts/weekly-focus.py sync` at 07:00 and 18:00.`` with ``- launchd runs `weekly-focus.py sync` at 07:00 and 18:00.`` (Task 4 replaces this whole text).

In both `skills/plan-week/launchd/*.plist.template` files replace `__HOME__/.claude/skills/weekly-focus/scripts/` with `__SCRIPTS__/` (so the lines read `<string>__SCRIPTS__/run-sync.sh</string>` and `<string>__SCRIPTS__/watchdog.sh</string>`).

In `skills/plan-week/scripts/install-launchd.sh`, in `render()`, replace:

```bash
  printf '%s\n' "${body//__HOME__/$HOME}"
```

with:

```bash
  body="${body//__SCRIPTS__/$SKILL_DIR/scripts}"
  printf '%s\n' "${body//__HOME__/$HOME}"
```

In `skills/plan-week/README.md`, replace each `~/.claude/skills/weekly-focus/scripts/install-launchd.sh` with `"$PW"/scripts/install-launchd.sh` and add under the `## Install` heading, before the code block: ``Set `PW` to this skill's directory in the installed plugin (Task 7's README explains the stable link).`` (Task 7 rewrites this README.)

- [ ] **Step 6: Update the two tests that pinned the old paths**

In `tests/test_weekly_focus_launchd.py`, in `test_plist_templates_have_no_keepalive_and_use_home_placeholder`, replace `assert "__HOME__/.claude/skills/weekly-focus/scripts/" in text` with:

```python
    assert "__SCRIPTS__/" in text and ".claude" not in text
```

In `tests/test_weekly_focus_skill_shell.py`, replace `test_skill_commands_run_in_shell` and add one test:

```python
def test_wf_points_at_the_skill_dir_placeholder():
    assert _wf_assignment().startswith('WF="${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"')


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_skill_commands_run_in_shell(shell, tmp_path):
    exe = shutil.which(shell)
    if not exe:
        pytest.skip(f"{shell} not installed")
    skill_dir = tmp_path / "plan-week"
    stub = skill_dir / "scripts" / "weekly-focus.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(STUB)
    # Claude Code substitutes ${CLAUDE_SKILL_DIR} as text when the skill loads; do the same.
    assign = re.split(r"\s+#\s", _wf_assignment())[0].replace("${CLAUDE_SKILL_DIR}", str(skill_dir))
    script = "\n".join([assign] + [f"{c} || exit 9" for c in _commands()])
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    r = subprocess.run([exe, "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"{shell} failed: {r.stderr}"
    out = [l for l in r.stdout.splitlines() if l.startswith("STUB ")]
    assert len(out) == len(_commands())
    assert out[0] == "STUB sync --json"
```

Also change the module docstring's first line to `"""plan-week SKILL.md's own commands must run in the shells the Bash tool uses (#217, #146).`.

- [ ] **Step 7: Run all tests and the validator**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
```

Expected: all pass; `Result: PASS`.

- [ ] **Step 8: Commit**

```bash
git add plugins/github-board/skills plugins/github-board/agents plugins/github-board/tests/test_paths.py \
  plugins/github-board/tests/test_weekly_focus_skill_shell.py plugins/github-board/tests/test_weekly_focus_launchd.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(github-board): run bundled scripts through CLAUDE_SKILL_DIR, no ~/.claude paths (#146)"
```

---

### Task 3: `lib/config.py` and `lib/config.sh` — load, validate, init

**Files:**
- Create: `plugins/github-board/lib/config.py`, `plugins/github-board/lib/config.sh`
- Test: `plugins/github-board/tests/test_config.py`

**Interfaces:**
- Consumes: `gbtest.load_lib`, `gbtest.write_config`, `gbtest.TEST_CFG`.
- Produces (Python, `lib/config.py`): `VERSION = 1`; `class ConfigError(Exception)` with `.exit_code = 2` and `.key`; `class ConfigMissing(ConfigError)` (`exit_code = 4`); `class ConfigConflict(ConfigError)` (`exit_code = 3`); `config_path() -> Path`; `cache_dir() -> Path`; `validate(cfg, require: Iterable[str] = ()) -> dict`; `load(require: Iterable[str] = ()) -> dict`; `get(cfg: dict, dotted: str) -> Any`; `read_payload(from_file: Optional[str]) -> Any`; `init_config(payload, require: Optional[str] = None, force: bool = False) -> Path`; `main(argv=None) -> int`. CLI: `config.py path | show | get KEY [--lines] | init [--require plan_week|create_board] [--force] [--from FILE]`.
- Produces (bash, `lib/config.sh`, sourced): `GB_LIB_DIR`, `GB_PYTHON` (default `python3`), `gb_config_get KEY [--lines]` (exit status of `config.py`).

- [ ] **Step 1: Write the failing tests**

`plugins/github-board/tests/test_config.py`:

```python
"""lib/config.py (#146): load, validate, init, and the CLI's exit codes."""
import json
import os
import subprocess
import sys

import pytest

from gbtest import LIB, TEST_CFG, cfg_copy, load_lib, write_config

CLI = [sys.executable, str(LIB / "config.py")]


def run_cli(*args, stdin=None):
    return subprocess.run(CLI + list(args), input=stdin, capture_output=True, text=True, timeout=30)


@pytest.fixture
def cfg_home(tmp_path):
    return tmp_path / "xdg-config"


def test_missing_config_exits_4_and_says_run_init():
    r = run_cli("get", "owner")
    assert r.returncode == 4
    assert "run `plan-week init`" in r.stderr


def test_load_returns_the_config(gb_config):
    gbc = load_lib()
    assert gbc.load(require=("plan_week",))["owner"] == "octo-user"
    assert gbc.config_path() == gb_config


def test_unparseable_file_exits_2(cfg_home):
    write_config(cfg_home, "{not json")
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "not valid JSON" in r.stderr


def test_unknown_version_exits_2_naming_version(cfg_home):
    c = cfg_copy(); c["version"] = 2
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "unknown version 2" in r.stderr


@pytest.mark.parametrize("path", [
    ("owner",), ("plan_week", "lanes"), ("plan_week", "schedule"), ("plan_week", "frozen"),
    ("plan_week", "capacity", "hours"), ("plan_week", "launchd", "label_prefix"),
])
def test_missing_key_exits_2_naming_the_key(cfg_home, path):
    c = cfg_copy()
    node = c
    for part in path[:-1]:
        node = node[part]
    del node[path[-1]]
    write_config(cfg_home, c)
    r = run_cli("get", "plan_week.board_title")
    assert r.returncode == 2
    assert "missing required key " + ".".join(path) in r.stderr


def test_schedule_with_unknown_lane_exits_2_naming_the_day(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"]["thu"] = ["Tolling"]
    write_config(cfg_home, c)
    r = run_cli("get", "plan_week.board_title")
    assert r.returncode == 2
    assert "plan_week.schedule.thu" in r.stderr and "'Tolling'" in r.stderr


def test_schedule_with_unknown_day_exits_2(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"]["funday"] = []
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "plan_week.schedule.funday" in r.stderr


@pytest.mark.parametrize("mutate,key", [
    (lambda pw: pw.update(default_lane="Tooling"), "plan_week.default_lane"),
    (lambda pw: pw["lanes"].append({"name": "Security", "repos": ["x"]}), "plan_week.lanes[3].name"),
    (lambda pw: pw["lanes"].append({"name": "Empty"}), "plan_week.lanes[3]"),
    (lambda pw: pw.update(always=["no-hash-here"]), "plan_week.always[0]"),
    (lambda pw: pw["launchd"].update(times=["7:00"]), "plan_week.launchd.times[0]"),
    (lambda pw: pw["launchd"].update(times=[]), "plan_week.launchd.times"),
    (lambda pw: pw["launchd"].update(label_prefix="has space"), "plan_week.launchd.label_prefix"),
    (lambda pw: pw["capacity"].update(hours=[20, 10]), "plan_week.capacity.hours"),
    (lambda pw: pw["capacity"].update(max_repos_besides_security=True), "plan_week.capacity.max_repos_besides_security"),
])
def test_bad_values_exit_2_naming_the_key(cfg_home, mutate, key):
    c = cfg_copy(); mutate(c["plan_week"])
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and key in r.stderr


def test_schedule_null_and_launchd_disabled_without_times_are_valid(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"] = None
    c["plan_week"]["launchd"] = {"enabled": False, "times": [], "label_prefix": "dev.x"}
    write_config(cfg_home, c)
    assert run_cli("get", "plan_week.schedule").stdout == "null\n"


def test_get_prints_scalars_raw_and_lists_one_per_line(gb_config):
    assert run_cli("get", "plan_week.launchd.label_prefix").stdout == "dev.example.plan-week\n"
    assert run_cli("get", "plan_week.launchd.enabled").stdout == "true\n"
    assert run_cli("get", "plan_week.launchd.times", "--lines").stdout == "07:00\n18:00\n"
    assert json.loads(run_cli("get", "plan_week.capacity").stdout) == TEST_CFG["plan_week"]["capacity"]


def test_get_of_a_missing_section_exits_2(cfg_home):
    c = cfg_copy(); del c["create_board"]
    write_config(cfg_home, c)
    r = run_cli("get", "create_board.template_owner")
    assert r.returncode == 2 and "missing required key create_board" in r.stderr


def test_bad_create_board_template_number_exits_2(cfg_home):
    c = cfg_copy(); c["create_board"]["template_number"] = 0
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "create_board.template_number" in r.stderr


# ---- init -------------------------------------------------------------------

def _payload(**over):
    p = {"owner": "octo-user", "plan_week": cfg_copy()["plan_week"]}
    p.update(over)
    return json.dumps(p)


def test_init_writes_the_file_from_stdin():
    gbc = load_lib()
    r = run_cli("init", "--require", "plan_week", stdin=_payload())
    assert r.returncode == 0, r.stderr
    written = json.loads(gbc.config_path().read_text())
    assert written["version"] == 1 and written["plan_week"] == TEST_CFG["plan_week"]


def test_init_refuses_a_different_section_without_force():
    gbc = load_lib()
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0
    before = gbc.config_path().read_text()
    changed = cfg_copy()["plan_week"]; changed["board_title"] = "Other"
    r = run_cli("init", "--require", "plan_week", stdin=_payload(plan_week=changed))
    assert r.returncode == 3 and "plan_week" in r.stderr and "--force" in r.stderr
    assert gbc.config_path().read_text() == before
    r = run_cli("init", "--require", "plan_week", "--force", stdin=_payload(plan_week=changed))
    assert r.returncode == 0
    assert json.loads(gbc.config_path().read_text())["plan_week"]["board_title"] == "Other"


def test_init_with_the_same_values_is_not_a_conflict():
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0


def test_init_adds_a_section_to_an_existing_config(gb_config):
    c = cfg_copy(); del c["create_board"]
    write_config(gb_config.parent.parent, c)
    r = run_cli("init", "--require", "create_board",
                stdin=json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}}))
    assert r.returncode == 0, r.stderr
    written = json.loads(gb_config.read_text())
    assert written["create_board"]["template_number"] == 4 and written["plan_week"] == TEST_CFG["plan_week"]


def test_init_from_file(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(_payload())
    assert run_cli("init", "--require", "plan_week", "--from", str(seed)).returncode == 0


def test_init_from_a_missing_file_exits_2(tmp_path):
    r = run_cli("init", "--from", str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "cannot read" in r.stderr


def test_init_with_an_invalid_payload_writes_nothing():
    gbc = load_lib()
    bad = cfg_copy()["plan_week"]; bad["schedule"]["mon"] = ["Nope"]
    r = run_cli("init", "--require", "plan_week", stdin=_payload(plan_week=bad))
    assert r.returncode == 2 and "plan_week.schedule.mon" in r.stderr
    assert not gbc.config_path().exists()


def test_init_require_plan_week_rejects_a_payload_without_it():
    r = run_cli("init", "--require", "plan_week", stdin=json.dumps({"owner": "octo-user"}))
    assert r.returncode == 2 and "missing required key plan_week" in r.stderr


# ---- config.sh --------------------------------------------------------------

def _bash(snippet):
    return subprocess.run(["bash", "-c", f'. "{LIB}/config.sh"; {snippet}'], capture_output=True,
                          text=True, timeout=30, env=dict(os.environ, GB_PYTHON=sys.executable))


def test_config_sh_get(gb_config):
    r = _bash("gb_config_get plan_week.launchd.label_prefix")
    assert r.returncode == 0 and r.stdout == "dev.example.plan-week\n"


def test_config_sh_get_passes_exit_4_through():
    assert _bash("gb_config_get owner").returncode == 4
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_config.py -q -p no:cacheprovider`
Expected: FAIL — `lib/config.py` not found.

- [ ] **Step 3: Write `lib/config.py`**

```python
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    os.replace(tmp, path)
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
```

- [ ] **Step 4: Write `lib/config.sh`**

```bash
#!/usr/bin/env bash
# github-board shared helpers for bash scripts. Sourced, not run:
#   . "<plugin>/lib/config.sh"
# Every helper runs lib/config.py with $GB_PYTHON (default python3). GB_PYTHON is separate from
# the launchd scripts' $PYTHON, which tests replace with a stub.
#   gb_config_get KEY [--lines]   print a config value; exit 4 when there is no config, 2 when invalid
GB_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_PYTHON="${GB_PYTHON:-python3}"

gb_config_get() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" get "$@"; }
```

Then `chmod +x plugins/github-board/lib/config.py plugins/github-board/lib/config.sh`.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest plugins/github-board/tests/test_config.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/github-board/lib plugins/github-board/tests/test_config.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(github-board): per-user config loader with validation and init (#146)"
```

---

### Task 4: plan-week reads its settings from the config

**Files:**
- Modify: `plugins/github-board/skills/plan-week/scripts/weekly-focus.py`
- Modify: `plugins/github-board/tests/test_weekly_focus.py`
- Create: `plugins/github-board/tests/test_plan_week_config.py`

**Interfaces:**
- Consumes: `lib/config.py` (`load`, `ConfigError`), `gbtest.load_weekly_focus`, `gbtest.TEST_CFG`.
- Produces in `weekly-focus.py`: module `gbconfig` (the loaded `lib/config.py`); globals `CONFIG, OWNER, TITLE, FROZEN, ALWAYS, LANES, DEFAULT_LANE, SCHEDULE, CAPACITY, LAUNCHD, FIELDS`; `apply_config(cfg: dict) -> None`; `lane_for(repo: str, labels: list) -> str`; `label_lane(labels: list) -> Optional[str]`; `board_readme() -> str`; `config_warnings(issues: dict) -> list[str]`; `show_items(p, issues=None)`; `main(argv)` handles `-h/--help/help` (exit 0, docstring on stdout) and loads the config (exit 4 / 2 through `gbconfig.ConfigError`). `sync --json` gains `config_warnings`; `show --json` gains `schedule`, `capacity`, `lanes`, `default_lane`, `config_warnings`.

- [ ] **Step 1: Point the moved tests at the config fixture**

```bash
T=plugins/github-board/tests/test_weekly_focus.py
perl -pi -e 's/Abhattacherjee/Octo-user/g; s/abhattacherjee/octo-user/g; s/marauders-map/frozen-repo/g; s/tiny-vacation-agent/frozen-repo/g; s/fantasy-football-advisor/season-repo/g; s/claude-code-config/tool-a/g' $T
grep -c 'octo-user\|frozen-repo\|season-repo\|tool-a' $T
```

Then in `test_weekly_focus.py`:

Add `import copy` to the imports and, after `import pytest`, add:

```python
from gbtest import TEST_CFG, write_config
```

Replace `_load` with:

```python
def _load(path: Path = SCRIPT, stub_gh=True):
    spec = importlib.util.spec_from_file_location("weekly_focus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.apply_config(copy.deepcopy(TEST_CFG))

    def _no_gh(*a, **k):
        raise AssertionError(f"real gh called: {a}")

    if stub_gh:
        mod.gh = _no_gh
    return mod
```

In `test_script_prints_one_error_line_and_no_traceback`, replace the `env={"PATH": f"{d}:{os.environ['PATH']}"}` argument with an env that carries a config and an isolated cache:

```python
        cfg_home = Path(d) / "cfg"
        write_config(cfg_home, TEST_CFG)
        env = {"PATH": f"{d}:{os.environ['PATH']}", "HOME": d,
               "XDG_CONFIG_HOME": str(cfg_home), "XDG_CACHE_HOME": str(Path(d) / "cache")}
        r = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=60, env=env)
```

In `test_sync_json_shape_and_human_output`, add `"config_warnings"` to the expected key set.

Append these tests to `test_weekly_focus.py`:

```python
# ---- config warnings (#146) -------------------------------------------------

def test_sync_json_reports_config_entries_with_no_open_issue(wf, monkeypatch, capsys):
    # frozen-repo was renamed: its issues now come back as new-name#N, so the config's
    # frozen and always entries match nothing. Sync carries on and says so.
    Board(wf, monkeypatch, items={}, issues={"new-name#951": _iss("new-name", "v1.0")},
          current={"new-name": "v1.0"}, in_progress=set())
    out = _sync_json(wf, capsys)
    assert out["added"] == ["new-name#951"]
    assert any("frozen repo 'frozen-repo'" in w for w in out["config_warnings"])
    assert any("always issue 'frozen-repo#951'" in w for w in out["config_warnings"])


def test_sync_has_no_warning_when_frozen_and_always_still_match(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, issues={"frozen-repo#951": _iss("frozen-repo", None)},
          current={}, in_progress=set())
    assert _sync_json(wf, capsys)["config_warnings"] == []


def test_sync_human_output_prints_config_warnings_on_stderr(wf, monkeypatch, capsys):
    Board(wf, monkeypatch, items={}, issues={}, current={}, in_progress=set())
    wf.sync()
    err = capsys.readouterr().err
    assert "warning: frozen repo 'frozen-repo'" in err


def test_show_json_reports_config_warnings_schedule_and_capacity(wf, monkeypatch, capsys):
    monkeypatch.setattr(wf, "find_or_create_project", lambda: {"number": 36, "url": "URL36"})
    monkeypatch.setattr(wf, "open_issues", lambda: {"app#1": _iss("app", "v1.0")})
    monkeypatch.setattr(wf, "current_milestones", lambda repos: {"app": "v1.0"})
    monkeypatch.setattr(wf, "board_items", lambda num: {})
    wf.show(as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert data["schedule"] == TEST_CFG["plan_week"]["schedule"]
    assert data["capacity"] == TEST_CFG["plan_week"]["capacity"]
    assert data["lanes"] == ["Security", "Season", "Tooling"] and data["default_lane"] == "Product"
    assert len(data["config_warnings"]) == 2
```

- [ ] **Step 2: Write the failing config-behaviour tests**

`plugins/github-board/tests/test_plan_week_config.py`:

```python
"""plan-week takes owner, lanes, schedule, capacity and frozen/always from the config (#146)."""
import json
import subprocess
import sys

import pytest

from gbtest import TEST_CFG, WEEKLY_FOCUS, cfg_copy, load_weekly_focus

SEASON = {"season-repo"}
TOOLING = {"tool-a", "tool-b"}


def legacy_lane_for(repo, labels):
    """weekly-focus.py's lane_for() before #146, verbatim, over TEST_CFG's repo sets."""
    if any("security" in l.lower() for l in labels):
        return "Security"
    if repo in SEASON:
        return "Season"
    return "Tooling" if repo in TOOLING else "Product"


# Every repo/label case the moved tests use, plus case and substring variants.
CASES = [("season-repo", ["Security"]), ("season-repo", ["bug"]), ("tool-a", []),
         ("some-app", []), ("tool-b", ["needs-security-review"]), ("some-app", ["SECURITY"]),
         ("tool-a", ["bug", "P1"]), ("season-repo", []), ("some-app", ["bug"])]


@pytest.mark.parametrize("repo,labels", CASES)
def test_config_lanes_give_the_same_lane_as_the_old_rule(repo, labels):
    assert load_weekly_focus(TEST_CFG).lane_for(repo, labels) == legacy_lane_for(repo, labels)


def test_first_matching_rule_wins():
    c = cfg_copy()
    c["plan_week"]["lanes"] = [{"name": "A", "repos": ["r"]}, {"name": "B", "repos": ["r"]}]
    c["plan_week"]["schedule"] = None
    assert load_weekly_focus(c).lane_for("r", []) == "A"


def test_single_lane_preset_puts_everything_in_the_default_lane():
    c = cfg_copy()
    c["plan_week"]["lanes"] = []
    c["plan_week"]["default_lane"] = "Work"
    c["plan_week"]["schedule"] = None
    wf = load_weekly_focus(c)
    assert wf.lane_for("anything", ["security"]) == "Work"
    assert wf.FIELDS["Lane"] == ["Work"]


def test_label_lane_is_the_first_label_rule_that_matches():
    wf = load_weekly_focus(TEST_CFG)
    assert wf.label_lane(["Security-Hotfix"]) == "Security"
    assert wf.label_lane(["bug"]) is None


def test_apply_config_sets_owner_title_and_queries():
    c = cfg_copy(); c["owner"] = "someone-else"; c["plan_week"]["board_title"] = "My Week"
    wf = load_weekly_focus(c)
    assert wf.OWNER == "someone-else" and wf.TITLE == "My Week"
    assert 'login:"someone-else"' in wf.PROJECTS_Q and 'login:"someone-else"' in wf.BOARD_ITEMS_Q
    assert "author:someone-else" in wf.PR_LINKED_Q


def test_add_skips_a_lane_the_board_does_not_have(capsys):
    wf = load_weekly_focus(TEST_CFG)
    sets = []
    wf.gh = lambda *a, **k: {"id": "ITEM"}
    wf.set_opt = lambda pid, item, field, opt: sets.append((field["id"], opt))
    fields = {"Lane": {"id": "L", "opts": {"Product": "p"}}, "Focus": {"id": "F", "opts": {"Next": "n"}}}
    wf.add(36, "PID", fields, "tool-a#1", [], "Next")
    assert sets == [("F", "Next")]
    assert "board has no Lane option 'Tooling'" in capsys.readouterr().err


def test_board_readme_is_built_from_the_config():
    text = load_weekly_focus(TEST_CFG).board_readme()
    assert "At most 3 repos per week besides Security" in text
    assert "Weekly rhythm (10-20h)" in text
    assert "- Thu: Tooling" in text and "- Fri: Season" in text
    assert "launchd runs `weekly-focus.py sync` at 07:00 and 18:00." in text
    assert "Frozen (not synced; issues kept open): frozen-repo." in text


def test_board_readme_without_a_schedule_or_launchd():
    c = cfg_copy()
    c["plan_week"]["schedule"] = None
    c["plan_week"]["launchd"]["enabled"] = False
    text = load_weekly_focus(c).board_readme()
    assert "No fixed days: Security first, then priority order." in text
    assert "launchd" not in text


def test_help_exits_0_without_a_config():
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "--help"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0 and "weekly-focus.py sync" in r.stdout


def test_show_without_a_config_exits_4():
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "show"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 4 and "plan-week init" in r.stderr


def test_show_with_a_bad_config_exits_2_naming_the_key(tmp_path):
    from gbtest import write_config
    c = cfg_copy(); del c["plan_week"]["frozen"]
    write_config(tmp_path / "xdg-config", c)
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "show"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 2 and "plan_week.frozen" in r.stderr
```

- [ ] **Step 3: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_plan_week_config.py plugins/github-board/tests/test_weekly_focus.py -q -p no:cacheprovider`
Expected: FAIL — `apply_config` does not exist.

- [ ] **Step 4: Change `weekly-focus.py`**

4a. Replace the docstring's first paragraph (lines 2-6, from `"""Cross-repo "Weekly Focus" GitHub Project for abhattacherjee.` through `"what do I work on next") is the normal way to use this.`) with:

```python
"""Cross-repo "Weekly Focus" GitHub Project, driven by the github-board config.

Script: <github-board plugin>/skills/plan-week/scripts/weekly-focus.py
Config: ${XDG_CONFIG_HOME:-~/.config}/github-board/config.json gives the owner, board title,
lanes, schedule, frozen and always lists, capacity and launchd settings.
launchd runs `sync` at the configured times. The skill (/github-board:plan-week, or a question
like "what do I work on next") is the normal way to use this.
```

In the same docstring, after the `show [--json]` entry (before the `"Current milestone"` paragraph) add:

```
  weekly-focus.py --help          this text (needs no config)

  --json on show also carries the config's schedule, capacity, lanes and default_lane.
  sync --json and show --json carry config_warnings: frozen or always entries that match no
  open issue (a renamed or deleted repo, or a closed issue).

Exit codes: 0 ok; 1 error; 2 usage or invalid config (names the key); 3 sync skipped
(GraphQL budget low); 4 no config yet (run `plan-week init`).
```

and change the last docstring sentence `Frozen repos are skipped by sync. Edit FROZEN to thaw one.` to `Frozen repos (plan_week.frozen) are skipped by sync. Edit the config to thaw one.`

4b. Add to the imports `import importlib.util` and `from pathlib import Path`, then directly after the imports add:

```python
def _load_github_board_lib():
    """lib/config.py of the plugin this script ships in (found from this file, never from HOME)."""
    path = Path(__file__).resolve().parents[3] / "lib" / "config.py"
    spec = importlib.util.spec_from_file_location("github_board_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gbconfig = _load_github_board_lib()
```

4c. Replace lines 39-55 (`OWNER = "abhattacherjee"` through the closing `}` of `FIELDS`) with:

```python
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
```

4d. Delete the `README = f"""…"""` constant (old lines 64-86) and put this function in its place:

```python
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
```

and in `write_readme` replace `"--readme", README,` with `"--readme", board_readme(),`.

4e. Turn the four owner-bound queries into templates. Rename `PROJECTS_Q`, `FIELDS_Q`, `BOARD_ITEMS_Q` (old lines 166-178) to `_PROJECTS_Q`, `_FIELDS_Q`, `_BOARD_ITEMS_Q` and remove the trailing `% OWNER` from each; rename `PR_LINKED_Q` (old lines 327-331) to `_PR_LINKED_Q` and remove its `% OWNER`. After `_BOARD_ITEMS_Q`, add:

```python
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
```

(`_PR_LINKED_Q` is defined further down the file; `apply_config` only runs after import, so the forward reference is fine.)

4f. Replace `lane_for` (old lines 266-271) with:

```python
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
```

4g. In `add`, replace `set_opt(pid, item["id"], fields["Lane"], lane_for(repo, labels))` with:

```python
    lane = lane_for(repo, labels)
    if lane in fields["Lane"]["opts"]:
        set_opt(pid, item["id"], fields["Lane"], lane)
    else:
        print(f"warning: board has no Lane option {lane!r} ({key}); add it to the board's Lane field",
              file=sys.stderr)
```

4h. In `refresh_lanes`, change the docstring's first line to `"""Fill an empty Lane, and lift an item to a label lane (e.g. Security) once it gains a matching label.` and replace:

```python
        if not cur:
            new = lane_for(issues[key]["repo"], labels)
        elif cur != "Security" and any("security" in l.lower() for l in labels):
            new = "Security"
        else:
            continue
```

with:

```python
        lifted = label_lane(labels)
        if not cur:
            new = lane_for(issues[key]["repo"], labels)
        elif lifted and cur != lifted:
            new = lifted
        else:
            continue
```

4i. Add, after `candidates`:

```python
def config_warnings(issues):
    """Config entries that match no open issue: usually a renamed or deleted repo."""
    repos = {i["repo"] for i in issues.values()}
    out = [f"frozen repo {r!r} has no open issues (renamed or deleted? check plan_week.frozen)"
           for r in sorted(FROZEN - repos)]
    out += [f"always issue {k!r} is not an open issue (closed, moved, or its repo renamed? "
            "check plan_week.always)" for k in sorted(ALWAYS - set(issues))]
    return out
```

4j. In `sync`, after `issues = open_issues()` add `warnings = config_warnings(issues)`. In the `as_json` dict add `"config_warnings": warnings,` after `"graphql_cost": cost,`. In the human branch, before `_finish_sync(failed_boards)` at the end, add:

```python
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
```

4k. Change `show_items(p)` to take the issues it was given:

```python
def show_items(p, issues=None):
    issues = open_issues() if issues is None else issues
```

(and delete its old first line `issues = open_issues()`). Replace `show` with:

```python
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
```

4l. Replace `main` and the `__main__` block with:

```python
COMMANDS = ("sync", "set", "pick", "show")


def main(argv):
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    args = [a for a in argv if a != "--json"]
    as_json = "--json" in argv
    cmd = args[0] if args else "show"
    if cmd not in COMMANDS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    apply_config(gbconfig.load(require=("plan_week",)))
    if cmd == "sync":
        sync(as_json)
    elif cmd == "set":
        set_focus(args[1] if len(args) > 1 else "", args[2:])
    elif cmd == "pick":
        pick(args[1:])
    else:
        show(as_json)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except gbconfig.ConfigError as e:
        print(f"weekly-focus: error: {e}", file=sys.stderr)
        sys.exit(e.exit_code)
    except (GhError, subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        print(f"weekly-focus: error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider`
Expected: PASS (all moved tests plus the new ones).

- [ ] **Step 6: Commit**

```bash
git add plugins/github-board/skills/plan-week/scripts/weekly-focus.py \
  plugins/github-board/tests/test_weekly_focus.py plugins/github-board/tests/test_plan_week_config.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(plan-week): read owner, lanes, schedule and capacity from the config (#146)"
```

---

### Task 5: `plan-week init` and `config`; exit 4 everywhere else

**Files:**
- Modify: `plugins/github-board/skills/plan-week/scripts/weekly-focus.py`
- Create: `plugins/github-board/tests/test_plan_week_init.py`

**Interfaces:**
- Consumes: `gbconfig.init_config`, `gbconfig.read_payload`, `gbconfig.ConfigConflict`.
- Produces: `weekly-focus.py init [--force] [--from FILE]` (payload JSON on stdin otherwise; must contain `plan_week`; exit 0 / 2 / 3); `weekly-focus.py config` (prints the config JSON; exit 4 when none). `COMMANDS` gains `"init"` and `"config"`. `init_cmd(args: list) -> None`.

- [ ] **Step 1: Write the failing tests**

`plugins/github-board/tests/test_plan_week_init.py`:

```python
"""plan-week init / config, and exit 4 for every other subcommand without a config (#146)."""
import json
import os
import subprocess
import sys

import pytest

from gbtest import TEST_CFG, WEEKLY_FOCUS, cfg_copy, gh_calls, install_fake_gh, load_lib


def run_wf(tmp_path, *args, stdin=None):
    log = tmp_path / "gh.log"
    env = dict(os.environ, HOME=str(tmp_path / "home"), **install_fake_gh(tmp_path / "bin", [], log))
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), *args], input=stdin, env=env,
                       capture_output=True, text=True, timeout=30)
    return r, gh_calls(log)


def payload(**over):
    p = {"owner": "octo-user", "plan_week": cfg_copy()["plan_week"]}
    p.update(over)
    return json.dumps(p)


@pytest.mark.parametrize("args", [["sync"], ["sync", "--json"], ["show"], ["show", "--json"],
                                  ["set", "Next", "app#1"], ["pick", "app#1"], ["config"]])
def test_every_subcommand_but_init_exits_4_without_a_config(tmp_path, args):
    r, calls = run_wf(tmp_path, *args)
    assert r.returncode == 4, r.stderr
    assert "run `plan-week init`" in r.stderr
    assert calls == []          # nothing reached gh


def test_init_writes_the_config_from_stdin(tmp_path):
    r, calls = run_wf(tmp_path, "init", stdin=payload())
    assert r.returncode == 0, r.stderr
    assert calls == []
    cfg = json.loads(load_lib().config_path().read_text())
    assert cfg["plan_week"] == TEST_CFG["plan_week"] and cfg["owner"] == "octo-user"


def test_init_refuses_to_replace_without_force_then_force_replaces(tmp_path):
    assert run_wf(tmp_path, "init", stdin=payload())[0].returncode == 0
    path = load_lib().config_path()
    before = path.read_text()
    other = cfg_copy()["plan_week"]; other["frozen"] = []
    r, _ = run_wf(tmp_path, "init", stdin=payload(plan_week=other))
    assert r.returncode == 3 and "--force" in r.stderr
    assert path.read_text() == before
    r, _ = run_wf(tmp_path, "init", "--force", stdin=payload(plan_week=other))
    assert r.returncode == 0
    assert json.loads(path.read_text())["plan_week"]["frozen"] == []


def test_init_from_file(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(payload())
    r, _ = run_wf(tmp_path, "init", "--from", str(seed))
    assert r.returncode == 0, r.stderr


def test_init_from_a_missing_file_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", "--from", str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "cannot read" in r.stderr


def test_init_without_plan_week_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", stdin=json.dumps({"owner": "octo-user"}))
    assert r.returncode == 2 and "missing required key plan_week" in r.stderr


def test_init_with_an_unknown_argument_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", "--frobnicate", stdin=payload())
    assert r.returncode == 2 and "--frobnicate" in r.stderr


def test_config_prints_the_config(tmp_path, gb_config):
    r, calls = run_wf(tmp_path, "config")
    assert r.returncode == 0 and json.loads(r.stdout) == TEST_CFG and calls == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_plan_week_init.py -q -p no:cacheprovider`
Expected: FAIL — `init` and `config` exit 2 (unknown command).

- [ ] **Step 3: Implement**

Add to the docstring after the `show [--json]` entry:

```
  weekly-focus.py init [--force] [--from FILE]
                                  write the config from a JSON payload ({"owner", "plan_week",
                                  optional "create_board"}) on stdin, or from FILE. Refuses
                                  (exit 3) to replace a different existing section without --force.
  weekly-focus.py config          print the current config as JSON (exit 4 when there is none)
```

and change its exit-code line to `Exit codes: 0 ok; 1 error; 2 usage or invalid config (names the key); 3 sync skipped (GraphQL budget low) or init refused; 4 no config yet (run \`plan-week init\`).`

Replace `COMMANDS` and `main` with:

```python
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
    if argv[:1] and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    args = [a for a in argv if a != "--json"]
    as_json = "--json" in argv
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
    elif cmd == "sync":
        sync(as_json)
    elif cmd == "set":
        set_focus(args[1] if len(args) > 1 else "", args[2:])
    elif cmd == "pick":
        pick(args[1:])
    else:
        show(as_json)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/github-board/skills/plan-week/scripts/weekly-focus.py plugins/github-board/tests/test_plan_week_init.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(plan-week): init and config subcommands; exit 4 without a config (#146)"
```

---

### Task 6: Metadata cache — lib, bash helpers, and plan-week's board ids

**Files:**
- Modify: `plugins/github-board/lib/config.py`, `plugins/github-board/lib/config.sh`
- Modify: `plugins/github-board/skills/plan-week/scripts/weekly-focus.py`
- Create: `plugins/github-board/tests/test_cache.py`

**Interfaces:**
- Consumes: Tasks 3-5.
- Produces (Python): `CACHE_MAX_AGE_DAYS = 7`; `cache_get(key, max_age_days=7, now=None) -> Any | None` (None when missing, unreadable, older than the limit, from the future, or empty); `cache_put(key, value, now=None) -> bool` (never raises; skips empty values; warns once on stderr when unwritable); `cache_drop(key)`; `cache_drop_prefix(prefix) -> int`; `cache_drop_containing(text) -> int`. CLI: `config.py cache get KEY [--max-age-days N]` (exit 1 on a miss), `cache put KEY` (stdin JSON; exit 0 always), `cache drop KEY`, `cache drop-prefix PREFIX`, `cache drop-containing TEXT`.
- Produces (bash): `gb_cache_get KEY`, `gb_cache_put KEY`, `gb_cache_drop KEY`, `gb_cache_drop_containing TEXT`; env `GB_NO_CACHE=1` (never read or write) and `GB_CACHE_REFRESH=1` (skip reads, still write).
- Produces (weekly-focus.py): `CACHE_MODE` (`"use"` | `"refresh"` | `"off"`), `STALE_RE`, `SCOPE_RE`, `--no-cache` on every command, `_run_with_refetch(fn)`. Cache keys: `plan-week-<owner>-project-<title>` (`{id, number, url, title}`), `plan-week-<owner>-fields-<number>` (the `ensure_fields` map).

- [ ] **Step 1: Write the failing tests**

`plugins/github-board/tests/test_cache.py`:

```python
"""Metadata cache (#146): 7-day reuse, stale-id refetch once, --no-cache, unwritable dir."""
import json
import os
import subprocess
import sys
import time

import pytest

from gbtest import LIB, load_lib, load_weekly_focus

PROJECT_KEY = "plan-week-octo-user-project-Weekly Focus"


@pytest.fixture
def gbc():
    return load_lib()


def test_fresh_entry_is_reused(gbc):
    assert gbc.cache_put("k", {"a": 1})
    assert gbc.cache_get("k") == {"a": 1}


def test_entry_older_than_7_days_is_a_miss(gbc):
    gbc.cache_put("old", {"a": 1}, now=time.time() - 8 * 86400)
    gbc.cache_put("young", {"a": 1}, now=time.time() - 6 * 86400)
    assert gbc.cache_get("old") is None
    assert gbc.cache_get("young") == {"a": 1}


def test_empty_lookups_are_never_cached(gbc):
    for value in (None, [], {}, ""):
        assert gbc.cache_put("e", value) is False
    assert not (gbc.cache_dir() / "e.json").exists()


def test_a_corrupt_entry_is_a_miss(gbc):
    gbc.cache_dir().mkdir(parents=True)
    (gbc.cache_dir() / "bad.json").write_text("{nope")
    assert gbc.cache_get("bad") is None


def test_drop_prefix_and_containing(gbc):
    gbc.cache_put("plan-week-a", {"id": "PVT_1"})
    gbc.cache_put("plan-week-b", {"id": "PVT_2"})
    gbc.cache_put("other", {"id": "PVT_1"})
    assert gbc.cache_drop_prefix("plan-week-") == 2
    assert gbc.cache_drop_containing("PVT_1") == 1
    assert gbc.cache_get("other") is None


def test_unwritable_cache_warns_once_and_returns_false(gbc, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    assert gbc.cache_put("k", {"a": 1}) is False
    assert gbc.cache_put("k2", {"a": 1}) is False
    assert capsys.readouterr().err.count("metadata cache not written") == 1
    assert gbc.cache_get("k") is None


def _cli(*args, stdin=None, **env):
    return subprocess.run([sys.executable, str(LIB / "config.py"), "cache", *args], input=stdin,
                          capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))


def test_cli_get_miss_exits_1_and_put_get_round_trips():
    assert _cli("get", "nope").returncode == 1
    assert _cli("put", "k", stdin='{"a": 1}').returncode == 0
    r = _cli("get", "k")
    assert r.returncode == 0 and json.loads(r.stdout) == {"a": 1}


def test_cli_put_never_fails(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert _cli("put", "k", stdin='{"a": 1}', XDG_CACHE_HOME=str(blocker)).returncode == 0
    assert _cli("put", "k", stdin="not json").returncode == 0


def _bash(snippet, **env):
    return subprocess.run(["bash", "-c", f'. "{LIB}/config.sh"; {snippet}'], capture_output=True,
                          text=True, timeout=30, env=dict(os.environ, GB_PYTHON=sys.executable, **env))


def test_bash_helpers_respect_no_cache_and_refresh():
    assert _bash("echo '{\"a\":1}' | gb_cache_put k && gb_cache_get k").stdout.strip() == '{"a": 1}'
    assert _bash("gb_cache_get k", GB_NO_CACHE="1").returncode != 0
    assert _bash("gb_cache_get k", GB_CACHE_REFRESH="1").returncode != 0
    _bash("echo '{\"a\":2}' | gb_cache_put k", GB_NO_CACHE="1")
    assert _bash("gb_cache_get k").stdout.strip() == '{"a": 1}'      # --no-cache never writes
    _bash("echo '{\"a\":3}' | gb_cache_put k", GB_CACHE_REFRESH="1")
    assert _bash("gb_cache_get k").stdout.strip() == '{"a": 3}'      # a refresh still writes


# ---- plan-week ------------------------------------------------------------------

def _fake_gh(wf, calls, stale_numbers=(99,)):
    def fake(*args, parse=True, **kw):
        calls.append(args)
        q = next((a for a in args if a.startswith("query=")), "")
        if any(f"projectV2(number:{n})" in q for n in stale_numbers):
            raise wf.GhError("gh api graphql failed (exit 1): GraphQL: Could not resolve to a "
                             "ProjectV2 with the number 99. (user.projectV2)")
        if "projectsV2" in q:
            return json.dumps({"id": "PVT_new", "number": 36, "title": "Weekly Focus",
                               "url": "U36", "closed": False})
        if "projectV2(number:36)" in q or "search(query" in q:
            return ""
        raise AssertionError(f"unexpected gh call {args}")
    wf.gh = fake


def _project_queries(calls):
    return [c for c in calls if any("projectsV2" in a for a in c)]


def test_plan_week_reuses_the_cached_project(gb_config, capsys):
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    assert len(_project_queries(calls)) == 1
    calls.clear()
    wf2 = load_weekly_focus()
    _fake_gh(wf2, calls)
    wf2.main(["show", "--json"])
    assert _project_queries(calls) == []
    capsys.readouterr()


def test_stale_cached_project_is_dropped_and_refetched_once(gb_config, gbc, capsys):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["url"] == "U36"
    assert "refetching once" in captured.err
    assert gbc.cache_get(PROJECT_KEY)["number"] == 36


def test_a_second_stale_error_is_not_retried_again(gb_config, gbc):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls, stale_numbers=(99, 36))
    with pytest.raises(wf.GhError):
        wf.main(["show", "--json"])
    assert len(_project_queries(calls)) == 1


def test_no_cache_never_reads_or_writes(gb_config, gbc, capsys):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    before = sorted(p.name for p in gbc.cache_dir().iterdir())
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json", "--no-cache"])
    assert json.loads(capsys.readouterr().out)["url"] == "U36"
    assert gbc.cache_get(PROJECT_KEY)["number"] == 99            # untouched
    assert sorted(p.name for p in gbc.cache_dir().iterdir()) == before


def test_plan_week_runs_when_the_cache_cannot_be_written(gb_config, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "cache-is-a-file"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["url"] == "U36"
    assert captured.err.count("metadata cache not written") == 1


SCOPE_ERR = ("GraphQL: Your token has not been granted the required scopes to execute this query. "
             "The 'id' field requires one of the following scopes: ['read:project']")


def test_scope_error_is_not_retried_and_names_the_fix(monkeypatch):
    wf = load_weekly_focus(stub_gh=False)
    runs, sleeps = [], []
    monkeypatch.setattr(wf.time, "sleep", sleeps.append)

    def fake_run(cmd, **kw):
        runs.append(cmd)
        raise subprocess.CalledProcessError(1, cmd, output="", stderr=SCOPE_ERR)
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as ei:
        wf.gh("api", "graphql", "-f", "query=x")
    assert "gh auth refresh -s read:project,project" in str(ei.value)
    assert len(runs) == 1 and sleeps == []


def test_scope_error_writes_no_cache(gb_config, gbc, monkeypatch):
    wf = load_weekly_focus(stub_gh=False)
    monkeypatch.setattr(wf.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, cmd, output="", stderr=SCOPE_ERR)))
    with pytest.raises(wf.GhError):
        wf.main(["show", "--json"])
    assert not gbc.cache_dir().exists() or list(gbc.cache_dir().iterdir()) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_cache.py -q -p no:cacheprovider`
Expected: FAIL — `cache_put` not defined; `--no-cache` unknown.

- [ ] **Step 3: Add the cache to `lib/config.py`**

Add `import time` to the imports and `CACHE_MAX_AGE_DAYS = 7` under `VERSION`. Add to the docstring, after the Preferences paragraph:

```
Metadata cache: ${XDG_CACHE_HOME:-~/.cache}/github-board/<key>.json, one file per lookup with
the time it was fetched. Entries are reused for 7 days. An empty lookup is never cached.
Deleting the directory is always safe.
```

and to the CLI list:

```
  config.py cache get KEY [--max-age-days N]   print a fresh entry (exit 1 on a miss)
  config.py cache put KEY                      store stdin JSON (never fails its caller)
  config.py cache drop KEY | drop-prefix PREFIX | drop-containing TEXT
```

and `1 cache miss;` to the exit codes. Add before the CLI section:

```python
# ---- metadata cache -------------------------------------------------------------

_cache_warned = False


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)


def _cache_file(key: str) -> Path:
    return cache_dir() / (_safe(key) + ".json")


def _empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == ""


def cache_get(key: str, max_age_days: float = CACHE_MAX_AGE_DAYS, now: Optional[float] = None) -> Any:
    """The cached value; None when missing, unreadable, too old, from the future, or empty."""
    try:
        entry = json.loads(_cache_file(key).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict):
        return None
    fetched = entry.get("fetched_at")
    now = time.time() if now is None else now
    if isinstance(fetched, bool) or not isinstance(fetched, (int, float)):
        return None
    if fetched > now + 300 or now - fetched > max_age_days * 86400:
        return None
    value = entry.get("value")
    return None if _empty(value) else value


def cache_put(key: str, value: Any, now: Optional[float] = None) -> bool:
    """Store value. Never raises: an unwritable cache warns once on stderr and returns False."""
    global _cache_warned
    if _empty(value):
        return False
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = _cache_file(key)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"key": key, "fetched_at": time.time() if now is None else now,
                                   "value": value}))
        os.replace(tmp, f)
        return True
    except OSError as e:
        if not _cache_warned:
            print(f"github-board: warning: metadata cache not written ({e}); carrying on without it",
                  file=sys.stderr)
            _cache_warned = True
        return False


def cache_drop(key: str) -> None:
    try:
        _cache_file(key).unlink()
    except OSError:
        pass


def _entries() -> list:
    try:
        return sorted(cache_dir().glob("*.json"))
    except OSError:
        return []


def cache_drop_prefix(prefix: str) -> int:
    n = 0
    for f in _entries():
        if f.name.startswith(_safe(prefix)):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def cache_drop_containing(text: str) -> int:
    n = 0
    for f in _entries():
        try:
            if text in f.read_text():
                f.unlink()
                n += 1
        except OSError:
            pass
    return n
```

In `_parser()`, before `return ap`, add:

```python
    c = sub.add_parser("cache")
    csub = c.add_subparsers(dest="op", required=True)
    cg = csub.add_parser("get")
    cg.add_argument("key")
    cg.add_argument("--max-age-days", type=float, default=CACHE_MAX_AGE_DAYS)
    csub.add_parser("put").add_argument("key")
    csub.add_parser("drop").add_argument("key")
    csub.add_parser("drop-prefix").add_argument("prefix")
    csub.add_parser("drop-containing").add_argument("text")
```

In `main`, after the `init` branch and inside the `try`, add:

```python
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
        elif args.op == "drop-prefix":
            print(cache_drop_prefix(args.prefix))
        elif args.op == "drop-containing":
            print(cache_drop_containing(args.text))
```

- [ ] **Step 4: Add the bash helpers to `lib/config.sh`**

Append to the header comment:

```bash
#   gb_cache_get KEY              print a fresh cache entry; non-zero on a miss
#   gb_cache_put KEY              store stdin JSON; never fails
#   gb_cache_drop KEY             forget one entry
#   gb_cache_drop_containing TEXT forget every entry whose JSON contains TEXT (a stale id)
# GB_NO_CACHE=1 (--no-cache): never read or write the cache.
# GB_CACHE_REFRESH=1: skip reads but write fresh entries (the one refetch after a stale id).
```

Append the functions:

```bash
gb_cache_get() {
  if [ "${GB_NO_CACHE:-0}" = 1 ] || [ "${GB_CACHE_REFRESH:-0}" = 1 ]; then return 1; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache get "$1"
}

gb_cache_put() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then cat >/dev/null; return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache put "$1" || true
}

gb_cache_drop() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop "$1" || true
}

gb_cache_drop_containing() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop-containing "$1" >/dev/null || true
}
```

- [ ] **Step 5: Use the cache in `weekly-focus.py`**

5a. Docstring: add after the `config` entry ``  --no-cache (any command)        never read or write the board-id cache (~/.cache/github-board)``.

5b. Under `RATE_RE = …` add:

```python
SCOPE_RE = re.compile(r"required scopes|INSUFFICIENT_SCOPES|missing required scopes?", re.I)
STALE_RE = re.compile(r"Could not resolve to (?:a|an) \w+ with|NOT_FOUND|Cannot iterate over null", re.I)
CACHE_MODE = "use"      # "use" | "refresh" (skip reads, write fresh) | "off" (--no-cache)
_CACHE_USED = False
```

5c. In `gh()`, inside `except subprocess.CalledProcessError as e:`, right after `body = …`, add:

```python
            if SCOPE_RE.search(err) or SCOPE_RE.search(body):
                raise GhError("GitHub token lacks the project scope; run "
                              f"`gh auth refresh -s read:project,project` (gh {' '.join(args[:2])}: "
                              f"{err[:200]})") from e
```

5d. After `_cached`, add:

```python
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
    """Run fn. If it fails on an id that came from the cache, drop the cache and run it once more."""
    global CACHE_MODE
    try:
        return fn()
    except GhError as e:
        if not (_CACHE_USED and CACHE_MODE == "use" and STALE_RE.search(str(e))):
            raise
    print("weekly-focus: cached board ids look stale; refetching once", file=sys.stderr)
    gbconfig.cache_drop_prefix(f"plan-week-{OWNER}-")
    _CACHE.clear()
    CACHE_MODE = "refresh"
    return fn()
```

5e. Replace `find_or_create_project` with:

```python
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
```

5f. In `ensure_fields`, make `read()` start with a cache read and end with a cache write, and add the completeness check above `ensure_fields`:

```python
def _fields_complete(out):
    """A cached field map is usable only if it has every field and option FIELDS needs."""
    return isinstance(out, dict) and all(
        isinstance(out.get(name), dict) and all(o in out[name].get("opts", {}) for o in opts)
        for name, opts in FIELDS.items())
```

```python
    def read():
        hit = _cache_read(f"fields-{num}")
        if _fields_complete(hit):
            return hit
        have = field_map(num)
        # … existing body unchanged down to the Status block …
        _cache_write(f"fields-{num}", out)
        return out
```

5g. In `main`, between `as_json = …` and `cmd = …`, handle the flag (so `--no-cache` never becomes the command), and run the commands through the refetch wrapper:

```python
    global CACHE_MODE
    if "--no-cache" in argv:
        CACHE_MODE = "off"
    args = [a for a in args if a != "--no-cache"]
```

(put `global CACHE_MODE` as the first line of `main`), and replace the final `if cmd == "config" … else: show(as_json)` chain with:

```python
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
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider`
Expected: PASS. (The moved `test_weekly_focus.py` tests hit the isolated cache dir only.)

- [ ] **Step 7: Commit**

```bash
git add plugins/github-board/lib plugins/github-board/skills/plan-week/scripts/weekly-focus.py \
  plugins/github-board/tests/test_cache.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(github-board): 7-day metadata cache; plan-week caches board ids, refetches once (#146)"
```

---

### Task 7: launchd — config labels, stable link, takeover guard

**Files:**
- Modify: `plugins/github-board/skills/plan-week/scripts/common.sh`, `install-launchd.sh`
- Rename + rewrite: `skills/plan-week/launchd/com.*-sync.plist.template` → `launchd/sync.plist.template`; `com.*-watchdog.plist.template` → `launchd/watchdog.plist.template`
- Rewrite: `plugins/github-board/skills/plan-week/README.md`
- Modify: `plugins/github-board/tests/test_weekly_focus_launchd.py`

**Interfaces:**
- Consumes: `gb_config_get` (`plan_week.launchd.label_prefix`, `.enabled`, `.times --lines`).
- Produces: `common.sh` exports `GITHUB_BOARD_LINK` (default `$HOME/.local/share/github-board/current`), sets `PLUGIN_ROOT` (symlinks resolved), `LABEL_PREFIX`, `SYNC_LABEL`, `WATCHDOG_LABEL`, `LABELS`; exits with `config.py`'s code (4 / 2) when the config cannot be read. `install-launchd.sh [--only <label>] [--no-reload] [--takeover] [--check]` with exit codes 0 / 1 / 2 / 3 / 4. Rendered plists run `$GITHUB_BOARD_LINK/skills/plan-week/scripts/{run-sync,watchdog}.sh` and set `XDG_CONFIG_HOME` / `XDG_CACHE_HOME`.

- [ ] **Step 1: Update the launchd tests**

In `tests/test_weekly_focus_launchd.py`, replace everything from the module docstring down to (not including) `@pytest.fixture\ndef e(tmp_path):` with:

```python
"""Tests for the plan-week launchd scripts (#214, #146).

Every external command is a stub executable in a tmp dir that appends its argv to a log file,
so nothing here touches the real launchctl, osascript, gh, ~/Library or ~/.local/share.
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gbtest import TEST_CFG, cfg_copy, write_config

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = PLUGIN / "skills" / "plan-week"
SCRIPTS = SKILL / "scripts"
PREFIX = TEST_CFG["plan_week"]["launchd"]["label_prefix"]
SYNC = f"{PREFIX}-sync"
WATCHDOG = f"{PREFIX}-watchdog"
T0 = 1_800_000_000          # arbitrary fixed "now"
HOUR = 3600


class Env:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.la = tmp / "LaunchAgents"
        self.state = tmp / "state"
        self.logs = tmp / "logs"
        self.bin = tmp / "bin"
        self.cfg_home = tmp / "launchd-config"
        self.cache_home = tmp / "launchd-cache"
        self.link = tmp / "share" / "github-board" / "current"
        for d in (self.home, self.bin):
            d.mkdir()
        self.set_config(TEST_CFG)
        self.calls = {n: tmp / f"{n}.calls" for n in ("launchctl", "osascript", "python")}
        cnt = tmp / "bootstrap.count"
        self._stub("launchctl", 'if [ "$1" = print ]; then exit "${LAUNCHCTL_PRINT_RC:-0}"; fi\n'
                                'if [ "$1" = bootstrap ]; then\n'
                                f'  c=$(cat "{cnt}" 2>/dev/null || echo 0); echo $((c+1)) > "{cnt}"\n'
                                '  if [ "$c" -lt "${LAUNCHCTL_BOOTSTRAP_FAILS:-0}" ]; then exit 5; fi\n'
                                '  exit "${LAUNCHCTL_BOOTSTRAP_RC:-0}"\n'
                                'fi\n')
        self._stub("osascript", "")
        self._stub("python", 'if [ -n "${PY_STDERR:-}" ]; then printf "%b" "$PY_STDERR" >&2; fi\n'
                             'exit "${PY_RC:-0}"\n')
        self.extra = {}

    def set_config(self, cfg):
        write_config(self.cfg_home, cfg)

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text(f'#!/bin/bash\necho "$@" >> "{self.calls[name]}"\n{body}')
        path.chmod(0o755)

    def env(self, **kw):
        e = {"PATH": os.environ["PATH"], "HOME": str(self.home),
             "LAUNCHCTL": str(self.bin / "launchctl"), "OSASCRIPT": str(self.bin / "osascript"),
             "PYTHON": str(self.bin / "python"), "LA_DIR": str(self.la),
             "STATE_DIR": str(self.state), "LOG_DIR": str(self.logs), "NOW": str(T0),
             "BOOTSTRAP_RETRY_SLEEP": "0", "GB_PYTHON": sys.executable,
             "XDG_CONFIG_HOME": str(self.cfg_home), "XDG_CACHE_HOME": str(self.cache_home),
             "GITHUB_BOARD_LINK": str(self.link)}
        e.update(self.extra)
        e.update({k: str(v) for k, v in kw.items()})
        return e

    def run(self, script, *args, **kw):
        return self.run_path(SCRIPTS / script, *args, **kw)

    def run_path(self, path, *args, **kw):
        return subprocess.run(["bash", str(path), *args], env=self.env(**kw),
                              capture_output=True, text=True, timeout=60)

    def plist(self, label):
        with open(self.la / f"{label}.plist", "rb") as f:
            return plistlib.load(f)

    def log(self, name):
        p = self.calls[name]
        return p.read_text().splitlines() if p.exists() else []

    def reset_logs(self):
        for p in self.calls.values():
            p.unlink(missing_ok=True)

    def set_heartbeat(self, age_seconds):
        self.state.mkdir(parents=True, exist_ok=True)
        hb = self.state / "last-success"
        hb.touch()
        os.utime(hb, (T0 - age_seconds, T0 - age_seconds))


def foreign_plist(e, label, program):
    e.la.mkdir(parents=True, exist_ok=True)
    with open(e.la / f"{label}.plist", "wb") as f:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", program]}, f)
```

Replace the `# ---- static checks` section (the two template tests; keep `test_skill_frontmatter_name_matches_directory`) with:

```python
# ---- static checks --------------------------------------------------------

@pytest.mark.parametrize("kind", ["sync", "watchdog"])
def test_plist_templates_have_no_keepalive_and_use_placeholders(kind):
    text = (SKILL / "launchd" / f"{kind}.plist.template").read_text()
    script = "run-sync.sh" if kind == "sync" else "watchdog.sh"
    assert "KeepAlive" not in text and ".claude" not in text
    assert "<string>__LABEL__</string>" in text and f"__SCRIPTS__/{script}" in text
    assert ("RunAtLoad" in text) == (kind == "watchdog")
    assert ("__CALENDAR__" in text) == (kind == "sync")


def test_only_the_two_generic_templates_exist():
    assert sorted(p.name for p in (SKILL / "launchd").iterdir()) == [
        "sync.plist.template", "watchdog.plist.template"]


@pytest.mark.parametrize("label", [SYNC, WATCHDOG])
def test_rendered_plists_parse_and_run_through_the_link(e, label):
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    d = e.plist(label)
    assert d["Label"] == label
    assert d["ProgramArguments"][1].startswith(f"{e.link}/skills/plan-week/scripts/")
    assert d["EnvironmentVariables"]["XDG_CONFIG_HOME"] == str(e.cfg_home)
    assert d["EnvironmentVariables"]["XDG_CACHE_HOME"] == str(e.cache_home)
    if shutil.which("plutil"):
        r = subprocess.run(["plutil", "-lint", str(e.la / f"{label}.plist")], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_sync_times_come_from_the_config(e):
    c = cfg_copy(); c["plan_week"]["launchd"]["times"] = ["06:30", "21:05"]
    e.set_config(c)
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    assert e.plist(SYNC)["StartCalendarInterval"] == [{"Hour": 6, "Minute": 30}, {"Hour": 21, "Minute": 5}]


# ---- stable link and takeover (#146) ----------------------------------------

def test_install_points_the_link_at_this_plugin(e):
    assert e.run("install-launchd.sh").returncode == 0
    assert e.link.is_symlink() and e.link.resolve() == PLUGIN.resolve()


def test_install_re_points_an_old_link(e, tmp_path):
    old = tmp_path / "old-version"
    old.mkdir()
    e.link.parent.mkdir(parents=True)
    e.link.symlink_to(old)
    assert e.run("install-launchd.sh").returncode == 0
    assert e.link.resolve() == PLUGIN.resolve()


def test_install_run_through_the_link_never_points_the_link_at_itself(e):
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    r = e.run_path(e.link / "skills" / "plan-week" / "scripts" / "install-launchd.sh", "--no-reload")
    assert r.returncode == 0, r.stderr
    assert os.readlink(e.link) == str(PLUGIN.resolve())


def test_takeover_is_refused_when_another_copy_owns_a_plist(e):
    other = "/Users/someone/old-skills/weekly-focus/scripts/run-sync.sh"
    foreign_plist(e, SYNC, other)
    before = (e.la / f"{SYNC}.plist").read_bytes()
    r = e.run("install-launchd.sh")
    assert r.returncode == 3
    assert other in r.stderr and "--takeover" in r.stderr
    assert (e.la / f"{SYNC}.plist").read_bytes() == before
    assert not (e.la / f"{WATCHDOG}.plist").exists()
    assert not e.link.exists() and e.log("launchctl") == []


def test_takeover_flag_hands_the_job_over(e):
    foreign_plist(e, SYNC, "/Users/someone/old-skills/weekly-focus/scripts/run-sync.sh")
    r = e.run("install-launchd.sh", "--takeover")
    assert r.returncode == 0, r.stderr
    assert e.plist(SYNC)["ProgramArguments"][1] == f"{e.link}/skills/plan-week/scripts/run-sync.sh"


def test_an_unreadable_plist_blocks_too(e):
    e.la.mkdir(parents=True)
    (e.la / f"{SYNC}.plist").write_bytes(b"\x00not a plist")
    r = e.run("install-launchd.sh")
    assert r.returncode == 3 and "cannot read" in r.stderr


def test_our_own_plist_is_not_a_foreign_owner(e):
    assert e.run("install-launchd.sh").returncode == 0
    assert e.run("install-launchd.sh").returncode == 0


def test_link_path_that_is_a_real_directory_is_refused(e):
    e.link.mkdir(parents=True)
    (e.link / "keep.txt").write_text("mine")
    r = e.run("install-launchd.sh")
    assert r.returncode == 3 and "not a symlink" in r.stderr
    assert (e.link / "keep.txt").read_text() == "mine" and sorted(p.name for p in e.link.iterdir()) == ["keep.txt"]
    assert not e.la.exists() or list(e.la.iterdir()) == []


def test_launchd_disabled_in_config_installs_nothing(e):
    c = cfg_copy(); c["plan_week"]["launchd"]["enabled"] = False
    e.set_config(c)
    r = e.run("install-launchd.sh")
    assert r.returncode == 2 and "enabled is false" in r.stderr
    assert not e.la.exists() and not e.link.exists()


def test_missing_config_exits_4(e):
    (e.cfg_home / "github-board" / "config.json").unlink()
    r = e.run("install-launchd.sh")
    assert r.returncode == 4 and "plan-week init" in r.stderr


def test_check_fails_on_a_missing_link(installed):
    installed.link.unlink()
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "MISSING LINK" in r.stdout


def test_check_fails_on_a_dangling_link(installed, tmp_path):
    installed.link.unlink()
    installed.link.symlink_to(tmp_path / "gone")
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "DANGLING LINK" in r.stdout


def test_check_fails_on_a_link_without_plan_week(installed, tmp_path):
    empty = tmp_path / "empty-plugin"
    empty.mkdir()
    installed.link.unlink()
    installed.link.symlink_to(empty)
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "BAD LINK" in r.stdout


def test_check_reports_a_real_directory_at_the_link_path(installed):
    installed.link.unlink()
    installed.link.mkdir()
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "NOT A LINK" in r.stdout
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_weekly_focus_launchd.py -q -p no:cacheprovider`
Expected: FAIL — labels still hard-coded, no link, templates still named by label.

- [ ] **Step 3: Templates**

```bash
L=plugins/github-board/skills/plan-week/launchd
git mv $L/com.abhattacherjee.weekly-focus-sync.plist.template $L/sync.plist.template
git mv $L/com.abhattacherjee.weekly-focus-watchdog.plist.template $L/watchdog.plist.template
```

`launchd/sync.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>__LABEL__</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>__SCRIPTS__/run-sync.sh</string>
	</array>
	<key>StartCalendarInterval</key>
	<array>
__CALENDAR__
	</array>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
		<key>XDG_CONFIG_HOME</key>
		<string>__XDG_CONFIG_HOME__</string>
		<key>XDG_CACHE_HOME</key>
		<string>__XDG_CACHE_HOME__</string>
	</dict>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>__HOME__/Library/Logs/weekly-focus/sync.log</string>
	<key>StandardErrorPath</key>
	<string>__HOME__/Library/Logs/weekly-focus/sync.err.log</string>
</dict>
</plist>
```

`launchd/watchdog.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>__LABEL__</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>__SCRIPTS__/watchdog.sh</string>
	</array>
	<key>StartInterval</key>
	<integer>3600</integer>
	<key>RunAtLoad</key>
	<true/>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
		<key>XDG_CONFIG_HOME</key>
		<string>__XDG_CONFIG_HOME__</string>
		<key>XDG_CACHE_HOME</key>
		<string>__XDG_CACHE_HOME__</string>
	</dict>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>__HOME__/Library/Logs/weekly-focus/watchdog.log</string>
	<key>StandardErrorPath</key>
	<string>__HOME__/Library/Logs/weekly-focus/watchdog.err.log</string>
</dict>
</plist>
```

The rendered `XDG_*` values are the ones in force when `install-launchd.sh` runs, so launchd reads the same config file the person wrote with `init`.

- [ ] **Step 4: `common.sh`**

Replace lines 1-16 (shebang through `DOMAIN="gui/$(id -u)"`) with:

```bash
#!/usr/bin/env bash
# Shared settings for the plan-week launchd scripts. Sourced, not run.
# Every external command and path can be overridden from the environment (tests do).
# Labels come from the github-board config (plan_week.launchd.label_prefix); a missing or
# invalid config exits here with config.py's code (4 or 2).
_WF_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SKILL_DIR="${SKILL_DIR:-$(cd "$_WF_SCRIPTS/.." && pwd)}"
export LAUNCHCTL="${LAUNCHCTL:-launchctl}"
export OSASCRIPT="${OSASCRIPT:-/usr/bin/osascript}"
export PYTHON="${PYTHON:-python3}"
export LA_DIR="${LA_DIR:-$HOME/Library/LaunchAgents}"
export STATE_DIR="${STATE_DIR:-$HOME/.local/state/weekly-focus}"
export LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/weekly-focus}"
export NOW="${NOW:-$(date +%s)}"
# Stable path the plists run through, so they survive plugin upgrades (re-pointed by install).
export GITHUB_BOARD_LINK="${GITHUB_BOARD_LINK:-$HOME/.local/share/github-board/current}"
# The plugin root this copy runs from, symlinks resolved, so the link never points at itself.
PLUGIN_ROOT="$(cd "$_WF_SCRIPTS/../../.." && pwd -P)"

. "$_WF_SCRIPTS/../../../lib/config.sh"
LABEL_PREFIX="$(gb_config_get plan_week.launchd.label_prefix)" || exit $?
SYNC_LABEL="$LABEL_PREFIX-sync"
WATCHDOG_LABEL="$LABEL_PREFIX-watchdog"
LABELS="$SYNC_LABEL $WATCHDOG_LABEL"
DOMAIN="gui/$(id -u)"
```

- [ ] **Step 5: `install-launchd.sh`**

Replace the whole file with:

```bash
#!/usr/bin/env bash
# Install (or check) the plan-week launchd agents.
#   install-launchd.sh                  point the stable link at this plugin, render both plists
#                                       into ~/Library/LaunchAgents and load them
#   install-launchd.sh --only <label>   just one label
#   install-launchd.sh --no-reload      write the link and plist files; no bootout/bootstrap
#   install-launchd.sh --takeover       replace plists that another copy (an older bare skill) owns
#   install-launchd.sh --check          write nothing; exit 1 if the link or a plist is missing or
#                                       wrong, differs from its template, or is not loaded
# Labels: <plan_week.launchd.label_prefix>-sync and -watchdog. Sync times: plan_week.launchd.times.
# The plists run the scripts through $GITHUB_BOARD_LINK (~/.local/share/github-board/current).
# Re-run this after every plugin update so the link points at the new version.
# Exit codes: 0 ok; 1 a launchctl step or a check failed; 2 bad arguments, or launchd is disabled
# in the config; 3 refused: another copy owns a plist (pass --takeover) or the link path is not a
# symlink; 4 no config (run plan-week init).
# Overrides for tests: LAUNCHCTL, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR, GITHUB_BOARD_LINK, GB_PYTHON,
# XDG_CONFIG_HOME, XDG_CACHE_HOME, BOOTSTRAP_RETRY_SLEEP.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

only="" check=0 reload=1 takeover=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) only="${2:-}"; shift 2 || { echo "--only needs a label" >&2; exit 2; } ;;
    --check) check=1; shift ;;
    --no-reload) reload=0; shift ;;
    --takeover) takeover=1; shift ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
if [ -n "$only" ]; then
  case " $LABELS " in *" $only "*) targets="$only" ;; *) echo "unknown label: $only" >&2; exit 2 ;; esac
else
  targets="$LABELS"
fi

enabled="$(gb_config_get plan_week.launchd.enabled)" || exit $?
if [ "$enabled" != true ]; then
  echo "plan_week.launchd.enabled is false in the config; nothing to install" >&2
  exit 2
fi

calendar_xml() { # one <dict> per plan_week.launchd.times entry
  local t h m times
  times="$(gb_config_get plan_week.launchd.times --lines)" || return 1
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    h=$((10#${t%%:*})); m=$((10#${t##*:}))
    printf '\t\t<dict>\n\t\t\t<key>Hour</key>\n\t\t\t<integer>%d</integer>\n\t\t\t<key>Minute</key>\n\t\t\t<integer>%d</integer>\n\t\t</dict>\n' "$h" "$m"
  done <<< "$times"
}

render() { # render <label> -> stdout
  local kind tpl body cal
  case "$1" in
    "$SYNC_LABEL") kind=sync ;;
    "$WATCHDOG_LABEL") kind=watchdog ;;
    *) echo "unknown label: $1" >&2; return 1 ;;
  esac
  tpl="$SKILL_DIR/launchd/$kind.plist.template"
  [ -f "$tpl" ] || { echo "missing template: $tpl" >&2; return 1; }
  body=$(<"$tpl")
  # None of these values contains '&', so bash 5.2's patsub_replacement cannot bite.
  body="${body//__LABEL__/$1}"
  body="${body//__SCRIPTS__/$GITHUB_BOARD_LINK/skills/plan-week/scripts}"
  body="${body//__XDG_CONFIG_HOME__/${XDG_CONFIG_HOME:-$HOME/.config}}"
  body="${body//__XDG_CACHE_HOME__/${XDG_CACHE_HOME:-$HOME/.cache}}"
  body="${body//__HOME__/$HOME}"
  if [ "$kind" = sync ]; then
    cal="$(calendar_xml)" || return 1
    body="${body//__CALENDAR__/$cal}"
  fi
  printf '%s\n' "$body"
}

plist_program() { # plist_program <plist> -> the script launchd runs; non-zero if unreadable
  "$GB_PYTHON" - "$1" <<'PY'
import plistlib, sys
try:
    with open(sys.argv[1], "rb") as f:
        print(plistlib.load(f)["ProgramArguments"][-1])
except Exception:
    sys.exit(1)
PY
}

guard_owner() { # guard_owner <label>: 0 when we may write its plist, 3 when another copy owns it
  local plist="$LA_DIR/$1.plist" prog
  [ -e "$plist" ] || return 0
  if ! prog="$(plist_program "$plist")"; then
    echo "refusing: cannot read $plist, so its owner is unknown. Inspect it, then re-run with --takeover." >&2
    return 3
  fi
  case "$prog" in "$GITHUB_BOARD_LINK"/*) return 0 ;; esac
  echo "refusing: $plist runs $prog, which belongs to another copy. Re-run with --takeover to hand the job to this plugin." >&2
  return 3
}

check_link() {
  if [ ! -L "$GITHUB_BOARD_LINK" ]; then
    if [ -e "$GITHUB_BOARD_LINK" ]; then echo "NOT A LINK $GITHUB_BOARD_LINK"; else echo "MISSING LINK $GITHUB_BOARD_LINK"; fi
    return 1
  fi
  if [ ! -e "$GITHUB_BOARD_LINK" ]; then echo "DANGLING LINK $GITHUB_BOARD_LINK"; return 1; fi
  if [ ! -f "$GITHUB_BOARD_LINK/skills/plan-week/scripts/run-sync.sh" ]; then
    echo "BAD LINK $GITHUB_BOARD_LINK (no skills/plan-week/scripts/run-sync.sh)"; return 1
  fi
  echo "ok $GITHUB_BOARD_LINK -> $(readlink "$GITHUB_BOARD_LINK")"
}

if [ "$check" -eq 1 ]; then
  rc=0
  check_link || rc=1
  for label in $targets; do
    plist="$LA_DIR/$label.plist"
    if ! is_loaded "$label"; then echo "NOT LOADED $label"; rc=1; fi
    if [ ! -f "$plist" ]; then echo "MISSING $plist"; rc=1; continue; fi
    want=$(render "$label") || { rc=1; continue; }
    have=$(<"$plist")
    if [ "$want" != "$have" ]; then echo "DIFFERS $plist"; rc=1; else echo "ok $plist"; fi
  done
  exit "$rc"
fi

# Refuse before writing anything.
if [ -e "$GITHUB_BOARD_LINK" ] && [ ! -L "$GITHUB_BOARD_LINK" ]; then
  echo "refusing: $GITHUB_BOARD_LINK exists and is not a symlink. Move it away, then re-run." >&2
  exit 3
fi
if [ "$takeover" -eq 0 ]; then
  refused=0
  for label in $targets; do guard_owner "$label" || refused=3; done
  [ "$refused" -eq 0 ] || exit 3
fi

mkdir -p "$(dirname "$GITHUB_BOARD_LINK")" || exit 1
ln -sfn "$PLUGIN_ROOT" "$GITHUB_BOARD_LINK" || { echo "could not write $GITHUB_BOARD_LINK" >&2; exit 1; }

mkdir -p "$LA_DIR" "$LOG_DIR" "$STATE_DIR"
rc=0
for label in $targets; do
  plist="$LA_DIR/$label.plist"
  if ! render "$label" > "$plist.tmp"; then rm -f "$plist.tmp"; rc=1; continue; fi
  mv "$plist.tmp" "$plist"
  if [ "$reload" -eq 0 ]; then echo "wrote $label (not reloaded)"; continue; fi
  "$LAUNCHCTL" bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  # bootout then bootstrap can fail with error 5 while launchd is still tearing the job down.
  ok=0
  for attempt in 1 2 3; do
    if "$LAUNCHCTL" bootstrap "$DOMAIN" "$plist"; then ok=1; break; fi
    [ "$attempt" -lt 3 ] && sleep "${BOOTSTRAP_RETRY_SLEEP:-1}"
  done
  if [ "$ok" -eq 1 ]; then
    echo "installed $label"
  else
    echo "bootstrap failed: $label" >&2; rc=1
  fi
done
exit "$rc"
```

- [ ] **Step 6: Rewrite the plan-week README**

`plugins/github-board/skills/plan-week/README.md`:

````markdown
# plan-week

A skill and script that keep a cross-repo "Weekly Focus" GitHub Project current, and answer "what do I work on next". Settings come from the github-board config (`plan-week init` writes it).

- `scripts/weekly-focus.py`: `sync`, `set <Focus> repo#N...` (`pick` = `set "This week"`), `show`, `init`, `config`. `sync` and `show` take `--json`; every command takes `--no-cache`.
- `SKILL.md`: `/github-board:plan-week` and questions like "what should I work on".
- `launchd/`: templates for two agents, labelled `<plan_week.launchd.label_prefix>-sync` (runs `scripts/run-sync.sh` at `plan_week.launchd.times`) and `<prefix>-watchdog` (runs `scripts/watchdog.sh` hourly and at load). No KeepAlive.

The watchdog reinstalls a missing plist, reloads an unloaded sync job, and sends a macOS notification if the last successful sync is more than 26 hours old (each alert at most once per 6 hours). Each sync run also reloads the watchdog if it is not loaded.

## Board setup

`sync` creates the board if it is missing. A new GitHub project starts with default workflows that GitHub's API cannot change, so turn two of them off by hand (board **⋯ → Workflows**):

- **Auto-add sub-issues to project**: when `sync` adds an epic, GitHub adds its sub-issues with no Focus or Lane.
- **Auto-close issue**: moving a card to Done here would close the real issue and skip that repo's own release flow.

Check with: `gh api graphql -f query='{user(login:"<owner>"){projectV2(number:<n>){workflows(first:20){nodes{name enabled}}}}}'`

## The stable link

The installed plugin lives under a versioned path (`~/.claude/plugins/cache/<marketplace>/github-board/<version>/`), which changes on every upgrade. The plists therefore run the scripts through `~/.local/share/github-board/current/skills/plan-week/scripts/`. `install-launchd.sh` points that link at the plugin copy it runs from. **Re-run `install-launchd.sh` after each plugin update.**

## Install

`PW` is this skill's directory in the installed plugin, for example:

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh"                       # link + both agents
"$PW/scripts/install-launchd.sh" --only <prefix>-watchdog
```

It points the link at the plugin, renders the templates into `~/Library/LaunchAgents/`, creates the log and state directories, then runs `launchctl bootout` and `launchctl bootstrap` for each label.

If a plist with the same label already runs another copy's scripts (an older bare skill), it refuses with exit 3 and names that copy. Pass `--takeover` to hand the jobs to the plugin. An unreadable plist blocks the same way.

## Uninstall

```bash
for l in <prefix>-sync <prefix>-watchdog; do
  launchctl bootout gui/$(id -u)/$l; rm -f ~/Library/LaunchAgents/$l.plist
done
rm ~/.local/share/github-board/current
```

## Check

```bash
"$PW/scripts/install-launchd.sh" --check    # exit 1 if the link or a plist is missing, wrong or not loaded
launchctl print gui/$(id -u)/<prefix>-sync
ls -l ~/.local/state/weekly-focus/            # last-success, last-error, alert-* stamps
tail ~/Library/Logs/weekly-focus/{sync,watchdog}.log
```

| What | Where |
|---|---|
| Config | `~/.config/github-board/config.json` (`plan_week`) |
| Cache | `~/.cache/github-board/` (board ids; safe to delete) |
| Link | `~/.local/share/github-board/current` → the plugin |
| Logs | `~/Library/Logs/weekly-focus/{sync,watchdog}.log` and `.err.log` |
| State | `~/.local/state/weekly-focus/` (`last-success` mtime is the heartbeat; `last-error` holds the last failure) |
| Plists | `~/Library/LaunchAgents/<prefix>-{sync,watchdog}.plist` |

Tests override `LAUNCHCTL`, `OSASCRIPT`, `PYTHON`, `GB_PYTHON`, `LA_DIR`, `STATE_DIR`, `LOG_DIR`, `SKILL_DIR`, `GITHUB_BOARD_LINK`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `NOW`.
````

- [ ] **Step 7: Run the tests and the validator**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
```

Expected: PASS; `Result: PASS`.

- [ ] **Step 8: Commit**

```bash
git add plugins/github-board/skills/plan-week plugins/github-board/tests/test_weekly_focus_launchd.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(plan-week): launchd labels from config, stable link, takeover guard (#146)"
```

---

### Task 8: plan-week SKILL.md — init flow, schedule and capacity from `show --json`

**Files:**
- Rewrite: `plugins/github-board/skills/plan-week/SKILL.md`
- Modify: `plugins/github-board/tests/test_weekly_focus_skill_shell.py`

**Interfaces:**
- Consumes: `weekly-focus.py` subcommands `sync`, `show`, `set`, `init`, `config`; `show --json` keys `schedule`, `capacity`, `lanes`, `default_lane`, `config_warnings`; `install-launchd.sh` exit 3.
- Produces: the skill text only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weekly_focus_skill_shell.py`:

```python
KNOWN = {"sync", "show", "set", "init", "config"}


def _text():
    return SKILL.read_text()


def test_every_wf_command_is_a_known_subcommand():
    for cmd in _commands():
        m = re.search(r'"\$WF"\s+(\S+)', cmd)
        assert m and m.group(1) in KNOWN, cmd


def test_no_hard_coded_weekday_table_or_capacity():
    text = _text()
    for stale in ("Today's lane: Mon", "Tue/Wed Product", "Fri Season", "sized for 10-20h",
                  "at most 3 repos"):
        assert stale not in text


def test_schedule_and_capacity_come_from_show_json():
    text = _text()
    for key in ("`schedule`", "`capacity`", "`default_lane`", "`config_warnings`"):
        assert key in text


def test_init_flow_is_present():
    text = _text()
    assert "## Mode: init" in text
    assert 'python3 "$WF" init --from "$CFG_JSON"' in text
    assert 'python3 "$WF" init --force --from "$CFG_JSON"' in text
    assert 'python3 "$WF" config' in text
    assert "Write this to `~/.config/github-board/config.json`?" in text
    assert "gh auth refresh -s read:project,project" in text
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"):
        assert f"**{q}" in text
    assert "--takeover" in text and "never pass `--takeover` unasked" in text
```

(The old `Board: … (<login>)` line goes with the rewrite; Task 11's scan proves no login is left.)

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_weekly_focus_skill_shell.py -q -p no:cacheprovider`
Expected: FAIL — no init mode, weekday table still present.

- [ ] **Step 3: Rewrite SKILL.md**

`plugins/github-board/skills/plan-week/SKILL.md`:

````markdown
---
name: plan-week
description: "Answers what to work on next from the cross-repo Weekly Focus board, plans the week, and sets the board up. Use when: (1) 'what do I work on next' or 'what should I work on', (2) 'what's my focus this week', (3) 'plan my next week' or 'weekly plan', (4) 'weekly focus' or /weekly-focus (the old name of this skill), (5) 'set up plan-week' or 'plan-week init', or a command exits 4 (no config yet)."
metadata:
  version: 2.0.0
---

# Plan Week

Board: the config owner's user project titled `plan_week.board_title`. All logic is in the script; this file only decides what to say.

```bash
WF="${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"   # path only: zsh does not word-split $WF
```

Exit 4 from any command means there is no config yet: run **Mode: init**, then carry on with what the user asked. Exit 2 that names a config key means the config is invalid: show the message and stop.

## Every mode except init

1. `python3 "$WF" sync --json`, with a Bash timeout of 300000 ms (it scans every board). Report changes first, one short line each, only non-empty: started (name the unplanned ones), stopped (cards reset to Todo), `lane_changed` (lanes filled or lifted to a label lane), `stale_in_progress` (name each key and tell the user to move the card back on its `board`), new since Monday, `done_this_week`, and each `config_warnings` entry (a frozen repo or always issue that matches no open issue: suggest fixing the config). If sync fails, say so, show the error, and carry on from `show --json` (it reads the board as it is). Exit 3 means sync skipped itself because the GitHub GraphQL budget is low: say so, carry on from `show --json`. Never fail silently.
2. `python3 "$WF" show --json`. It carries the config's `schedule`, `capacity`, `lanes` and `default_lane`. Use those; never a remembered weekday table.

## Mode: next (default)

Recommend ONE item and up to 2 alternates, each with its `url` and a one-line reason. Only `This week` items.

**Read the right field.** `focus` holds the board lane (`This week` / `Next`); `status` holds Todo / In Progress / Done. Filter on `focus == "This week"`. Filtering on `status` finds no This-week items and yields a wrong "nothing planned" answer.

**Scope to the current repo first.** When the current working directory is a repo with `This week` items (the item's `repo` field), recommend only from that repo's This-week items. The user is asking what to do next *here*. Take the repo name from `git remote get-url origin`, not the directory name: a worktree directory carries a `--<branch>` suffix. Pick the obvious next item using what you know from this session and the repo, not just the board order:

- Finish what is `in_progress` in this repo before starting something new.
- Prefer the item that continues work just shipped or in flight: the next plan slice of an in-progress epic, or a follow-up of something closed today.
- Then order by `priority` (P1 before P2; null last).
- Say in the one-line reason *why* it is next, citing that context (e.g. "Plan C of #368, which is in progress").

Mention other repos in at most one line, and only for an open Security-lane P1 (`Security elsewhere: repo#N — title`). It is never the pick. Leave everything else off unless the user asks for the whole board.

**Board-wide ordering.** Use this when the cwd is not a repo, or the repo has no This-week items (say so first):

1. `in_progress` items (finish before starting). Ignore items that are not `in_progress` for this rule.
2. Security lane, any day.
3. Today's lanes: look up today's weekday (`mon` … `sun`) in `schedule` and prefer items whose `lane` is listed there. When `schedule` is null, or today's list is empty, skip this rule.
4. Within a lane, order by `priority` (P1 before P2; null last).

If nothing is left, say so and suggest the plan mode.

## Mode: focus

Read-only. This week items grouped by Lane with status; done/total for the week (`done_this_week` from sync counts as done); list any `not_current` or `unplanned` items by name.

## Mode: plan

Draft from `show --json`:

- Carry over every unfinished This week item (in-progress ones always).
- Add Security lane Next items.
- Add at most `capacity.max_repos_besides_security` repos besides Security, only from items with `in_current` true. Take lanes in the order `schedule` names them from Monday to Sunday (when `schedule` is null: `default_lane` first, then `lanes` in order), with at most one milestone per lane besides `default_lane`. Size the week to `capacity.hours` (low to high hours).

Show a compact table, then ONE AskUserQuestion: apply / edit / cancel. On apply:

```bash
python3 "$WF" set "This week" repo#N ...     # the picks
python3 "$WF" set Next repo#N ...            # This week items dropped from the plan
python3 "$WF" show
```

## Mode: init

Use when the user asks to set up plan-week, or a command exited 4. Ask with AskUserQuestion, one question at a time. Fetch suggestions first so most answers are a confirmation.

0. `python3 "$WF" config`. Exit 0 prints the current config: pre-fill every answer from it. Exit 4: first run. Then check `gh auth status` lists the `project` scope (sync creates the board and edits its fields). If not, tell the user to run `gh auth refresh -s read:project,project` and stop.
1. **Q1 — account.** Suggest `gh api user --jq .login`. plan-week reads one user's projects, issues and PRs, so offer user accounts only; if the user names an organization, say it is not supported yet.
2. **Q2 — active and frozen repos.** `gh repo list <owner> --no-archived --limit 300 --json name,pushedAt,issues --jq '.[] | [.name, .pushedAt, .issues.totalCount] | @tsv'`. Active = pushed in the last 90 days and has open issues; suggest the rest as `frozen`. Show the split as an editable list. Frozen repos are never synced unless listed in Q7. A repo created later is not frozen.
3. **Q3 — lanes.** Presets: Security / Product / Tooling (default); a single lane; custom names. Security is not a question: it is always the first rule, `{"name": "Security", "labels_containing": ["security"]}`. The lane that gets no repos becomes `default_lane` (Product in the default preset; the only lane in the single-lane preset; the user picks one for custom names).
4. **Q4 — lane repos.** For Tooling (or each custom lane except Security and `default_lane`): which active repos belong to it? Suggest none. Unassigned repos go to `default_lane`.
5. **Q5 — fixed days.** Presets: no fixed days (`"schedule": null`, default); Mon Security, Tue-Wed Product, Thu Tooling, Fri releases (`{"mon": ["Security"], "tue": ["Product"], "wed": ["Product"], "thu": ["Tooling"], "fri": [], "sat": [], "sun": []}`); custom (every lane named must be one of the lanes).
6. **Q6 — capacity.** Default `{"max_repos_besides_security": 3, "hours": [10, 20]}`.
7. **Q7 — always include.** Issues as `repo#N` to include even from frozen repos. Default none.
8. **Q8 — background sync.** Ask only when `uname -s` prints `Darwin`; elsewhere write `"enabled": false`. Default `{"enabled": true, "times": ["07:00", "18:00"], "label_prefix": "dev.github-board.plan-week"}`.

Board title: ask only when `gh project list --owner <owner> --format json --jq '.projects[] | select(.closed == false) | .title'` already lists "Weekly Focus" — reuse that board, or pick another title. Otherwise use "Weekly Focus".

Build `{"owner": …, "plan_week": {"board_title", "lanes", "default_lane", "schedule", "frozen", "always", "capacity", "launchd"}}`, show it, and ask once: "Write this to `~/.config/github-board/config.json`?" On yes, put the JSON in a temp file (`CFG_JSON=$(mktemp)`, then write it there) and run:

```bash
python3 "$WF" init --from "$CFG_JSON"            # first run
python3 "$WF" init --force --from "$CFG_JSON"    # a config exists and the user confirmed the change
```

Exit 3: a different `plan_week` (or owner) is already there and `--force` was not passed. Exit 2 names the bad key: fix that answer and ask again.

When `launchd.enabled` is true, offer to run `"${CLAUDE_SKILL_DIR}/scripts/install-launchd.sh"`. Exit 3 means another copy (an older bare `/weekly-focus` skill) owns the jobs: say so and point at the plugin README's hand-over steps; never pass `--takeover` unasked.

## Rules

- This week takes work from the repo's current milestone only.
- Security may jump ahead; move that issue into the current milestone.
- Unplanned in-progress work is shown, never hidden or demoted.
- Frozen repos stay off unless work is in progress.

## Scheduling

launchd runs `sync` at `plan_week.launchd.times`; an hourly watchdog alerts if it goes stale. `"${CLAUDE_SKILL_DIR}/scripts/install-launchd.sh" --check` verifies the link, the plists and that both jobs are loaded. Logs: `~/Library/Logs/weekly-focus/`. See README.md.
````

Note: every mention of `$WF` in this file is a complete, runnable `python3 "$WF" …` command, because the shell test runs each one.

- [ ] **Step 4: Run the tests and the validator**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
```

Expected: PASS; `Result: PASS`.

- [ ] **Step 5: Commit**

```bash
git add plugins/github-board/skills/plan-week/SKILL.md plugins/github-board/tests/test_weekly_focus_skill_shell.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(plan-week): init question flow; schedule and capacity from show --json (#146)"
```

---

### Task 9: create-board — template from the config, `init`, no hard-coded owner

**Files:**
- Create: `plugins/github-board/skills/create-board/scripts/init-config.sh`
- Modify: `plugins/github-board/skills/create-board/scripts/audit-board.sh`, `plugins/github-board/skills/create-board/SKILL.md`, `plugins/github-board/agents/template-inspector.md`
- Create: `plugins/github-board/tests/test_create_board_config.py`

**Interfaces:**
- Consumes: `lib/config.sh` (`gb_config_get`, `GB_PYTHON`, `GB_LIB_DIR`), `config.py init --require create_board`, `config.py show`.
- Produces: `init-config.sh [--force] < payload` (exit 0/2/3) and `init-config.sh --show` (exit 0/4); `audit-board.sh` defaults `--template-owner`/`--template` from `create_board.*` (flags win; neither → exit 2 naming `create-board init`).

- [ ] **Step 1: Write the failing tests**

`plugins/github-board/tests/test_create_board_config.py`:

```python
"""create-board takes its template from the config; nothing names the author's board (#146)."""
import json
import os
import subprocess
import sys

from gbtest import SKILLS_DIR, TEST_CFG, cfg_copy, gh_calls, install_fake_gh, load_lib, write_config

SCRIPTS = SKILLS_DIR / "create-board" / "scripts"
PLUGIN = SKILLS_DIR.parent


def run(tmp_path, script, *args, stdin=None):
    log = tmp_path / "gh.log"
    env = dict(os.environ, GB_PYTHON=sys.executable, **install_fake_gh(tmp_path / "bin", [], log))
    r = subprocess.run(["bash", str(SCRIPTS / script), *args], input=stdin, env=env,
                       capture_output=True, text=True, timeout=60)
    return r, gh_calls(log)


def test_audit_without_config_or_flags_asks_for_init(tmp_path):
    r, calls = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2 and "create-board init" in r.stderr
    assert calls == []


def test_audit_reads_the_template_from_the_config(tmp_path, gb_config):
    r, _ = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2           # the fake gh fails the snapshot
    assert "Could not snapshot template octo-user/31" in r.stderr


def test_audit_flags_win_over_the_config(tmp_path, gb_config):
    r, _ = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all",
               "--template-owner", "other-owner", "--template", "7")
    assert "Could not snapshot template other-owner/7" in r.stderr


def test_audit_with_config_but_no_create_board_section_asks_for_init(tmp_path):
    c = cfg_copy(); del c["create_board"]
    write_config(tmp_path / "xdg-config", c)
    r, calls = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2 and "create-board init" in r.stderr and calls == []


def test_init_config_adds_the_section_to_a_plan_week_config(tmp_path):
    c = cfg_copy(); del c["create_board"]
    path = write_config(tmp_path / "xdg-config", c)
    r, calls = run(tmp_path, "init-config.sh",
                   stdin=json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}}))
    assert r.returncode == 0, r.stderr
    written = json.loads(path.read_text())
    assert written["create_board"] == {"template_owner": "octo-org", "template_number": 4}
    assert written["plan_week"] == TEST_CFG["plan_week"] and calls == []


def test_init_config_refuses_a_different_template_without_force(tmp_path, gb_config):
    new = json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}})
    r, _ = run(tmp_path, "init-config.sh", stdin=new)
    assert r.returncode == 3
    r, _ = run(tmp_path, "init-config.sh", "--force", stdin=new)
    assert r.returncode == 0


def test_init_config_first_run_needs_an_owner(tmp_path):
    body = {"create_board": {"template_owner": "octo-org", "template_number": 4}}
    r, _ = run(tmp_path, "init-config.sh", stdin=json.dumps(body))
    assert r.returncode == 2 and "missing required key owner" in r.stderr
    body["owner"] = "octo-user"
    r, _ = run(tmp_path, "init-config.sh", stdin=json.dumps(body))
    assert r.returncode == 0
    assert load_lib().load(require=("create_board",))["create_board"]["template_number"] == 4


def test_init_config_show(tmp_path, gb_config):
    r, _ = run(tmp_path, "init-config.sh", "--show")
    assert r.returncode == 0 and json.loads(r.stdout) == TEST_CFG


def test_init_config_show_without_config_exits_4(tmp_path):
    assert run(tmp_path, "init-config.sh", "--show")[0].returncode == 4


def test_init_config_help_and_bad_argument(tmp_path):
    assert run(tmp_path, "init-config.sh", "--help")[0].returncode == 0
    assert run(tmp_path, "init-config.sh", "--nope")[0].returncode == 2


def test_skill_and_agents_name_no_default_template():
    text = (SKILLS_DIR / "create-board" / "SKILL.md").read_text()
    assert "#31" not in text and "`31`" not in text
    assert "## Mode: init" in text and "init-config.sh" in text
    inspector = (PLUGIN / "agents" / "template-inspector.md").read_text()
    assert "(default `" not in inspector
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_create_board_config.py -q -p no:cacheprovider`
Expected: FAIL — `init-config.sh` missing; audit uses the built-in template.

- [ ] **Step 3: `init-config.sh`**

`plugins/github-board/skills/create-board/scripts/init-config.sh`:

```bash
#!/usr/bin/env bash
# Write (or show) the create_board section of the github-board config.
#   init-config.sh --show            print the current config (exit 4 when there is none)
#   init-config.sh [--force] < payload.json
#     payload: {"create_board": {"template_owner": "<login>", "template_number": <n>}}
#     plus "owner": "<login>" when there is no config yet.
# Exit codes: 0 written or shown; 2 invalid payload (names the key); 3 a different create_board
# (or owner) is already there and --force was not passed; 4 no config (--show only).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"

force=()
case "${1:-}" in
  -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
  --show) exec "$GB_PYTHON" "$GB_LIB_DIR/config.py" show ;;
  --force) force=(--force) ;;
  "") ;;
  *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac
exec "$GB_PYTHON" "$GB_LIB_DIR/config.py" init --require create_board ${force[@]+"${force[@]}"}
```

`chmod +x plugins/github-board/skills/create-board/scripts/init-config.sh`.

- [ ] **Step 4: `audit-board.sh`**

Replace lines 17-18:

```bash
TEMPLATE_OWNER="abhattacherjee"
TEMPLATE_NUMBER="31"
```

with:

```bash
TEMPLATE_OWNER=""      # --template-owner, else create_board.template_owner in the config
TEMPLATE_NUMBER=""     # --template, else create_board.template_number
```

In `usage()`, replace the two flag lines with:

```
  --template-owner <login> Template owner. Default: create_board.template_owner in the
                           github-board config (create-board init writes it).
  --template <n>           Template project number. Default: create_board.template_number.
```

After the `--all`/`--number` validation (just before `HERE="$(dirname "$0")"`), add:

```bash
# Flags win; otherwise the template comes from the github-board config.
if [ -z "$TEMPLATE_OWNER" ] || [ -z "$TEMPLATE_NUMBER" ]; then
  . "$(dirname "$0")/../../../lib/config.sh"
  if cfg_owner="$(gb_config_get create_board.template_owner)" \
     && cfg_number="$(gb_config_get create_board.template_number)"; then
    TEMPLATE_OWNER="${TEMPLATE_OWNER:-$cfg_owner}"
    TEMPLATE_NUMBER="${TEMPLATE_NUMBER:-$cfg_number}"
  else
    echo "No template board: pass --template-owner <login> --template <n>, or run create-board init." >&2
    exit 2
  fi
fi
```

- [ ] **Step 5: SKILL.md**

In `plugins/github-board/skills/create-board/SKILL.md`:

5a. Replace the Quick Check code block with:

```bash
"${CLAUDE_SKILL_DIR}/scripts/init-config.sh" --show                              # the configured template
"${CLAUDE_SKILL_DIR}/scripts/inspect-template.sh" --owner <template-owner> --number <n>   # snapshot it
"${CLAUDE_SKILL_DIR}/scripts/audit-board.sh" --owner <login> --all               # drift sweep, read-only
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" full                              # task list for creation
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" audit                             # task list for the audit
```

5b. In the Inputs table, the two default cells become: `--template <num>` → `` `create_board.template_number` from the config ``; `--template-owner <login>` → `` `create_board.template_owner` from the config ``.

5c. Replace the heading `## The template (project #31, "TEMPLATE — Standard Repo Board")` with `## The template`, and add as its first line: ``The template is the board `create_board` in the github-board config names. The layout this skill expects of it:``. Replace `The option descriptions match the Git Flow rules in \`~/.claude/CLAUDE.md\`:` with `The option descriptions follow Git Flow:`. Replace the last sentence of the `markProjectV2AsTemplate` paragraph, which spans two lines (`It is a template by convention and by its \`#31\`` / `default here; copying does not need the badge.`), with `It is a template by convention; copying does not need the badge.`

5d. In `### Phase 0 — Validate`, add as the first bullet: ``- Resolve the template: `--template-owner`/`--template` win; else `init-config.sh --show` → `create_board`; else run **Mode: init** first.``

5e. Add before `## Sub-Agent Registry`:

````markdown
## Mode: init

One question: which existing board should new boards copy? Suggest from
`gh project list --owner <login> --format json --jq '.projects[] | select(.closed == false) | "\(.number)\t\(.title)"'`
for the logged-in user (`gh api user --jq .login`) and each of their orgs (`gh api user/orgs --jq '.[].login'`).
Default: none — then ask again the first time a board is created.

Show the result and ask once: "Write this to `~/.config/github-board/config.json`?" On yes:

```bash
"${CLAUDE_SKILL_DIR}/scripts/init-config.sh" < "$CFG_JSON"           # {"create_board": {...}}
"${CLAUDE_SKILL_DIR}/scripts/init-config.sh" --force < "$CFG_JSON"   # replacing a different template
```

Add `"owner": "<login>"` to the payload only when `init-config.sh --show` exits 4 (no config yet).
Exit 3: a different template is configured; ask before passing `--force`.
````

- [ ] **Step 6: Agent defaults**

In `plugins/github-board/agents/template-inspector.md`, replace the two input lines with:

```markdown
- `owner`: template project owner login (the orchestrator passes the flag or `create_board.template_owner`)
- `number`: template project number (the flag or `create_board.template_number`)
```

- [ ] **Step 7: Run the tests and the validator**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
```

Expected: PASS; `Result: PASS`.

- [ ] **Step 8: Commit**

```bash
git add plugins/github-board/skills/create-board plugins/github-board/agents/template-inspector.md \
  plugins/github-board/tests/test_create_board_config.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(create-board): template from the config, init, no built-in owner (#146)"
```

---

### Task 10: promote-shipped and move-card — cached board discovery, generic examples

**Files:**
- Modify: `plugins/github-board/skills/promote-shipped/scripts/discover-boards.sh`, `inventory-board.sh`, `SKILL.md`, `references/projects-v2-graphql-snippets.md`, `CHANGELOG.md`
- Modify: `plugins/github-board/skills/move-card/scripts/board-move.sh`, `SKILL.md`, `CHANGELOG.md`
- Create: `plugins/github-board/tests/test_board_cache.py`

**Interfaces:**
- Consumes: `gb_cache_get`, `gb_cache_put`, `gb_cache_drop`, `gb_cache_drop_containing`, `GB_NO_CACHE`, `GB_CACHE_REFRESH`.
- Produces: `discover-boards.sh <owner> <repo> [--json] [--no-cache]`, cache key `promote-boards-<owner>-<repo>` (the `{owner, repo, boards}` object; not cached when `boards` is empty). `inventory-board.sh` drops every entry naming a board id that did not resolve and says to re-run discovery. `board-move.sh … [--no-cache]`, cache keys `move-boards-<owner>-<name>` (open boards array) and `move-status-<owner>-<name>-<project>` (`{pid, field}`); on a stale-id GraphQL error with cached ids it drops both and re-runs itself once with `GB_CACHE_REFRESH=1`.

- [ ] **Step 1: Write the failing tests**

`plugins/github-board/tests/test_board_cache.py`:

```python
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
    load_lib().cache_put("promote-boards-octo-user-app",
                         {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, title="Old")]},
                         now=time.time() - 8 * 86400)
    r, calls = run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]), "octo-user", "app", "--json")
    assert len(graphql_calls(calls)) == 1 and json.loads(r.stdout)["boards"][0]["title"] == "Board"


def test_discover_no_cache_never_reads_or_writes(tmp_path):
    gbc = load_lib()
    gbc.cache_put("promote-boards-octo-user-app",
                  {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, title="Cached")]})
    r, calls = run(tmp_path, PROMOTE / "discover-boards.sh", discover_routes([BOARD]),
                   "octo-user", "app", "--json", "--no-cache")
    assert json.loads(r.stdout)["boards"][0]["title"] == "Board"
    assert gbc.cache_get("promote-boards-octo-user-app")["boards"][0]["title"] == "Cached"


# ---- inventory-board.sh -----------------------------------------------------------

def test_inventory_drops_a_cached_board_list_naming_a_stale_id(tmp_path):
    gbc = load_lib()
    gbc.cache_put("promote-boards-octo-user-app",
                  {"owner": "octo-user", "repo": "app", "boards": [dict(BOARD, id="PVT_gone")]})
    gone = {"data": {"node": None}, "errors": [{"type": "NOT_FOUND",
            "message": "Could not resolve to a node with the global id of 'PVT_gone'"}]}
    r, _ = run(tmp_path, PROMOTE / "inventory-board.sh", [AUTH, {"match": ["api", "graphql"], "stdout": json.dumps(gone)}],
               "--board-id", "PVT_gone")
    assert r.returncode == 4
    assert "re-run discover-boards.sh" in r.stderr
    assert gbc.cache_get("promote-boards-octo-user-app") is None


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
    gbc.cache_put("move-boards-octo-user-app", [{"number": 7, "title": "Board", "closed": False}])
    gbc.cache_put("move-status-octo-user-app-7", {"pid": "PVT_old", "field": FIELD})
    return gbc


def test_board_move_refetches_once_after_a_stale_id(tmp_path):
    gbc = _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS)
    assert r.returncode == 0, r.stderr
    assert "look stale" in r.stderr and 'Moved issue #5 -> "In Progress"' in r.stdout
    assert len(updates(calls)) == 2
    assert gbc.cache_get("move-status-octo-user-app-7")["pid"] == "PVT_new"


def test_board_move_does_not_loop_when_the_refetch_also_fails(tmp_path):
    _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(new_pid_fails=True), *ARGS)
    assert r.returncode == 1 and len(updates(calls)) == 2


def test_board_move_no_cache_never_reads_or_writes(tmp_path):
    gbc = _seed_stale()
    r, calls = run(tmp_path, MOVE, move_routes(), *ARGS, "--no-cache")
    assert r.returncode == 0 and len(updates(calls)) == 1
    assert gbc.cache_get("move-status-octo-user-app-7")["pid"] == "PVT_old"
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest plugins/github-board/tests/test_board_cache.py -q -p no:cacheprovider`
Expected: FAIL — no caching; `--no-cache` unknown to `board-move.sh`.

- [ ] **Step 3: `discover-boards.sh`**

- Header comment: change the usage lines to `#   discover-boards.sh <owner> <repo> [--json] [--no-cache]` and add `# The board list is cached for 7 days (~/.cache/github-board); --no-cache skips the cache.`
- `usage()`: change the first line to `Usage: discover-boards.sh <owner> <repo> [--json] [--no-cache]`, and the two example lines to:

```
  discover-boards.sh OWNER REPO
  discover-boards.sh OWNER REPO --json | jq
```

- Replace the argument handling (`OWNER="$1"` … `[ "${3:-}" = "--json" ] && JSON_MODE="true"`) with:

```bash
OWNER="$1"
REPO="$2"
shift 2
JSON_MODE="false"
for arg in "$@"; do
  case "$arg" in
    --json) JSON_MODE="true" ;;
    --no-cache) export GB_NO_CACHE=1 ;;
  esac
done
. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"
```

- Replace the block from `QUERY='query(…` through the `BOARDS=$(echo "$RESPONSE" | jq …)` assignment with the same code wrapped in a cache lookup (keep `QUERY` and the `jq` projection text exactly as they are):

```bash
CACHE_KEY="promote-boards-$OWNER-$REPO"
if ! BOARDS=$(gb_cache_get "$CACHE_KEY"); then
  QUERY='query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    projectsV2(first:50) {
      nodes { id title number url closed }
    }
  }
}'
  # -f (not -F): owner/name are String!. -F does type inference, so an all-numeric
  # owner or repo name would be sent as an Int and rejected by the schema.
  RESPONSE=$(gh api graphql -f query="$QUERY" -f owner="$OWNER" -f name="$REPO" 2>&1) || {
    echo "ERROR: GraphQL query failed:" >&2
    echo "$RESPONSE" >&2
    exit 4
  }
  BOARDS=$(echo "$RESPONSE" | jq '{
  owner: "'"$OWNER"'",
  repo: "'"$REPO"'",
  boards: [
    .data.repository.projectsV2.nodes[]
    | select(.closed == false)
    | {id, number, title, url}
  ]
}')
  # An empty list is never cached, so a board linked later shows up at once.
  if [ "$(echo "$BOARDS" | jq '.boards | length')" -gt 0 ]; then
    printf '%s' "$BOARDS" | gb_cache_put "$CACHE_KEY"
  fi
fi
```

The scope preflight stays above this block, so a token without the scope fails even on a cache hit.

- [ ] **Step 4: `inventory-board.sh`**

After `set -eu`, add `. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"`. In the `META=$(…) || { … }` failure block, before `exit 4`, add:

```bash
  if echo "$META" | grep -Eq 'Could not resolve to (a|an) [A-Za-z0-9]+ with|NOT_FOUND'; then
    gb_cache_drop_containing "$BOARD_ID"
    echo "       Dropped any cached board list naming this id; re-run discover-boards.sh to refetch." >&2
  fi
```

In the `did not resolve to a ProjectV2 node` block, before its `exit 4`, add:

```bash
  gb_cache_drop_containing "$BOARD_ID"
  echo "       Dropped any cached board list naming this id; re-run discover-boards.sh to refetch." >&2
```

- [ ] **Step 5: `board-move.sh`**

5a. After `set -euo pipefail` add:

```bash
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../../lib/config.sh"
ORIG_ARGS=("$@")
STALE_RE='Could not resolve to (a|an) [A-Za-z0-9]+ with|NOT_FOUND'
CACHE_USED=0
```

5b. In `usage()`: add the option line `  --no-cache          Skip the 7-day board/Status cache (~/.cache/github-board).` under `--dry-run`, and change the example `board-move.sh --issue 9 --to done --repo abhattacherjee/foo --project 7` to `board-move.sh --issue 9 --to done --repo OWNER/REPO --project 7`. Change the header comment line `# Mid-lifecycle companion to promote-shipped (which only does release -> Done).` to keep it as Task 1 left it, and add below the comment block: `# Board and Status lookups are cached for 7 days; a stale id triggers one automatic refetch.`

5c. In the argument loop add `    --no-cache) export GB_NO_CACHE=1; shift;;` before `-h|--help`.

5d. After `gql() { … }`, add:

```bash
# refetch_once <error text>: when cached ids look stale, drop them and re-run once without reading the cache.
refetch_once() {
  if [[ "$CACHE_USED" == 1 && -z "${GB_CACHE_REFRESH:-}" ]] && grep -Eq "$STALE_RE" <<<"$1"; then
    echo "Cached board ids for $REPO look stale; refetching once." >&2
    gb_cache_drop "$BOARDS_KEY"
    gb_cache_drop "$STATUS_KEY"
    GB_CACHE_REFRESH=1 exec bash "${BASH_SOURCE[0]}" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
  fi
}
```

5e. Replace the `# discover board` block and the `PID=…` / `FIELD_JSON=…` lookups (old lines 88-111) with:

```bash
BOARDS_KEY="move-boards-$OWNER-$NAME"
# discover board (cached; an empty list is never cached)
if [[ -z "$PROJECT" ]]; then
  if BOARDS=$(gb_cache_get "$BOARDS_KEY"); then
    CACHE_USED=1
  else
    BOARDS=$(gql 'query($o:String!,$n:String!){repository(owner:$o,name:$n){projectsV2(first:100){nodes{number title closed}}}}' \
      -F o="$OWNER" -F n="$NAME" --jq '[.data.repository.projectsV2.nodes[]|select(.closed==false)]')
    if [[ "$(echo "$BOARDS" | jq 'length')" -ge 1 ]]; then printf '%s' "$BOARDS" | gb_cache_put "$BOARDS_KEY"; fi
  fi
  COUNT=$(echo "$BOARDS" | jq 'length')
  [[ "$COUNT" -ge 1 ]] || die "no open Project (v2) board linked to $REPO."
  if [[ "$COUNT" -gt 1 ]]; then
    echo "Multiple boards linked to $REPO — pass --project <number>:" >&2
    echo "$BOARDS" | jq -r '.[]|"  #\(.number) \(.title)"' >&2
    exit 1
  fi
  PROJECT=$(echo "$BOARDS" | jq -r '.[0].number')
fi
[[ "$PROJECT" =~ ^[0-9]+$ ]] || die "--project must be a number (got: $PROJECT)."

STATUS_KEY="move-status-$OWNER-$NAME-$PROJECT"
if CACHED=$(gb_cache_get "$STATUS_KEY"); then
  CACHE_USED=1
  PID=$(echo "$CACHED" | jq -r '.pid')
  FIELD_JSON=$(echo "$CACHED" | jq -c '.field')
else
  PID=$(gql 'query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){projectV2(number:$p){id}}}' \
    -F o="$OWNER" -F n="$NAME" -F p="$PROJECT" --jq '.data.repository.projectV2.id // empty')
  [[ -n "$PID" ]] || die "board #$PROJECT not found on $REPO."
  # Status field + options (exact 'Status', else first single-select named like status)
  FIELD_JSON=$(gql 'query($id:ID!){node(id:$id){... on ProjectV2{fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}' \
    -F id="$PID" --jq '.data.node.fields.nodes | map(select(.id!=null)) | (map(select((.name//"")|ascii_downcase=="status"))[0]) // empty')
  [[ -n "$FIELD_JSON" ]] || die "no single-select 'Status' field on board #$PROJECT."
  jq -cn --arg pid "$PID" --argjson field "$FIELD_JSON" '{pid: $pid, field: $field}' | gb_cache_put "$STATUS_KEY"
fi
FID=$(echo "$FIELD_JSON" | jq -r '.id')
```

5f. Replace the add-mutation lines (`IID=$(gql 'mutation…addProjectV2ItemById…') ` and its `[[ -n "$IID" ]] || die …`) with:

```bash
  if ! IID=$(gql 'mutation($pid:ID!,$cid:ID!){addProjectV2ItemById(input:{projectId:$pid,contentId:$cid}){item{id}}}' \
    -F pid="$PID" -F cid="$CONTENT_ID" --jq '.data.addProjectV2ItemById.item.id // empty' 2>&1); then
    refetch_once "$IID"
    die "failed to add $KIND #$NUM to board #$PROJECT: $IID"
  fi
  [[ -n "$IID" ]] || die "failed to add $KIND #$NUM to board #$PROJECT."
```

5g. Replace the final update-mutation statement (the `gql 'mutation…updateProjectV2ItemFieldValue…' … && echo "Moved …"`) with:

```bash
if ! OUT=$(gql 'mutation($pid:ID!,$iid:ID!,$fid:ID!,$oid:String!){updateProjectV2ItemFieldValue(input:{projectId:$pid,itemId:$iid,fieldId:$fid,value:{singleSelectOptionId:$oid}}){projectV2Item{id}}}' \
  -F pid="$PID" -F iid="$IID" -F fid="$FID" -f oid="$OID" --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id' 2>&1); then
  refetch_once "$OUT"
  die "move failed: $OUT"
fi
echo "Moved $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT."
```

- [ ] **Step 6: Docs and examples**

- `promote-shipped/references/projects-v2-graphql-snippets.md` lines 29 and 182: replace `-f owner=abhattacherjee -f name=tiny-vacation-agent` with `-f owner=OWNER -f name=REPO`.
- `promote-shipped/SKILL.md`, at the end of `### Phase 1 — Discover boards`, add: ``The board list is cached for 7 days (`--no-cache` skips it). If Phase 2 exits 4 saying the board id did not resolve, `inventory-board.sh` has dropped the cached list: re-run Phase 1 once.``
- `move-card/SKILL.md`, in `## Key facts`, add: ``- **Lookups are cached** for 7 days under `~/.cache/github-board/` (board list and Status options). A stale id triggers one automatic refetch; `--no-cache` skips the cache.``
- Add to each skill's `## [2.0.0] - 2026-10-02` CHANGELOG entry (from Task 1), under a `### Added` heading: promote-shipped — ``- `discover-boards.sh` caches the repo's board list for 7 days (`--no-cache` skips it). `inventory-board.sh` drops the cached list when a board id no longer resolves.``; move-card — ``- `board-move.sh` caches the board list and Status options for 7 days and refetches once when a cached id is stale. `--no-cache` skips the cache.``

- [ ] **Step 7: Run all tests and the validator**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
scripts/validate-plugin.sh plugins/github-board
```

Expected: PASS (including the five moved promote tests); `Result: PASS`.

- [ ] **Step 8: Commit**

```bash
git add plugins/github-board/skills/promote-shipped plugins/github-board/skills/move-card \
  plugins/github-board/tests/test_board_cache.py
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "feat(github-board): cached board discovery for promote-shipped and move-card (#146)"
```

---

### Task 11: No personal values; clean-HOME smoke test; CI job

**Files:**
- Create: `plugins/github-board/tests/test_no_personal_values.py`, `plugins/github-board/tests/smoke-clean-home.sh`
- Modify: `plugins/github-board/skills/plan-milestones/references/triage-criteria.md`, `plugins/github-board/skills/prune-branches/SKILL.md`
- Modify: `.github/workflows/validate-skill.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: `tests/smoke-clean-home.sh [--help]` (exit 0 when all three commands exit 0); CI job `github-board-tests`.

- [ ] **Step 1: Write the failing test**

`plugins/github-board/tests/test_no_personal_values.py`:

```python
"""No file in the plugin carries the author's own values (#146).

The forbidden tokens are stored as SHA-256 hashes so this file does not carry them either:
the author's GitHub login and every repo name in the pre-#146 FROZEN, ALWAYS, TOOLING and
SEASON constants of weekly-focus.py (19 tokens). Text is split into tokens on anything but
letters, digits and '-', lowercased, and hashed. `com.<login>.weekly-focus-sync` splits into
com / <login> / weekly-focus-sync, so the login hash catches the old launchd label too.
To check a candidate token: printf '%s' TOKEN | shasum -a 256
"""
import hashlib
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
FORBIDDEN = {
    "3268eeadb560d946d44fbe0ab8126795a0acd406e88a96261f9a930fbdc804d5",
    "cf8ecb2554470e7885282f67c586b27f1df77fd7dbc9cb520a4ed2da2d647f4d",
    "42ef2bf0562d528872334ccc1fe7b8fb5cec1628cd0955c2ebbd64349a57d3e2",
    "2b3d3623a09ba50b31a21db0aa31cb428d0c349a1c48b7df06b665c383d9905b",
    "375c078cd4b9b56abbaa02662a6a61b995d3651313e2336ff9aff3358d38ed3a",
    "ca272ae82d4c3c15b2ebab0ffb3b84a655224e1dc6bd27dd92a600c39db87608",
    "b0019ef18d89eaa86c7cebe680bc5cd820d4cd2a5ac233006c09b0ba7415b89b",
    "c49fac153a2d8a398dd22a32f67d816b1b1b4a8d9d4bae31d45d51ed50950612",
    "60b1037df992cde7cfa185303c86ff57c9d4067bfbf91e3b1f03b77a9fc94e20",
    "2efb9a597ae3c6ddc0e42a1082adae0893afcea4fbea91614f2fc51591904f69",
    "c00b8ce02147ec5f4536f565b41aab684a9a19865e07b3f922a0c90958b83350",
    "d652a40d10ca6e006b99e14e87addbded972f9d9b682c2b6959f97fc251b5af9",
    "01d1abd1891e9a89a193bdf7480b6bc65f81ef504e4c7569830ecc26184279d7",
    "ce64ec554e787e4ed335d742b30ff91e34786487043a9c21f94f15beddad4f31",
    "f955878785dd3ad4c856503c237567f02958a93a0b2225689194b0bf4e72b86a",
    "d5a28a15bc08bd019e4cca2a597e98384d6eecf3fc2f06dc3865c4afed8b1bff",
    "5829e8b56eca724d0378c75a2c04f31b31e52c0bf431ef720b5ed1bf90f08e6c",
    "b10f516ccef95b68f9c8b037d64592b437224873f2d6db81b2287e25fb2b8cb8",
    "a8b08ea6b01909f459c2d9e4d7381a046887894e83acd64dfa7c18077c42ae90",
}
# The plugin's root README.md may name the marketplace repo and the four repos whose callers
# move in follow-up PRs (the migration runbook). Nothing else may.
README_ALLOWED = {
    "01d1abd1891e9a89a193bdf7480b6bc65f81ef504e4c7569830ecc26184279d7",
    "c00b8ce02147ec5f4536f565b41aab684a9a19865e07b3f922a0c90958b83350",
    "d5a28a15bc08bd019e4cca2a597e98384d6eecf3fc2f06dc3865c4afed8b1bff",
    "d652a40d10ca6e006b99e14e87addbded972f9d9b682c2b6959f97fc251b5af9",
    "5829e8b56eca724d0378c75a2c04f31b31e52c0bf431ef720b5ed1bf90f08e6c",
}
TOKEN = re.compile(r"[A-Za-z0-9-]+")
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def _h(token: str) -> str:
    return hashlib.sha256(token.lower().encode()).hexdigest()


def hits_in(text: str, forbidden: set, allowed: set = frozenset()) -> list:
    """Line numbers (1-based) of lines carrying a forbidden, non-allowed token."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(_h(t) in forbidden and _h(t) not in allowed for t in TOKEN.findall(line)):
            out.append(i)
    return out


def _files():
    for p in sorted(PLUGIN.rglob("*")):
        rel = p.relative_to(PLUGIN)
        if p.is_file() and not SKIP_PARTS & set(rel.parts) and p.name != "CHANGELOG.md":
            yield p, rel


def test_hash_lists_are_well_formed():
    assert len(FORBIDDEN) == 19 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in FORBIDDEN)
    assert README_ALLOWED <= FORBIDDEN and len(README_ALLOWED) == 5


def test_the_scan_catches_a_planted_token_and_respects_the_allow_list():
    planted = {_h("planted-value")}
    assert hits_in("a\nx planted-value y\n", planted) == [2]
    assert hits_in("x Planted-Value.git\n", planted) == [1]
    assert hits_in("x planted-value-longer\n", planted) == []
    assert hits_in("x planted-value\n", planted, planted) == []


def test_no_personal_values_in_file_contents():
    bad = []
    for p, rel in _files():
        allowed = README_ALLOWED if rel == Path("README.md") else set()
        bad += [f"{rel}:{i}" for i in hits_in(p.read_text(errors="replace"), FORBIDDEN, allowed)]
    assert bad == [], "personal values found; genericize them:\n" + "\n".join(bad)


def test_no_personal_values_in_file_names():
    assert [str(rel) for _, rel in _files() if hits_in(str(rel), FORBIDDEN)] == []
```

- [ ] **Step 2: Run it to see what is left**

Run: `python3 -m pytest plugins/github-board/tests/test_no_personal_values.py -q -p no:cacheprovider`
Expected: FAIL listing `skills/plan-milestones/references/triage-criteria.md:8`, `:72` and `skills/prune-branches/SKILL.md:68` (Tasks 1-10 cleaned every other file). If anything else is listed, genericize it the same way.

- [ ] **Step 3: Genericize the residue**

- `plan-milestones/references/triage-criteria.md` line 8: `- [Worked example: an app's v3.6 → v3.7](#worked-example-an-apps-v36--v37)`; line 72: `## Worked example: an app's v3.6 → v3.7`.
- `prune-branches/SKILL.md` line 68: replace `Verified 2026-06-03 on obsidian-brain:` with `Verified 2026-06-03 on a real repo:`.

Run the test again. Expected: PASS.

- [ ] **Step 4: The clean-HOME smoke script**

`plugins/github-board/tests/smoke-clean-home.sh`:

```bash
#!/usr/bin/env bash
# Clean-HOME smoke test for the github-board plugin (#146). HOME is an empty temp dir and the
# environment is cleared, so no command can fall back to an installed copy under ~/.claude.
# Usage: smoke-clean-home.sh [--help]. Exit 0 when every command exits 0, else 1.
set -uo pipefail
case "${1:-}" in
  -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac
PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME"' EXIT
fail=0

run() { # run <label> <command...>
  local label="$1" out rc
  shift
  out="$(env -i PATH="$PATH" HOME="$TMP_HOME" "$@" 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "ok   $label"
  else
    echo "FAIL $label (exit $rc)"
    printf '%s\n' "$out" | head -5
    fail=1
  fi
}

run "plan-milestones milestone-report.sh --help" bash "$PLUGIN/skills/plan-milestones/scripts/milestone-report.sh" --help
run "plan-week weekly-focus.py --help" python3 "$PLUGIN/skills/plan-week/scripts/weekly-focus.py" --help
run "create-board task-manifest.sh" bash "$PLUGIN/skills/create-board/scripts/task-manifest.sh"
exit "$fail"
```

`chmod +x plugins/github-board/tests/smoke-clean-home.sh`, then run it: `bash plugins/github-board/tests/smoke-clean-home.sh`. Expected: three `ok` lines, exit 0. Perturb once to prove it can fail: `bash -c 'sed "s#--help\$#--bogus#" plugins/github-board/tests/smoke-clean-home.sh > "$TMPDIR/smoke.sh"; bash "$TMPDIR/smoke.sh"; echo rc=$?'` must print a `FAIL` line and `rc=1` (weekly-focus.py exits 2 on an unknown command). Do not commit the perturbed copy.

- [ ] **Step 5: CI job**

Append to `.github/workflows/validate-skill.yml` (same indentation as `adversarial-review-tests`):

```yaml
  github-board-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # 3.9 is the oldest Python the plugin supports (standard library only).
      - name: Set up Python 3.9
        uses: actions/setup-python@v5
        with:
          python-version: "3.9"

      - name: Install pytest
        run: python -m pip install pytest

      # Unconditional, like the jobs above: lib/ and tests/ are outside the skill
      # filters, and a change anywhere in the plugin can break a moved test.
      - name: Run github-board test suite
        run: python -m pytest plugins/github-board/tests -q -p no:cacheprovider

      - name: Clean-HOME smoke test
        run: bash plugins/github-board/tests/smoke-clean-home.sh
```

Check the YAML parses: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/validate-skill.yml'))"` (if PyYAML is missing, `ruby -ryaml -e 'YAML.load_file(".github/workflows/validate-skill.yml")'`).

- [ ] **Step 6: Run everything**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
bash plugins/github-board/tests/smoke-clean-home.sh
scripts/validate-plugin.sh plugins/github-board
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add plugins/github-board/tests/test_no_personal_values.py plugins/github-board/tests/smoke-clean-home.sh \
  plugins/github-board/skills/plan-milestones/references/triage-criteria.md \
  plugins/github-board/skills/prune-branches/SKILL.md .github/workflows/validate-skill.yml
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "test(github-board): no personal values, clean-HOME smoke test, CI job (#146)"
```

---

### Task 12: Callers in this repo, READMEs, CHANGELOG

**Files:**
- Modify: `skill-authoring/SKILL.md`, `skill-authoring/references/task-tracking-pattern.md`, `plugins/skill-authoring/skills/skill-authoring/SKILL.md`, `plugins/skill-authoring/skills/skill-authoring/references/task-tracking-pattern.md`, `skill-authoring/CHANGELOG.md`, `plugins/skill-authoring/CHANGELOG.md`, `plugins/skill-authoring/skills/skill-authoring/CHANGELOG.md`, `plugins/skill-authoring/.claude-plugin/plugin.json`
- Modify: `plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh`, both skill-publishing CHANGELOGs
- Modify: `.claude-plugin/marketplace.json`, `README.md`, `CHANGELOG.md`
- Rewrite: `plugins/github-board/README.md`

**Interfaces:**
- Consumes: the finished plugin.
- Produces: docs only. Leave `scripts/test-sync-hygiene.sh` comments and CHANGELOG history untouched.

- [ ] **Step 1: Write the failing check**

Append to `plugins/github-board/tests/test_structure.py`:

```python
REPO = PLUGIN.parent.parent
CALLERS = ["skill-authoring/SKILL.md", "skill-authoring/references/task-tracking-pattern.md",
           "plugins/skill-authoring/skills/skill-authoring/SKILL.md",
           "plugins/skill-authoring/skills/skill-authoring/references/task-tracking-pattern.md",
           "plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh",
           "README.md"]


@pytest.mark.parametrize("rel", CALLERS)
def test_callers_in_this_repo_use_the_new_names(rel):
    lines = (REPO / rel).read_text().splitlines()
    bad = [f"{rel}:{i}" for i, line in enumerate(lines, 1)
           if not re.search(r"\bwas\b|before it moved", line)
           and any(BARE[n].search(line) or SLASH[n].search(line) for n in OLD)]
    assert bad == []


def test_root_readme_lists_the_plugin():
    text = (REPO / "README.md").read_text()
    assert "[github-board](./plugins/github-board/)" in text
    assert "/github-board-move" not in text


def test_old_root_skill_dir_is_gone():
    assert not (REPO / "github-board-move").exists()


def test_plugin_readme_has_the_runbook():
    text = (PLUGIN / "README.md").read_text()
    for heading in ("## Configuration", "## Background sync", "## Phase 3", "## Phase 4"):
        assert heading in text
    assert "--takeover" in text and "install-launchd.sh --check" in text
```

Run: `python3 -m pytest plugins/github-board/tests/test_structure.py -q -p no:cacheprovider`
Expected: FAIL on the callers, the root README entry and the plugin README headings.

- [ ] **Step 2: skill-authoring callers (both copies)**

- `SKILL.md` line 422 (both copies): `` `github-issue-triage`: full-audit (5 tasks) + quick-check (2 tasks) `` → `` `triage-issues`: full-audit (5 tasks) + quick-check (2 tasks) ``.
- `references/task-tracking-pattern.md` line 133 (both copies): `### github-issue-triage (5 tasks)` → `### triage-issues (5 tasks)`.
- Bump the skill 2.6.0 → 2.6.1: `metadata.version` in both `SKILL.md` copies. Add above `## [2.6.0]` in `skill-authoring/CHANGELOG.md`, `plugins/skill-authoring/CHANGELOG.md` and `plugins/skill-authoring/skills/skill-authoring/CHANGELOG.md`:

```markdown
## [2.6.1] - 2026-10-02

### Changed

- Examples name `triage-issues`, the new name of `github-issue-triage` in the github-board plugin (#146).
```

- Plugin version 2.3.0 → 2.3.1 in `plugins/skill-authoring/.claude-plugin/plugin.json` and its `.claude-plugin/marketplace.json` row. In `README.md`: the skills-table row `| [skill-authoring](./skill-authoring/) | 2.6.0 |` → `2.6.1`, the plugins-table row `| [skill-authoring](./plugins/skill-authoring/) | 2.3.0 |` → `2.3.1`.

- [ ] **Step 3: skill-publishing caller**

In `plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh` line 161, replace `# script blind to every in-repo-source-only skill (github-board-move, the` and the following line `# spec-* family) — it fell into the branch below, was silently skipped, and` with:

```bash
  # script blind to every in-repo-source-only skill (the spec-* family, and
  # github-board-move before it moved into the github-board plugin) — it fell into the branch below, was silently skipped, and
```

Add to the `## [4.5.0] - 2026-10-02` entry from Task 1, in both skill-publishing CHANGELOGs, under `### Changed`: ``- `validate-pre-sync.sh`: a comment no longer names `github-board-move` as a live in-repo-only skill; it moved into the github-board plugin (#146).``

- [ ] **Step 4: Root README and CHANGELOG**

`README.md`, Plugins table, insert between the `figma-ui-designer` and `obsidian-brain` rows:

```markdown
| [github-board](./plugins/github-board/) | 1.0.0 | 7 | 0 | GitHub workflow skills in one install: create-board, triage-issues, plan-milestones, plan-week, move-card, promote-shipped and prune-branches, plus the four agents create-board dispatches. Per-user settings live in ~/.config/github-board/config.json. |
```

`CHANGELOG.md`, under `## [Unreleased]` → `### Added`, add as the first bullet:

```markdown
- **`github-board` plugin 1.0.0 (#146).** One install for seven GitHub-workflow skills with short names — `create-board`, `triage-issues`, `plan-milestones`, `plan-week`, `move-card`, `promote-shipped`, `prune-branches` — and the four agents `create-board` dispatches (`github-board:template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier`). Per-user values (owner, lanes, schedule, frozen repos, capacity, launchd labels, the board template) moved out of the code into `~/.config/github-board/config.json`, written by `plan-week init` / `create-board init`; nothing falls back to built-in values. Board ids are cached for 7 days under `~/.cache/github-board/`. plan-week's launchd jobs run through `~/.local/share/github-board/current`, so they survive plugin upgrades, and `install-launchd.sh` refuses (exit 3) to take over jobs another copy owns unless `--takeover` is passed. The repo-root `github-board-move/` moved into the plugin as `move-card`.
```

and add a `### Changed` section (after `### Added`, inside `[Unreleased]`) if none exists, with:

```markdown
- `validate-skill.sh` (repo root and skill-publishing 4.5.0) accepts the `disable-model-invocation` frontmatter field (#146).
- skill-authoring 2.6.1 (plugin 2.3.1): examples use `triage-issues` (#146).
```

- [ ] **Step 5: Plugin README**

Replace `plugins/github-board/README.md` with:

````markdown
# github-board

GitHub workflow skills in one install: create a board from a template, triage issues, plan milestones, plan the week, move cards, promote shipped work to Done, and prune stale branches.

```shell
/plugin install github-board@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/github-board:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `create-board` | `create-gh-board` | Copies a template ProjectV2 board onto a repo, links it, backfills issues and verifies the copy. Audits boards for drift. |
| `triage-issues` | `github-issue-triage` | Audits, updates, labels and closes open issues against the code. |
| `plan-milestones` | `github-milestone-planning` | Keeps each milestone small and themed; defers the rest. |
| `plan-week` | `weekly-focus` | Keeps a cross-repo "Weekly Focus" board current and answers "what do I work on next". |
| `move-card` | `github-board-move` | Moves an issue or PR card to any Status column. |
| `promote-shipped` | `github-release-board-promote` | Moves shipped cards to Done after a release or hotfix. |
| `prune-branches` | `git-branch-cleanup` | Finds and deletes stale local and remote branches. |

## Agents

Dispatched by `create-board` only, as `github-board:<agent>`: `template-inspector` (Phase 1), `board-creator` (Phases 2, 3 and 5), `workflow-syncer` (Phase 4), `board-verifier` (Phase 6). They were `gh-board-*`; the old agents keep their names, so both sets can be installed at once.

## Configuration

Per-user values live outside the plugin, so upgrades never touch them and launchd can read them:

`${XDG_CONFIG_HOME:-~/.config}/github-board/config.json`

```json
{
  "version": 1,
  "owner": "<login>",
  "plan_week": {
    "board_title": "Weekly Focus",
    "lanes": [
      {"name": "Security", "labels_containing": ["security"]},
      {"name": "Tooling", "repos": ["<repo>", "<repo>"]}
    ],
    "default_lane": "Product",
    "schedule": null,
    "frozen": ["<repo>"],
    "always": ["<repo>#<n>"],
    "capacity": {"max_repos_besides_security": 3, "hours": [10, 20]},
    "launchd": {"enabled": true, "times": ["07:00", "18:00"], "label_prefix": "dev.github-board.plan-week"}
  },
  "create_board": {"template_owner": "<login>", "template_number": 1}
}
```

- Write it with `/github-board:plan-week init` and `/github-board:create-board init`. Both ask a few questions with suggestions fetched from GitHub, show the file, and write it only after you confirm.
- Lane rules match in order; the first match wins, else `default_lane`. `schedule` is `null` (no fixed days) or `{"mon": [lanes], …}`.
- No config: every `plan-week` command except `init` exits 4. An invalid file exits 2 and names the key.
- To seed from an existing setup, write the same shape to a file outside the repo and run `python3 <plan-week>/scripts/weekly-focus.py init --from <file>`. Do not commit that file.

## Metadata cache

Board numbers, node ids, field and option ids, and each repo's linked boards are cached in `${XDG_CACHE_HOME:-~/.cache}/github-board/` for 7 days. A GraphQL error naming a stale id drops the entry and refetches once. Deleting the directory is always safe. `--no-cache` skips it.

## Background sync (macOS)

`plan-week` can run `sync` from launchd. The plists run the scripts through the stable link `~/.local/share/github-board/current`, which `install-launchd.sh` points at the plugin copy it runs from. **Re-run `install-launchd.sh` after every plugin update.**

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh"            # link + both jobs
"$PW/scripts/install-launchd.sh" --check    # link, plists, loaded
```

If a plist with the same label already runs another copy's scripts, the install refuses with exit 3 and names that copy. `--takeover` hands the jobs to the plugin.

## Running next to the old bare skills

While both are installed, `/weekly-focus` and `/github-board:plan-week` read and write the same state (`~/.local/state/weekly-focus`, `~/Library/Logs/weekly-focus`) and the same board. Set `launchd.label_prefix` to the prefix the bare copy's labels use, so a later takeover replaces those same jobs. The bare copy keeps owning the launchd jobs until Phase 3.

## Phase 3: hand the launchd jobs to the plugin

Run by hand on the machine that has the bare `weekly-focus` jobs:

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh" --takeover
"$PW/scripts/install-launchd.sh" --check
python3 "$PW/scripts/weekly-focus.py" sync --json
```

Then set the `restart_command` of the two plan-week entries in `~/.claude/skills/boot-doctor/services.json` to `~/.local/share/github-board/current/skills/plan-week/scripts/install-launchd.sh`.

Rollback: `~/.claude/skills/weekly-focus/scripts/install-launchd.sh` (the bare copy) rewrites both plists to point back at itself.

## Phase 4: remove the bare copies

1. In claude-code-config, drop `weekly-focus`, `create-gh-board` and `github-release-board-promote` from `sync.sh`'s `SKILLS` array first, so a sync cannot bring them back.
2. Diff each bare copy against the plugin; expect only the renames and the config changes:

   ```bash
   P="$(ls -d ~/.claude/plugins/cache/*/github-board/* | sort -V | tail -1)"
   for pair in create-gh-board:create-board github-issue-triage:triage-issues \
       github-milestone-planning:plan-milestones weekly-focus:plan-week \
       github-board-move:move-card github-release-board-promote:promote-shipped \
       git-branch-cleanup:prune-branches; do
     diff -r ~/.claude/skills/"${pair%%:*}" "$P/skills/${pair##*:}"
   done
   ```

3. Delete the bare skills and agents:

   ```bash
   rm -rf ~/.claude/skills/{create-gh-board,github-issue-triage,github-milestone-planning,weekly-focus,github-board-move,github-release-board-promote,git-branch-cleanup}
   rm -f ~/.claude/agents/gh-board-{creator,template-inspector,verifier,workflow-syncer}.md
   ```

4. Confirm only `github-board:` names remain: `ls ~/.claude/skills ~/.claude/agents` shows none of the old names, and `/help` lists the `github-board:` skills.

Callers of the old names in claude-code-config, git-flow, obsidian-brain and codex-config move in one small PR per repo.

## Tests

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
bash plugins/github-board/tests/smoke-clean-home.sh
```

Everything runs offline: `gh`, `launchctl` and `osascript` are fakes, and the config, cache and link paths point into a temp dir.
````

- [ ] **Step 6: Run everything**

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
bash plugins/github-board/tests/smoke-clean-home.sh
scripts/validate-plugin.sh plugins/github-board
scripts/validate-plugin.sh plugins/skill-authoring
scripts/validate-plugin.sh plugins/skill-publishing
scripts/validate-skill.sh skill-authoring
jq . .claude-plugin/marketplace.json >/dev/null && echo marketplace-ok
```

Expected: all pass. (The no-personal-values test checks the new plugin README against its allow-list.)

- [ ] **Step 7: Commit**

```bash
git add plugins/github-board/README.md plugins/github-board/tests/test_structure.py \
  skill-authoring/SKILL.md skill-authoring/references/task-tracking-pattern.md skill-authoring/CHANGELOG.md \
  plugins/skill-authoring/skills/skill-authoring/SKILL.md \
  plugins/skill-authoring/skills/skill-authoring/references/task-tracking-pattern.md \
  plugins/skill-authoring/skills/skill-authoring/CHANGELOG.md plugins/skill-authoring/CHANGELOG.md \
  plugins/skill-authoring/.claude-plugin/plugin.json \
  plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh \
  plugins/skill-publishing/CHANGELOG.md plugins/skill-publishing/skills/skill-publishing/CHANGELOG.md \
  .claude-plugin/marketplace.json README.md CHANGELOG.md
```

```bash
./scripts/commit-preflight.sh
```

```bash
git commit -m "docs(github-board): plugin README with migration runbook; callers use new names (#146)"
```

---

## Notes for the reviewer (deviations from the spec, decided here)

- **`weekly-focus.py --help` exited 2** (`main`, old lines 744-746). The spec's smoke test needs exit 0, so Task 4 adds `-h/--help/help`.
- **`create-gh-board` has `disable-model-invocation: true`**, which `validate-skill.sh:267-277` rejected. Task 1 keeps the field and widens the validator (root copy and its byte-identical skill-publishing copy; skill-publishing → 4.5.0).
- **`common.sh` had no shebang**, which `validate-skill.sh:316-322` fails. Task 1 adds one.
- **`validate-plugin.sh` does not check `github-board:<agent>` dispatches**: its agent check (line 259) only matches `agents/<name>.md` and only warns (line 270). `test_structure.py` covers the dispatch names instead.
- **Init Q1 offers user accounts only.** The spec suggests orgs too, but `weekly-focus.py` reads `user(login:)` (old lines 167, 170, 173) and `author:<owner>` (328), so an org owner would break. Task 8 says orgs are not supported yet.
- **Lane parity uses invented names** (`season-repo`, `tool-a`) with the same rule shape as today's constants, because the no-personal-values test forbids the real repo names in the plugin. The legacy `lane_for` is kept verbatim in the test as the oracle.
- **`init` refuses per section, not per file**, so `create-board init` can add `create_board` to a config `plan-week init` wrote. A different value in an existing section still needs `--force` (exit 3).
- **The board README text changes slightly** for an existing board (built from the config; e.g. the Friday line now lists lanes). `sync` rewrites it on its next run.
- **plists carry `XDG_CONFIG_HOME` and `XDG_CACHE_HOME`**, rendered at install time, so a person with a non-default `XDG_CONFIG_HOME` still has launchd read the file `init` wrote.
- **The SKILL.md init flow passes the answers with `--from <tempfile>`** rather than stdin, so every `"$WF"` line stays runnable in the shell test. The script accepts stdin too, as the spec says.
