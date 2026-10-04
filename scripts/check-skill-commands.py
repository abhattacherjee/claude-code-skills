#!/usr/bin/env python3
"""Statically check the commands written in a plugin's skill text.

Usage: check-skill-commands.py <plugin-dir>...

This reads the text only. It does not run any command. For each
skills/*/SKILL.md and skills/*/references/*.md under each plugin dir it checks:

  - every command in a fenced bash block and in an inline code span goes through
    the review plugin's analyzer: a script path that is not spelled with
    ${CLAUDE_SKILL_DIR}/, ${CLAUDE_PLUGIN_ROOT}/ or <SCRIPTS_DIR>/ (so a bare
    `./scripts/x.sh` fails), a `$VAR` read in a block that did not set it, `$0`;
  - every `${CLAUDE_SKILL_DIR}/...` path exists under that skill's directory, and
    every `${CLAUDE_PLUGIN_ROOT}/...` path under the plugin directory;
  - a command whose first word is such a path points at an executable file;
  - a `cd` or `pushd` into one of those directories is an error: it would move the
    user's shell into the skill directory;
  - a references/*.md file holds no `${CLAUDE_...}` at all (it is read as plain
    text, so the text is never substituted);
  - `<SCRIPTS_DIR>` is defined in SKILL.md by a definition line (a line that names
    `<SCRIPTS_DIR>` and a `${CLAUDE_...}` path), and every `<SCRIPTS_DIR>/name`
    is a file in the directory that line names;
  - fences that are not bash (unlabeled, `text`, `console`, `~~~` and so on) may
    not read a `$VAR`, and may not spell a script with a path that has no accepted
    prefix (`./x.sh`, `scripts/x.sh`, `bash x.sh`, `python3 scripts/y.py`). A line
    that starts with `$ ` in such a fence is checked like a bash command. A bare
    name in a diagram (`detect-mode.sh`) is allowed.

There is one analyzer. It lives in plugins/review/skills/adversarial/scripts/
test_skill_paths.py and is imported from there by path, not copied.

Exit 0 when clean. Exit 1 with one line per problem: `file:line: message`, or
`dir: message` for a plugin with no SKILL.md. Exit 2 on a usage error: no
argument, a missing directory, or an analyzer that is missing or fails to load.
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # do not leave __pycache__ next to the analyzer

REPO = Path(__file__).resolve().parent.parent
ANALYZER = REPO / "plugins" / "review" / "skills" / "adversarial" / "scripts" / "test_skill_paths.py"

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
PROMPT = re.compile(r"^\s*\$\s+(.*)$")
# Fence languages whose content can be a command. A json or yaml fence is data.
COMMAND_LANGS = {"", "text", "txt", "console", "terminal", "shell-session", "sh-session", "plain", "plaintext"}
INTERPRETER_BEFORE = re.compile(r"\b(?:bash|sh|zsh|python3?|source)\s+(?:-\S+\s+)*$")
CD_ENV = re.compile(r"^(?:cd|pushd)\b.*\$\{CLAUDE_(?:SKILL_DIR|PLUGIN_ROOT)\}")
SCRIPTS_DIR_USE = re.compile(r"<SCRIPTS_DIR>/([A-Za-z0-9_.-]+)")
SCRIPTS_DIR_BARE = re.compile(r"<SCRIPTS_DIR>(?!/)")
ENV_PATH_TEXT = re.compile(r"\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}/([A-Za-z0-9_./-]*)")


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


def parse_fences(text):
    """Return [(lang, first content line number, [lines], first fence line, last fence line)].

    Handles ``` and ~~~ fences of any length. A fence closes on the same character,
    at least as long, with nothing else on the line. An unclosed fence runs to the end.
    """
    out, cur = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if cur is None:
            m = FENCE.match(line)
            if m:
                cur = {"char": m.group(2)[0], "len": len(m.group(2)), "lang": m.group(3).lower(),
                       "start": n + 1, "open": n, "lines": []}
        else:
            m = FENCE.match(line)
            if m and m.group(2)[0] == cur["char"] and len(m.group(2)) >= cur["len"] \
                    and line.strip().strip(cur["char"]) == "":
                out.append((cur["lang"], cur["start"], cur["lines"], cur["open"], n))
                cur = None
            else:
                cur["lines"].append(line)
    if cur is not None:
        out.append((cur["lang"], cur["start"], cur["lines"], cur["open"], len(text.splitlines())))
    return out


def prose_only(text, fences):
    """The text with every fenced line (fence lines too) blanked, so line numbers still match."""
    lines = text.splitlines()
    for _, _, _, first, last in fences:
        for i in range(first, last + 1):
            if i - 1 < len(lines):
                lines[i - 1] = ""
    return "\n".join(lines)


def env_exec_problem(a, word, line, skill_dir, plugin_dir):
    m = a.FIRST_ENV.match(word)
    if not m:
        return []
    root = skill_dir if m.group(1) == "SKILL_DIR" else plugin_dir
    target = root / m.group(2)
    # Only a script is run. A path to a document in a span (`${CLAUDE_SKILL_DIR}/references/x.md`) is not.
    is_script = m.group(2).startswith("scripts/") or m.group(2).endswith((".sh", ".py"))
    if is_script and target.is_file() and not os.access(str(target), os.X_OK):
        return [(line, "${CLAUDE_%s}/%s starts a command but is not executable" % (m.group(1), m.group(2)))]
    return []


def cd_problems(a, line_text, line_no):
    found = []
    for cmd, _ in a.top_level_commands(a.strip_line(line_text)):
        _, rest = a.command_parts(cmd)
        if CD_ENV.match(rest):
            found.append((line_no, "`cd` into ${CLAUDE_...} moves your shell into the skill directory; "
                                   "call the script by its full path instead"))
    return found


def other_fence_problems(a, lang, start, lines):
    """Rules for a fence that is not bash: unlabeled, text, console, markdown, ..."""
    found = []
    prompt_lines = []
    for off, line in enumerate(lines):
        stripped = a.strip_line(line)
        bare = stripped
        for tok in a.ENV_TOKENS:
            bare = bare.replace(tok, "")
        if a.VAR_READ.search(bare):
            found.append((start + off, "a %s fence reads a shell variable: %s" % (
                repr(lang) if lang else "unlabeled", line.strip()[:60])))
        for m in (a.SCRIPT_TOKEN.finditer(stripped) if lang in COMMAND_LANGS else []):
            tok = m.group(0)
            if any(tok.startswith(p + "/") for p in a.SCRIPT_PREFIXES):
                continue
            if "/" in tok or INTERPRETER_BEFORE.search(stripped[:m.start()]):
                found.append((start + off, "script `%s` has no ${CLAUDE_...} or <SCRIPTS_DIR> path in front "
                                           "(in a %s fence)" % (tok, repr(lang) if lang else "unlabeled")))
        pm = PROMPT.match(line)
        if pm:
            prompt_lines.append((start + off, pm.group(1)))
    # A "$ cmd" line is a command, so it gets the full bash analysis.
    for n, cmd in prompt_lines:
        for _, msg in a.block_problems([cmd]):
            found.append((n, msg))
    return found


def check_doc(a, path, skill_dir, plugin_dir, is_reference, scripts_dir):
    """Return the problems for one markdown file as (line, message) pairs."""
    text = path.read_text(encoding="utf-8")
    fences = parse_fences(text)
    found = []

    # 1. Bash fences: the analyzer, the executable check, the cd rule.
    for lang, start, lines, _, _ in fences:
        if lang in a.BASH_LANGS:
            for off, msg in a.block_problems(lines):
                found.append((start + off, msg))
            for off, line in enumerate(lines):
                for w in a.first_words(line):
                    found.extend(env_exec_problem(a, w, start + off, skill_dir, plugin_dir))
                found.extend(cd_problems(a, line, start + off))
        else:
            found.extend(other_fence_problems(a, lang, start, lines))

    # 2. Inline code spans in the prose.
    prose = prose_only(text, fences)
    for n, span in a.spans_with_lines(prose):
        for msg in a.span_problems("`%s`" % span):
            found.append((n, msg))
        for w in a.first_words(span):
            found.extend(env_exec_problem(a, w, n, skill_dir, plugin_dir))
        found.extend(cd_problems(a, span, n))

    for n, line in enumerate(text.splitlines(), 1):
        # 3. A reference is read as plain text: no ${CLAUDE_...} is ever substituted.
        if is_reference and "${CLAUDE_" in line:
            found.append((n, "${CLAUDE_...} in a references file is never substituted; "
                             "use <SCRIPTS_DIR>, which SKILL.md defines"))
        # 4. Every ${CLAUDE_*}/path must exist. A trailing . , ; : ) is sentence punctuation.
        for m in ENV_PATH_TEXT.finditer(line):
            root = skill_dir if m.group(1) == "SKILL_DIR" else plugin_dir
            rel = m.group(2).rstrip(".,;:)")
            if not (root / rel).exists():
                found.append((n, "${CLAUDE_%s}/%s does not exist" % (m.group(1), rel)))
        # 5. <SCRIPTS_DIR>/name must be a file in the directory SKILL.md defines.
        for name in SCRIPTS_DIR_USE.findall(line):
            if scripts_dir is None:
                found.append((n, "uses <SCRIPTS_DIR>/%s but SKILL.md has no definition line for <SCRIPTS_DIR>" % name))
            elif not (scripts_dir / name).is_file():
                found.append((n, "<SCRIPTS_DIR>/%s does not exist in %s" % (name, scripts_dir)))
    return found


def scripts_dir_definition(a, skill_md_text, skill_dir, plugin_dir):
    """The directory <SCRIPTS_DIR> stands for, from a definition line in SKILL.md, or None.

    A definition line names <SCRIPTS_DIR> (not as <SCRIPTS_DIR>/name) and a
    ${CLAUDE_...} path. A line that only uses <SCRIPTS_DIR>/x does not define it.
    """
    for line in skill_md_text.splitlines():
        if SCRIPTS_DIR_BARE.search(line):
            m = ENV_PATH_TEXT.search(line)
            if m:
                root = skill_dir if m.group(1) == "SKILL_DIR" else plugin_dir
                return root / m.group(2).rstrip(".,;:)`")
    return None


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
        scripts_dir = scripts_dir_definition(a, skill_text, skill_dir, plugin_dir)
        for doc in docs:
            files += 1
            try:
                for line, msg in check_doc(a, doc, skill_dir, plugin_dir, doc != skill_md, scripts_dir):
                    problems.append("%s:%d: %s" % (shown(doc), line, msg))
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
    print("OK: %d file(s) in %d plugin(s); every script path exists and is executable, and no command "
          "reads a variable it did not set (static check, nothing was run)" % (files, len(dirs)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
