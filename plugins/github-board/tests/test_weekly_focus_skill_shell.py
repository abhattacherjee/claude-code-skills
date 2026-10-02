"""SKILL.md's own commands must run in the shells the Bash tool uses (#217).

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


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_skill_commands_run_in_shell(shell, tmp_path):
    exe = shutil.which(shell)
    if not exe:
        pytest.skip(f"{shell} not installed")
    stub = tmp_path / ".claude" / "skills" / "weekly-focus" / "scripts" / "weekly-focus.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(STUB)
    script = "\n".join([re.split(r"\s+#\s", _wf_assignment())[0]] +[f"{c} || exit 9" for c in _commands()])
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    r = subprocess.run([exe, "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"{shell} failed: {r.stderr}"
    out = [l for l in r.stdout.splitlines() if l.startswith("STUB ")]
    assert len(out) == len(_commands())
    assert out[0] == "STUB sync --json"
