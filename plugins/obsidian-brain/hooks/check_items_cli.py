"""
CLI wrappers for /check-items sub-agent stages.

Keeps SKILL.md free of inline agent prompts. Two entry points:
  - run_semantic_merge: Stage 2b grouping sub-agent.
  - run_classifier:     Stage 4 classification sub-agent (Phase E).

Per spec § New hooks/check_items_cli.py (lines 581-587).
Stdin is capped at 1_000_000 bytes (project CLAUDE.md security pattern).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

STDIN_CAP_BYTES = 1_000_000
SUBAGENT_TIMEOUT_SEC = int(os.environ.get("CHECK_ITEMS_SUBAGENT_TIMEOUT_SEC", "180"))


_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")


def _strip_json_fences(text: str) -> str:
    """Strip leading/trailing markdown code fences (```json … ```) from sub-agent
    stdout output. Some models (notably Haiku) wrap JSON responses in fences
    even when prompted to write raw JSON; the stdout-fallback path must
    tolerate this before json.loads.

    R12 dogfood finding: 52-group obsidian-brain payload, Haiku semantic-merge
    consistently emits fenced output AND skips the output_path write, so the
    fallback's json.loads(cp.stdout) crashed on the leading backtick."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = _FENCE_OPEN_RE.sub("", stripped, count=1)
    stripped = _FENCE_CLOSE_RE.sub("", stripped, count=1)
    return stripped.strip()


_REQUIRED_CLASSIFIER_FIELDS = {
    "group_id", "classification", "confidence",
    "canonical_text", "evidence_citation", "action_required",
}
_VALID_CLASSIFICATIONS = frozenset({"DONE", "NEEDS-ACTION", "STALE", "ACTIVE"})


def _validate_classifier_payload(parsed) -> bool:
    """Return True iff parsed is a list of dicts with all required classifier
    fields and a recognised classification value.

    Mirrors the checks in open_item_dedup._validate_classifier_response so the
    stdout-fallback path in run_classifier() rejects wrong-shape sub-agent
    responses before they are written to disk.
    """
    if not isinstance(parsed, list):
        return False
    for item in parsed:
        if not isinstance(item, dict):
            return False
        if not _REQUIRED_CLASSIFIER_FIELDS.issubset(item.keys()):
            return False
        if item.get("classification") not in _VALID_CLASSIFICATIONS:
            return False
    return True


SEMANTIC_MERGE_PROMPT = """You are the semantic-merge sub-agent for an open-items pipeline. Read
<input-json-path>. It contains N coarse token-grouped open items.

## Your job

Identify groups that describe the same concrete action even when they
share few tokens. Token-based grouping already caught literal
duplicates; your job is to catch semantic duplicates.

## The key test - are these the same action?

Two items A and B should merge when a user would mark BOTH as done
simultaneously once the underlying work ships. If completing A leaves
B still genuinely to-do, they are NOT the same action.

## Concrete examples from real vault data

### SHOULD MERGE (same action, different phrasing)

Example 1:
- A: "Decide text-fallback routing vs. sentinel option to satisfy
     AskUserQuestion minItems=2"
- B: "Review fuzzy-matched cascade candidate about routing N=1 to
     text-fallback"
-> MERGE. Both describe the same decision about N=1 text-fallback
  routing. B is just pointing at a prior note that raised it.

Example 2:
- A: "Fresh session: execute Phases 1-4 (live /compact x2 + Ctrl-D)"
- B: "Complete live-CC smoke test from DEV-TEST-SNAPSHOTS.md"
-> MERGE. Both describe running the smoke-test protocol; the first
  literally lists the steps, the second names it.

### SHOULD NOT MERGE (related but distinct)

Example 3:
- A: "Run /vault-doctor --check snapshot-integrity (dry-run)"
- B: "Run /vault-doctor fix --check snapshot-integrity (apply mode)"
-> DO NOT MERGE. Different commands with different side effects.

Example 4:
- A: "Investigate dispatcher-discovery fallback logic"
- B: "Fix dispatcher-discovery fallback to probe check availability"
-> DO NOT MERGE. Investigate is not Fix.

Example 5:
- A: "PR #67 (doc): Finalize snapshot-summary user-facing docs"
- B: "PR #70 (read-path): Fix session->snapshots forward backlink
     undercounting"
-> DO NOT MERGE. Same parent feature, different PRs shipping different
  work.

## Rules

1. Same-project only (enforced in Python, not by you).
2. Apply the "both get marked done simultaneously" test above.
3. Emit a mergeable pair even when tokens do not overlap - that is the
   whole reason you exist.
4. When in doubt between merging and not, DO NOT MERGE. Classifier
   downstream can still close items separately.

## Output format

Return STRICT JSON ONLY - no prose, no markdown fences, nothing
outside the JSON. Write the same JSON to <output-json-path>.

{
  "merges": [
    {
      "canonical_group_id": "ob-NNNN",
      "absorbed_group_ids": ["ob-MMMM"],
      "reasoning": "one sentence with the both-done-together justification"
    }
  ],
  "total_groups_before": <int>,
  "total_groups_after": <int>
}

Your final message must be exactly the JSON.
"""


