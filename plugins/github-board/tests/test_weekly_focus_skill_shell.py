"""Every SKILL.md command must run on its own, in a fresh shell (#217, #146, round-1 R2).

The Bash tool does not keep shell variables between calls. plan-week's SKILL.md once set
WF=... in one block and ran `python3 "$WF" sync` in later ones: in a fresh shell "$WF" is
empty, `python3 ""` fails, and `init --from "$CFG_JSON"` read stdin instead of the file.
So every command spells out "${CLAUDE_SKILL_DIR}/scripts/...", and these tests run each
plan-week command in a fresh shell, and check every skill's commands for a variable that
some other command was supposed to set.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
PLAN_WEEK = PLUGIN / "skills" / "plan-week" / "SKILL.md"

OPENERS = re.compile(r"^\s*(for|while|until|if|case)\b|\{\s*$|\(\s*$")
CLOSERS = re.compile(r"^\s*(done|fi|esac)\b|^\s*[})]")
HEREDOC = re.compile(r"<<-?\s*'?\"?([A-Za-z_]+)'?\"?")
# Variables a fresh shell always has, and the skill-dir placeholder Claude Code substitutes.
AMBIENT = {"CLAUDE_SKILL_DIR", "HOME", "PATH", "PWD", "USER", "TMPDIR", "GH_HOST"}


def fenced_commands(text):
    """Logical shell commands of every ```bash block: one per line, except that a heredoc,
    a backslash continuation or an open for/while/if/case/{ ... } keeps lines together."""
    cmds = []
    for block in re.findall(r"```(?:bash|sh|zsh)\n(.*?)```", text, re.S):
        cur, depth, heredoc = [], 0, None
        for line in block.splitlines():
            if heredoc:
                cur.append(line)
                if line.strip() == heredoc:
                    heredoc = None
                    if depth == 0:
                        cmds.append("\n".join(cur)); cur = []
                continue
            if not cur and (not line.strip() or line.lstrip().startswith("#")):
                continue
            cur.append(line)
            code = re.split(r"\s+#\s", line)[0]
            m = HEREDOC.search(code)
            if m:
                heredoc = m.group(1)
                continue
            depth += len(OPENERS.findall(code)) - len(CLOSERS.findall(code))
            if depth <= 0 and not code.rstrip().endswith("\\"):
                cmds.append("\n".join(cur)); cur, depth = [], 0
        if cur:
            cmds.append("\n".join(cur))
    return cmds


def inline_commands(text):
    """`...` spans that run a bundled script (a real file name, not the `scripts/...` pattern)."""
    return [c for c in re.findall(r"`([^`\n]+)`", text)
            if re.search(r"\$\{CLAUDE_SKILL_DIR\}/scripts/[A-Za-z]", c)]


def free_variables(cmd):
    """Variables a command reads but does not set itself (heredoc bodies excluded)."""
    body = re.sub(r"<<-?\s*'([A-Za-z_]+)'.*?\n\1\b", "", cmd, flags=re.S)   # quoted heredoc: literal
    body = re.sub(r"\s#\s.*", "", body)
    used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", body))
    set_here = set(re.findall(r"(?:^|[\s;(&|])([A-Za-z_][A-Za-z0-9_]*)=", body))
    set_here |= set(re.findall(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", body))
    set_here |= {v for m in re.findall(r"\bread\s+(?:-\w+\s+)*([A-Za-z_ ]+)", body) for v in m.split()}
    return used - set_here - AMBIENT


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_no_command_reads_a_variable_another_command_set(skill):
    text = skill.read_text()
    bad = [(c, sorted(free_variables(c))) for c in fenced_commands(text) + inline_commands(text)
           if free_variables(c)]
    assert bad == [], f"{skill.parent.name}: commands that depend on another command's variable: {bad}"


def test_the_checker_catches_the_old_pattern():
    old = '```bash\nWF="${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"\n```\n\n' \
          '```bash\npython3 "$WF" sync --json\n```\n'
    assert [free_variables(c) for c in fenced_commands(old)] == [set(), {"WF"}]


STUB = """import sys
print("STUB " + " ".join(sys.argv[1:]))
data = sys.stdin.read() if "init" in sys.argv[1:2] and "--from" not in sys.argv else ""
if "init" in sys.argv[1:2] and not data.strip() and "--from" not in sys.argv:
    sys.exit(7)       # init without a payload
"""
SH_STUB = '#!/bin/sh\necho "STUB $*"\n'


def plan_week_commands():
    text = PLAN_WEEK.read_text()
    cmds = [c for c in fenced_commands(text) + inline_commands(text) if "${CLAUDE_SKILL_DIR}" in c]
    assert cmds, "no plan-week commands found"
    return cmds


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_each_plan_week_command_runs_in_a_fresh_shell(shell, tmp_path):
    exe = shutil.which(shell)
    if not exe:
        pytest.skip(f"{shell} not installed")
    skill_dir = tmp_path / "plan-week"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "weekly-focus.py").write_text(STUB)
    for name in ("install-launchd.sh",):
        (skill_dir / "scripts" / name).write_text(SH_STUB)
        (skill_dir / "scripts" / name).chmod(0o755)
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    for cmd in plan_week_commands():
        # Claude Code substitutes ${CLAUDE_SKILL_DIR} as text when the skill loads; do the same.
        script = cmd.replace("${CLAUDE_SKILL_DIR}", str(skill_dir))
        r = subprocess.run([exe, "-c", script], capture_output=True, text=True, env=env, timeout=30)
        assert r.returncode == 0 and "STUB " in r.stdout, f"{shell}: {cmd!r} failed: {r.stderr}"


KNOWN = {"sync", "show", "set", "init", "config"}


def test_every_weekly_focus_command_is_a_known_subcommand():
    for cmd in plan_week_commands():
        m = re.search(r'weekly-focus\.py"\s+(\S+)', cmd)
        if m:
            assert m.group(1) in KNOWN, cmd


def _text():
    return PLAN_WEEK.read_text()


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
    wf = 'python3 "${CLAUDE_SKILL_DIR}/scripts/weekly-focus.py"'
    assert "## Mode: init" in text
    assert f"{wf} init <<'JSON'" in text
    assert f"{wf} init --force <<'JSON'" in text
    assert f"{wf} config" in text
    assert "Write this to `~/.config/github-board/config.json`?" in text
    assert "gh auth refresh -s read:project,project" in text
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"):
        assert f"**{q}" in text
    assert "--takeover" in text and "never pass `--takeover` unasked" in text
    assert "$WF" not in text and "CFG_JSON" not in text
