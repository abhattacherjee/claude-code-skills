import json
from pathlib import Path

from hooks.obsidian_utils import collect_vault_corpus


def _setup(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    ins = vault / "claude-insights"
    sess.mkdir(parents=True); ins.mkdir()
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        "tags: [claude/session]\n---\n\n# S\n\n## Summary\nSession body.\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-aa-snapshot-140000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        "tags: [claude/snapshot]\n---\n\n# Snap\n\n## Summary\nSnapshot body.\n",
        encoding="utf-8",
    )
    return vault


def test_collect_vault_corpus_excludes_snapshots_by_default(tmp_path):
    vault = _setup(tmp_path)
    raw = collect_vault_corpus(str(vault), "claude-sessions", "claude-insights", days=30)
    notes = json.loads(raw)["notes"]
    types = {n["type"] for n in notes}
    assert "claude-snapshot" not in types
    assert "claude-session" in types


def test_collect_vault_corpus_include_snapshots_flag(tmp_path):
    vault = _setup(tmp_path)
    raw = collect_vault_corpus(
        str(vault), "claude-sessions", "claude-insights", days=30,
        exclude_types=(),
    )
    types = {n["type"] for n in json.loads(raw)["notes"]}
    assert "claude-snapshot" in types
