from hooks.open_item_dedup import collect_open_items


def test_collect_open_items_ignores_snapshots(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nproject: demo\n---\n\n"
        "# S\n\n## Open Questions / Next Steps\n- [ ] Session open item\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-aa-snapshot-140000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nproject: demo\n---\n\n"
        "# Snap\n\n## Open Questions / Next Steps\n- [ ] Snapshot item — should be ignored\n",
        encoding="utf-8",
    )
    items = collect_open_items(str(tmp_path), "claude-sessions", "demo")
    texts = [t for _, _, t in items]
    assert any("Session open item" in t for t in texts)
    assert not any("should be ignored" in t for t in texts)


def test_collect_open_items_treats_no_type_field_as_session(tmp_path):
    """Legacy notes without a type frontmatter field default to claude-session."""
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    (sess / "2026-04-18-legacy-aa.md").write_text(
        "---\ndate: 2026-04-18\nproject: demo\n---\n\n"
        "# Legacy\n\n## Open Questions / Next Steps\n- [ ] Legacy open item\n",
        encoding="utf-8",
    )
    items = collect_open_items(str(tmp_path), "claude-sessions", "demo")
    texts = [t for _, _, t in items]
    assert any("Legacy open item" in t for t in texts)
