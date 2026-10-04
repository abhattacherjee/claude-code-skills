#!/usr/bin/env python3
"""Path and variable checks for the review plugin's skill text.

The Bash tool keeps no shell variables between calls. A fenced bash block that
reads $SCRIPTS, $ADV_REVIEW or $RUN_DIR, which an earlier block set, runs with
an empty value. These tests read every fenced bash block in both SKILL.md files
and in skills/deep/references/*.md and fail on such a read.

Run: python3 test_skill_paths.py -v
"""
import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]  # plugins/review
SKILLS = PLUGIN / "skills"
AGENTS = PLUGIN / "agents"

DOC_FILES = [
    SKILLS / "adversarial" / "SKILL.md",
    SKILLS / "deep" / "SKILL.md",
] + sorted((SKILLS / "deep" / "references").glob("*.md"))

BASH_LANGS = {"bash", "sh", "shell", "zsh"}

# Variables a command may read without setting: the user's environment. The two
# CLAUDE_* names are not here. Claude Code substitutes them as text in SKILL.md and
# does not export them to the shell, so only the exact braced text below is allowed.
ALLOWED_READS = {"HOME", "PATH", "TMPDIR", "GH_HOST"}
ENV_TOKENS = ("${CLAUDE_SKILL_DIR}", "${CLAUDE_PLUGIN_ROOT}")
# A script named in a command must start with one of these, then a slash.
# <SCRIPTS_DIR> is for the deep references, which are read as plain text.
SCRIPT_PREFIXES = ENV_TOKENS + ("<SCRIPTS_DIR>",)

# Inline spans that may read a variable: documentation about the variable itself.
SPAN_ALLOW = {
    "$XDG_CACHE_HOME/adversarial-review/codex-isolation-<version>-<key>.ok",
    "$RUN_DIR",
}

FENCE_OPEN = re.compile(r"^(\s*)```([A-Za-z0-9_-]*)\s*$")
FENCE_CLOSE = re.compile(r"^\s*```\s*$")
VAR_READ = re.compile(r"\$(?:\{[!#]?([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))")
FOR_VAR = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
SEG_SPLIT = re.compile(r"\s*(?:&&|\|\||[;&|()])\s*")
LEAD_KEYWORD = re.compile(r"(?:if|then|else|elif|do|while|until|!|time)\s+")
LEAD_DECL = re.compile(r"(?:export|local|readonly|declare(?:\s+-[A-Za-z]+)?)\s+")
READ_CMD = re.compile(r"read\s+((?:-[A-Za-z]+\s+)*)([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*)")
ZERO = re.compile(r"\$(?:0\b|\{0\})")
SCRIPT_TOKEN = re.compile(r"[^\s\"'|;&()=]*?[A-Za-z0-9_-]\.(?:sh|py)(?![\w.-])")
ENV_PATH = re.compile(r"\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}/([A-Za-z0-9_./-]*)")
FIRST_ENV = re.compile(r"^\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}/([A-Za-z0-9_./-]+)$")
SPAN = re.compile(r"(?<!`)`([^`\n]+(?:\n[^`\n]+)?)`(?!`)")
AGENT_REF = re.compile(r"(?<![\w:/-])review:([a-z][a-z-]*)")


def fenced_blocks(text):
    """Yield (lang, first_line_number, [lines]) for each fenced block."""
    out, cur, lang, start = [], None, "", 0
    for n, line in enumerate(text.splitlines(), 1):
        if cur is None:
            m = FENCE_OPEN.match(line)
            if m:
                cur, lang, start = [], m.group(2).lower(), n + 1
        elif FENCE_CLOSE.match(line):
            out.append((lang, start, cur))
            cur = None
        else:
            cur.append(line)
    if cur is not None:
        out.append((lang, start, cur))  # unclosed block: still check it
    return out


