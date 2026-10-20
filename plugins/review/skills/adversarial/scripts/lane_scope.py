#!/usr/bin/env python3
"""lane_scope.py — classify changed repo-relative paths for the review lane.

Usage: lane_scope.py --files <file>

Reads one path per line, ignoring blank lines. Prints light only when every
path is eligible; empty input and code paths require full review.
Only documentation and images under docs/, documentation extensions anywhere,
lockfiles, and requirements*.txt are light (agent code rules still win).
Manifests require full review because they can carry executable content.
Exit codes: 0 on success; 2 on a usage error or unreadable input.
"""
import argparse
import fnmatch
import sys
from pathlib import Path

LIGHT_BASENAME_GLOBS = (
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "yarn.lock", "bun.lockb", "requirements*.txt", "poetry.lock", "uv.lock",
    "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock", "*.md", "*.mdx", "*.rst",
)
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".png", ".jpg", ".jpeg",
                  ".gif", ".svg", ".webp"}
CODE_COMPONENTS = {"agents", "skills", "commands"}
# Agent instruction files steer models, so they are code too.
CODE_BASENAMES = {"SKILL.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md"}


def classify(paths) -> str:
    """Return light only for a non-empty list of entirely eligible paths."""
    if not paths:
        return "full"
    for path in paths:
        parts = path.split("/")
        name = parts[-1]
        # These Markdown files are code, even when they live under docs.
        if name in CODE_BASENAMES or CODE_COMPONENTS.intersection(parts):
            return "full"
        docs_content = parts[0] == "docs" and Path(name).suffix in DOC_EXTENSIONS
        if not docs_content and not any(fnmatch.fnmatchcase(name, glob)
                                        for glob in LIGHT_BASENAME_GLOBS):
            return "full"
    return "light"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", required=True, help="file containing one repo-relative path per line")
    args = parser.parse_args(argv)
    try:
        text = Path(args.files).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print("lane_scope: cannot read %s: %s" % (args.files, exc), file=sys.stderr)
        return 2
    paths = [line for line in text.splitlines() if line.strip()]
    print(classify(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