def _pick_model(group_count: int) -> str:
    """<=60 groups -> haiku, >60 -> sonnet. Per spec line 83."""
    return "haiku" if group_count <= 60 else "sonnet"


def _read_stdin_capped() -> str:
    """Read stdin with the 1_000_000-byte cap (project security pattern)."""
    return sys.stdin.read(STDIN_CAP_BYTES)


def _safe_workdir() -> Path:
    """Return ~/.claude/obsidian-brain/, ensure 0o700, no predictable /tmp paths."""
    workdir = Path.home() / ".claude" / "obsidian-brain"
    workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return workdir


def run_semantic_merge(stdin_json: str, output_path: str) -> int:
    """
    Stage 2b: invoke the semantic-merge sub-agent.

    Reads coarse groups from stdin_json, writes merge map to output_path
    as STRICT JSON. Returns 0 on success, non-zero on subprocess failure
    or JSON validation failure.
    """
    try:
        payload = json.loads(stdin_json)
    except json.JSONDecodeError as exc:
        print(f"[check-items-cli] ERROR: invalid stdin JSON: {exc}", file=sys.stderr)
        return 2

    groups = payload.get("groups", [])
    model = _pick_model(len(groups))

    workdir = _safe_workdir()
    in_tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(workdir), suffix=".in.json", encoding="utf-8"
    )
    try:
        json.dump(payload, in_tmp)
        in_tmp.flush()
    finally:
        in_tmp.close()
    os.chmod(in_tmp.name, 0o600)

    prompt = SEMANTIC_MERGE_PROMPT.replace(
        "<input-json-path>", in_tmp.name
    ).replace(
        "<output-json-path>", output_path
    )

    cmd = ["claude", "-p", "--model", model]
    try:
        cp = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=SUBAGENT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        print(f"[check-items-cli] timeout after {SUBAGENT_TIMEOUT_SEC}s on model={model}",
              file=sys.stderr)
        return 3
    finally:
        try:
            os.unlink(in_tmp.name)
        except OSError:
            pass

    if cp.returncode != 0:
        print(f"[check-items-cli] subagent failed rc={cp.returncode}: {cp.stderr[:500]}",
              file=sys.stderr)
        return cp.returncode

    if not Path(output_path).exists():
        try:
            parsed = json.loads(_strip_json_fences(cp.stdout))
        except json.JSONDecodeError as exc:
            print(f"[check-items-cli] subagent output invalid JSON: {exc}", file=sys.stderr)
            return 4
        Path(output_path).write_text(json.dumps(parsed), encoding="utf-8")
        os.chmod(output_path, 0o600)

    return 0