def strip_line(line):
    """Drop `'...'` text and `#` comments, but only outside double quotes, so
    `"it's done" "$X"` and `"Fixes #12 $X"` keep their reads. An unclosed single
    quote hides nothing."""
    out, i, in_double = [], 0, False
    while i < len(line):
        c = line[i]
        if in_double:
            if c == "\\" and i + 1 < len(line):
                out.append(line[i:i + 2])
                i += 2
                continue
            if c == '"':
                in_double = False
        else:
            if c == "'":
                j = line.find("'", i + 1)
                if j < 0:
                    out.append(line[i:])
                    break
                out.append("''")
                i = j + 1
                continue
            if c == "#" and (i == 0 or line[i - 1].isspace()):
                break
            if c == '"':
                in_double = True
        out.append(c)
        i += 1
    return "".join(out)


def word_end(s, i):
    """Index just past the shell word that starts at s[i]: stop at whitespace outside
    quotes and ( ) groups, so `X="$(gh pr view "a b")"` is one word."""
    depth, in_double = 0, False
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == '"':
            in_double = not in_double
        elif c == "(" and not in_double or c == "(" and s[i - 1:i] == "$":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif c.isspace() and depth == 0 and not in_double:
            break
        i += 1
    return i


ASSIGN_HEAD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\+?=")


def command_parts(segment):
    """Return (names assigned by leading NAME=value words, the rest of the command)."""
    s, names = segment.strip(), []
    while True:
        for pat in (LEAD_KEYWORD, LEAD_DECL):
            m = pat.match(s)
            if m:
                s = s[m.end():]
                break
        else:
            m = ASSIGN_HEAD.match(s)
            if not m:
                return names, s
            names.append(m.group(1))
            s = s[word_end(s, m.end()):].lstrip()


def top_level_commands(line):
    """Split one line into [(command text, piped)] at ; && || | and a lone &, outside
    quotes and outside ( ) groups. Text inside a group stays in its command, so its
    reads are checked, but the command is marked as a group (see below)."""
    cmds, buf, depth, in_double, i = [], [], 0, False, 0
    piped_before = False

    def flush(piped_after):
        nonlocal buf, piped_before
        text = "".join(buf).strip()
        if text:
            cmds.append((text, piped_before or piped_after))
        buf = []
        piped_before = piped_after

    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            buf.append(line[i:i + 2])
            i += 2
            continue
        if c == '"':
            in_double = not in_double
        elif c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and not in_double:
            two = line[i:i + 2]
            if two in ("&&", "||"):
                flush(False)
                i += 2
                continue
            if c == ";":
                flush(False)
                i += 1
                continue
            if c == "|":
                flush(True)
                i += 1
                continue
            if c == "&" and not (i > 0 and line[i - 1] in "<>") and not line[i + 1:i + 2].isdigit():
                flush(False)
                i += 1
                continue
        buf.append(c)
        i += 1
    flush(False)
    return cmds


def names_set_by(cmd, piped):
    """The names one command sets for the commands after it. A name counts only when
    the whole command is the assignment (or an export/local/readonly/declare of it),
    or the command is `read NAME` or `for NAME in`, and it is not in a pipeline or a
    ( ) group, which run in a subshell. `X=v cmd` sets X for cmd only."""
    if piped or cmd.startswith("("):
        return set()
    names = set(FOR_VAR.findall(cmd)) if re.match(r"(?:(?:do|then)\s+)?for\s", cmd) else set()
    got, rest = command_parts(cmd)
    if not rest:
        names.update(got)
    m = READ_CMD.match(rest)
    if m:
        names.update(m.group(2).split())
    return names


def logical_lines(lines):
    """Join backslash-continued lines. Yields (offset of the first line, text)."""
    out, cur, start = [], None, 0
    for i, raw in enumerate(lines):
        if cur is None:
            cur, start = raw, i
        else:
            cur += " " + raw.strip()
        if cur.rstrip().endswith("\\"):
            cur = cur.rstrip()[:-1]
            continue
        out.append((start, cur))
        cur = None
    if cur is not None:
        out.append((start, cur))
    return out


