#!/usr/bin/env python3
"""Check that every command in a plugin's skill text runs as written.

Usage: check-skill-commands.py <plugin-dir>...

For each skills/*/SKILL.md and skills/*/references/*.md under each plugin dir:

  - every command in a fenced bash block and in an inline code span is run through
    the review plugin's analyzer (a bare `./scripts/x.sh`, a `$VAR` that an earlier
    block set, `$0`: all fail);
  - every `${CLAUDE_SKILL_DIR}/...` path must exist under that skill's directory,
    and every `${CLAUDE_PLUGIN_ROOT}/...` path under the plugin directory;
  - a command whose first word is such a path must point at an executable file;
  - a file that writes `<SCRIPTS_DIR>/...` needs a SKILL.md that defines `<SCRIPTS_DIR>`.

There is one analyzer. It lives in plugins/review/skills/adversarial/scripts/
test_skill_paths.py and is imported from there by path, not copied.

Exit 0 when clean, 1 with one `file:line: message` line per problem, 2 on a usage
error (no argument, a missing directory, or the analyzer file is missing).
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # do not leave __pycache__ next to the analyzer

REPO = Path(__file__).resolve().parent.parent
ANALYZER = REPO / "plugins" / "review" / "skills" / "adversarial" / "scripts" / "test_skill_paths.py"


RELATIVE_SCRIPT = re.compile(r"^\.{1,2}/\S*\.(?:sh|py)$")


def load_analyzer():
    if not ANALYZER.is_file():
        sys.stderr.write("error: analyzer not found: %s\n" % ANALYZER)
        sys.exit(2)
    try:
        spec = importlib.util.spec_from_file_location("skill_path_analyzer", str(ANALYZER))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # a broken analyzer is an environment error, not "problems found"
        sys.stderr.write("error: cannot load the analyzer %s: %s\n" % (ANALYZER, exc))
        sys.exit(2)
    return mod


def shown(path):
    """Path relative to the cwd, or absolute when it is outside the cwd."""
    rel = os.path.relpath(str(path), os.getcwd())
    return str(path) if rel.startswith("..") else rel


def check_doc(a, path, skill_dir, plugin_dir):
    """Return the problems for one markdown file as (line, message) pairs."""
    text = path.read_text(encoding="utf-8")
    found = []

    # Fenced bash blocks.
    for lang, start, lines in a.fenced_blocks(text):
        if lang == "":
            # An unlabeled fence may be a diagram, so it is not analyzed like bash.
            # A line that starts with a relative script path is still a command.
            for off, line in enumerate(lines):
                words = line.split()
                if words and RELATIVE_SCRIPT.match(words[0]):
                    found.append((start + off, "script `%s` is a relative path in an unlabeled block" % words[0]))
            continue
        if lang not in a.BASH_LANGS:
            continue
        for off, msg in a.block_problems(lines):
            found.append((start + off, msg))
        for off, line in enumerate(lines):
            for w in a.first_words(line):
                found.extend(exec_problems(a, w, start + off, skill_dir, plugin_dir))

    # Inline code spans in the prose (fenced lines blanked, line numbers kept).
    prose = a.doc_prose(path)
    for n, span in a.spans_with_lines(prose):
        for msg in a.span_problems("`%s`" % span):
            found.append((n, msg))
        for w in a.first_words(span):
            found.extend(exec_problems(a, w, n, skill_dir, plugin_dir))

    # Every ${CLAUDE_*}/path, anywhere in the file, must exist.
    for n, line in enumerate(text.splitlines(), 1):
        for m in a.ENV_PATH.finditer(line):
            root = skill_dir if m.group(1) == "SKILL_DIR" else plugin_dir
            rel = m.group(2).rstrip(".,;:)")
            if not (root / rel).exists():
                found.append((n, "${CLAUDE_%s}/%s does not exist" % (m.group(1), rel)))
    return found


def exec_problems(a, word, line, skill_dir, plugin_dir):
    m = a.FIRST_ENV.match(word)
    if not m:
        return []
    root = skill_dir if m.group(1) == "SKILL_DIR" else plugin_dir
    target = root / m.group(2)
    if target.is_file() and not os.access(str(target), os.X_OK):
        return [(line, "${CLAUDE_%s}/%s starts a command but is not executable" % (m.group(1), m.group(2)))]
    return []


def check_plugin(a, plugin_dir):
    problems, files = [], 0
    skill_mds = sorted(plugin_dir.glob("skills/*/SKILL.md"))
    if not skill_mds:
        # Zero files checked must not read as a pass.
        return ["%s: no skills/*/SKILL.md found, nothing to check" % shown(plugin_dir)], 0
    for skill_md in skill_mds:
        skill_dir = skill_md.parent
        docs = [skill_md] + sorted((skill_dir / "references").glob("*.md"))
        try:
            skill_text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append("%s:1: cannot read file: %s" % (shown(skill_md), exc))
            files += 1
            continue
        for doc in docs:
            files += 1
            try:
                for line, msg in check_doc(a, doc, skill_dir, plugin_dir):
                    problems.append("%s:%d: %s" % (shown(doc), line, msg))
                if doc != skill_md and "<SCRIPTS_DIR>" in doc.read_text(encoding="utf-8") \
                        and "<SCRIPTS_DIR>" not in skill_text:
                    problems.append("%s:1: uses <SCRIPTS_DIR> but %s never defines it" % (shown(doc), shown(skill_md)))
            except (OSError, UnicodeDecodeError) as exc:
                # Exit 1 means "problems found". Say so, rather than dying with a traceback.
                problems.append("%s:1: cannot read file: %s" % (shown(doc), exc))
    return problems, files


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print("usage: check-skill-commands.py <plugin-dir>...")
        return 0
    if not argv:
        sys.stderr.write("usage: check-skill-commands.py <plugin-dir>...\n")
        return 2
    dirs = []
    for arg in argv:
        d = Path(arg)
        if not d.is_dir():
            sys.stderr.write("error: not a directory: %s\n" % arg)
            return 2
        dirs.append(d.resolve())
    a = load_analyzer()
    problems, files = [], 0
    for d in dirs:
        p, n = check_plugin(a, d)
        problems.extend(p)
        files += n
    if problems:
        print("\n".join(problems))
        return 1
    print("OK: %d file(s) in %d plugin(s), every command runs as written" % (files, len(dirs)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