# Stage 4 classifier prompt. Spec §§:
#   - Classifier contract / Prompt shape (lines 262-289)
#   - Classification semantics (lines 317-322) — INCLUDING the self-referential
#     rule (line 321, Patch 3): discovery evidence is NOT completion evidence.
CLASSIFIER_PROMPT = """You are the classifier sub-agent for /check-items. Read the JSON at
<input-json-path>. It contains:
  - groups: list of merged open-item groups (post Stage 2b).
  - evidence: per-project bundle (commits, merged_prs, closed_issues,
    releases, changelog_excerpt, fts_mentions).

## Your job

For each group, decide whether the action it describes is DONE,
NEEDS-ACTION, STALE, or ACTIVE. Cite the specific evidence you used.

## Classification semantics

- DONE — the action is complete. Cite at least one of: merged PR title,
  commit sha, closed issue body, release note, or an insight note that
  explicitly marks the item done.
- NEEDS-ACTION — the fix is shipped, but the literal action is an
  external command this tool cannot run (e.g. `gh issue close`, token
  rotation, manual verification). Set `action_required` to a
  copy-pasteable command or instruction.
- STALE — item is >90 days old and no recent evidence mentions it.
  LOW confidence by default.
- ACTIVE — you did not find sufficient evidence to close. Set
  `evidence_citation` to null.

## Self-referential evidence rule (CRITICAL)

If the cited evidence is a discovery or description of the bug rather
than its fix-merge (closed PR/issue or commit sha), prefer ACTIVE.
Discovery evidence is NOT completion evidence. Examples:

- Item: "Fix dispatcher-discovery fallback to probe check availability"
- Evidence: "Note 2026-04-22 describes the dispatcher-discovery bug."
- -> ACTIVE. The note describes the bug; it does not ship the fix.

- Item: "Close GitHub issue #534"
- Evidence: "PR #534 merged as abc1234 on 2026-04-24."
- -> DONE. The fix-merge is cited directly.

## Anti-conflation rule

Different PR numbers under the same parent feature ship different work.
If the item references PR #N and the only evidence is PR #M (M != N),
do NOT mark DONE. Prefer ACTIVE unless there is independent evidence
that #N itself merged.

## Output format

Return STRICT JSON ONLY - no prose, no markdown fences. Write the same
JSON to <output-json-path>.

[
  {
    "group_id": "ob-NNNN",
    "classification": "DONE | NEEDS-ACTION | STALE | ACTIVE",
    "confidence": "HIGH | MED | LOW",
    "canonical_text": "<short canonical phrasing of the action>",
    "evidence_citation": "<specific commit sha / PR# / issue# / release / note ref, OR null>",
    "action_required": "<command string for NEEDS-ACTION, else null>"
  }
]

Your final message must be exactly the JSON array.
"""


def _pick_classifier_model(group_count: int) -> str:
    """<=30 merged groups -> haiku; >30 -> sonnet. Per spec line 106."""
    return "haiku" if group_count <= 30 else "sonnet"


def run_classifier(stdin_json: str, output_path: str) -> int:
    """
    Stage 4: invoke the classifier sub-agent.

    Reads merged groups + evidence from stdin_json, writes a strict-JSON
    array of {group_id, classification, confidence, canonical_text,
    evidence_citation, action_required} to output_path. Returns 0 on
    success, non-zero on failure.
    """
    try:
        payload = json.loads(stdin_json)
    except json.JSONDecodeError as exc:
        print(f"[check-items-cli] ERROR: classifier stdin invalid JSON: {exc}",
              file=sys.stderr)
        return 2

    groups = payload.get("groups", [])
    model = _pick_classifier_model(len(groups))

    workdir = _safe_workdir()
    in_tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(workdir), suffix=".classin.json", encoding="utf-8"
    )
    try:
        json.dump(payload, in_tmp)
        in_tmp.flush()
    finally:
        in_tmp.close()
    os.chmod(in_tmp.name, 0o600)

    prompt = CLASSIFIER_PROMPT.replace(
        "<input-json-path>", in_tmp.name
    ).replace(
        "<output-json-path>", output_path
    )

    cmd = ["claude", "-p", "--model", model]
    try:
        cp = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=SUBAGENT_TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired:
        print(f"[check-items-cli] classifier timeout after {SUBAGENT_TIMEOUT_SEC}s",
              file=sys.stderr)
        return 3
    finally:
        try:
            os.unlink(in_tmp.name)
        except OSError:
            pass

    if cp.returncode != 0:
        print(f"[check-items-cli] classifier failed rc={cp.returncode}: {cp.stderr[:500]}",
              file=sys.stderr)
        return cp.returncode

    if not Path(output_path).exists():
        try:
            parsed = json.loads(_strip_json_fences(cp.stdout))
        except json.JSONDecodeError as exc:
            print(f"[check-items-cli] classifier output invalid JSON: {exc}", file=sys.stderr)
            return 4
        if not _validate_classifier_payload(parsed):
            print(
                "[check-items-cli] classifier stdout-fallback produced invalid shape"
                f" (expected list of classifier objects, got {type(parsed).__name__})",
                file=sys.stderr,
            )
            return 4
        Path(output_path).write_text(json.dumps(parsed), encoding="utf-8")
        os.chmod(output_path, 0o600)

    return 0


def main():
    """CLI entrypoint. Usage: python3 check_items_cli.py <command> <output_path>"""
    if len(sys.argv) < 3:
        print("usage: check_items_cli.py <semantic_merge|classifier> <output_path>",
              file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    output_path = sys.argv[2]
    stdin_json = _read_stdin_capped()
    if cmd == "semantic_merge":
        sys.exit(run_semantic_merge(stdin_json, output_path))
    if cmd == "classifier":
        sys.exit(run_classifier(stdin_json, output_path))
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