def block_problems(lines):
    """Return [(offset, message)] for one command block (offset is 0-based)."""
    assigned = set()
    problems = []
    for i, raw in logical_lines(lines):
        l = strip_line(raw)
        if ZERO.search(l):
            problems.append((i, '`$0` is the shell, not the skill; never use `dirname "$0"`'))
        for m in SCRIPT_TOKEN.finditer(l):
            tok = m.group(0)
            if not any(tok.startswith(p + "/") for p in SCRIPT_PREFIXES):
                problems.append((i, "script `%s` has no ${CLAUDE_...} or <SCRIPTS_DIR> path in front" % tok))
        # Commands run in order. A command reads what earlier commands set, so a read
        # before the assignment, on this line or an earlier one, is a read of nothing.
        for cmd, piped in top_level_commands(l):
            bare = cmd
            for tok in ENV_TOKENS:
                bare = bare.replace(tok, "")
            for m in VAR_READ.finditer(bare):
                name = m.group(1) or m.group(2)
                if name not in assigned and name not in ALLOWED_READS:
                    problems.append((i, "reads $%s, which this block never sets" % name))
            assigned |= names_set_by(cmd, piped)
    return problems


def spans_with_lines(text):
    """Yield (line number, span text) for each `code span`. A span may wrap over one
    newline; the newline becomes a space."""
    for m in SPAN.finditer(text):
        yield text.count("\n", 0, m.start()) + 1, m.group(1).replace("\n", " ")


def span_problems(prose):
    """Check each `code span` in some prose like a command."""
    out = []
    for _, span in spans_with_lines(prose):
        if span in SPAN_ALLOW:
            continue
        is_command = bool(re.search(r"\s", span))  # a lone `name.sh` just names a script
        for _, msg in block_problems([span]):
            if msg.startswith("script ") and not is_command:
                continue
            out.append("`%s`: %s" % (span[:70], msg))
    return out


def prose_lines(text):
    """Yield (line_number, line) for every line outside a fenced block."""
    inside = False
    for n, line in enumerate(text.splitlines(), 1):
        if inside:
            if FENCE_CLOSE.match(line):
                inside = False
        elif FENCE_OPEN.match(line):
            inside = True
        else:
            yield n, line


def doc_problems(path):
    text = path.read_text(encoding="utf-8")
    found = []
    for lang, start, lines in fenced_blocks(text):
        if lang not in BASH_LANGS:
            continue
        for off, msg in block_problems(lines):
            found.append("%s:%d: %s" % (path.relative_to(PLUGIN), start + off, msg))
    return found


def doc_prose(path):
    """The file's text with every fenced line blanked, so line numbers still match."""
    keep = dict(prose_lines(path.read_text(encoding="utf-8")))
    n = len(path.read_text(encoding="utf-8").splitlines())
    return "\n".join(keep.get(i, "") for i in range(1, n + 1))


def doc_span_problems(path):
    found = []
    for n, span in spans_with_lines(doc_prose(path)):
        for msg in span_problems("`%s`" % span):
            found.append("%s:%d: %s" % (path.relative_to(PLUGIN), n, msg))
    return found


def first_words(line):
    """The first word of each command on a line, quotes removed."""
    words = []
    for seg in SEG_SPLIT.split(strip_line(line)):
        _, rest = command_parts(seg)
        if rest:
            words.append(rest.split()[0].strip("\"'"))
    return words


