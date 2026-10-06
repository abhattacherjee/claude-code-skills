#!/usr/bin/env python3
"""check-doc-refs.py — every path, link and plugin:skill name in the current docs must exist (#190).

Files: README.md, CONTRIBUTING.md, LOCAL-TESTING.md, AGENTS.md, CLAUDE.md and
plugins/*/README.md. Dated plans and specs under docs/ and CHANGELOGs are
history, so they are not checked.

Rules, outside fenced code blocks:
  R1  a relative Markdown link target must exist, relative to the file
      (a target starting with / is relative to the repo root);
  R2  an inline-code token starting with plugins/, scripts/, .github/,
      .claude-plugin/ or docs/ must exist relative to the repo root (in a
      plugin README also relative to the plugin and each of its skill
      directories); <anything> and * match one path segment, and a :N line
      suffix is ignored;
  R3  an inline-code /plugin:name or plugin:name, where plugin is one of
      plugins/*, must name one of its skills, agents or commands.

Blind spots: bare file names (`record.sh`), paths with other prefixes,
anything inside fenced blocks, inline-code tokens with spaces, links with a
title, and paths in a user's own project are not checked.

Usage: check-doc-refs.py [<repo>]   (default: the repo this script is in)
Exit: 0 clean, 1 broken references (file:line: token: reason), 2 cannot run.
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT_DOCS = ["README.md", "CONTRIBUTING.md", "LOCAL-TESTING.md", "AGENTS.md", "CLAUDE.md"]
LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")
PREFIXES = ("plugins/", "scripts/", ".github/", ".claude-plugin/", "docs/")
NS = re.compile(r"^/?([a-z0-9-]+):([a-z0-9-]+)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
LINE_SUFFIX = re.compile(r":\d+(-\d+)?$")


class CannotRun(Exception):
    pass


def exists(bases, token):
    t = token[2:] if token.startswith("./") else token
    t = LINE_SUFFIX.sub("", t)
    pattern = re.sub(r"<[^>]*>", "*", t).rstrip("/")
    for b in bases:
        if "*" in pattern:
            if any(True for _ in b.glob(pattern)):
                return True
        elif (b / pattern).exists():
            return True
    return False


def plugin_dirs(repo):
    pdir = repo / "plugins"
    if not pdir.is_dir():
        raise CannotRun(f"{repo}: no plugins/ directory")
    return sorted(d for d in pdir.iterdir() if d.is_dir() and not d.name.startswith("."))


def plugin_names(dirs):
    out = {}
    for d in dirs:
        names = {s.parent.name for s in d.glob("skills/*/SKILL.md")}
        names |= {a.stem for a in d.glob("agents/*.md")}
        names |= {c.stem for c in d.glob("commands/*.md")}
        out[d.name] = names
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
    out, fence = [], None
    for i, line in enumerate(read(f, rel).splitlines(), 1):
        fm = FENCE.match(line)
        if fence is None and fm:
            fence = fm.group(1)  # opens; closes on the same char, at least as long
            continue
        if fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence) \
                    and not line.strip()[len(fm.group(1)):].strip():
                fence = None
            continue
        for m in LINK.finditer(CODE.sub("", line)):
            t = m.group(1)
            if t.startswith(("#", "<")) or SCHEME.match(t):
                continue
            target = unquote(t.split("#", 1)[0])
            if not target:
                continue
            path = repo / target.lstrip("/") if target.startswith("/") else f.parent / target
            if not path.exists():
                out.append(f"{rel}:{i}: {t}: link target does not exist")
        for m in CODE.finditer(line):
            t = m.group(1)
            if " " in t:
                continue
            bare = t[2:] if t.startswith("./") else t
            if bare.startswith(PREFIXES):
                if not exists(bases, t):
                    out.append(f"{rel}:{i}: {t}: no such path")
                continue
            n = NS.match(t)
            if n and n.group(1) in names and n.group(2) not in names[n.group(1)]:
                out.append(f"{rel}:{i}: {t}: {n.group(1)} has no skill, agent or command named {n.group(2)}")
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
    names = plugin_names(dirs)
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
