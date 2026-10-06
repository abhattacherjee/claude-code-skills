#!/usr/bin/env python3
"""check-doc-refs.py — every path, link and plugin:skill name in the current docs must exist (#190).

Files: README.md, CONTRIBUTING.md, LOCAL-TESTING.md, AGENTS.md, CLAUDE.md and
plugins/*/README.md. Dated plans and specs under docs/ and CHANGELOGs are
history, so they are not checked.

Rules, outside fenced code blocks:
  R1  a relative link target must exist, relative to the file (a target
      starting with / is relative to the repo root). Inline links
      [x](target) and [x](<target>), reference definitions [r]: target,
      and HTML href="..." and src="..." are all checked;
  R2  an inline-code token starting with plugins/, scripts/, .github/,
      .claude-plugin/ or docs/ must exist relative to the repo root (in a
      plugin README also relative to the plugin and each of its skill
      directories); <anything> and * match one path segment, and a :N line
      suffix is ignored;
  R3  an inline-code /plugin:name or plugin:name, where plugin is one of
      plugins/*, must name one of its skills, agents or commands.
A link or path that resolves outside the repo is reported too. An unclosed
fence is reported (the rest of that file is not checked).

Blind spots (not checked): bare file names (`record.sh`); paths with other
prefixes; anything inside fenced blocks; inline-code tokens with spaces;
upper-case namespaces (`Kit:x`); double-backtick spans; #anchor fragments
(only the file part of a link is checked); a misspelt plugin namespace
(`kti:publish` is not a plugin, so it is skipped); and paths in a user's own
project.

Usage: check-doc-refs.py [<repo>]   (default: the repo this script is in)
Exit: 0 clean, 1 broken references (file:line: token: reason), 2 cannot run.
"""
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# The one enumeration of a plugin's skills, agents and commands lives in
# catalogue.py; import it from this repo's copy.
CATALOGUE_DIR = Path(__file__).resolve().parent.parent / "plugins" / "skill-kit" / "skills" / "publish" / "scripts"
sys.path.insert(0, str(CATALOGUE_DIR))
sys.dont_write_bytecode = True  # no __pycache__ beside catalogue.py
try:
    import catalogue  # noqa: E402
except Exception as e:  # fail closed: without it nothing can be counted
    print(f"check-doc-refs.py: cannot run: cannot import catalogue.py from {CATALOGUE_DIR}: {e}", file=sys.stderr)
    sys.exit(2)