def first_word_env_paths(path):
    """Yield (where, SKILL_DIR|PLUGIN_ROOT, relative path) when a command's first word
    is a ${CLAUDE_...} path. Those are run directly, so they need the exec bit."""
    text = path.read_text(encoding="utf-8")
    name = path.relative_to(PLUGIN)
    for lang, start, lines in fenced_blocks(text):
        if lang in BASH_LANGS:
            for off, line in enumerate(lines):
                for w in first_words(line):
                    m = FIRST_ENV.match(w)
                    if m:
                        yield "%s:%d" % (name, start + off), m.group(1), m.group(2)
    for n, span in spans_with_lines(doc_prose(path)):
        for w in first_words(span):
            m = FIRST_ENV.match(w)
            if m:
                yield "%s:%d" % (name, n), m.group(1), m.group(2)


def skill_dir_of(path):
    rel = path.relative_to(SKILLS)
    return SKILLS / rel.parts[0]


def unresolved_env_paths(path):
    text = path.read_text(encoding="utf-8")
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in ENV_PATH.finditer(line):
            root = skill_dir_of(path) if m.group(1) == "SKILL_DIR" else PLUGIN
            rel = m.group(2).rstrip(".,;:)")
            if not (root / rel).exists():
                found.append("%s:%d: ${CLAUDE_%s}/%s does not exist" % (
                    path.relative_to(PLUGIN), n, m.group(1), rel))
    return found


class BlockAnalyzerSelfTest(unittest.TestCase):
    """The analyzer must flag the bad shapes and pass the good ones, or the doc
    tests below could be green by never matching anything."""

    def msgs(self, *lines):
        return [m for _, m in block_problems(list(lines))]

    def test_flags_a_variable_set_only_in_an_earlier_block(self):
        got = self.msgs('"$SCRIPTS/pick-adversary.sh" --x')
        self.assertTrue(any("$SCRIPTS" in m for m in got), got)

    def test_flags_braced_reads(self):
        got = self.msgs('echo "${RUN_DIR}/r1.json"')
        self.assertTrue(any("$RUN_DIR" in m for m in got), got)

    def test_flags_dirname_of_zero(self):
        got = self.msgs('S="$(dirname "$0")/scripts"')
        self.assertTrue(any("$0" in m for m in got), got)

    def test_flags_bare_script_names(self):
        got = self.msgs("codex-review.sh --mode find")
        self.assertTrue(any("codex-review.sh" in m for m in got), got)

    def test_flags_a_read_that_comes_before_the_assignment(self):
        got = self.msgs('echo "$X"', 'X=1')
        self.assertTrue(any("$X" in m for m in got), got)

    def test_a_prose_word_read_does_not_count_as_setting_a_variable(self):
        got = self.msgs('git log --oneline  # then read the log', 'echo "$the"')
        self.assertTrue(any("$the" in m for m in got), got)
        got = self.msgs('echo read the log "$the"')
        self.assertTrue(any("$the" in m for m in got), got)

    def test_passes_a_variable_set_in_the_same_block(self):
        self.assertEqual(self.msgs('X=$(mktemp -d)', 'echo "$X"'), [])

    def test_passes_loop_and_read_variables(self):
        self.assertEqual(self.msgs('for f in a b; do echo "$f"; done'), [])
        self.assertEqual(self.msgs('while read -r line; do echo "$line"; done'), [])

    def test_passes_allowed_names_and_full_paths(self):
        self.assertEqual(
            self.msgs('"${CLAUDE_SKILL_DIR}/scripts/detect-mode.sh" "$HOME"'), [])

    def test_ignores_comments_single_quotes_and_positionals(self):
        self.assertEqual(self.msgs('# uses $SCRIPTS here', "echo '$SCRIPTS'", 'echo "$1 $? $$"'), [])


