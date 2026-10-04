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


REPO = PLUGIN.parent.parent
# skill-authoring used to name github-issue-triage; it was renamed once its SKILL.md was
# trimmed under validate-skill.sh's 500-line limit (2.6.1).
CALLERS = ["skill-authoring/SKILL.md", "skill-authoring/references/task-tracking-pattern.md",
           "plugins/skill-authoring/skills/skill-authoring/SKILL.md",
           "plugins/skill-authoring/skills/skill-authoring/references/task-tracking-pattern.md"]
CALLERS += ["plugins/skill-publishing/skills/skill-publishing/scripts/validate-pre-sync.sh",
            "README.md"]
# The same files in the skill-kit plugin. The old paths stay until #167 removes them.
CALLERS += ["plugins/skill-kit/skills/author/SKILL.md",
            "plugins/skill-kit/skills/author/references/task-tracking-pattern.md",
            "plugins/skill-kit/skills/publish/scripts/validate-pre-sync.sh"]


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


def test_the_two_skill_authoring_copies_are_identical():
    import filecmp
    root, plugin = REPO / "skill-authoring", REPO / "plugins" / "skill-authoring" / "skills" / "skill-authoring"
    for rel in ("SKILL.md", "CHANGELOG.md", "references/agent-teams.md",
                "references/skill-templates.md", "references/task-tracking-pattern.md",
                "references/quality-checklist.md"):
        assert filecmp.cmp(root / rel, plugin / rel, shallow=False), rel


def test_old_root_skill_dir_is_gone():
    assert not (REPO / "github-board-move").exists()


def test_plugin_readme_has_the_runbook():
    text = (PLUGIN / "README.md").read_text()
    for heading in ("## Configuration", "## Background sync", "## Phase 3", "## Phase 4"):
        assert heading in text
    assert "--takeover" in text and "install-launchd.sh --check" in text


def test_promote_shipped_skill_documents_every_class_the_script_emits():
    # The SKILL.md first copied in was an older snapshot that listed four hold classes while
    # find-promotable.sh emits five (hold-discovery-failed was missing). hold-foreign-pr makes six.
    skill = PLUGIN / "skills" / "promote-shipped"
    script = (skill / "scripts" / "find-promotable.sh").read_text()
    classes = set(re.findall(r'"((?:hold-[a-z-]+)|merged|nopr|wontfix)"', script))
    assert len(classes) == 9
    text = (skill / "SKILL.md").read_text()
    assert [c for c in sorted(classes) if f"`{c}`" not in text] == []