ROOT_DOCS = ["README.md", "CONTRIBUTING.md", "LOCAL-TESTING.md", "AGENTS.md", "CLAUDE.md"]
# A CommonMark link title is "T", 'T' or (T).
TITLE = r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?"
LINK = re.compile(r"\]\(([^)\s<][^)\s]*)" + TITLE + r"\s*\)")
ANGLE_LINK = re.compile(r"\]\(<([^>\n]+)>")
REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(?:<([^>\n]+)>|([^\s<]\S*))")
HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
CODE = re.compile(r"`([^`\n]+)`")
PREFIXES = ("plugins/", "scripts/", ".github/", ".claude-plugin/", "docs/")
NS = re.compile(r"^/?([a-z0-9-]+):([a-z0-9-]+)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
LINE_SUFFIX = re.compile(r":\d+(-\d+)?$")


class CannotRun(Exception):
    pass


def inside(repo, path):
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def exists(repo, bases, token):
    """'yes', 'no' or 'outside' (the token resolves outside the repo)."""
    t = token[2:] if token.startswith("./") else token
    t = LINE_SUFFIX.sub("", t)
    pattern = re.sub(r"<[^>]*>", "*", t).rstrip("/")
    # Any .. segment is refused: glob() follows it, so a pattern such as
    # docs/*/../../../* could match outside the repo.
    if ".." in pattern.split("/"):
        return "outside"
    if "*" not in pattern and not inside(repo, bases[0] / pattern):
        return "outside"
    seen_outside = False
    for b in bases:
        if "*" in pattern:
            for m in b.glob(pattern):
                if inside(repo, m):
                    return "yes"
                seen_outside = True
        elif (b / pattern).exists():
            return "yes"
    # Only matches that resolve outside the repo (through a symlink).
    return "outside" if seen_outside else "no"


def plugin_dirs(repo):
    pdir = repo / "plugins"
    if not pdir.is_dir():
        raise CannotRun(f"{repo}: no plugins/ directory")
    return sorted(d for d in pdir.iterdir() if d.is_dir() and not d.name.startswith("."))


def plugin_names(repo, dirs):
    """Each plugin's skill, agent and command names, from catalogue.py's own
    plugin_parts(), so both tools count a plugin the same way (#190 C-006)."""
    out = {}
    for d in dirs:
        try:
            skills, agents, commands = catalogue.plugin_parts(d, f"plugins/{d.name}")
        except catalogue.CannotRun as e:
            raise CannotRun(str(e))
        out[d.name] = set(skills) | set(agents) | set(commands)
    return out


def read(f, rel):
    try:
        return f.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CannotRun(f"{rel}: {e}")


def check_file(repo, f, names):
    rel = f.relative_to(repo)
    bases = [repo]
    if rel.parts[0] == "plugins":
        pd = repo / "plugins" / rel.parts[1]
        bases += [pd] + sorted(s for s in pd.glob("skills/*") if s.is_dir())
    out, fence, fence_line = [], None, 0
    for i, line in enumerate(read(f, rel).splitlines(), 1):
        fm = FENCE.match(line)
        if fence is None and fm:
            fence, fence_line = fm.group(1), i  # opens; closes on the same char, at least as long
            continue
        if fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence) \
                    and not line.strip()[len(fm.group(1)):].strip():
                fence = None
            continue
        prose = CODE.sub("", line)
        targets = [m.group(1) for m in LINK.finditer(prose)]
        targets += [m.group(1) for m in ANGLE_LINK.finditer(prose)]
        targets += [m.group(1) or m.group(2) for m in HTML_ATTR.finditer(prose)]
        rd = REF_DEF.match(prose)
        if rd:
            targets.append(rd.group(1) or rd.group(2))
        for t in targets:
            if not t or t.startswith("#") or SCHEME.match(t):
                continue
            target = unquote(t.split("#", 1)[0])
            if not target:
                continue
            path = repo / target.lstrip("/") if target.startswith("/") else f.parent / target
            if not inside(repo, path):
                out.append(f"{rel}:{i}: {t}: link target is outside the repo")
            elif not path.exists():
                out.append(f"{rel}:{i}: {t}: link target does not exist")
        for m in CODE.finditer(line):
            t = m.group(1)
            if " " in t:
                continue
            bare = t[2:] if t.startswith("./") else t
            if bare.startswith(PREFIXES):
                found = exists(repo, bases, t)
                if found == "outside":
                    out.append(f"{rel}:{i}: {t}: path is outside the repo")
                elif found == "no":
                    out.append(f"{rel}:{i}: {t}: no such path")
                continue
            n = NS.match(t)
            if n and n.group(1) in names and n.group(2) not in names[n.group(1)]:
                out.append(f"{rel}:{i}: {t}: {n.group(1)} has no skill, agent or command named {n.group(2)}")
    if fence is not None:
        out.append(f"{rel}:{fence_line}: unclosed fence; rest of file not checked")
    return out


def run(repo):
    if not repo.is_dir():
        raise CannotRun(f"{repo}: not a directory")
    files = []
    for d in ROOT_DOCS:
        if not (repo / d).is_file():
            raise CannotRun(f"{d}: missing")
        files.append(repo / d)
    dirs = plugin_dirs(repo)
    files += [d / "README.md" for d in dirs if (d / "README.md").is_file()]
    names = plugin_names(repo, dirs)
    broken = []
    for f in files:
        broken += check_file(repo, f, names)
    return broken


def main(argv):
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    try:
        broken = run(repo)
    except CannotRun as e:
        print(f"check-doc-refs.py: cannot run: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # fail closed: an unexpected error is "cannot run", never "clean"
        print(f"check-doc-refs.py: cannot run: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for b in broken:
        print(b)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