class AnalyzerFixWave1(unittest.TestCase):
    """Cases a reviewer showed the first analyzer got wrong (PR #170, fix wave 1)."""

    def msgs(self, *lines):
        return [m for _, m in block_problems(list(lines))]

    def flagged(self, name, *lines):
        got = self.msgs(*lines)
        self.assertTrue(any("$" + name in m for m in got), got)

    def test_claude_names_are_allowed_only_in_the_exact_braced_form(self):
        self.assertEqual(self.msgs('"${CLAUDE_SKILL_DIR}/scripts/sink.sh" --x'), [])
        self.assertEqual(self.msgs('python3 "${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts/pr-audit.py" x'), [])
        self.flagged("CLAUDE_SKILL_DIR", 'echo "$CLAUDE_SKILL_DIR"')
        self.flagged("CLAUDE_SKILL_DIR", 'echo "${CLAUDE_SKILL_DIR:-}"')
        self.flagged("CLAUDE_PLUGIN_ROOT", 'echo "$CLAUDE_PLUGIN_ROOT"')

    def test_every_script_token_needs_an_allowed_prefix(self):
        for bad in ("scripts/x.sh --a", "./scripts/x.sh --a", "~/scripts/x.sh --a",
                    '"$HOME/x.sh" --a', "python3 pr-audit.py post", "python3 scripts/pr-audit.py post"):
            got = self.msgs(bad)
            self.assertTrue(any(".sh" in m or ".py" in m for m in got), (bad, got))
        for good in ('"${CLAUDE_SKILL_DIR}/scripts/x.sh" --a', '"<SCRIPTS_DIR>/pr-audit.py" post'):
            self.assertEqual([m for m in self.msgs(good) if "script" in m], [], good)

    def test_a_single_quote_inside_double_quotes_does_not_hide_a_read(self):
        self.flagged("RUN_DIR", 'gh pr comment --body "it\'s done" "$RUN_DIR/x"')

    def test_a_hash_inside_double_quotes_is_not_a_comment(self):
        self.flagged("RUN_DIR", 'gh pr comment --body "Fixes #12 $RUN_DIR"')

    def test_a_real_comment_and_single_quotes_outside_double_quotes_still_hide(self):
        self.assertEqual(self.msgs("echo hi  # uses $RUN_DIR", "echo '$RUN_DIR'"), [])

    def test_a_flag_value_is_not_an_assignment(self):
        self.flagged("state", "gh api -f state=open", 'echo "$state"')

    def test_a_whole_command_assignment_still_counts(self):
        self.assertEqual(self.msgs('X=1; echo "$X"'), [])
        self.assertEqual(self.msgs('A=1 && B=2', 'echo "$A$B"'), [])
        self.assertEqual(self.msgs('if true; then Y=2; fi', 'echo "$Y"'), [])
        self.assertEqual(self.msgs('export Z=3', 'echo "$Z"'), [])
        self.assertEqual(self.msgs('X=$(mktemp -d)', 'echo "$X"'), [])
        self.assertEqual(self.msgs('read A B', 'echo "$A$B"'), [])
        self.assertEqual(self.msgs('for f in a b; do echo "$f"; done'), [])

    def test_a_prefix_assignment_is_scoped_to_its_command(self):
        # `X=v cmd` sets X for cmd only; the shell expands "$X" in cmd's args first.
        self.flagged("X", 'X=v echo "$X"')
        self.flagged("A", 'A=1 B=2 true', 'echo "$A$B"')

    def test_a_read_in_a_pipeline_does_not_set_the_variable(self):
        self.flagged("X", 'echo v | read X', 'echo "$X"')

    def test_a_subshell_assignment_does_not_set_the_variable(self):
        self.flagged("X", '(X=1)', 'echo "$X"')
        self.flagged("X", 'echo "$(X=1)"', 'echo "$X"')

    def test_a_read_earlier_on_the_same_line_is_not_covered_by_a_later_assignment(self):
        self.flagged("X", 'echo "$X"; X=1')
        self.flagged("X", 'echo "$X" && X=1')

    def test_a_value_may_read_a_variable_set_by_an_earlier_command(self):
        self.assertEqual(self.msgs('D=$(mktemp -d)', 'F="$D/x"', 'echo "$F"'), [])
        self.flagged("D", 'F="$D/x"; D=1')

    def test_a_backslash_continued_command_is_one_command(self):
        self.assertEqual(self.msgs('X=1', 'echo a \\', '  "$X"'), [])
        self.flagged("Y", 'echo a \\', '  "$Y"')

    def test_a_continuation_line_is_an_argument_not_a_new_command(self):
        # `echo a \` + `X=1` is one command whose last argument is X=1: it sets nothing.
        self.flagged("X", 'echo a \\', '  X=1', 'echo "$X"')

    def test_a_value_that_reads_its_own_name_reads_it_before_it_is_set(self):
        self.flagged("X", 'X="$X/a"')
        self.assertEqual(self.msgs('X=1', 'X="$X/a"'), [])

    def test_a_code_span_wrapped_across_two_lines_is_checked(self):
        self.assertTrue(span_problems('see `python3 pr-audit.py\n  post --pr 1` here'))
        self.assertTrue(span_problems('see `echo\n  "$RUN_DIR"` here'))
        self.assertEqual(span_problems('see `echo\n  hi` here'), [])

    def test_wrapped_spans_in_the_real_docs_are_found(self):
        # The scan must reach them: count spans that contain a newline.
        wrapped = 0
        for path in DOC_FILES:
            wrapped += sum("\n" in m.group(1) for m in SPAN.finditer(doc_prose(path)))
        self.assertGreater(wrapped, 0, "no wrapped spans found; the join is not looking")

    def test_ifs_prefix_before_read_still_sets_the_variable(self):
        self.assertEqual(self.msgs('while IFS= read -r line; do echo "$line"; done'), [])

    def test_inline_spans_are_checked(self):
        self.assertTrue(span_problems('`python3 pr-audit.py post --pr "$PR"`'))
        self.assertEqual(span_problems('`python3 "${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts/pr-audit.py" post`'), [])
        self.assertEqual(span_problems("a name only: `codex-review.sh`"), [])
        self.assertTrue(span_problems("run `$RUN_DIR/x`"))


