"""plan-week SKILL.md's own commands must run in the shells the Bash tool uses (#217, #146).

The skill once set WF="python3 <path>" and called `$WF sync`. zsh does not
word-split an unquoted variable, so every mode failed with "no such file or
directory: python3 /Users/...". No test ran SKILL.md's commands through a real
shell, so this shipped. These tests take the commands straight from SKILL.md.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "plan-week" / "SKILL.md"

STUB = """import sys
print("STUB " + " ".join(sys.argv[1:]))
"""


def _wf_assignment():
    lines = [l for l in SKILL.read_text().splitlines() if re.match(r"^WF=", l)]
    assert len(lines) == 1, f"expected one WF= line in SKILL.md, got {lines}"
    return lines[0]


def _commands():
    """Every SKILL.md command that invokes $WF, inline (backticks) or in a code block."""
    cmds = []
    for line in SKILL.read_text().splitlines():
        if "$WF" not in line or line.startswith("WF="):
            continue
        for inline in re.findall(r"`([^`]*\$WF[^`]*)`", line):
            cmds.append(inline)
        if "`" not in line:
            cmds.append(re.split(r"\s+#\s", line)[0].strip())  # drop a trailing comment, keep repo#N
    assert cmds, "no $WF commands found in SKILL.md"
    return cmds


def test_wf_is_a_bare_path_not_a_command_with_arguments():
    value = re.split(r"\s+#\s", _wf_assignment())[0].strip()[len("WF="):].strip().strip('"')
    assert not re.search(r"\s", value), f"WF must be a path only, got {value!r}"


def test_every_wf_call_quotes_the_variable():
    for cmd in _commands():
        assert '"$WF"' in cmd, f"unquoted $WF in SKILL.md command: {cmd!r}"


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
