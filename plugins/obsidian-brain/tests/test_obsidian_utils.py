# tests/test_obsidian_utils.py
"""Tests for obsidian_utils.py — config, metadata, messages, I/O, upgrade, sampling."""

import hashlib
import json
import os
import uuid

import pytest

import obsidian_utils


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_sid() -> str:
    """Return a unique string to use as a fake session ID (bypasses cache)."""
    return f"test-sid-{uuid.uuid4().hex}"


# ===========================================================================
# Section 1: Config & session context
# ===========================================================================


class TestLoadConfig:
    def test_load_config_valid(self, tmp_path, monkeypatch):
        """Write a valid config JSON, verify it merges with defaults."""
        config_file = tmp_path / "obsidian-brain-config.json"
        user_cfg = {
            "vault_path": str(tmp_path / "vault"),
            "sessions_folder": "my-sessions",
        }
        config_file.write_text(json.dumps(user_cfg), encoding="utf-8")

        monkeypatch.setattr(obsidian_utils, "_CONFIG_PATH", config_file)
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        result = obsidian_utils.load_config()

        assert result["vault_path"] == str(tmp_path / "vault")
        assert result["sessions_folder"] == "my-sessions"
        # Default keys still present
        assert result["insights_folder"] == "claude-insights"
        assert result["min_messages"] == 3
        assert result["summary_model"] == "haiku"

    def test_load_config_missing(self, tmp_path, monkeypatch):
        """Monkeypatch to nonexistent path — defaults should be returned."""
        monkeypatch.setattr(
            obsidian_utils, "_CONFIG_PATH", tmp_path / "no-such-config.json"
        )
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        result = obsidian_utils.load_config()

        assert result["vault_path"] == ""
        assert result["sessions_folder"] == "claude-sessions"
        assert result["min_messages"] == 3
        assert result["auto_log_enabled"] is True

    def test_get_project_name(self):
        """Test get_project_name with a path and with empty string."""
        assert obsidian_utils.get_project_name("/home/user/my-project") == "my-project"
        assert obsidian_utils.get_project_name("") == "unknown"


# ===========================================================================
# Section 2: Frontmatter parsing
# ===========================================================================


class TestReadNoteMetadata:
    def test_read_note_metadata_valid(self, sample_session_note, monkeypatch):
        """Parse valid frontmatter and verify fields + tags."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        meta = obsidian_utils.read_note_metadata(str(sample_session_note))

        assert meta is not None
        assert meta["type"] == "claude-session"
        assert meta["date"] == "2026-04-10"
        assert meta["session_id"] == "test-session-id-1234"
        assert meta["project"] == "test-project"
        assert meta["status"] == "summarized"
        assert "claude/session" in meta["tags"]
        assert "claude/project/test-project" in meta["tags"]
        assert "claude/auto" in meta["tags"]

    def test_read_note_metadata_no_frontmatter(self, tmp_path, monkeypatch):
        """File without --- markers should return None."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        note = tmp_path / "plain.md"
        note.write_text("# Just a heading\n\nNo frontmatter here.\n", encoding="utf-8")

        result = obsidian_utils.read_note_metadata(str(note))
        assert result is None

    def test_read_note_metadata_empty_file(self, tmp_path, monkeypatch):
        """Empty file should return None."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        note = tmp_path / "empty.md"
        note.write_text("", encoding="utf-8")

        result = obsidian_utils.read_note_metadata(str(note))
        assert result is None


# ===========================================================================
# Section 3: Message extraction
# ===========================================================================


class TestMessageExtraction:
    def test_extract_user_messages(self, sample_jsonl):
        """Extract user messages from JSONL transcript — expect 2."""
        entries = obsidian_utils.read_transcript(str(sample_jsonl))
        msgs = obsidian_utils.extract_user_messages(entries)
        assert len(msgs) == 2
        assert "Fix the login bug" in msgs[0]
        assert "deploy" in msgs[1].lower()

    def test_extract_assistant_messages(self, sample_jsonl):
        """Extract assistant messages — expect 2 including text from content blocks."""
        entries = obsidian_utils.read_transcript(str(sample_jsonl))
        msgs = obsidian_utils.extract_assistant_messages(entries)
        assert len(msgs) == 2
        assert "login handler" in msgs[0].lower()
        assert "deployed" in msgs[1].lower() or "done" in msgs[1].lower()

    def test_extract_user_messages_empty(self):
        """Empty list returns []."""
        assert obsidian_utils.extract_user_messages([]) == []


# ===========================================================================
# Section 4: Slug & filename
# ===========================================================================


class TestSlugAndFilename:
    def test_slugify(self):
        """Lowercases, replaces spaces/special chars, truncates at 40, empty returns 'session'."""
        assert obsidian_utils.slugify("Hello World") == "hello-world"
        assert obsidian_utils.slugify("Fix: AUTH bug #42!") == "fix-auth-bug-42"
        # Truncates at 40
        long_text = "a" * 50
        result = obsidian_utils.slugify(long_text)
        assert len(result) <= 40
        # Empty string returns "session"
        assert obsidian_utils.slugify("") == "session"
        # Only special chars → "session"
        assert obsidian_utils.slugify("---") == "session"

    def test_make_filename(self):
        """Verify format YYYY-MM-DD-slug-hash.md with sha256[:4]; test suffix parameter."""
        session_id = "test-session-abc"
        expected_hash = hashlib.sha256(session_id.encode()).hexdigest()[:4]

        filename = obsidian_utils.make_filename("2026-04-10", "my-slug", session_id)
        assert filename == f"2026-04-10-my-slug-{expected_hash}.md"

        # With suffix
        filename_suffixed = obsidian_utils.make_filename(
            "2026-04-10", "my-slug", session_id, suffix="-snapshot"
        )
        assert filename_suffixed == f"2026-04-10-my-slug-{expected_hash}-snapshot.md"


# ===========================================================================
# Section 5: Session skip logic
# ===========================================================================


class TestShouldSkipSession:
    def test_should_skip_session_short(self):
        """Below message threshold → True."""
        assert obsidian_utils.should_skip_session(["hello", "world"], 10.0) is True

    def test_should_skip_session_long(self):
        """Meets thresholds → False."""
        msgs = ["msg1", "msg2", "msg3", "msg4"]
        assert obsidian_utils.should_skip_session(msgs, 5.0) is False

    def test_should_skip_session_short_duration(self):
        """Known short duration (>0, <min_duration) → True."""
        msgs = ["msg1", "msg2", "msg3", "msg4"]
        assert obsidian_utils.should_skip_session(msgs, 1.0, min_duration=2.0) is True

    def test_should_skip_session_zero_duration(self):
        """Zero (unknown) duration bypasses duration check → False."""
        msgs = ["msg1", "msg2", "msg3", "msg4"]
        # zero duration means unknown — do not skip based on duration
        assert obsidian_utils.should_skip_session(msgs, 0.0, min_duration=2.0) is False


# ===========================================================================
# Section 6: Transcript parsing
# ===========================================================================


class TestReadTranscript:
    def test_read_transcript_valid_jsonl(self, sample_jsonl):
        """Read valid JSONL — expect 4 entries."""
        entries = obsidian_utils.read_transcript(str(sample_jsonl))
        assert len(entries) == 4

    def test_read_transcript_empty(self, tmp_path):
        """Empty file → []."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        result = obsidian_utils.read_transcript(str(empty))
        assert result == []

    def test_read_transcript_nonexistent(self, tmp_path):
        """Missing file → []."""
        result = obsidian_utils.read_transcript(str(tmp_path / "no-such.jsonl"))
        assert result == []


