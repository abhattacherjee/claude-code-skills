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
SUBAGENT_TIMEOUT_SEC = int(os.environ.get("CHECK_ITEMS_SUBAGENT_TIMEOUT_SEC", "300"))

# Cap groups per classifier sub-agent dispatch. Above this count, run_classifier()
# splits into sequential chunks of <=N so a single Sonnet call stays well under
# SUBAGENT_TIMEOUT_SEC. Override via CHECK_ITEMS_CLASSIFIER_CHUNK_SIZE; values <1
# are clamped to 1.
CLASSIFIER_CHUNK_SIZE = max(
    1, int(os.environ.get("CHECK_ITEMS_CLASSIFIER_CHUNK_SIZE", "25"))
)


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


def _strip_unreleased_section(changelog: str) -> str:
    """Remove the `## [Unreleased]` section (up to the next `## [x.y.z]` heading
    or end of text) from a Keep-a-Changelog excerpt. Released sections are
    completion statements by construction; the Unreleased section is WIP and
    over-triggers Rule 2 of has_classifiable_evidence.

    Case-insensitive match on `## [Unreleased]` (with optional trailing
    whitespace). If no Unreleased section is present, returns the input
    unchanged.
    """
    if not changelog:
        return ""
    # Match "## [Unreleased]" through the start of the next "## [" version heading
    # OR end-of-string. DOTALL so '.' spans newlines.
    pattern = re.compile(
        r"##\s*\[Unreleased\][^\n]*\n.*?(?=^##\s*\[|\Z)",
        flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    return pattern.sub("", changelog)


def _bridge_project_evidence(evidence: dict, project: str) -> dict:
    """Convert project evidence to the _text-suffixed flat format expected by
    has_classifiable_evidence().

    The live evidence payload from open_item_dedup.py uses a project-keyed nested
    structure with bare keys:
        {project_name: {"commits": [...], "merged_prs": [...], ...}}

    has_classifiable_evidence() expects a flat dict with _text-suffixed keys:
        {"commits_text": "...", "merged_prs_text": "...", ...}

    This helper bridges both shapes:
    - If the evidence dict contains the project key AND its value is a dict
      with bare keys → extract and convert to _text form.
    - If the evidence dict already has _text-suffixed keys at the top level
      (test fixtures, simplified payloads) → return as-is.
    - If neither shape matches → return empty dict (fail-safe: no evidence → synthetic).
    """
    # Shape A: project-nested bare keys (production shape from open_item_dedup.py)
    if project and project in evidence and isinstance(evidence[project], dict):
        proj = evidence[project]
        # Convert list/dict values to text by joining stringified items
        def _to_text(val) -> str:
            if not val:
                return ""
            if isinstance(val, str):
                return val
            if isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        # merged_prs / closed_issues: titles encode completion;
                        # bodies are activity content (discuss problem + adjacent work)
                        # and would over-trigger Rule 2 of has_classifiable_evidence.
                        # Include number for traceability but NOT body.
                        title = item.get("title", "")
                        number = item.get("number", "")
                        if title or number:
                            parts.append(f"#{number} {title}".strip() if number else title)
                        else:
                            # Unknown dict shape — fall back to joining values (preserves
                            # backward-compat for non-{title,body} dicts)
                            parts.append(" ".join(str(v) for v in item.values() if v))
                return " ".join(parts)
            if isinstance(val, dict):
                # fts_mentions: {text: count} — join all keys
                return " ".join(str(k) for k in val)
            return str(val)

        return {
            "commits_text": _to_text(proj.get("commits")),
            "merged_prs_text": _to_text(proj.get("merged_prs")),
            "closed_issues_text": _to_text(proj.get("closed_issues")),
            "releases_text": _to_text(proj.get("releases")),
            "changelog_excerpt": _strip_unreleased_section(proj.get("changelog_excerpt") or ""),
            "fts_mentions_text": _to_text(proj.get("fts_mentions")),
        }

    # Shape B: already _text-suffixed at top level (test fixtures / simplified payloads)
    _TEXT_KEYS = {"commits_text", "merged_prs_text", "closed_issues_text",
                  "releases_text", "changelog_excerpt", "fts_mentions_text"}
    if _TEXT_KEYS.intersection(evidence.keys()):
        return evidence

    # Unknown shape or missing project → no evidence (fail-safe).
    # Before warning, check whether the payload IS a valid shape A for a
    # different project (multi-project payload, this group's project not
    # present). Shape A is recognized by any top-level value being a dict
    # that contains at least one bare evidence key. In that case, the
    # legitimate answer is "no evidence for this project" — return {} silently.
    # Only WARN when neither shape A nor shape B is recognizable at all.
    _BARE_KEYS = {"commits", "merged_prs", "closed_issues", "releases",
                  "changelog_excerpt", "fts_mentions"}
    _is_shape_a_payload = any(
        isinstance(v, dict) and _BARE_KEYS.intersection(v.keys())
        for v in evidence.values()
    )
    if _is_shape_a_payload:
        # Valid shape A payload, but project not present — no evidence for this group.
        return {}

    # Genuinely unrecognized shape — warn, as this indicates a format change
    # that would silently STALE all groups without this diagnostic.
    if evidence:
        print(
            f"[check-items-cli] WARN: _bridge_project_evidence unrecognized shape "
            f"for project={project!r}; top-level keys={list(evidence.keys())[:10]}",
            file=sys.stderr,
        )
    return {}


def _dispatch_classifier_chunk(
    chunk_groups: list, evidence: dict, model: str, output_path: str,
    chunk_label: str = "",
) -> tuple[int, list]:
    """Dispatch one claude -p classifier call for a single chunk of groups.

    Writes the classifier input as a temp file under the workdir, invokes
    `claude -p --model {model}` with the CLASSIFIER_PROMPT pointing at that
    file and at `output_path`, then reads results from `output_path` (or
    stdout as fallback). The temp input is unlinked even if json.dump,
    os.chmod, or the subprocess raise.

    `chunk_label` is prepended to diagnostic messages so callers running
    multiple sequential dispatches can identify the failing chunk. Pass
    "" (default) for single-call use.

    Returns (rc, sub_results). On success rc == 0 and sub_results is the
    validated classifier payload. On any failure rc is non-zero and
    sub_results is [].

    rc semantics: 0 success; 3 subprocess timeout; 4 invalid JSON or
    wrong payload shape from sub-agent; any other value = passthrough
    of claude -p's non-zero returncode.
    """
    workdir = _safe_workdir()
    in_tmp = tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(workdir),
        suffix=".classin.json", encoding="utf-8",
    )
    in_tmp_path = in_tmp.name
    try:
        try:
            sub_payload = {"groups": chunk_groups, "evidence": evidence}
            json.dump(sub_payload, in_tmp)
            in_tmp.flush()
        finally:
            in_tmp.close()
        os.chmod(in_tmp_path, 0o600)

        prompt = CLASSIFIER_PROMPT.replace(
            "<input-json-path>", in_tmp_path
        ).replace(
            "<output-json-path>", output_path
        )

        cmd = ["claude", "-p", "--model", model]
        try:
            cp = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=SUBAGENT_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            print(
                f"[check-items-cli] {chunk_label}classifier timeout after "
                f"{SUBAGENT_TIMEOUT_SEC}s",
                file=sys.stderr,
            )
            return 3, []
    finally:
        try:
            os.unlink(in_tmp_path)
        except OSError:
            pass

    if cp.returncode != 0:
        print(
            f"[check-items-cli] {chunk_label}classifier failed "
            f"rc={cp.returncode}: {cp.stderr[:500]}",
            file=sys.stderr,
        )
        return cp.returncode, []

    if Path(output_path).exists():
        try:
            parsed = json.loads(Path(output_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"[check-items-cli] {chunk_label}classifier output invalid "
                f"JSON: {exc}",
                file=sys.stderr,
            )
            return 4, []
        if not _validate_classifier_payload(parsed):
            print(
                f"[check-items-cli] {chunk_label}classifier file-path output "
                f"produced invalid shape (expected list of classifier "
                f"objects, got {type(parsed).__name__})",
                file=sys.stderr,
            )
            return 4, []
        return 0, parsed

    try:
        parsed = json.loads(_strip_json_fences(cp.stdout))
    except json.JSONDecodeError as exc:
        print(
            f"[check-items-cli] {chunk_label}classifier output invalid "
            f"JSON: {exc}",
            file=sys.stderr,
        )
        return 4, []
    if not _validate_classifier_payload(parsed):
        print(
            f"[check-items-cli] {chunk_label}classifier stdout-fallback "
            f"produced invalid shape (expected list of classifier objects, "
            f"got {type(parsed).__name__})",
            file=sys.stderr,
        )
        return 4, []
    return 0, parsed


def run_classifier(stdin_json: str, output_path: str) -> int:
    """
    Stage 4: invoke the classifier sub-agent, with L2 evidence-presence
    pre-filter applied to all groups before any claude -p dispatch.

    Flow:
      1. Parse stdin JSON to extract groups + evidence.
      2. Apply L2 pre-filter (if enabled): items with no evidence go to
         synthetic_classification(); items with evidence go to the sub-agent.
      3. If to_classify is non-empty, dispatch claude -p. When
         len(to_classify) > CLASSIFIER_CHUNK_SIZE, split into sequential
         chunks of <=CLASSIFIER_CHUNK_SIZE groups so a single call stays
         well under SUBAGENT_TIMEOUT_SEC.
      4. Merge sub-agent results + synthetic results in input order.
      5. Write merged output to output_path (0o600).
      6. Emit telemetry line to stderr.

    Returns 0 on success, non-zero on failure.
    """
    import time as _time
    _wall_start = _time.monotonic()

    try:
        payload = json.loads(stdin_json)
    except json.JSONDecodeError as exc:
        print(f"[check-items-cli] ERROR: classifier stdin invalid JSON: {exc}",
              file=sys.stderr)
        return 2

    groups = payload.get("groups", [])
    evidence = payload.get("evidence", {})

    # -----------------------------------------------------------------------
    # Validate group_id presence — a None group_id causes silent key collision
    # in merged_by_id, so two groups overwrite each other and the ordered list
    # contains the same record twice.  Fail fast with a clear diagnostic.
    # -----------------------------------------------------------------------
    invalid_ids = [i for i, g in enumerate(groups) if g.get("group_id") is None]
    if invalid_ids:
        print(
            f"[check-items-cli] ERROR: {len(invalid_ids)} group(s) have group_id=None "
            f"(indices {invalid_ids[:10]}); cannot merge — aborting classifier",
            file=sys.stderr,
        )
        return 5

    # -----------------------------------------------------------------------
    # L2: evidence-presence pre-filter
    # Groups reaching this function are already L1-miss (partition() in the
    # SKILL.md orchestration layer handled cache hits before calling the CLI).
    # -----------------------------------------------------------------------
    from check_items_prefilter import (
        has_classifiable_evidence,
        synthetic_classification,
        is_prefilter_enabled,
    )

    synthetic: list = []
    to_classify: list = list(groups)

    if is_prefilter_enabled() and groups:
        to_classify = []
        for g in groups:
            project = g.get("project", "")
            bridged_evidence = _bridge_project_evidence(evidence, project)
            if has_classifiable_evidence(g, bridged_evidence):
                to_classify.append(g)
            else:
                synthetic.append(synthetic_classification(g))

    # -----------------------------------------------------------------------
    # Sub-agent dispatch — only on groups that have evidence
    # -----------------------------------------------------------------------
    sub_results: list = []
    chunk_count = 0

    if to_classify:
        if len(to_classify) <= CLASSIFIER_CHUNK_SIZE:
            model = _pick_classifier_model(len(to_classify))
            chunk_count = 1
            rc, chunk_results = _dispatch_classifier_chunk(
                to_classify, evidence, model, output_path
            )
            if rc != 0:
                return rc
            sub_results = chunk_results
        else:
            chunks = [
                to_classify[i:i + CLASSIFIER_CHUNK_SIZE]
                for i in range(0, len(to_classify), CLASSIFIER_CHUNK_SIZE)
            ]
            chunk_count = len(chunks)
            # Per-chunk model picking: the 30-group Haiku/Sonnet threshold was
            # tuned against single-dispatch payloads. Each chunk here is sized
            # at <=CLASSIFIER_CHUNK_SIZE, which is below that threshold by
            # default — so chunks get Haiku regardless of the total payload
            # size. Lets large vaults stay on the fast/cheap model per call.
            print(
                f"[check-items-cli] classifier: chunking {len(to_classify)} "
                f"groups into {chunk_count} chunk(s) of <={CLASSIFIER_CHUNK_SIZE}",
                file=sys.stderr,
            )
            workdir = _safe_workdir()
            chunk_outputs: list = []
            completed_chunks = 0
            try:
                for idx, chunk in enumerate(chunks):
                    out_tmp = tempfile.NamedTemporaryFile(
                        mode="w", delete=False, dir=str(workdir),
                        suffix=f".chunk-{idx}.classout.json", encoding="utf-8",
                    )
                    chunk_outputs.append(out_tmp.name)
                    out_tmp.close()
                    chunk_model = _pick_classifier_model(len(chunk))
                    label = f"chunk {idx + 1}/{chunk_count} (model={chunk_model}): "
                    rc, chunk_results = _dispatch_classifier_chunk(
                        chunk, evidence, chunk_model, out_tmp.name,
                        chunk_label=label,
                    )
                    if rc != 0:
                        # Discarded earlier-chunk classifications surfaced so
                        # operators can tell partial chunking from total failure.
                        print(
                            f"[check-items-cli] classifier: aborting after "
                            f"chunk {idx + 1}/{chunk_count} rc={rc} "
                            f"(completed={completed_chunks}, "
                            f"discarded_groups={len(sub_results)})",
                            file=sys.stderr,
                        )
                        return rc
                    sub_results.extend(chunk_results)
                    completed_chunks += 1
            finally:
                for path in chunk_outputs:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    # -----------------------------------------------------------------------
    # Merge in input order and write final output
    # -----------------------------------------------------------------------
    merged_by_id: dict = {}
    for s in sub_results:
        merged_by_id[s["group_id"]] = s
    for s in synthetic:
        merged_by_id[s["group_id"]] = s

    ordered = [merged_by_id[g["group_id"]] for g in groups if g["group_id"] in merged_by_id]

    Path(output_path).write_text(json.dumps(ordered), encoding="utf-8")
    os.chmod(output_path, 0o600)

    # -----------------------------------------------------------------------
    # Telemetry — inner line (CLI sees only L1-miss groups; cache_hit is '-'
    # by design — the orchestration layer in open_item_dedup.py holds that
    # count and emits the outer classifier-result line with real cache_hit).
    # -----------------------------------------------------------------------
    _wall = int(_time.monotonic() - _wall_start)
    total = len(groups)
    prefiltered_count = len(synthetic)
    subagent_count = len(sub_results)
    chunks_field = f" chunks={chunk_count}" if chunk_count > 1 else ""
    print(
        f"[check-items-cli] classifier: total={total} cache_hit=- "
        f"prefiltered={prefiltered_count} subagent={subagent_count}"
        f"{chunks_field} wall={_wall}s",
        file=sys.stderr,
    )

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