class DocCoverage(unittest.TestCase):
    def test_inline_code_spans_get_the_same_checks(self):
        problems = []
        for path in DOC_FILES:
            problems += doc_span_problems(path)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_a_command_started_by_an_env_path_is_executable(self):
        seen = 0
        for path in DOC_FILES:
            for where, rel_root, rel in first_word_env_paths(path):
                seen += 1
                root = skill_dir_of(path) if rel_root == "SKILL_DIR" else PLUGIN
                self.assertTrue(os.access(str(root / rel), os.X_OK), "%s: %s is not executable" % (where, rel))
        self.assertGreater(seen, 0, "no command starts with a ${CLAUDE_...} path; the scan is not looking")
    def test_a_fence_with_another_language_tag_cannot_hide_a_variable_read(self):
        # Only bash fences are analysed above. A command block tagged `text` or left
        # untagged would escape that, so no other fence may read a shell variable.
        problems = []
        for path in DOC_FILES:
            for lang, start, lines in fenced_blocks(path.read_text(encoding="utf-8")):
                if lang in BASH_LANGS:
                    continue
                for off, line in enumerate(lines):
                    if VAR_READ.search(strip_line(line)):
                        problems.append("%s:%d: a %r fence reads a shell variable: %s" % (
                            path.relative_to(PLUGIN), start + off, lang or "untagged", line.strip()[:60]))
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_the_files_exist_and_have_bash_blocks(self):
        self.assertGreaterEqual(len(DOC_FILES), 4, DOC_FILES)
        for path in DOC_FILES:
            self.assertTrue(path.is_file(), path)
        for path in (SKILLS / "adversarial" / "SKILL.md", SKILLS / "deep" / "SKILL.md",
                     SKILLS / "deep" / "references" / "audit-trail.md"):
            blocks = [b for b in fenced_blocks(path.read_text(encoding="utf-8")) if b[0] in BASH_LANGS]
            self.assertTrue(blocks, "no bash blocks found in %s" % path)


