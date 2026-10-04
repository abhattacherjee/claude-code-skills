#!/usr/bin/env python3
"""Path and variable checks for the review plugin's skill text.

The Bash tool keeps no shell variables between calls. A fenced bash block that
reads $SCRIPTS, $ADV_REVIEW or $RUN_DIR, which an earlier block set, runs with
an empty value. These tests read every fenced bash block in both SKILL.md files
and in skills/deep/references/*.md and fail on such a read.

Run: python3 -m pytest test_skill_paths.py -q -p no:cacheprovider
"""
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

# Variables a block may read without setting. The Bash tool gives every call the
# user's environment, and Claude Code sets the two CLAUDE_* names.
ALLOWED_READS = {
    "HOME", "PATH", "TMPDIR", "GH_HOST", "CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT",
}

FENCE_OPEN = re.compile(r"^(\s*)```([A-Za-z0-9_-]*)\s*$")
FENCE_CLOSE = re.compile(r"^\s*```\s*$")
VAR_READ = re.compile(r"\$(?:\{[!#]?([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))")
ASSIGN = re.compile(
    r"(?:^|[\s;&|(])(?:(?:export|local|readonly|declare(?:\s+-[A-Za-z]+)?)\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\+?="
)
FOR_VAR = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
READ_VAR = re.compile(r"\bread\s+((?:-[A-Za-z]+\s+)*)([A-Za-z_][A-Za-z0-9_ ]*)")
ZERO = re.compile(r"\$(?:0\b|\{0\})")
SCRIPT_WORD = re.compile(r"(?<![\w./${}-])([A-Za-z0-9_-]+\.(?:sh|py))\b")
ENV_PATH = re.compile(r"\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}/([A-Za-z0-9_./-]*)")
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


def strip_comments_and_single_quotes(line):
    line = re.sub(r"'[^']*'", "''", line)
    return re.sub(r"(^|\s)#.*$", "", line)


def block_problems(lines):
    """Return [(offset, message)] for one bash block (offset is 0-based)."""
    code = [strip_comments_and_single_quotes(l) for l in lines]
    assigned = set()
    for l in code:
        assigned.update(ASSIGN.findall(l))
        assigned.update(FOR_VAR.findall(l))
        for flags, names in READ_VAR.findall(l):
            assigned.update(names.split())
    problems = []
    for i, l in enumerate(code):
        if ZERO.search(l):
            problems.append((i, '`$0` is the shell, not the skill; never use `dirname "$0"`'))
        for m in VAR_READ.finditer(l):
            name = m.group(1) or m.group(2)
            if name not in assigned and name not in ALLOWED_READS:
                problems.append((i, "reads $%s, which this block never sets" % name))
        for m in SCRIPT_WORD.finditer(l):
            problems.append((i, "script `%s` has no ${CLAUDE_...} path in front" % m.group(1)))
    return problems


def doc_problems(path):
    text = path.read_text(encoding="utf-8")
    found = []
    for lang, start, lines in fenced_blocks(text):
        if lang not in BASH_LANGS:
            continue
        for off, msg in block_problems(lines):
            found.append("%s:%d: %s" % (path.relative_to(PLUGIN), start + off, msg))
    return found


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


class DocCoverage(unittest.TestCase):
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
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