# ===========================================================================
# Section 7: Matching
# ===========================================================================


class TestMatchItemsAgainstEvidence:
    def test_match_items_against_evidence_match(self, tmp_path):
        """Evidence with distinctive tokens matches the open item."""
        # Create a fake file for the item reference
        fake_file = str(tmp_path / "session-note.md")
        item_text = "implement login authentication handler"
        evidence = (
            "Implemented the login authentication handler for user sessions. "
            "The feature is complete and deployed."
        )
        open_items = [(fake_file, 10, item_text)]

        results = obsidian_utils.match_items_against_evidence(evidence, open_items)
        assert len(results) >= 1
        assert results[0]["confidence"] >= 3

    def test_match_items_against_evidence_no_match(self, tmp_path):
        """Completely dissimilar evidence → []."""
        fake_file = str(tmp_path / "session-note.md")
        item_text = "refactor the database migration scripts"
        evidence = "The UI was redesigned with a new color palette."
        open_items = [(fake_file, 5, item_text)]

        results = obsidian_utils.match_items_against_evidence(evidence, open_items)
        assert results == []

    def test_match_items_against_evidence_empty_evidence(self, tmp_path):
        """Empty/whitespace evidence → []."""
        fake_file = str(tmp_path / "session-note.md")
        open_items = [(fake_file, 1, "add unit tests for authentication")]

        assert obsidian_utils.match_items_against_evidence("", open_items) == []
        assert obsidian_utils.match_items_against_evidence("   ", open_items) == []


# ===========================================================================
# Section 8: File I/O
# ===========================================================================


class TestWriteVaultNote:
    def test_write_vault_note_creates_file(self, tmp_vault):
        """Write succeeds and content is correct."""
        content = "# Test Note\n\nHello, vault!\n"
        result = obsidian_utils.write_vault_note(
            str(tmp_vault), "claude-sessions", "test-note.md", content
        )
        assert result is True
        written = (tmp_vault / "claude-sessions" / "test-note.md").read_text(encoding="utf-8")
        assert written == content

    def test_write_vault_note_creates_dirs(self, tmp_vault):
        """Creates missing directories."""
        content = "# New Folder Note\n"
        result = obsidian_utils.write_vault_note(
            str(tmp_vault), "new-folder/sub-folder", "note.md", content
        )
        assert result is True
        assert (tmp_vault / "new-folder" / "sub-folder" / "note.md").exists()

    def test_write_vault_note_permissions(self, tmp_vault):
        """Written file has 0o600 permissions."""
        obsidian_utils.write_vault_note(
            str(tmp_vault), "claude-sessions", "perm-test.md", "content\n"
        )
        note_path = tmp_vault / "claude-sessions" / "perm-test.md"
        mode = oct(note_path.stat().st_mode & 0o777)
        assert mode == oct(0o600)


# ===========================================================================
# Section 9: Upgrade pipeline
# ===========================================================================


