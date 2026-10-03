"""Shared helpers for the statusline tests. Not a test module.

Every run gets HOME and TMPDIR inside pytest's tmp_path, so no test reads or writes the
real ~/.claude. CLAUDE_CONFIG_DIR is removed from the environment for the same reason.
"""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

PLUGIN = Path(__file__).resolve().parent.parent
LIB = PLUGIN / "lib" / "write-statusline.sh"
SKILLS = PLUGIN / "skills"
INSTALL = SKILLS / "install" / "scripts" / "install.sh"
REFERENCE = SKILLS / "install" / "references" / "statusline-command.sh"
GENERATE = SKILLS / "create" / "scripts" / "generate-statusline.sh"
CONTEXT_BAR = SKILLS / "context-bar" / "scripts" / "context-bar.sh"
MARKER = "# managed-by: statusline-plugin"
DEFAULT_CMD = "bash ~/.claude/statusline-command.sh"
MOCK_JSON = ('{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/test"},'
             '"context_window":{"used_percentage":42,"context_window_size":200000},'
             '"cost":{"total_cost_usd":0.05,"total_duration_ms":120000}}')
# A stand-in for a user's own hand-written statusline: no marker, and big.
USER_SCRIPT = "#!/bin/bash\n# my own statusline\n" + "echo hand-written\n" * 2800


def bash_version(path: str) -> Optional[str]:
    try:
        out = subprocess.run([path, "-c", 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"'],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def find_bash32() -> Optional[str]:
    for cand in ("/bin/bash", "/usr/local/bin/bash3.2"):
        if os.path.exists(cand) and bash_version(cand) == "3.2":
            return cand
    return None


def tool_dir(tmp: Path, exclude=()) -> Path:
    """A PATH dir of symlinks to the tools the scripts use, minus `exclude`."""
    d = tmp / "tools"
    d.mkdir(exist_ok=True)
    for name in ("bash", "cat", "chmod", "cmp", "cp", "date", "dirname", "basename", "git",
                 "head", "jq", "ls", "mkdir", "mktemp", "mv", "python3", "readlink", "rm",
                 "sed", "seq", "sort", "tr", "wc", "awk", "cut", "printf", "stat", "env",
                 "ps", "tput", "stty", "xargs", "grep", "tail", "cksum", "pwd"):
        if name in exclude:
            continue
        real = shutil.which(name)
        if real and not (d / name).exists():
            (d / name).symlink_to(real)
    return d


def stub(tmp: Path, name: str, body: str) -> Path:
    """Write an executable stub `name` into tmp/stubs; put that dir first on PATH."""
    d = tmp / "stubs"
    d.mkdir(exist_ok=True)
    real = shutil.which(name)
    p = d / name
    p.write_text("#!/bin/sh\nREAL=" + str(real) + "\n" + body + "\n")
    p.chmod(0o755)
    return d


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir(exist_ok=True)
        (tmp / "tmpdir").mkdir(exist_ok=True)
        self.claude = self.home / ".claude"
        self.script = self.claude / "statusline-command.sh"
        self.settings = self.claude / "settings.json"
        self.path_prefix = []
        self.path_only = None

    def env(self, extra=None) -> dict:
        e = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        e["HOME"] = str(self.home)
        e["TMPDIR"] = str(self.tmp / "tmpdir")
        path = self.path_only or os.environ["PATH"]
        e["PATH"] = os.pathsep.join([str(p) for p in self.path_prefix] + [path])
        if extra:
            e.update(extra)
        return e

    def run(self, bash: str, script: Path, *args, cwd=None, stdin=None, extra=None):
        return subprocess.run([bash, str(script), *map(str, args)], capture_output=True,
                              text=True, cwd=str(cwd or self.home), input=stdin,
                              env=self.env(extra), timeout=60)

    def call_lib(self, bash: str, func: str, *args):
        code = '. "$1"; shift; f=$1; shift; "$f" "$@"'
        return subprocess.run([bash, "-c", code, "_", str(LIB), func, *map(str, args)],
                              capture_output=True, text=True, cwd=str(self.home),
                              env=self.env(), timeout=60)


def snapshot(path: Path):
    """Bytes and mtime of a file, or None when it does not exist."""
    if not path.exists():
        return None
    st = path.stat()
    return path.read_bytes(), st.st_mtime_ns


def backups(path: Path):
    return sorted(path.parent.glob(path.name + ".bak-*"))


def leftovers(directory: Path):
    """Temp files a failed write could leave behind."""
    return sorted(p.name for p in directory.glob(".*") if p.is_file())
