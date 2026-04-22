#!/usr/bin/env python3
"""Fail CI if any test calls a DB-opening helper without an explicit ``db_path=`` kwarg.

Guards against recurrence of GH #46: pytest fixtures polluting the user's live
``~/.claude/obsidian-brain-vault.db`` because ``ensure_index()`` /
``rebuild_index()`` / ``deep_analysis_pipeline()`` default ``db_path=None`` to
the user-home path when the caller forgets to pass one.

Exit codes:
    0 — every call site passes ``db_path=`` (clean)
    1 — one or more violations (printed to stdout, summary on stderr)
    2 — script malfunction: missing tests dir, unreadable file, parse error

To silence a known-safe call (e.g. the helper is mocked at runtime), place a
``# noqa: no-default-db`` comment anywhere on the lines spanning the call
(from the function name through the closing paren).

Known limitations:
    * Name-based matching — the guard checks the *trailing* attribute or name
      (``ensure_index`` / ``vault_index.ensure_index`` / ``self.x.ensure_index``
      all match). Unrelated helpers with the same trailing name will trip the
      guard; add ``# noqa: no-default-db`` or rename them.
    * Aliased imports — ``from vault_index import ensure_index as ei`` then
      ``ei(...)`` will NOT be detected. Avoid aliasing the guarded helpers.
    * ``**kwargs`` expansion — calls forwarding unknown keywords via
      ``**kwargs`` are allowed (we cannot statically verify them) but a warning
      is emitted to stderr so reviewers can verify the caller.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

GUARDED_FUNCS = frozenset({
    "ensure_index",
    "rebuild_index",
    "deep_analysis_pipeline",
})
NOQA_MARKER = "# noqa: no-default-db"
TESTS_DIR = Path(__file__).resolve().parent.parent.parent / "tests"


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _kwargs_state(node: ast.Call) -> tuple[bool, bool]:
    """Return (has_db_path, has_kwargs_expansion)."""
    has_db_path = False
    has_expansion = False
    for kw in node.keywords:
        if kw.arg is None:
            has_expansion = True
        elif kw.arg == "db_path":
            has_db_path = True
    return has_db_path, has_expansion


def _call_line_span(node: ast.Call) -> range:
    start = node.lineno
    end = getattr(node, "end_lineno", None) or start
    return range(start, end + 1)


def _has_noqa(source_lines: list[str], span: range) -> bool:
    for lineno in span:
        if 0 < lineno <= len(source_lines):
            if NOQA_MARKER in source_lines[lineno - 1]:
                return True
    return False


def audit_file(path: Path) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (violations, kwargs_warnings) for a single test file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    violations: list[tuple[int, str]] = []
    warnings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in GUARDED_FUNCS:
            continue
        span = _call_line_span(node)
        if _has_noqa(lines, span):
            continue
        has_db_path, has_expansion = _kwargs_state(node)
        if has_db_path:
            continue
        if has_expansion:
            warnings.append((node.lineno, name))
            continue
        violations.append((node.lineno, name))
    return violations, warnings


def main(argv: list[str]) -> int:
    tests_dir = Path(argv[1]) if len(argv) > 1 else TESTS_DIR
    if not tests_dir.is_dir():
        print(f"ERROR: tests directory not found: {tests_dir}", file=sys.stderr)
        return 2

    total_violations = 0
    for path in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            violations, warnings = audit_file(path)
        except SyntaxError as exc:
            print(f"{path}: SyntaxError — {exc}", file=sys.stderr)
            return 2
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            print(f"{path}: cannot read — {exc}", file=sys.stderr)
            return 2
        rel = path.relative_to(tests_dir.parent) if tests_dir.parent in path.parents else path
        for lineno, name in violations:
            print(f"{rel}:{lineno}: {name}(...) missing db_path= kwarg")
            total_violations += 1
        for lineno, name in warnings:
            print(
                f"{rel}:{lineno}: warning: {name}(...) accepted via **kwargs "
                "— verify caller passes db_path",
                file=sys.stderr,
            )

    if total_violations:
        print(
            f"\n{total_violations} violation(s). Every call to "
            + ", ".join(sorted(GUARDED_FUNCS))
            + " in tests/ must pass an explicit db_path= kwarg to avoid "
            "polluting the user's live ~/.claude/obsidian-brain-vault.db.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
