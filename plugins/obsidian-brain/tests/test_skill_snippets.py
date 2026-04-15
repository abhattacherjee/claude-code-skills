"""Validate python3 -c '...' snippets in all SKILL.md files compile without SyntaxError."""

import glob
import os
import re
import textwrap
import pytest

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _extract_python_snippets():
    """Extract python3 -c '...' blocks from all SKILL.md files."""
    snippets = []
    for skill_path in sorted(glob.glob(os.path.join(_REPO_ROOT, "skills/*/SKILL.md"))):
        # Extract skill name from path: .../skills/<name>/SKILL.md
        parts = skill_path.replace("\\", "/").split("/")
        skill_name = parts[-2]
        with open(skill_path, encoding="utf-8") as f:
            content = f.read()
        for i, match in enumerate(re.finditer(r"python3\s+-c\s+'(.*?)'", content, re.DOTALL)):
            # Dedent to handle snippets indented inside bash blocks in SKILL.md
            code = textwrap.dedent(match.group(1))
            snippets.append((f"{skill_name}-{i}", code))
    return snippets


_SNIPPETS = _extract_python_snippets()


@pytest.mark.parametrize("name,code", _SNIPPETS, ids=[s[0] for s in _SNIPPETS])
def test_python_snippet_syntax(name, code):
    """Each python3 -c snippet must be valid Python syntax."""
    compile(code, f"<{name}>", "exec")


def test_at_least_one_snippet_found():
    """Sanity check: we should find at least 10 snippets across all skills."""
    assert len(_SNIPPETS) >= 10, (
        f"Expected at least 10 python3 -c snippets, found {len(_SNIPPETS)}"
    )


def test_no_hardcoded_hooks_path():
    """No snippet should use the old hardcoded sys.path.insert(0, "hooks")."""
    for name, code in _SNIPPETS:
        assert 'sys.path.insert(0, "hooks")' not in code, (
            f"Snippet {name} uses hardcoded hooks path. "
            "Use glob-based cache resolution instead."
        )


def test_snippets_use_cache_glob():
    """Every snippet that imports from hooks should use the cache glob pattern."""
    for name, code in _SNIPPETS:
        if "from obsidian_utils" in code or "from open_item_dedup" in code:
            assert "plugins/cache/" in code, (
                f"Snippet {name} imports from hooks but doesn't use "
                "cache glob pattern for path resolution."
            )


def test_cache_glob_finds_installed_hooks():
    """The glob pattern used in skills should match the actual installed cache."""
    matches = sorted(glob.glob(os.path.expanduser(
        "~/.claude/plugins/cache/*/obsidian-brain/*/hooks"
    )))
    # This test only passes when the plugin is installed
    if not matches:
        pytest.skip("obsidian-brain plugin not installed in cache")
    hooks_dir = matches[-1]
    assert os.path.isfile(os.path.join(hooks_dir, "obsidian_utils.py")), (
        f"Cache hooks dir {hooks_dir} exists but obsidian_utils.py not found"
    )


def test_no_tail_c_in_skills():
    """SKILL.md files must not use 'tail -c' for hash extraction.

    tail -c counts raw bytes including trailing newlines, producing fewer
    visible characters than expected (e.g. 3 hex chars instead of 4).
    Use 'cut -c' instead. Lines containing "Do NOT use" are warnings, not usage.
    """
    _TAIL_C_RE = re.compile(r'tail -c')
    _WARNING_RE = re.compile(r'Do NOT use.*tail -c')
    for skill_path in sorted(glob.glob(os.path.join(_REPO_ROOT, "skills/*/SKILL.md"))):
        skill_name = skill_path.replace("\\", "/").split("/")[-2]
        with open(skill_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if _TAIL_C_RE.search(line) and not _WARNING_RE.search(line):
                    raise AssertionError(
                        f"Skill {skill_name} line {lineno} uses 'tail -c' which "
                        "miscounts bytes due to trailing newlines. Use 'cut -c' instead."
                    )


def test_hooks_future_annotations():
    """All .py files using PEP 604/585 type hints must have 'from __future__ import annotations'.

    Without this import, `dict | None` and `list[str]` syntax fails on
    Python < 3.10 (macOS system Python is 3.9.6). Scans hooks/ and scripts/.
    """
    pep604_re = re.compile(r':\s*\w+\s*\|\s*\w+|-> \w+\s*\|\s*\w+')
    pep585_re = re.compile(r':\s*(?:list|dict|set|tuple)\[')
    py_files = sorted(
        glob.glob(os.path.join(_REPO_ROOT, "hooks", "*.py"))
        + glob.glob(os.path.join(_REPO_ROOT, "scripts", "**", "*.py"), recursive=True)
    )
    for py_file in py_files:
        with open(py_file, encoding="utf-8") as f:
            content = f.read()
        uses_modern = pep604_re.search(content) or pep585_re.search(content)
        if uses_modern:
            rel_path = os.path.relpath(py_file, _REPO_ROOT)
            assert "from __future__ import annotations" in content, (
                f"{rel_path} uses PEP 604/585 type hints "
                "but is missing 'from __future__ import annotations'. "
                "This breaks on Python < 3.10 (macOS system Python 3.9.6)."
            )


def test_snippets_import_os_before_usage():
    """Snippets using os.* must import os on a PRIOR line.

    The check must not false-pass by matching 'os' in usage lines like
    ``import glob; ... os.path.expanduser(...)``. Only actual import
    statements count: ``import os``, ``import sys, os``, etc.
    """
    # Matches 'import os' as a standalone import or in a comma-separated list
    _IMPORT_OS_RE = re.compile(
        r'^\s*import\s+(?:[\w]+\s*,\s*)*os(?:\s*,|\s*$)'
    )
    _OS_USAGE_RE = re.compile(r'\bos\.')
    for name, code in _SNIPPETS:
        if not _OS_USAGE_RE.search(code):
            continue
        lines = code.strip().split("\n")
        os_imported = False
        for line in lines:
            if _IMPORT_OS_RE.search(line):
                os_imported = True
            if _OS_USAGE_RE.search(line) and not _IMPORT_OS_RE.search(line):
                assert os_imported, (
                    f"Snippet {name} uses os.* before importing os"
                )
                break


def test_snippets_import_glob_before_usage():
    """SNIP_05: Snippets using glob.* must import glob on a PRIOR or SAME line."""
    _IMPORT_GLOB_RE = re.compile(
        r'^\s*import\s+(?:[\w]+\s*,\s*)*glob(?:\s*[,;]|\s*$)'
    )
    _GLOB_USAGE_RE = re.compile(r'\bglob\.')
    for name, code in _SNIPPETS:
        if not _GLOB_USAGE_RE.search(code):
            continue
        lines = code.strip().split("\n")
        glob_imported = False
        for line in lines:
            # Check import first (handles 'import glob; glob.glob(...)' on same line)
            if _IMPORT_GLOB_RE.search(line):
                glob_imported = True
            elif _GLOB_USAGE_RE.search(line):
                assert glob_imported, (
                    f"Snippet {name} uses glob.* before importing glob"
                )
                break
