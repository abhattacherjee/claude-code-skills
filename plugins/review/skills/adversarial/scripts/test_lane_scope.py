"""Unit and CLI tests for lane_scope.py."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lane_scope  # noqa: E402


class LaneScopeTests(unittest.TestCase):
    def test_lockfile_only_is_light(self):
        self.assertEqual(lane_scope.classify(["package-lock.json"]), "light")

    def test_docs_only_is_light(self):
        self.assertEqual(lane_scope.classify(["README.md", "docs/a/b.md"]), "light")

    def test_mixed_diff_is_full(self):
        self.assertEqual(lane_scope.classify(["yarn.lock", "src/app.ts"]), "full")

    def test_empty_is_full(self):
        self.assertEqual(lane_scope.classify([]), "full")

    def test_skill_md_is_full(self):
        self.assertEqual(lane_scope.classify(["plugins/x/skills/y/SKILL.md"]), "full")

    def test_agent_instruction_files_are_full(self):
        for path in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "sub/CLAUDE.md"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify(["README.md", path]), "full")

    def test_agent_md_is_full(self):
        self.assertEqual(lane_scope.classify(["plugins/review/agents/bug-hunter.md"]), "full")

    def test_requirements_files_are_full(self):
        # A requirements file can install from a URL or a git repo.
        for name in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(name=name):
                self.assertEqual(lane_scope.classify([name]), "full")

    def test_agent_instruction_dirs_are_full(self):
        for path in (".github/copilot-instructions.md", ".claude/rules/style.md",
                     ".cursor/rules/a.mdc", "prompts/review.md", "docs/rules/a.md"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify(["README.md", path]), "full")

    def test_each_manifest_and_lockfile_is_light(self):
        for name in ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
                     "yarn.lock", "bun.lockb", "poetry.lock", "uv.lock",
                     "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock"):
            with self.subTest(name=name):
                self.assertEqual(lane_scope.classify(["nested/" + name]), "light")

    def test_documentation_extensions_and_docs_contents_are_light(self):
        for path in ("guide.mdx", "nested/guide.rst", "docs/image.png"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify([path]), "light")

    def test_executable_under_docs_is_full(self):
        for path in ("docs/conf.py", "docs/build.sh", "docs/app.js"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify([path]), "full")

    def test_image_under_docs_is_light(self):
        self.assertEqual(lane_scope.classify(["docs/diagram.png"]), "light")

    def test_manifests_are_full(self):
        for name in ("package.json", "Cargo.toml", "go.mod", "Gemfile", "Pipfile"):
            with self.subTest(name=name):
                self.assertEqual(lane_scope.classify([name]), "full")

    def test_code_overrides_light_eligibility(self):
        for path in ("SKILL.md", "docs/SKILL.md", "docs/agents/a.md",
                     "docs/skills/package.json", "docs/commands/a.rst"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify(["README.md", path]), "full")

    def test_matches_are_exact_and_case_sensitive(self):
        for path in ("nested/docs/a.py", "docs-other/a.py", "PACKAGE.JSON", "notes.txt"):
            with self.subTest(path=path):
                self.assertEqual(lane_scope.classify([path]), "full")
        self.assertEqual(lane_scope.classify(["agents-guide.md", "commands-guide.md"]), "light")


class LaneScopeCliTests(unittest.TestCase):
    def run_cli(self, path):
        return subprocess.run([sys.executable, str(HERE / "lane_scope.py"), "--files", str(path)],
                              capture_output=True, text=True, timeout=10)

    def test_cli_prints_light(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files.txt"
            path.write_text("\nREADME.md\n\npackage-lock.json\n", encoding="utf-8")
            res = self.run_cli(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "light\n")
        self.assertEqual(res.stderr, "")

    def test_cli_missing_file_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self.run_cli(Path(tmp) / "missing.txt")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout, "")
        self.assertIn("cannot read", res.stderr)

    def test_cli_unreadable_input_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self.run_cli(tmp)  # A directory cannot be read as a files list.
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout, "")
        self.assertIn("cannot read", res.stderr)

    def test_cli_blank_input_prints_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files.txt"
            path.write_text("\n  \n", encoding="utf-8")
            res = self.run_cli(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "full\n")


if __name__ == "__main__":
    unittest.main()