class TestUpgradeNoteWithSummary:
    def test_upgrade_note_with_summary_valid(self, sample_unsummarized_note, tmp_vault, monkeypatch):
        """Valid summary with all sections — status flipped and content inserted."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "Fixed the login bug and deployed to production.\n\n"
            "## Key Decisions\n"
            "- Used JWT for session management.\n\n"
            "## Changes Made\n"
            "- `src/auth.py` — new authentication handler\n\n"
            "## Errors Encountered\n"
            "None.\n\n"
            "## Open Questions / Next Steps\n"
            "- [ ] Add integration tests\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Upgraded")
        content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "status: summarized" in content
        assert "## Summary" in content
        assert "Fixed the login bug" in content

    def test_upgrade_note_with_summary_malformed(self, sample_unsummarized_note, tmp_vault):
        """Summary without '## Summary' → starts with 'Failed:'."""
        bad_summary = "This summary has no proper sections.\n\nJust random text."

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            bad_summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )
        assert result.startswith("Failed:")

    def test_upgrade_note_with_summary_no_frontmatter(self, tmp_vault, monkeypatch):
        """Note without --- frontmatter → starts with 'Failed:'."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        note = tmp_vault / "claude-sessions" / "no-frontmatter.md"
        note.write_text("# No frontmatter here\n\nJust content.\n", encoding="utf-8")

        valid_summary = (
            "## Summary\nSomething happened.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(note),
            valid_summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )
        assert result.startswith("Failed:")

    def test_upgrade_note_with_summary_post_write_detects_status_not_flipped(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Clobber with original (auto-logged) content — status-flip branch fires."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "SIGNATURE_MARKER_FOR_STATUS_BRANCH landed successfully.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)
        stale_content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "status: auto-logged" in stale_content  # sanity check fixture

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(stale_content)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "status not flipped" in result, (
            f"expected status-branch message, got {result!r}"
        )

    def test_upgrade_note_with_summary_post_write_detects_body_missing(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Clobber preserves status: summarized but strips the body signature —
        signature branch MUST fire (regression guard for deleted body check)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "BODY_BRANCH_SIGNATURE_LINE that must appear on disk.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)

        # Craft stale content that passes status check but lacks the signature.
        fake_summarized = (
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "session_id: stale-session\n"
            "status: summarized\n"
            "---\n"
            "\n# Stale content\n\n## Summary\nDifferent prior summary body.\n"
        )

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(fake_summarized)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "summary body missing" in result, (
            f"expected body-branch message, got {result!r}"
        )

    def test_upgrade_note_with_summary_body_check_scoped_to_summary_section(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Signature check must be scoped to ## Summary — if the signature
        appears only in a preserved audit trail (not in Summary body), the
        function must still return Failed. Regression guard for Copilot #1."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "AUDIT_TRAIL_FALSE_POSITIVE_SIGNATURE test line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)

        # Craft stale content that:
        #   - passes the frontmatter status check (status: summarized)
        #   - has a ## Summary section with a DIFFERENT body
        #   - leaks the signature into an audit trail section
        # If the signature check were whole-file, it would pass here. It
        # must only pass when the signature is in the Summary block.
        fake_content = (
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "session_id: stale-session\n"
            "status: summarized\n"
            "---\n"
            "\n# Stale content\n\n"
            "## Summary\nThis is a different body that does not contain the signature.\n\n"
            "## Tool Usage\n"
            "- Message: AUDIT_TRAIL_FALSE_POSITIVE_SIGNATURE test line.\n"
        )

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(fake_content)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "summary body missing" in result, (
            f"expected body-branch message, got {result!r}"
        )

    def test_upgrade_note_with_summary_tab_separated_next_section_breaks_cleanly(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Pre-write: an empty Summary body followed by `##\\tKey Decisions`
        (tab separator, not space) must still be recognized as the next
        top-level section so the loop breaks and the malformed-body check
        fires. Regression guard for Copilot #6 round 7 (level-2 heading
        must match any whitespace, not just space)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        # Empty Summary body, next section uses a TAB after `##`.
        tab_summary = (
            "## Summary\n\n"
            "##\tKey Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            tab_summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        # Must fail malformed — if the break condition missed the tab,
        # the loop would pick up "Key Decisions" text as the signature
        # and proceed to an Upgraded state with an empty real Summary.
        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "malformed summary" in result.lower()
        assert "empty or heading-only" in result.lower()

    def test_upgrade_note_with_summary_post_write_tab_separated_section_boundary(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Post-write: the Summary block extraction regex must terminate
        at `##\\tKey Decisions` (tab separator), not swallow the next
        section. If it failed to terminate, a signature that lives ONLY
        in the next tabbed section would false-positive the body check.

        The clobber moves the signature out of the Summary body and into
        the tabbed Key Decisions section — so:
          - correct regex termination → Summary block is empty of signature
            → Failed: summary body missing
          - buggy regex (swallows the tabbed section) → Summary block
            contains the signature → phantom Upgraded

        Regression guard for Copilot round 7 #2 (lookahead must allow any
        whitespace after the `##` delimiter) AND round 8 (the round-7 test
        was branch-confused because it only checked the happy path)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "TAB_BOUNDARY_SIGNATURE content line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)

        # Stale content: valid YAML frontmatter with status: summarized,
        # an empty Summary body, and the signature hiding in a tab-
        # separated next section. If the extraction regex terminates
        # properly at `##\t`, the Summary block will be empty (no signature)
        # and the function must return Failed. If it fails to terminate,
        # it swallows the Key Decisions section and false-positives.
        clobber_content = (
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "session_id: stale-session\n"
            "status: summarized\n"
            "---\n"
            "\n# Clobbered\n\n"
            "## Summary\n\n"
            "##\tKey Decisions\n"
            "- TAB_BOUNDARY_SIGNATURE content line.\n"
        )

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(clobber_content)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "summary body missing" in result, (
            f"expected body-branch message, got {result!r}"
        )

    def test_upgrade_note_with_summary_hash_prefixed_content_is_not_a_heading(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """A line starting with `#` followed by non-whitespace (e.g. `#1234`
        or `#hashtag`) is legitimate Markdown content, not an ATX heading,
        and must be accepted as the signature. Regression guard for
        Copilot #6 (strict ATX heading detection)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        # First real content line starts with `#` but is not an ATX heading.
        summary = (
            "## Summary\n"
            "#1234 issue reference — fixed the auth bug.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Upgraded"), (
            f"expected Upgraded, got {result!r} — hash-prefixed content line "
            f"was incorrectly classified as a heading"
        )
        disk_content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "status: summarized" in disk_content
        assert "#1234 issue reference — fixed the auth bug." in disk_content

    def test_upgrade_note_with_summary_skips_sub_headings_inside_summary(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """A legitimate ATX sub-heading like `### Context` inside the Summary
        block should be skipped, and the next real content line becomes the
        signature. Pins the "sub-heading != break" branch of the new logic."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "### Context\n"
            "The real signature is on this line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Upgraded"), f"expected Upgraded, got {result!r}"
        disk_content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "The real signature is on this line." in disk_content

    def test_upgrade_note_with_summary_body_check_is_line_granular(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Signature must match as a full stripped line in the Summary block,
        not as a substring of another line. Regression guard for Copilot #4."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        # Signature is "Short sig." — could false-positive as a substring
        # of "Before: Short sig. After: also changed." if the check used
        # a substring match instead of line equality.
        summary = (
            "## Summary\n"
            "Short sig.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)

        # Stale content has `## Summary` with a line that CONTAINS "Short sig."
        # as a substring but is not equal to it. Under a substring check
        # this false-positives; under line-granularity it must fail.
        fake_content = (
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "session_id: stale-session\n"
            "status: summarized\n"
            "---\n"
            "\n# Stale content\n\n"
            "## Summary\nBefore: Short sig. After: something else entirely.\n"
        )

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(fake_content)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "summary body missing" in result, (
            f"expected line-granular miss, got {result!r}"
        )

    def test_upgrade_note_with_summary_accepts_bare_filename(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Bare filename (no directory component) must not crash tempfile.mkstemp.
        Regression guard for Copilot #3 latent bug (low-confidence suppressed)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())
        # cd into the note's parent so a bare filename resolves correctly.
        monkeypatch.chdir(sample_unsummarized_note.parent)

        summary = (
            "## Summary\n"
            "BARE_FILENAME_SIGNATURE content line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            sample_unsummarized_note.name,  # bare filename, no directory
            summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Upgraded"), f"expected Upgraded, got {result!r}"
        disk_content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "status: summarized" in disk_content
        assert "BARE_FILENAME_SIGNATURE content line." in disk_content

    def test_upgrade_note_with_summary_frontmatter_anchored_to_file_start(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Clobber writes content with no YAML frontmatter but with a Markdown
        horizontal rule `---` and `status: summarized` in the body. The
        frontmatter scope check must fail because the opening `---` is not
        anchored to the start of the file. Regression guard for Copilot #3."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "FRONTMATTER_ANCHOR_SIGNATURE content line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        real_replace = os.replace
        note_path_str = str(sample_unsummarized_note)

        # No YAML frontmatter at start — just a title, a Markdown HR, and
        # a line that SAYS status: summarized in the body text. If the
        # frontmatter detector was not start-anchored, it would scoop the
        # HR as "frontmatter" and find the status line within it.
        fake_content = (
            "# Stale session with no frontmatter\n"
            "\n"
            "Some narrative text here.\n"
            "\n"
            "---\n"
            "status: summarized\n"
            "(this is a body line that LOOKS like frontmatter)\n"
            "---\n"
            "\n"
            "## Summary\nFRONTMATTER_ANCHOR_SIGNATURE content line.\n"
        )

        def clobbering_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(fake_content)

        monkeypatch.setattr(os, "replace", clobbering_replace)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "YAML frontmatter not found at start" in result, (
            f"expected anchored-frontmatter message, got {result!r}"
        )

    def test_upgrade_note_with_summary_rejects_empty_body(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Summary with header but no body content fails loudly (not phantom OK)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        empty_body_summary = (
            "## Summary\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            empty_body_summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "malformed summary" in result.lower()
        assert "empty or heading-only" in result.lower()

    def test_upgrade_note_with_summary_post_write_read_failure(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Post-write re-read raising OSError → Failed (not phantom success)."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "POST_READ_FAILURE_SIGNATURE content line.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        import builtins
        real_open = builtins.open
        note_path_str = str(sample_unsummarized_note)
        replace_done = {"flag": False}
        real_replace = os.replace

        def flagging_replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if str(dst) == note_path_str:
                replace_done["flag"] = True

        def failing_open(path, mode="r", *args, **kwargs):
            if (
                replace_done["flag"]
                and str(path) == note_path_str
                and "r" in mode
                and "w" not in mode
            ):
                raise OSError("simulated post-write read failure")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(os, "replace", flagging_replace)
        monkeypatch.setattr(builtins, "open", failing_open)

        result = obsidian_utils.upgrade_note_with_summary(
            note_path_str, summary, str(tmp_vault), "claude-sessions", "test-project"
        )

        assert result.startswith("Failed:"), f"expected Failed:, got {result!r}"
        assert "post-write read verification failed" in result

    def test_upgrade_note_with_summary_persists_to_disk(
        self, sample_unsummarized_note, tmp_vault, monkeypatch
    ):
        """Happy path: the summary signature is readable from disk after return."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        summary = (
            "## Summary\n"
            "UNIQUE_POST_WRITE_CHECK_PHRASE landed on disk successfully.\n\n"
            "## Key Decisions\nNone noted.\n\n"
            "## Changes Made\nNone noted.\n\n"
            "## Errors Encountered\nNone.\n\n"
            "## Open Questions / Next Steps\nNone.\n"
        )

        result = obsidian_utils.upgrade_note_with_summary(
            str(sample_unsummarized_note),
            summary,
            str(tmp_vault),
            "claude-sessions",
            "test-project",
        )

        assert result.startswith("Upgraded")
        # Re-read from disk (not cached text).
        disk_content = sample_unsummarized_note.read_text(encoding="utf-8")
        assert "status: summarized" in disk_content
        assert "UNIQUE_POST_WRITE_CHECK_PHRASE landed on disk successfully." in disk_content


# ===========================================================================
# Section 10: Prepare summary input
# ===========================================================================


class TestPrepareSummaryInput:
    def test_prepare_summary_input_no_session_id(self, tmp_path):
        """Note without session_id → 'NO_CONTENT:...'."""
        note = tmp_path / "no-session-id.md"
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "status: auto-logged\n"
            "---\n\n"
            "# Session\n\n## Summary\nSomething.\n",
            encoding="utf-8",
        )
        result = obsidian_utils.prepare_summary_input(str(note))
        assert result.startswith("NO_CONTENT:")

    def test_prepare_summary_input_no_jsonl(self, tmp_path, monkeypatch):
        """Has session_id, JSONL not found → 'RAW_OK:...'."""
        note = tmp_path / "with-session-id.md"
        note.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-10\n"
            "session_id: fake-session-no-jsonl\n"
            "project: test-project\n"
            "status: auto-logged\n"
            "---\n\n"
            "# Session\n\n## Summary\nSomething.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(obsidian_utils, "find_transcript_jsonl", lambda sid: None)
        result = obsidian_utils.prepare_summary_input(str(note))
        assert result.startswith("RAW_OK:")

    def test_prepare_summary_input_read_error(self, tmp_path):
        """Nonexistent file → 'NO_CONTENT:...'."""
        result = obsidian_utils.prepare_summary_input(str(tmp_path / "ghost.md"))
        assert result.startswith("NO_CONTENT:")


# ===========================================================================
# Section 11: Sampling logic (mock-based)
# ===========================================================================


class TestGenerateSummarySampling:
    """Test message sampling and truncation inside generate_summary()."""

    def _fake_run_factory(self, captured: dict):
        """Return a fake subprocess.run that captures its input."""
        def fake_run(cmd, **kwargs):
            captured["prompt"] = kwargs.get("input", "")
            return type(
                "Result",
                (),
                {"returncode": 0, "stdout": "## Summary\nDone.\n", "stderr": ""},
            )()
        return fake_run

    def test_generate_summary_sampling_under_20(self, monkeypatch):
        """15 messages — no '[... middle messages omitted ...]' marker."""
        captured: dict = {}
        monkeypatch.setattr("subprocess.run", self._fake_run_factory(captured))

        user_msgs = [f"user message {i}" for i in range(15)]
        assistant_msgs = [f"assistant response {i}" for i in range(15)]
        metadata = {"project": "test", "git_branch": "main", "duration_minutes": 5, "files_touched": []}

        obsidian_utils.generate_summary(user_msgs, assistant_msgs, metadata)

        assert captured.get("prompt") is not None
        assert "[... middle messages omitted ...]" not in captured["prompt"]
        # All messages should appear
        assert "user message 0" in captured["prompt"]
        assert "user message 14" in captured["prompt"]

    def test_generate_summary_sampling_over_20(self, monkeypatch):
        """30 messages — marker present, first/last present, middle absent."""
        captured: dict = {}
        monkeypatch.setattr("subprocess.run", self._fake_run_factory(captured))

        user_msgs = [f"user message {i}" for i in range(30)]
        assistant_msgs = [f"assistant response {i}" for i in range(30)]
        metadata = {"project": "test", "git_branch": "main", "duration_minutes": 10, "files_touched": []}

        obsidian_utils.generate_summary(user_msgs, assistant_msgs, metadata)

        prompt = captured.get("prompt", "")
        assert "[... middle messages omitted ...]" in prompt
        # First and last 10 present
        assert "user message 0" in prompt
        assert "user message 29" in prompt
        # Middle absent
        assert "user message 15" not in prompt

    def test_generate_summary_truncation_12k(self, monkeypatch):
        """15 messages of 1000 chars each — total prompt stays bounded."""
        captured: dict = {}
        monkeypatch.setattr("subprocess.run", self._fake_run_factory(captured))

        user_msgs = ["u" * 1000 for _ in range(15)]
        assistant_msgs = ["a" * 1000 for _ in range(15)]
        metadata = {"project": "test", "git_branch": "main", "duration_minutes": 5, "files_touched": []}

        obsidian_utils.generate_summary(user_msgs, assistant_msgs, metadata)

        prompt = captured.get("prompt", "")
        # 15 msgs × 1000 chars + separators ≤ 12000 for user + 12000 for assistant + overhead
        # The join is truncated at 12000 each, so total user+assistant ≤ 24000
        assert len(prompt) < 30000  # generous upper bound; key check is it's bounded


# ===========================================================================
# Section 7: build_context_brief — sort order and duration
# ===========================================================================

def _make_session_note(path, project, date, branch, duration, summary, mtime=None):
    """Helper: write a minimal session note and optionally set its mtime."""
    content = f"""---
type: claude-session
date: {date}
project: {project}
git_branch: {branch}
duration_minutes: {duration}
status: summarized
---

# Session: {project} ({branch})

## Summary
{summary}
"""
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class TestBuildContextBriefSort:
    """Verify hybrid sort (date desc, mtime desc within same date) and duration column."""

    def test_same_day_sorted_by_mtime(self, tmp_path, monkeypatch):
        """Sessions from the same day should sort by mtime descending, not filename."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        # Create two notes from the same day — 'aaaa' is alphabetically first
        # but should sort SECOND because its mtime is older.
        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 30, "First created session.", mtime=1000,
        )
        _make_session_note(
            sessions / "2026-04-10-proj-zzzz.md",
            "proj", "2026-04-10", "main", 60, "Second created session.", mtime=2000,
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        # The more recent mtime (zzzz) should appear first in the table
        zzzz_pos = output.find("Second created session.")
        aaaa_pos = output.find("First created session.")
        assert zzzz_pos < aaaa_pos, "mtime-newer session should appear first"

    def test_different_days_sorted_by_date(self, tmp_path, monkeypatch):
        """Older-date session should not float up even if its mtime is newer."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        # April 5 note has a NEWER mtime than April 10 note
        _make_session_note(
            sessions / "2026-04-05-proj-aaaa.md",
            "proj", "2026-04-05", "main", 10, "Older date session.", mtime=9999,
        )
        _make_session_note(
            sessions / "2026-04-10-proj-bbbb.md",
            "proj", "2026-04-10", "main", 20, "Newer date session.", mtime=1000,
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        newer_pos = output.find("Newer date session.")
        older_pos = output.find("Older date session.")
        assert newer_pos < older_pos, "date descending should take priority over mtime"

    def test_duration_format_hours_minutes(self, tmp_path, monkeypatch):
        """Duration >= 60 min should display as Xh Ym."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 80.3, "Long session.",
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        assert "| 1h 20m |" in output

    def test_duration_format_minutes_only(self, tmp_path, monkeypatch):
        """Duration < 60 min should display as Xm."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 27, "Short session.",
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        assert "| 27m |" in output

    def test_duration_format_zero(self, tmp_path, monkeypatch):
        """Duration 0 should produce empty string in column."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 0, "No duration.",
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        assert "|  |" in output or "| |" in output

    def test_session_number_column(self, tmp_path, monkeypatch):
        """Each row should have a sequential number in the first column."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 10, "First.", mtime=2000,
        )
        _make_session_note(
            sessions / "2026-04-10-proj-bbbb.md",
            "proj", "2026-04-10", "main", 20, "Second.", mtime=1000,
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        rows = [l for l in output.split("\n") if l.startswith("| ") and l[2:3].isdigit()]
        assert len(rows) == 2
        assert rows[0].startswith("| 1 |")
        assert rows[1].startswith("| 2 |")

    def test_stat_failure_does_not_crash(self, tmp_path, monkeypatch):
        """A broken symlink in the sessions dir should not crash build_context_brief."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        # Create a valid note
        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 15, "Valid session.",
        )
        # Create a broken symlink (.md suffix so it passes the filter)
        broken = sessions / "2026-04-10-proj-broken.md"
        broken.symlink_to(tmp_path / "nonexistent-target.md")

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        # Should still produce output with the valid session
        assert "Valid session." in output

    def test_duration_boundary_60_minutes(self, tmp_path, monkeypatch):
        """Duration of exactly 60 min should display as 1h 0m."""
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: _unique_sid())

        sessions = tmp_path / "sessions"
        insights = tmp_path / "insights"
        sessions.mkdir()
        insights.mkdir()

        _make_session_note(
            sessions / "2026-04-10-proj-aaaa.md",
            "proj", "2026-04-10", "main", 60, "Boundary session.",
        )

        output = obsidian_utils.build_context_brief(
            str(tmp_path), "sessions", "insights", "proj",
        )

        assert "| 1h 0m |" in output


def test_get_session_id_fast_rejects_stale_bootstrap(tmp_path, monkeypatch):
    """Fast path must fall through to slow path when a newer JSONL exists."""
    import obsidian_utils
    import os
    import time

    # Fake ~/.claude/projects/<project>/ with two JSONL files
    project_basename = "fake-proj-abc"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    old_jsonl = cc_projects / "old-sid-0000.jsonl"
    new_jsonl = cc_projects / "new-sid-9999.jsonl"
    old_jsonl.write_text("{}", encoding="utf-8")
    new_jsonl.write_text("{}", encoding="utf-8")
    os.utime(old_jsonl, (time.time() - 7200, time.time() - 7200))
    os.utime(new_jsonl, (time.time() - 60, time.time() - 60))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("old-sid-0000", encoding="utf-8")
    os.utime(bootstrap, (time.time() - 3600, time.time() - 3600))

    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    result = obsidian_utils._get_session_id_fast()
    assert result == "new-sid-9999", f"expected newest sid, got {result}"


def test_get_session_id_fast_trusts_fresh_bootstrap(tmp_path, monkeypatch):
    """Fast path must return bootstrap sid when bootstrap is newer than all JSONLs."""
    import obsidian_utils
    import os
    import time

    project_basename = "fresh-proj-xyz"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    jsonl = cc_projects / "fresh-sid-1234.jsonl"
    jsonl.write_text("{}", encoding="utf-8")
    os.utime(jsonl, (time.time() - 3600, time.time() - 3600))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("fresh-sid-1234", encoding="utf-8")
    os.utime(bootstrap, (time.time() - 60, time.time() - 60))

    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    result = obsidian_utils._get_session_id_fast()
    assert result == "fresh-sid-1234"


def test_get_session_id_fast_invalidates_when_cached_jsonl_deleted(tmp_path, monkeypatch):
    """Bootstrap points at a sid whose JSONL has been removed — slow path picks newest survivor."""
    import obsidian_utils
    import os
    import time

    project_basename = "deleted-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    # Create only the "surviving" JSONL; the cached one in the bootstrap doesn't exist on disk
    survivor = cc_projects / "survivor-sid-ffff.jsonl"
    survivor.write_text("{}", encoding="utf-8")
    os.utime(survivor, (time.time() - 60, time.time() - 60))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("deleted-sid-0000", encoding="utf-8")

    monkeypatch.setattr(
        obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-")
    )

    result = obsidian_utils._get_session_id_fast()
    assert result == "survivor-sid-ffff", (
        f"expected fast path to fall through and return newest survivor, got {result}"
    )


def test_check_hook_status_matches(tmp_path, monkeypatch):
    """check_hook_status returns ok=True when bootstrap matches current sid."""
    import obsidian_utils
    import os

    project_basename = "stat-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)
    jsonl = cc_projects / "live-sid-1111.jsonl"
    jsonl.write_text("{}", encoding="utf-8")

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap_prefix = str(tmp_path / ".obsidian-brain-sid-")
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", bootstrap_prefix)
    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("live-sid-1111", encoding="utf-8")
    # Make bootstrap newer than the JSONL so the fast path trusts it
    import time
    os.utime(jsonl, (time.time() - 3600, time.time() - 3600))
    os.utime(bootstrap, (time.time() - 60, time.time() - 60))

    status = obsidian_utils.check_hook_status()
    assert status["ok"] is True
    assert status["bootstrap_sid"] == "live-sid-1111"
    assert status["current_sid"] == "live-sid-1111"


def test_check_hook_status_sid_mismatch_is_ok(tmp_path, monkeypatch):
    """SID mismatch (e.g. after reconnect) is ok=True when bootstrap exists."""
    import obsidian_utils
    import os, time

    project_basename = "mismatch-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)
    # Two JSONLs: old one matching bootstrap, newer one for current session
    old_jsonl = cc_projects / "old-sid-aaaa.jsonl"
    old_jsonl.write_text("{}", encoding="utf-8")
    new_jsonl = cc_projects / "new-sid-bbbb.jsonl"
    new_jsonl.write_text("{}", encoding="utf-8")
    os.utime(old_jsonl, (time.time() - 3600, time.time() - 3600))
    os.utime(new_jsonl, (time.time() - 10, time.time() - 10))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap_prefix = str(tmp_path / ".obsidian-brain-sid-")
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", bootstrap_prefix)
    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("old-sid-aaaa", encoding="utf-8")

    status = obsidian_utils.check_hook_status()
    assert status["ok"] is True
    assert status["current_sid"] == "new-sid-bbbb"
    assert status["bootstrap_sid"] == "old-sid-aaaa"
    assert "resumed session" in status["message"]


def test_check_hook_status_no_session_files(tmp_path, monkeypatch):
    """check_hook_status returns ok=False when bootstrap exists but no JSONLs."""
    import obsidian_utils

    project_basename = "no-sessions-proj"
    # CC projects dir exists but has NO .jsonl files
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    bootstrap_prefix = str(tmp_path / ".obsidian-brain-sid-")
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", bootstrap_prefix)
    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("some-old-sid", encoding="utf-8")

    status = obsidian_utils.check_hook_status()
    assert status["ok"] is False
    assert "No session files found" in status["message"] or "not be active" in status["message"]
    assert status["bootstrap_sid"] == "some-old-sid"
    assert status["current_sid"] == "unknown"


def test_slow_path_underscore_to_hyphen_fallback(tmp_path, monkeypatch):
    """_slow_path_newest_sid matches when cwd has underscores but CC dir has hyphens."""
    import obsidian_utils

    # cwd basename has underscores
    proj_dir = tmp_path / "personal_ws"
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Claude Code normalizes underscores to hyphens in project dir names
    cc_projects = tmp_path / ".claude" / "projects" / "-Users-foo-personal-ws"
    cc_projects.mkdir(parents=True)
    jsonl = cc_projects / "abc123.jsonl"
    jsonl.write_text("{}", encoding="utf-8")

    sid = obsidian_utils._slow_path_newest_sid()
    assert sid == "abc123", f"Expected 'abc123' but got '{sid}' — hyphen fallback failed"


def test_fast_path_underscore_to_hyphen_fallback(tmp_path, monkeypatch):
    """_get_session_id_fast matches when cwd has underscores but CC dir has hyphens."""
    import obsidian_utils

    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    # CC dir uses hyphens
    cc_projects = tmp_path / ".claude" / "projects" / "-Users-foo-my-project"
    cc_projects.mkdir(parents=True)
    jsonl = cc_projects / "sess-fast-123.jsonl"
    jsonl.write_text("{}", encoding="utf-8")

    # Bootstrap file points to the correct sid
    bootstrap_prefix = str(tmp_path / ".obsidian-brain-sid-")
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", bootstrap_prefix)
    bootstrap = tmp_path / ".obsidian-brain-sid-my_project"
    bootstrap.write_text("sess-fast-123", encoding="utf-8")

    sid = obsidian_utils._get_session_id_fast()
    assert sid == "sess-fast-123", f"Expected 'sess-fast-123' but got '{sid}'"


def test_get_session_context_normalizes_underscores(tmp_path, monkeypatch):
    """get_session_context normalizes underscores to hyphens in project name."""
    import obsidian_utils

    proj_dir = tmp_path / "personal_ws"
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Stub _get_session_id_fast to return unknown (avoids bootstrap setup)
    monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: "unknown")

    ctx = obsidian_utils.get_session_context()
    assert ctx["project"] == "personal-ws", (
        f"Expected 'personal-ws' but got '{ctx['project']}' — underscores not normalized"
    )


def test_extract_session_metadata_normalizes_underscores():
    """extract_session_metadata normalizes underscores to hyphens in project name."""
    import obsidian_utils

    meta = obsidian_utils.extract_session_metadata([], "/Users/foo/personal_ws")
    assert meta["project"] == "personal-ws", (
        f"Expected 'personal-ws' but got '{meta['project']}' — underscores not normalized"
    )


def test_extract_session_metadata_normalizes_case_and_spaces():
    """extract_session_metadata lowercases and normalizes spaces like get_session_context."""
    import obsidian_utils

    meta = obsidian_utils.extract_session_metadata([], "/Users/foo/My Project")
    assert meta["project"] == "my-project", (
        f"Expected 'my-project' but got '{meta['project']}' — case/space normalization failed"
    )


def test_check_hook_status_missing_bootstrap(tmp_path, monkeypatch):
    """check_hook_status returns ok=False when bootstrap file is absent."""
    import obsidian_utils

    project_basename = "missing-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)
    (cc_projects / "sid-xxxx.jsonl").write_text("{}", encoding="utf-8")

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    monkeypatch.setattr(
        obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-")
    )

    status = obsidian_utils.check_hook_status()
    assert status["ok"] is False
    assert "not be active" in status["message"]


def test_build_context_brief_prepends_hook_status(tmp_path):
    """build_context_brief prepends the hook_status_line when provided."""
    import obsidian_utils

    vault = tmp_path / "vault"
    (vault / "sessions").mkdir(parents=True)
    (vault / "insights").mkdir(parents=True)

    status_line = "[OK] Session logging active"
    output = obsidian_utils.build_context_brief(
        str(vault),
        "sessions",
        "insights",
        "nonexistent-project",
        hook_status_line=status_line,
    )

    # Extract the CONTEXT_BRIEF section and verify the first content line
    # is the status line, appearing before the "## Project Context" header.
    assert "<<<OB_CONTEXT_BRIEF>>>" in output
    brief_section = output.split("<<<OB_CONTEXT_BRIEF>>>", 1)[1].split("<<<OB_LOAD_MANIFEST>>>", 1)[0]
    brief_lines = [ln for ln in brief_section.split("\n") if ln.strip()]
    assert brief_lines[0] == status_line
    # Header should still exist after the status line
    assert any(ln.startswith("## Project Context") for ln in brief_lines)
    # Ensure the status line appears BEFORE the header
    status_idx = brief_lines.index(status_line)
    header_idx = next(i for i, ln in enumerate(brief_lines) if ln.startswith("## Project Context"))
    assert status_idx < header_idx


def test_build_context_brief_without_hook_status(tmp_path):
    """build_context_brief omits the status line when not provided (default)."""
    import obsidian_utils

    vault = tmp_path / "vault"
    (vault / "sessions").mkdir(parents=True)
    (vault / "insights").mkdir(parents=True)

    output = obsidian_utils.build_context_brief(
        str(vault),
        "sessions",
        "insights",
        "nonexistent-project",
    )

    brief_section = output.split("<<<OB_CONTEXT_BRIEF>>>", 1)[1].split("<<<OB_LOAD_MANIFEST>>>", 1)[0]
    brief_lines = [ln for ln in brief_section.split("\n") if ln.strip()]
    # First non-empty line should be the Project Context header, not a status line
    assert brief_lines[0].startswith("## Project Context")


def test_get_session_id_fast_same_second_tiebreaker(tmp_path, monkeypatch):
    """Same-second mtime ties: cached sid wins when its JSONL is tied for newest."""
    import obsidian_utils
    import os
    import time

    project_basename = "tie-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    # Two JSONLs with IDENTICAL mtimes
    now = time.time()
    old_jsonl = cc_projects / "aaa-previous.jsonl"
    current_jsonl = cc_projects / "zzz-current.jsonl"
    old_jsonl.write_text("{}", encoding="utf-8")
    current_jsonl.write_text("{}", encoding="utf-8")
    os.utime(old_jsonl, (now, now))
    os.utime(current_jsonl, (now, now))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    # Bootstrap claims "aaa-previous" is current. Because path-sort tiebreak
    # would otherwise pick "zzz-current" (lexicographically larger) as the
    # newest, the cached sid must win via the same-mtime tie-breaker.
    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("aaa-previous", encoding="utf-8")

    result = obsidian_utils._get_session_id_fast()
    assert result == "aaa-previous", (
        f"expected cached sid to win same-mtime tie, got {result}"
    )


def test_get_session_id_fast_multiple_cached_matches_tiebreak(tmp_path, monkeypatch):
    """When multiple project dirs contain the cached sid's JSONL, at least one
    must tie the newest mtime for the cache to be trusted."""
    import obsidian_utils
    import os
    import time

    project_basename = "multi-proj"
    # Two project-dir variants (like worktrees)
    dir_a = tmp_path / ".claude" / "projects" / f"-alpha-{project_basename}"
    dir_b = tmp_path / ".claude" / "projects" / f"-beta-{project_basename}"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    cached_sid = "shared-sid-1234"
    # Put the cached sid's jsonl in BOTH project dirs
    a_jsonl = dir_a / f"{cached_sid}.jsonl"
    b_jsonl = dir_b / f"{cached_sid}.jsonl"
    other_jsonl = dir_b / "other-sid-5678.jsonl"
    a_jsonl.write_text("{}", encoding="utf-8")
    b_jsonl.write_text("{}", encoding="utf-8")
    other_jsonl.write_text("{}", encoding="utf-8")

    # Scenario: a_jsonl is OLDER, b_jsonl matches newest mtime, other_jsonl
    # is also at newest mtime. Tiebreaker MUST trust the cache because
    # at least one cached match (b_jsonl) ties newest mtime.
    now = time.time()
    os.utime(a_jsonl, (now - 3600, now - 3600))  # old
    os.utime(b_jsonl, (now, now))  # tied with other
    os.utime(other_jsonl, (now, now))  # tied with b

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text(cached_sid, encoding="utf-8")

    result = obsidian_utils._get_session_id_fast()
    assert result == cached_sid, (
        f"expected cached sid to win via multi-match tiebreaker, got {result}"
    )


def test_get_session_id_fast_slow_path_is_readonly(tmp_path, monkeypatch):
    """Slow path must NOT write to the bootstrap file.

    Regression test for the SessionStart-hook race: the hook writes the
    authoritative sid, then downstream hook code can trigger
    _get_session_id_fast() before CC has flushed the new session's JSONL.
    In that window, the cached_pattern glob misses and the slow path fires.
    If the slow path writes back to the bootstrap, it clobbers the hook's
    authoritative write with a stale result.
    """
    import obsidian_utils
    import os
    import time

    project_basename = "readonly-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    # Previous session's JSONL exists (what the hook race would find as 'newest')
    old_jsonl = cc_projects / "old-sid-0000.jsonl"
    old_jsonl.write_text("{}", encoding="utf-8")
    os.utime(old_jsonl, (time.time() - 600, time.time() - 600))

    # New session's JSONL does NOT exist yet — this is the race window
    # (CC hasn't flushed it yet when the hook fires)

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    # Bootstrap contains the NEW authoritative sid (just written by the hook)
    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    bootstrap.write_text("new-sid-9999", encoding="utf-8")
    bootstrap_mtime_before = os.path.getmtime(bootstrap)
    bootstrap_contents_before = bootstrap.read_text(encoding="utf-8").strip()

    # Trigger _get_session_id_fast: cached JSONL doesn't exist yet, fall
    # through to slow path which finds old-sid-0000 as newest.
    result = obsidian_utils._get_session_id_fast()

    # The function may return either value — the return value is not what
    # we're testing. What matters: the bootstrap file MUST NOT be clobbered.
    bootstrap_contents_after = bootstrap.read_text(encoding="utf-8").strip()
    assert bootstrap_contents_after == bootstrap_contents_before, (
        f"slow path clobbered the bootstrap: before={bootstrap_contents_before!r} "
        f"after={bootstrap_contents_after!r}"
    )
    # And the mtime must be unchanged
    assert os.path.getmtime(bootstrap) == bootstrap_mtime_before


def test_get_session_id_fast_slow_path_returns_without_writing(tmp_path, monkeypatch):
    """When no bootstrap exists, slow path returns newest sid but creates no bootstrap file."""
    import obsidian_utils
    import os
    import time

    project_basename = "nobootstrap-proj"
    cc_projects = tmp_path / ".claude" / "projects" / f"-foo-{project_basename}"
    cc_projects.mkdir(parents=True)

    only_jsonl = cc_projects / "only-sid-abcd.jsonl"
    only_jsonl.write_text("{}", encoding="utf-8")
    os.utime(only_jsonl, (time.time() - 60, time.time() - 60))

    proj_dir = tmp_path / project_basename
    proj_dir.mkdir()
    monkeypatch.chdir(proj_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(obsidian_utils, "_BOOTSTRAP_PREFIX", str(tmp_path / ".obsidian-brain-sid-"))

    bootstrap = tmp_path / f".obsidian-brain-sid-{project_basename}"
    assert not bootstrap.exists()

    result = obsidian_utils._get_session_id_fast()
    assert result == "only-sid-abcd"

    # Slow path must NOT have created a bootstrap file
    assert not bootstrap.exists(), (
        "slow path should be read-only and not create the bootstrap file"
    )


# ===========================================================================
# Section: upgrade_batch — concurrent wrapper around upgrade_unsummarized_note
# ===========================================================================


class TestUpgradeBatch:
    """Tests for upgrade_batch() — GH #69.

    `upgrade_unsummarized_note` is monkeypatched with fast fakes so none of
    these tests touch the filesystem, load a vault config, or shell out to
    `claude -p`. That isolation also means the `vault_path`/`sessions_folder`
    args are inert placeholder strings.
    """

    def test_upgrade_batch_empty_list_returns_empty(self, monkeypatch):
        """Empty input: return [] immediately and never invoke the wrapped fn."""
        calls = []

        def fake_impl(*args, **kwargs):
            calls.append(args)
            return "ok"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)

        result = obsidian_utils.upgrade_batch(
            [], "/vault", "sessions", "proj",
        )
        assert result == []
        assert calls == []

    def test_upgrade_batch_n1(self, monkeypatch):
        """Single path: single (path, status) tuple returned."""
        def fake_impl(note_path, *args, **kwargs):
            return f"Summarized: {os.path.basename(note_path)}"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)

        result = obsidian_utils.upgrade_batch(
            ["/vault/sessions/one.md"], "/vault", "sessions", "proj",
        )
        assert result == [("/vault/sessions/one.md", "Summarized: one.md")]

    def test_upgrade_batch_n5_preserves_input_order(self, monkeypatch):
        """5 paths with variable sleeps: return order matches input, not completion order."""
        import time as _time

        # Force inverted completion order: last input completes first.
        sleeps = {
            "a.md": 0.15,
            "b.md": 0.12,
            "c.md": 0.09,
            "d.md": 0.06,
            "e.md": 0.03,
        }

        def fake_impl(note_path, *args, **kwargs):
            _time.sleep(sleeps[os.path.basename(note_path)])
            return f"done:{os.path.basename(note_path)}"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)

        paths = [f"/vault/sessions/{name}" for name in ("a.md", "b.md", "c.md", "d.md", "e.md")]
        result = obsidian_utils.upgrade_batch(paths, "/vault", "sessions", "proj")

        assert len(result) == 5
        assert [p for p, _ in result] == paths, "input order must be preserved"
        assert [status for _, status in result] == [
            "done:a.md", "done:b.md", "done:c.md", "done:d.md", "done:e.md",
        ]

    def test_upgrade_batch_n10_runs_in_parallel(self, monkeypatch):
        """N=10 workers must all enter fake_impl concurrently.

        Concurrency is verified via threading.Barrier rather than wall-time
        bounds to avoid CI flakes; the Barrier times out with
        BrokenBarrierError if the executor serializes.
        """
        import threading

        N = 10
        barrier = threading.Barrier(N, timeout=5.0)  # generous margin for CI

        def fake_impl(note_path, *args, **kwargs):
            barrier.wait()  # raises BrokenBarrierError if < N threads ever gather
            return f"Upgraded {os.path.basename(note_path)} (source: JSONL)"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)
        paths = [f"/vault/sessions/note{i}.md" for i in range(N)]
        results = obsidian_utils.upgrade_batch(
            paths, "/vault", "sessions", "proj", max_workers=N,
        )
        assert len(results) == N
        assert all(s.startswith("Upgraded ") for _, s in results)

    def test_upgrade_batch_captures_exceptions_per_note(self, monkeypatch):
        """One raising impl does not kill the batch; failure becomes a status string."""
        def fake_impl(note_path, *args, **kwargs):
            if os.path.basename(note_path) == "three.md":
                raise RuntimeError("boom")
            return f"ok:{os.path.basename(note_path)}"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)

        paths = [f"/vault/sessions/{n}" for n in
                 ("one.md", "two.md", "three.md", "four.md", "five.md")]
        result = obsidian_utils.upgrade_batch(paths, "/vault", "sessions", "proj")

        assert len(result) == 5
        assert [p for p, _ in result] == paths
        assert result[0][1] == "ok:one.md"
        assert result[1][1] == "ok:two.md"
        assert result[2] == ("/vault/sessions/three.md", "Failed: RuntimeError: boom")
        assert result[3][1] == "ok:four.md"
        assert result[4][1] == "ok:five.md"

    def test_upgrade_batch_max_workers_caps_at_input_size(self, monkeypatch):
        """N=3 < max_workers=10: min() guard still yields real parallelism.

        Concurrency is verified via threading.Barrier rather than wall-time
        bounds to avoid CI flakes; all 3 threads must gather at the barrier
        simultaneously or BrokenBarrierError fails the test.
        """
        import threading

        N = 3
        barrier = threading.Barrier(N, timeout=5.0)

        def fake_impl(note_path, *args, **kwargs):
            barrier.wait()
            return f"Upgraded {os.path.basename(note_path)} (source: JSONL)"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)
        paths = [f"/vault/sessions/a{i}.md" for i in range(N)]
        results = obsidian_utils.upgrade_batch(
            paths, "/vault", "sessions", "proj", max_workers=10,
        )
        assert len(results) == N
        assert all(s.startswith("Upgraded ") for _, s in results)

    def test_upgrade_batch_forwards_model_and_timeout(self, monkeypatch):
        received = {}

        def fake_impl(note_path, vault_path, sessions_folder, project,
                      summary_model, summary_timeout):
            received["model"] = summary_model
            received["timeout"] = summary_timeout
            return f"ok:{os.path.basename(note_path)}"

        monkeypatch.setattr(obsidian_utils, "upgrade_unsummarized_note", fake_impl)
        results = obsidian_utils.upgrade_batch(
            ["/vault/sessions/a.md"],
            "/vault",
            "sessions",
            "proj",
            summary_model="claude-3-5-haiku",
            summary_timeout=30,
        )
        assert results == [("/vault/sessions/a.md", "ok:a.md")]
        assert received == {"model": "claude-3-5-haiku", "timeout": 30}

    def test_upgrade_batch_rejects_invalid_max_workers(self, monkeypatch):
        monkeypatch.setattr(
            obsidian_utils, "upgrade_unsummarized_note",
            lambda *a, **k: "Upgraded test.md (source: ...)",
        )
        for bad in (0, -1, -100):
            with pytest.raises(ValueError, match="max_workers must be >= 1"):
                obsidian_utils.upgrade_batch(
                    ["/vault/sessions/a.md"], "/vault", "sessions", "proj",
                    max_workers=bad,
                )

    def test_upgrade_batch_skill_md_json_round_trip(self, monkeypatch):
        """Pins the exact expression used in skills/recall/SKILL.md Phase 1.

        If the tuple contract ever changes (e.g. to list[dict]), this test
        fails BEFORE production /recall breaks.
        """
        import json

        monkeypatch.setattr(
            obsidian_utils, "upgrade_unsummarized_note",
            lambda note_path, *a, **k: f"Upgraded {os.path.basename(note_path)} (source: JSONL)",
        )
        paths = [
            "/vault/sessions/a.md",
            "/vault/sessions/b.md",
            "/vault/sessions/c.md",
        ]
        results = obsidian_utils.upgrade_batch(paths, "/vault", "sessions", "proj")

        # This is the exact expression from skills/recall/SKILL.md line ~117
        serialized = json.dumps([{"path": p, "status": s} for p, s in results])
        parsed = json.loads(serialized)
        assert parsed == [
            {"path": "/vault/sessions/a.md", "status": "Upgraded a.md (source: JSONL)"},
            {"path": "/vault/sessions/b.md", "status": "Upgraded b.md (source: JSONL)"},
            {"path": "/vault/sessions/c.md", "status": "Upgraded c.md (source: JSONL)"},
        ]

    def test_upgrade_batch_real_integration_catches_signature_drift(
        self, monkeypatch, tmp_path
    ):
        """Drive the real upgrade_unsummarized_note through upgrade_batch.

        Monkeypatches only generate_summary (the claude -p shell-out) and
        find_transcript_jsonl (forced to None so the raw-note fallback
        runs deterministically). The rest of the pipeline runs for real.
        If upgrade_unsummarized_note ever gains a required positional
        parameter that upgrade_batch doesn't forward, this test fails —
        unit tests using *args/**kwargs fakes would silently pass.
        """
        vault = tmp_path / "vault"
        sessions_dir = vault / "sessions"
        sessions_dir.mkdir(parents=True)

        note_path = sessions_dir / "2026-04-20-integration-test-abcd.md"
        note_path.write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-20\n"
            "session_id: integration-test-session-id-0000-0000-000000000000\n"
            "project: test-project\n"
            "status: auto-logged\n"
            "tags:\n"
            "  - claude/session\n"
            "  - claude/project/test-project\n"
            "---\n\n"
            "# Session: test-project\n\n"
            "## Conversation (raw)\n"
            "**User:** hello\n"
            "**Assistant:** hi there\n"
        )

        def fake_generate_summary(*args, **kwargs):
            return (
                "## Summary\nDid a thing.\n\n"
                "## Key Decisions\n- None noted.\n\n"
                "## Changes Made\n- None noted.\n\n"
                "## Errors Encountered\n- None.\n\n"
                "## Open Questions / Next Steps\n- [ ] None.\n\n"
                "IMPORTANCE: 5\n"
            )

        monkeypatch.setattr(
            obsidian_utils, "generate_summary", fake_generate_summary
        )
        # Force raw-note fallback so we don't accidentally pick up a JSONL
        # from the developer's running CC environment.
        monkeypatch.setattr(
            obsidian_utils, "find_transcript_jsonl", lambda session_id: None
        )

        results = obsidian_utils.upgrade_batch(
            [str(note_path)], str(vault), "sessions", "test-project",
        )

        assert len(results) == 1
        path_result, status = results[0]
        assert path_result == str(note_path)
        assert status.startswith("Upgraded "), f"expected success, got: {status}"

        # Verify the note was actually rewritten with a summary
        updated = note_path.read_text()
        assert "status: summarized" in updated
        assert "## Summary" in updated
        assert "Did a thing." in updated
