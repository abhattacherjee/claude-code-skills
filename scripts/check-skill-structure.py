#!/usr/bin/env python3
"""check-skill-structure.py — plugin skills follow the skill authoring layout rules (#210).

Checks every plugins/*/skills/*/SKILL.md and the .md files beside it:
  S1  the SKILL.md body (the lines after the closing --- of the frontmatter)
      is under 500 lines;
  S2  every .md file under the skill directory, other than SKILL.md,
      README.md and CHANGELOG.md, is named in SKILL.md by its path relative
      to the skill directory (`references/x.md`, `./references/x.md`,
      `${CLAUDE_SKILL_DIR}/references/x.md` or a markdown link), or its file
      name appears in a file under the skill's scripts/ (a script reads it),
      so Claude reaches it one level deep from SKILL.md;
  S3  every such file over 100 lines has a `## Contents` or
      `## Table of contents` heading within its first 30 lines.

Blind spots (not checked): whether the place SKILL.md names a file tells
Claude when to read it; whether a Contents list matches the file's headings;
files that are not .md; a scripts/ file that names the file but never opens it.

Usage: check-skill-structure.py [<repo>]   (default: the repo this script is in)
Exit: 0 clean, 1 violations (one line each: path: rule: reason), 2 cannot run.
"""
import re
import sys
from pathlib import Path

MAX_BODY = 500        # S1: the body must be shorter than this
TOC_MIN_LINES = 100   # S3: files longer than this need a Contents list
TOC_WITHIN = 30       # S3: ...in this many first lines
EXCLUDED = {"SKILL.md", "README.md", "CHANGELOG.md"}
TOC = re.compile(r"^##\s+(contents|table of contents)\s*$", re.I)


def body_lines(text):
    """Lines after the frontmatter's closing ---, or all lines if there is none."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return len(lines) - i - 1
    return len(lines)


def named_in(text, rel):
    """True when text names rel as a path relative to the skill directory."""
    # Before rel: the start, ./, ${CLAUDE_SKILL_DIR}/ or a char that cannot be
    # part of a longer path. After it: a char that cannot extend the name.
    pat = r"(?:^|\./|\$\{CLAUDE_SKILL_DIR\}/|[^\w./${}-])" + re.escape(rel) + r"(?![\w-])"
    return re.search(pat, text, re.M) is not None


def read_by_script(text, name):
    """True when a script names the file: "$DIR/name", 'references/name', ..."""
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])", text) is not None


def check_skill(skill, repo):
    out = []
    skill_md = skill / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    shown = skill.relative_to(repo).as_posix()
    n = body_lines(text)
    if n >= MAX_BODY:
        out.append(f"{shown}/SKILL.md: S1: body is {n} lines (must be under {MAX_BODY})")

    scripts = skill / "scripts"
    script_text = ""
    if scripts.is_dir():
        for f in sorted(scripts.rglob("*")):
            if f.is_file():
                try:
                    script_text += f.read_text(encoding="utf-8") + "\n"
                except UnicodeDecodeError:
                    continue

    for md in sorted(skill.rglob("*.md")):
        if md.name in EXCLUDED or not md.is_file():
            continue
        rel = md.relative_to(skill).as_posix()
        if not (named_in(text, rel) or read_by_script(script_text, md.name)):
            out.append(f"{shown}/{rel}: S2: not named in SKILL.md or read by a script in scripts/")
        lines = md.read_text(encoding="utf-8").splitlines()
        if len(lines) > TOC_MIN_LINES and not any(TOC.match(l) for l in lines[:TOC_WITHIN]):
            out.append(f"{shown}/{rel}: S3: {len(lines)} lines with no '## Contents' heading in the first {TOC_WITHIN} lines")
    return out


def main(argv):
    repo = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    plugins = repo / "plugins"
    if not plugins.is_dir():
        print(f"check-skill-structure.py: cannot run: {plugins} is not a directory", file=sys.stderr)
        return 2
    skills = sorted(p.parent for p in plugins.glob("*/skills/*/SKILL.md"))
    if not skills:
        print(f"check-skill-structure.py: cannot run: no plugins/*/skills/*/SKILL.md under {repo}", file=sys.stderr)
        return 2
    problems = []
    for skill in skills:
        problems += check_skill(skill, repo)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
