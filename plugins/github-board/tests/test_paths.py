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
