"""Structure of the statusline plugin (#158): three skills, new names only, plugin-relative paths."""
import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = {"install", "create", "context-bar"}
# context-bar keeps its name, so only the other two old skill names and the two old
# plugin names count as old.
OLD = ["install-statusline", "custom-statusline", "statusline-creator"]
BARE = {n: re.compile(r"(?<![\w/.-])" + re.escape(n) + r"(?![\w.-])") for n in OLD}
SLASH = {n: re.compile(r"(?:^|[\s(`'\"])/" + re.escape(n) + r"(?![\w/.-])") for n in OLD}
FENCE = re.compile(r"^```(?:bash|sh|shell)?\n(.*?)^```", re.M | re.S)


def _frontmatter(path: Path) -> str:
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path}: no frontmatter"
    return m.group(1)


def _field(path: Path, field: str):
    m = re.search(rf"^{field}:\s*(.+?)\s*$", _frontmatter(path), re.M)
    return m.group(1).strip('"') if m else None


def _skill_docs():
    return sorted(p for p in (PLUGIN / "skills").rglob("*.md") if p.name != "CHANGELOG.md")


def test_plugin_manifest():
    data = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert data["name"] == "statusline"
    assert data["version"] == "1.0.0"


def test_exactly_the_three_skills():
    assert {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()} == SKILLS


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_name_matches_directory_and_version_is_1_0_0(skill):
    path = PLUGIN / "skills" / skill / "SKILL.md"
    assert _field(path, "name") == skill
    assert re.search(r"^metadata:\n\s+version:\s*1\.0\.0\s*$", _frontmatter(path), re.M)


@pytest.mark.parametrize("skill,old", [("install", "install-statusline"),
                                       ("create", "statusline-creator")])
def test_description_still_names_the_old_skill(skill, old):
    assert old in _field(PLUGIN / "skills" / skill / "SKILL.md", "description")


def test_no_home_skills_paths_in_the_plugin():
    bad = []
    for p in sorted(PLUGIN.rglob("*")):
        if p.is_file() and "tests" not in p.relative_to(PLUGIN).parts and p.suffix in (".md", ".sh", ".py"):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if ".claude/skills/" in line:
                    bad.append(f"{p.relative_to(PLUGIN)}:{i}")
    assert bad == []


def test_every_script_reference_in_a_skill_doc_spells_the_full_skill_dir_path():
    bad = []
    for md in _skill_docs():
        for block in FENCE.findall(md.read_text()):
            for line in block.splitlines():
                for m in re.finditer(r"\S*scripts/[\w.-]+\.(?:sh|py)", line):
                    if not m.group(0).lstrip("\"'").startswith("${CLAUDE_SKILL_DIR}/scripts/"):
                        bad.append(f"{md.relative_to(PLUGIN)}: {line.strip()}")
    assert bad == []


def test_no_shell_variable_is_set_in_one_block_and_used_in_another():
    # The Bash tool keeps no state between calls, so each fenced block in a SKILL.md stands
    # alone. references/item-recipes.md is exempt: its snippets are pasted into one script.
    bad = []
    for md in sorted((PLUGIN / "skills").glob("*/SKILL.md")):
        blocks = FENCE.findall(md.read_text())
        for i, block in enumerate(blocks):
            for var in re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", block, re.M):
                for j, other in enumerate(blocks):
                    if j != i and re.search(r"\$\{?" + var + r"\b", other) and not re.search(
                            r"^\s*(?:export\s+)?" + var + "=", other, re.M):
                        bad.append(f"{md.relative_to(PLUGIN)}: {var}")
    assert bad == []


def test_every_script_a_skill_doc_names_exists():
    for md in _skill_docs():
        skill_dir = md.parent if md.name == "SKILL.md" else md.parent.parent
        for rel in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/(scripts/[\w.-]+)", md.read_text()):
            assert (skill_dir / rel).is_file(), f"{md}: {rel} missing"


def _allowed(line: str) -> bool:
    # Trigger phrases live in description:; "was …" notes name the old name on purpose.
    return line.startswith(("description:", "name:")) or re.search(r"\bwas\b", line) is not None


def _hits(paths):
    out = []
    for p in paths:
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _allowed(line):
                continue
            for n in OLD:
                if BARE[n].search(line) or SLASH[n].search(line):
                    out.append(f"{p.relative_to(PLUGIN)}:{i}: {n}")
    return out


def test_no_old_name_in_skill_docs_or_scripts():
    scripts = [p for p in (PLUGIN / "skills").rglob("*") if p.suffix in (".sh", ".py")]
    assert _hits(_skill_docs() + sorted(scripts)) == []


def test_context_bar_ships_no_statusline_script_of_its_own():
    assert not list((PLUGIN / "skills" / "context-bar").rglob("statusline-command.sh"))


def test_install_ships_the_three_tier_statusline():
    ref = PLUGIN / "skills" / "install" / "references" / "statusline-command.sh"
    assert "3-tier adaptive" in ref.read_text()


REPO = PLUGIN.parent.parent
OLD_PLUGINS = ["context-bar", "custom-statusline", "statusline-creator"]
DEPRECATED = ("Deprecated: use the statusline plugin "
              "(statusline:install / statusline:create / statusline:context-bar).")


def _market():
    return {r["name"]: r for r in json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text())["plugins"]}


def test_marketplace_lists_the_plugin():
    row = _market()["statusline"]
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert row["source"] == "./plugins/statusline"
    assert row["version"] == plugin["version"] == "1.0.0"
    assert row["description"] == plugin["description"]


@pytest.mark.parametrize("old", OLD_PLUGINS)
def test_old_marketplace_entries_are_deprecated_but_still_installable(old):
    row = _market()[old]
    assert row["description"].startswith(DEPRECATED + " ")
    assert row["source"] == f"./plugins/{old}"
    assert (REPO / "plugins" / old / ".claude-plugin" / "plugin.json").is_file()


def _readme_row(name):
    rows = [line for line in (REPO / "README.md").read_text().splitlines()
            if line.startswith(f"| [{name}](./plugins/{name}/)")]
    assert len(rows) == 1, name
    return [c.strip() for c in rows[0].strip("|").split("|")]


def test_readme_catalogue_row_counts_match_the_plugin():
    cells = _readme_row("statusline")
    skills = [p for p in (PLUGIN / "skills").iterdir() if (p / "SKILL.md").is_file()]
    assert cells[1:4] == ["1.0.0", str(len(skills)), "0"]


@pytest.mark.parametrize("old", OLD_PLUGINS)
def test_readme_marks_old_rows_deprecated(old):
    assert _readme_row(old)[4].startswith("Deprecated")


def test_plugin_readme_counts_match():
    text = (PLUGIN / "README.md").read_text()
    n = len([p for p in (PLUGIN / "skills").iterdir() if (p / "SKILL.md").is_file()])
    assert f"**{n}** skills" in text


def test_create_doc_item_count_matches_the_generator():
    text = (PLUGIN / "skills" / "create" / "SKILL.md").read_text()
    rows = re.findall(r"^\| `([a-z0-9-]+)` \| (?:Display|Context|Metrics|Git) \|", text, re.M)
    gen = (PLUGIN / "skills" / "create" / "scripts" / "generate-statusline.sh").read_text()
    m = re.search(r"\n    (model\|model-full\|.*?)\) ;;", gen, re.S)
    valid = set(re.split(r"[|\\\s]+", m.group(1))) - {""}
    assert len(rows) == len(valid) == 20 and set(rows) == valid
    assert "## Available Items (20 composable blocks)" in text
    assert "20 composable items" in json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["description"]