class SkillText(unittest.TestCase):
    def test_no_block_reads_a_variable_it_did_not_set(self):
        problems = []
        for path in DOC_FILES:
            problems += doc_problems(path)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_every_env_path_resolves_to_a_file_in_the_plugin(self):
        problems = []
        seen = 0
        for path in DOC_FILES:
            problems += unresolved_env_paths(path)
            seen += len(ENV_PATH.findall(path.read_text(encoding="utf-8")))
        self.assertGreater(seen, 0, "no ${CLAUDE_...} paths found; the scan is not looking")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_references_use_the_scripts_dir_placeholder_that_skill_md_defines(self):
        # A reference is read as plain text, so ${CLAUDE_...} in it is never
        # substituted. It must use <SCRIPTS_DIR>, and SKILL.md must say what that is.
        refs = sorted((SKILLS / "deep" / "references").glob("*.md"))
        skill = (SKILLS / "deep" / "SKILL.md").read_text(encoding="utf-8")
        used = False
        for path in refs:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("${CLAUDE_", text, "%s: ${CLAUDE_...} is not substituted in a reference" % path.name)
            used = used or "<SCRIPTS_DIR>" in text
        self.assertTrue(used, "no reference uses <SCRIPTS_DIR>; the scan is not looking")
        self.assertIn("<SCRIPTS_DIR>", skill)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts`", skill)

    def test_every_scripts_dir_placeholder_names_a_real_script(self):
        # <SCRIPTS_DIR>/name in a reference is not covered by the ${CLAUDE_...} check.
        scripts = HERE
        seen = 0
        problems = []
        for path in DOC_FILES:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for name in re.findall(r"<SCRIPTS_DIR>/([A-Za-z0-9_.-]+)", line):
                    seen += 1
                    if not (scripts / name).is_file():
                        problems.append("%s:%d: <SCRIPTS_DIR>/%s does not exist" % (
                            path.relative_to(PLUGIN), n, name))
        self.assertGreater(seen, 0, "no <SCRIPTS_DIR>/ paths found; the scan is not looking")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_every_review_name_is_an_agent_or_a_skill(self):
        agents = {p.stem for p in AGENTS.glob("*.md")}
        skills = {p.name for p in SKILLS.iterdir() if p.is_dir()}
        self.assertEqual(agents, {"bug-hunter", "convention-reviewer", "cross-examiner"})
        problems, seen = [], set()
        for path in DOC_FILES:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for name in AGENT_REF.findall(line):
                    seen.add(name)
                    if name not in agents | skills:
                        problems.append("%s:%d: review:%s is not an agent or skill here" % (
                            path.relative_to(PLUGIN), n, name))
        self.assertTrue(agents <= seen, "agents never named in the skills: %s" % sorted(agents - seen))
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_agent_name_matches_its_file(self):
        for path in sorted(AGENTS.glob("*.md")):
            m = re.search(r"^name:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(m, path)
            self.assertEqual(m.group(1), path.stem, path)

    def test_no_old_agent_or_plugin_name_is_left_in_the_skill_text(self):
        old = re.compile(r"adversarial-(?:bug-hunter|convention-reviewer|cross-examiner)"
                         r"|adversarial-review:|deep-review:")
        problems = []
        for path in DOC_FILES:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if old.search(line):
                    problems.append("%s:%d: %s" % (path.relative_to(PLUGIN), n, line.strip()[:80]))
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_each_skill_names_its_old_name(self):
        for skill, old in (("deep", "deep-review"), ("adversarial", "adversarial-review")):
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            m = re.search(r'^description:\s*"(.*)"\s*$', text, re.M)
            self.assertIsNotNone(m, skill)
            # "deep-reviewing" in the trigger text must not satisfy this; name the old skill.
            self.assertRegex(m.group(1), r"\bWas the %s skill\b" % re.escape(old), skill)


if __name__ == "__main__":
    unittest.main()
