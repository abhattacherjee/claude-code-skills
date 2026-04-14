"""CLI helpers for /standup deep — thin wrappers around open_item_dedup functions.

Each function is designed to be called from a minimal ``python3 -c`` stub
in the standup SKILL.md, keeping inline code to 2-3 lines.
"""
from __future__ import annotations

import json
import os
import sys
import time

from open_item_dedup import build_deep_presentation, deep_analysis_pipeline


def run_pipeline(vault_path: str, sessions_folder: str, insights_folder: str) -> None:
    """Run deep analysis pipeline for /standup deep.

    Reads ``{"basenames": [...], "projects": [...]}`` from stdin.
    Prints status line: ``OK:<n>:<g>:<e>`` or ``CACHED:<n>:<g>:<e>``.
    """
    data = json.load(sys.stdin)
    basenames = data["basenames"]
    projects_json = json.dumps(data["projects"])

    output_path = os.path.expanduser("~/.claude/obsidian-brain/deep-pipeline.json")

    # Cache check: reuse if exists and < 15 min old
    if os.path.isfile(output_path) and (time.time() - os.path.getmtime(output_path)) < 900:
        with open(output_path) as f:
            cached = json.load(f)
        items = cached.get("items", {})
        n = items.get("total_raw", 0)
        g = items.get("group_count", 0)
        e = sum(
            1
            for v in cached.get("evidence", {}).values()
            if v.get("commits") or v.get("releases")
        )
        print(f"CACHED:{n}:{g}:{e}")
        return

    status = deep_analysis_pipeline(
        basenames,
        projects_json,
        output_path,
        vault_path,
        sessions_folder,
        insights_folder,
    )

    # Filter out recently acted-on items so they aren't re-recommended
    acted = _load_acted_items()
    if acted and not status.startswith("ERROR:") and os.path.isfile(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                pipeline_data = json.load(f)
            groups = pipeline_data.get("items", {}).get("groups", [])
            original_count = len(groups)
            filtered = [g for g in groups if g.get("representative", "") not in acted]
            if len(filtered) < original_count:
                pipeline_data["items"]["groups"] = filtered
                pipeline_data["items"]["group_count"] = len(filtered)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(pipeline_data, f, indent=2)
                skipped = original_count - len(filtered)
                print(f"[obsidian-brain] filtered {skipped} recently acted-on item(s)", file=sys.stderr)
        except (OSError, json.JSONDecodeError):
            pass  # best-effort filtering

    print(status)


def run_present(vault_path: str, sessions_folder: str, insights_folder: str) -> None:
    """Build deep analysis presentation.

    Reads basenames JSON array from stdin.
    Prints formatted markdown output.
    """
    basenames_json = sys.stdin.read(1_000_000)
    output = build_deep_presentation(
        os.path.expanduser("~/.claude/obsidian-brain/deep-pipeline.json"),
        os.path.expanduser("~/.claude/obsidian-brain/deep-classifications.json"),
        basenames_json,
        vault_path,
        sessions_folder,
        insights_folder,
    )
    print(output)


_ACTED_ITEMS_PATH = os.path.expanduser("~/.claude/obsidian-brain/deep-acted-items.json")
_ACTED_TTL_SECONDS = 86400  # 24 hours


def _load_acted_items() -> set[str]:
    """Load recently acted-on item texts (within TTL)."""
    if not os.path.isfile(_ACTED_ITEMS_PATH):
        return set()
    try:
        import time
        if time.time() - os.path.getmtime(_ACTED_ITEMS_PATH) > _ACTED_TTL_SECONDS:
            os.remove(_ACTED_ITEMS_PATH)
            return set()
        with open(_ACTED_ITEMS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_acted_items(items: set[str]) -> None:
    """Persist acted-on item texts (append to existing). Best-effort."""
    existing = _load_acted_items()
    combined = existing | items
    try:
        os.makedirs(os.path.dirname(_ACTED_ITEMS_PATH), exist_ok=True)
        with open(_ACTED_ITEMS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(combined), f)
    except OSError as exc:
        print(f"[obsidian-brain] warning: could not save acted items: {exc}", file=sys.stderr)


def run_batch_edit() -> None:
    """Batch edit vault files (checkoffs, link additions).

    Reads JSON array of ``[filepath, old_text, new_text]`` triples from stdin.
    Prints ``Applied N/M edits``.
    Records acted-on items so they aren't re-recommended on next run.
    """
    import tempfile

    from obsidian_utils import load_config

    c = load_config()
    vault_root = os.path.realpath(c["vault_path"])

    edits = json.load(sys.stdin)
    success = 0
    acted_texts: set[str] = set()
    for filepath, old_text, new_text in edits:
        try:
            real_path = os.path.realpath(filepath)
            if not real_path.startswith(vault_root + os.sep) and real_path != vault_root:
                print(f"[obsidian-brain] path containment violation: {filepath}", file=sys.stderr)
                continue

            with open(real_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if old_text in content:
                content = content.replace(old_text, new_text, 1)
                fd, tmp = tempfile.mkstemp(
                    dir=os.path.dirname(real_path), suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(content)
                    os.chmod(tmp, 0o600)
                    os.replace(tmp, real_path)
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                success += 1
                # Track the item text (strip checkbox prefix for matching)
                item_text = old_text.replace("- [ ] ", "").replace("- [x] ", "").strip()
                if item_text:
                    acted_texts.add(item_text)
        except OSError as e:
            print(f"[obsidian-brain] edit failed {filepath}: {e}", file=sys.stderr)
    if acted_texts:
        _save_acted_items(acted_texts)
    print(f"Applied {success}/{len(edits)} edits")
