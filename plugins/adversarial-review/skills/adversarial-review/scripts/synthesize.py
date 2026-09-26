#!/usr/bin/env python3
"""
synthesize.py — symmetric convergence of Claude↔Gemini adversarial review rounds.

Usage:
  synthesize.py --claude-findings FILE --gemini-findings FILE
                --gemini-verdicts FILE --claude-verdicts FILE
                [--adversary gemini|codex|claude-only] [--md FILE] [--json FILE] [--help]

  --adversary-findings and --adversary-verdicts are the same flags as
  --gemini-findings and --gemini-verdicts. The adversary's verdict on a Claude
  finding is adversary_verdict; files that still say gemini_verdict are read
  too. --adversary sets killed_by, the default origin of the adversary's
  findings, and the labels in the report and the direction lines.

  --adversary claude-only is for the degraded no-adversary path: pass
  {"findings":[]} for --adversary-findings and {"verdicts":[]} for
  --adversary-verdicts and --claude-verdicts. Every Claude finding then comes
  out status=unconfirmed (nothing to confirm it), and report.json's
  summary.adversary is "claude-only", matching what `pr-audit.py record
  --adversary claude-only` expects.

Convergence rule (mechanical):
  A finding survives iff its author asserts it AND the opponent confirms it.
  No model adjudicates the other's findings — verdicts are looked up by id.

  Claude finding (origin=claude):
    adversary_verdict=confirm   -> status=survivor
    adversary_verdict=refute    -> status=rejected, killed_by=<adversary> (gemini by default)
    missing/none             -> status=unconfirmed

  Adversary finding (origin=<adversary>, gemini by default):
    claude_verdict=confirm   -> status=survivor
    claude_verdict=refute    -> status=rejected, killed_by=claude
    missing/none             -> status=unconfirmed

Exit codes:
  0  Success
  1  Error (file not found, parse error, etc.)
  2  Usage error
"""

import argparse
import json
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Confirm-rate guard: detects rubber-stamping (all-confirm) and
# rubber-rejecting (all-refute) judge behaviour, both of which are low-signal.
# ---------------------------------------------------------------------------
RUBBER_STAMP_MIN_JUDGED = 5            # below this, near-unanimity isn't meaningful signal
RUBBER_STAMP_CONFIRM_RATE_HIGH = 0.95  # >= this confirm-rate looks like rubber-stamping (all-confirm)
RUBBER_STAMP_CONFIRM_RATE_LOW = 0.05   # <= this looks like rubber-rejecting (all-refute), equally low-signal


def compute_confirm_rate(verdict_map: dict, verdict_field: str) -> dict:
    """Return {confirmed, refuted, judged, confirm_rate, low_signal, unrecognized} for one judge direction.

    judged = confirmed + refuted (verdicts that are neither are ignored for the rate).
    unrecognized = verdicts whose verdict_field is neither "confirm" nor "refute".
    confirm_rate = confirmed/judged (0.0 when judged==0).
    low_signal fires only with a meaningful sample AND near-unanimity in EITHER direction.
    """
    confirmed = sum(
        1 for v in verdict_map.values()
        if v.get(verdict_field) == "confirm"
    )
    refuted = sum(
        1 for v in verdict_map.values()
        if v.get(verdict_field) == "refute"
    )
    unrecognized = sum(
        1 for v in verdict_map.values()
        if v.get(verdict_field) not in ("confirm", "refute")
    )
    judged = confirmed + refuted
    confirm_rate = confirmed / judged if judged else 0.0
    low_signal = (
        judged >= RUBBER_STAMP_MIN_JUDGED
        and (
            confirm_rate >= RUBBER_STAMP_CONFIRM_RATE_HIGH
            or confirm_rate <= RUBBER_STAMP_CONFIRM_RATE_LOW
        )
    )
    return {
        "confirmed": confirmed,
        "refuted": refuted,
        "judged": judged,
        "confirm_rate": confirm_rate,
        "low_signal": low_signal,
        "unrecognized": unrecognized,
    }


def count_unjudged(findings, verdict_map):
    """Findings with an id but no entry at all in the judge's verdict map -- what a
    partial judge run (missing or unknown ids silently dropped, not defaulted)
    never answered. Distinct from "unrecognized" (an entry exists, its verdict
    value doesn't parse)."""
    return sum(1 for f in findings if f.get("id") and f["id"] not in verdict_map)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Symmetric convergence of Claude↔Gemini adversarial review: "
            "a finding survives iff its author asserts it AND the opponent confirms it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Convergence rule (mechanical):
  Claude finding: adversary_verdict=confirm -> survivor
                  adversary_verdict=refute  -> rejected (killed_by=<adversary>, gemini by default)
                  missing/none           -> unconfirmed

  Adversary finding (gemini by default): claude_verdict=confirm -> survivor
                  claude_verdict=refute  -> rejected (killed_by=claude)
                  missing/none           -> unconfirmed

Exit codes:
  0  Success
  1  Error (file not found, parse error, etc.)
  2  Usage error
""",
    )
    parser.add_argument("--claude-findings", required=True, metavar="FILE",
                        help="Claude R1 findings JSON (bare list OR {\"findings\":[...]})")
    parser.add_argument("--gemini-findings", "--adversary-findings", dest="gemini_findings",
                        required=True, metavar="FILE",
                        help="Adversary (Gemini or Codex) R1 findings JSON ({\"findings\":[...]} OR bare list)")
    parser.add_argument("--gemini-verdicts", "--adversary-verdicts", dest="gemini_verdicts",
                        required=True, metavar="FILE",
                        help="Adversary judging Claude: {\"verdicts\":[{\"id\",\"adversary_verdict\",\"reason\",\"confidence\"}]}")
    parser.add_argument("--adversary", choices=("gemini", "codex", "claude-only"), default="gemini",
                        help="the adversary model: sets killed_by, the default origin of its "
                             "findings, and the report labels (default: gemini). claude-only "
                             "is the degraded no-adversary path: pass empty findings/verdicts")
    parser.add_argument("--claude-verdicts", required=True, metavar="FILE",
                        help="Claude judging the adversary: {\"verdicts\":[{\"id\",\"claude_verdict\",\"reason\"}]}")
    parser.add_argument("--md", metavar="FILE",
                        help="Write human-readable markdown report to this file")
    parser.add_argument("--json", metavar="FILE", dest="json_out",
                        help="Write full structured JSON to this file")
    return parser.parse_args()


def load_json(path: str, label: str) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {label} file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: {label} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)


def unwrap_findings(raw: Any, label: str) -> list[dict]:
    """Accept a bare list OR {"findings": [...]}. Exit 1 on invalid shape."""
    if isinstance(raw, dict) and isinstance(raw.get("findings"), list):
        raw = raw["findings"]
    if not isinstance(raw, list):
        print(
            f"Error: {label} must be a JSON array of findings "
            "(or an object with a 'findings' list)",
            file=sys.stderr,
        )
        sys.exit(1)
    return raw


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _warn(msg: str) -> None:
    print(f"[synthesize] WARNING: {msg}", file=sys.stderr)


def reconcile_verdict_map(verdicts: list[dict], findings: list[dict], verdict_field: str) -> dict[str, dict]:
    """Map finding-id -> verdict, recovering verdicts whose 'id' is a slug or
    other non-canonical value instead of the orchestrator's C-NNN/G-NNN id.

    Matching is layered and conservative:
      1. exact finding-id,
      2. slugified-title equality (ambiguous title slugs are dropped),
      3. a single unambiguous file:line token in the verdict's reason.
    A candidate already claimed by another verdict is never overwritten, and the
    reason-location heuristic abstains when the reason points at more than one
    finding. Recovery is heuristic, so every recovery and every unrecoverable
    verdict is logged to stderr for audit. Returns a finding-id -> verdict dict;
    recovered verdicts are keyed by the resolved finding id. Every recovery and
    every unrecoverable verdict is logged to stderr for audit.
    """
    findings = [f for f in findings if f.get("id")]
    finding_ids = {f["id"] for f in findings}
    resolved = {}
    leftover = []
    for v in verdicts:
        vid = v.get("id")
        if not vid:
            continue
        if vid in finding_ids:
            if vid in resolved:
                _warn(f"duplicate verdict for finding id '{vid}'; keeping first "
                      f"({resolved[vid].get(verdict_field)!r}), ignoring later "
                      f"({v.get(verdict_field)!r})")
            else:
                resolved[vid] = v
        else:
            leftover.append(v)

    def build_index(key_fn):
        idx, ambiguous = {}, set()
        for f in findings:
            k = key_fn(f)
            if not k:
                continue
            if k in idx and idx[k] != f["id"]:
                ambiguous.add(k)
            else:
                idx[k] = f["id"]
        for k in ambiguous:
            idx.pop(k, None)
        return idx

    slug_index = build_index(lambda f: _slugify(f.get("title")))
    loc_index = build_index(
        lambda f: f"{f.get('path')}:{f.get('line')}"
        if f.get("path") and f.get("line") is not None else None
    )

    for v in leftover:
        vid = v["id"]
        candidates = set()
        slug_cand = slug_index.get(_slugify(vid))
        if slug_cand and slug_cand not in resolved:
            candidates.add(slug_cand)
        reason = v.get("reason", "") or ""
        loc_cands = {
            loc_index[tok]
            for tok in re.findall(r"[\w./-]+:\d+", reason)
            if tok in loc_index and loc_index[tok] not in resolved
        }
        if len(loc_cands) == 1:
            candidates.add(next(iter(loc_cands)))
        if len(candidates) == 1:
            target = next(iter(candidates))
            resolved[target] = v
            _warn(f"verdict id '{vid}' did not match any finding id; recovered "
                  f"(heuristic) -> '{target}' — verify this association")
        elif len(candidates) > 1:
            _warn(f"verdict id '{vid}' has conflicting recovery signals "
                  f"(slug and reason-location point to different findings: "
                  f"{sorted(candidates)}); abstaining — the targeted finding stays "
                  f"'unconfirmed' (its {verdict_field} is ignored)")
        else:
            _warn(f"verdict id '{vid}' did not match any finding id and could not "
                  f"be recovered; the targeted finding stays 'unconfirmed' "
                  f"(its {verdict_field} is ignored)")
    return resolved


def classify_findings(
    claude_findings: list[dict],
    gemini_findings: list[dict],
    gemini_verdicts_raw: dict,
    claude_verdicts_raw: dict,
    adversary="gemini",
) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """Apply symmetric convergence and return (findings, gemini_verdict_map, claude_verdict_map).

    The verdict maps are returned alongside the classified findings so callers can
    reuse them for the confirm-rate guard without a second reconcile call.
    """

    # Build verdict lookup maps with slug/location fallback matching (bug #30).
    # gemini_verdict_map: Gemini's verdicts on Claude findings, keyed by the
    # resolved Claude finding id (C-NNN); reconcile recovers slug/location-keyed
    # verdicts back to that id.
    gemini_verdict_map: dict[str, dict] = reconcile_verdict_map(
        gemini_verdicts_raw.get("verdicts", []), claude_findings, "adversary_verdict"
    )
    # claude_verdict_map: Claude's verdicts on Gemini findings, keyed by the
    # resolved Gemini finding id (G-NNN); same recovery applies.
    claude_verdict_map: dict[str, dict] = reconcile_verdict_map(
        claude_verdicts_raw.get("verdicts", []), gemini_findings, "claude_verdict"
    )

    classified: list[dict] = []

    # --- Process Claude findings ---
    for finding in claude_findings:
        f = dict(finding)
        if not f.get("id"):
            continue  # skip id-less entries defensively
        f.setdefault("origin", "claude")
        f.setdefault("killed_by", None)
        f.setdefault("kill_reason", None)
        f.setdefault("claude_verdict", None)
        f.setdefault("adversary_verdict", None)
        f.setdefault("status", None)

        fid = f["id"]
        g_verdict = gemini_verdict_map.get(fid)

        if g_verdict is None:
            f["adversary_verdict"] = None
            f["status"] = "unconfirmed"
        elif g_verdict.get("adversary_verdict") == "confirm":
            f["adversary_verdict"] = "confirm"
            f["status"] = "survivor"
        elif g_verdict.get("adversary_verdict") == "refute":
            f["adversary_verdict"] = "refute"
            f["status"] = "rejected"
            f["killed_by"] = adversary
            f["kill_reason"] = g_verdict.get("reason", "")
        else:
            f["adversary_verdict"] = g_verdict.get("adversary_verdict")
            f["status"] = "unconfirmed"
        if g_verdict is not None:
            f["verdict_reason"] = g_verdict.get("reason", "") or ""

        classified.append(f)

    # --- Process Gemini findings ---
    for finding in gemini_findings:
        f = dict(finding)
        if not f.get("id"):
            continue  # skip id-less entries defensively
        f.setdefault("origin", adversary)
        f.setdefault("killed_by", None)
        f.setdefault("kill_reason", None)
        f.setdefault("claude_verdict", None)
        f.setdefault("adversary_verdict", None)
        f.setdefault("status", None)

        fid = f["id"]
        c_verdict = claude_verdict_map.get(fid)

        if c_verdict is None:
            f["claude_verdict"] = None
            f["status"] = "unconfirmed"
        elif c_verdict.get("claude_verdict") == "confirm":
            f["claude_verdict"] = "confirm"
            f["status"] = "survivor"
        elif c_verdict.get("claude_verdict") == "refute":
            f["claude_verdict"] = "refute"
            f["status"] = "rejected"
            f["killed_by"] = "claude"
            f["kill_reason"] = c_verdict.get("reason", "")
        else:
            f["claude_verdict"] = c_verdict.get("claude_verdict")
            f["status"] = "unconfirmed"
        if c_verdict is not None:
            f["verdict_reason"] = c_verdict.get("reason", "") or ""

        classified.append(f)

    return classified, gemini_verdict_map, claude_verdict_map


ADVERSARY_LABEL = {"gemini": "Gemini", "codex": "Codex", "claude-only": "Claude-only"}
VERDICT_KEY = "adversary_verdict"
LEGACY_VERDICT_KEY = "gemini_verdict"


def upgrade_verdict_key(items):
    """Accept run files written before the rename: move gemini_verdict to adversary_verdict."""
    for item in items:
        if isinstance(item, dict) and LEGACY_VERDICT_KEY in item:
            value = item.pop(LEGACY_VERDICT_KEY)
            if item.get(VERDICT_KEY) is None:
                item[VERDICT_KEY] = value
    return items


SEVERITY_ORDER = {"critical": 0, "important": 1, "minor": 2}


def sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.get("severity", "minor"), 99), f.get("id", ""))
    )


def format_markdown(
    survivors: list[dict],
    unconfirmed: list[dict],
    rejected: list[dict],
    adversary="gemini",
) -> str:
    lines: list[str] = []

    lines.append("# Adversarial PR Review — Synthesis Report")
    lines.append("")
    lines.append(
        f"Survivors: {len(survivors)} | "
        f"Unconfirmed: {len(unconfirmed)} | "
        f"Rejected: {len(rejected)}"
    )
    lines.append("")
    lines.append(
        "> Convergence rule: a finding survives iff its author asserts it AND "
        "the opponent confirms it."
    )
    lines.append("")

    # SURVIVORS
    lines.append("---")
    lines.append("")
    lines.append("## Confirmed Findings (Survivors)")
    lines.append("")
    if survivors:
        for f in sort_findings(survivors):
            severity = f.get("severity", "unknown")
            category = f.get("category", "unknown")
            origin = f.get("origin", "unknown")
            path = f.get("path", "")
            line = f.get("line")
            loc = f"{path}:{line}" if line is not None else path
            lines.append(
                f"### [{severity.upper()}] {f.get('title', '(no title)')} "
                f"`{category}` *(origin: {origin})*"
            )
            if loc:
                lines.append(f"**Location:** `{loc}`")
            lines.append("")
            lines.append(f.get("rationale", ""))
            # Optionally append confirmer's reason
            if origin == "claude":
                g_v = f.get("adversary_verdict")
                if g_v == "confirm":
                    lines.append("")
                    lines.append(f"> Confirmed by {ADVERSARY_LABEL[adversary]}.")
            else:
                c_v = f.get("claude_verdict")
                if c_v == "confirm":
                    lines.append("")
                    lines.append("> Confirmed by Claude.")
            lines.append("")
    else:
        lines.append("_No findings confirmed by both models._")
        lines.append("")

    # UNCONFIRMED
    lines.append("---")
    lines.append("")
    lines.append("## Unconfirmed Findings (Single-Model Only)")
    lines.append("")
    lines.append(
        "> These findings were raised by one model but not confirmed (or not addressed) "
        "by the other. Review manually."
    )
    lines.append("")
    if unconfirmed:
        for f in sort_findings(unconfirmed):
            severity = f.get("severity", "unknown")
            category = f.get("category", "unknown")
            origin = f.get("origin", "unknown")
            path = f.get("path", "")
            line = f.get("line")
            loc = f"{path}:{line}" if line is not None else path
            lines.append(
                f"### [{severity.upper()}] {f.get('title', '(no title)')} "
                f"`{category}` *(origin: {origin})*"
            )
            if loc:
                lines.append(f"**Location:** `{loc}`")
            lines.append("")
            lines.append(f.get("rationale", ""))
            lines.append("")
    else:
        lines.append("_No unconfirmed findings._")
        lines.append("")

    # REJECTED
    lines.append("---")
    lines.append("")
    lines.append("## Rejected Findings")
    lines.append("")
    lines.append("> Findings that were raised by one model but explicitly refuted by the other.")
    lines.append("")
    if rejected:
        for f in sort_findings(rejected):
            severity = f.get("severity", "unknown")
            category = f.get("category", "unknown")
            origin = f.get("origin", "unknown")
            killed_by = f.get("killed_by", "unknown")
            kill_reason = f.get("kill_reason", "")
            path = f.get("path", "")
            line = f.get("line")
            loc = f"{path}:{line}" if line is not None else path
            lines.append(
                f"### [{severity.upper()}] {f.get('title', '(no title)')} "
                f"`{category}` *(origin: {origin})*"
            )
            if loc:
                lines.append(f"**Location:** `{loc}`")
            lines.append(f"**Killed by:** {killed_by}")
            if kill_reason:
                lines.append(f"**Reason:** {kill_reason}")
            lines.append("")
            lines.append(f.get("rationale", ""))
            lines.append("")
    else:
        lines.append("_No rejected findings._")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    claude_findings_raw = load_json(args.claude_findings, "claude-findings")
    gemini_findings_raw = load_json(args.gemini_findings, "gemini-findings")
    gemini_verdicts_raw = load_json(args.gemini_verdicts, "gemini-verdicts")
    claude_verdicts_raw = load_json(args.claude_verdicts, "claude-verdicts")

    # Unwrap / validate findings inputs (accept bare list or {"findings":[...]})
    claude_findings = unwrap_findings(claude_findings_raw, "claude-findings")
    gemini_findings = unwrap_findings(gemini_findings_raw, "gemini-findings")

    # Validate verdicts inputs must be dicts
    if not isinstance(gemini_verdicts_raw, dict):
        print(
            "Error: gemini-verdicts must be a JSON object with a 'verdicts' key",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(claude_verdicts_raw, dict):
        print(
            "Error: claude-verdicts must be a JSON object with a 'verdicts' key",
            file=sys.stderr,
        )
        sys.exit(1)

    upgrade_verdict_key(claude_findings)
    upgrade_verdict_key(gemini_findings)
    if isinstance(gemini_verdicts_raw.get("verdicts"), list):
        upgrade_verdict_key(gemini_verdicts_raw["verdicts"])
    adv = args.adversary
    classified, gemini_verdict_map, claude_verdict_map = classify_findings(
        claude_findings, gemini_findings, gemini_verdicts_raw, claude_verdicts_raw, adv
    )

    # Warn on id collisions across origins (both are preserved in the list)
    seen_ids: dict[str, str] = {}
    for f in classified:
        fid = f.get("id", "")
        origin = f.get("origin", "")
        if fid in seen_ids and seen_ids[fid] != origin:
            print(
                f"Warning: id '{fid}' appears in both claude and {adv} findings; "
                "both are preserved in output",
                file=sys.stderr,
            )
        seen_ids[fid] = origin

    survivors = [f for f in classified if f.get("status") == "survivor"]
    unconfirmed = [f for f in classified if f.get("status") == "unconfirmed"]
    rejected = [f for f in classified if f.get("status") == "rejected"]

    # Print summary counts to stdout
    print(f"survivors={len(survivors)} unconfirmed={len(unconfirmed)} rejected={len(rejected)}")

    # Confirm-rate guard: report rubber-stamp / rubber-reject signals for each judge direction.
    # Reuse the verdict maps built once inside classify_findings (no duplicate reconcile).
    gem_stats = compute_confirm_rate(gemini_verdict_map, "adversary_verdict")
    cla_stats = compute_confirm_rate(claude_verdict_map, "claude_verdict")
    # Findings whose id got no verdict entry at all from the judge (as opposed to
    # one with an unrecognized value): what a partial judge run (Task 4: Codex's
    # validate_judge drops missing/unknown ids, exit 0) silently skipped. These
    # findings are never confirmed by the convergence rule above -- they stay
    # "unconfirmed" -- but that count must be visible, not just implied.
    gem_unjudged = count_unjudged(claude_findings, gemini_verdict_map)
    cla_unjudged = count_unjudged(gemini_findings, claude_verdict_map)

    # Warn on unrecognized verdicts (Fix D)
    if gem_stats["unrecognized"] > 0:
        _warn(
            f"confirm-rate({adv}_on_claude): {gem_stats['unrecognized']} verdict(s) had an "
            "unrecognized verdict value — judge output may be malformed"
        )
    if cla_stats["unrecognized"] > 0:
        _warn(
            f"confirm-rate(claude_on_{adv}): {cla_stats['unrecognized']} verdict(s) had an "
            "unrecognized verdict value — judge output may be malformed"
        )

    print(
        f"{adv}_on_claude: confirmed={gem_stats['confirmed']} refuted={gem_stats['refuted']} "
        f"judged={gem_stats['judged']} confirm_rate={gem_stats['confirm_rate']:.3f} "
        f"low_signal={'true' if gem_stats['low_signal'] else 'false'} "
        f"unrecognized={gem_stats['unrecognized']} unjudged={gem_unjudged}"
    )
    print(
        f"claude_on_{adv}: confirmed={cla_stats['confirmed']} refuted={cla_stats['refuted']} "
        f"judged={cla_stats['judged']} confirm_rate={cla_stats['confirm_rate']:.3f} "
        f"low_signal={'true' if cla_stats['low_signal'] else 'false'} "
        f"unrecognized={cla_stats['unrecognized']} unjudged={cla_unjudged}"
    )

    # Warn loudly when low_signal fires (Fix E)
    if gem_stats["low_signal"]:
        _warn(
            f"confirm-rate guard FIRED ({adv}_on_claude): "
            f"confirm_rate={gem_stats['confirm_rate']:.3f} over {gem_stats['judged']} judged "
            "— judge may be rubber-stamping/rubber-rejecting; treat survivors with caution"
        )
    if cla_stats["low_signal"]:
        _warn(
            f"confirm-rate guard FIRED (claude_on_{adv}): "
            f"confirm_rate={cla_stats['confirm_rate']:.3f} over {cla_stats['judged']} judged "
            "— judge may be rubber-stamping/rubber-rejecting; treat survivors with caution"
        )

    # Write JSON output
    if args.json_out:
        output = {
            "summary": {
                "survivors": len(survivors),
                "unconfirmed": len(unconfirmed),
                "rejected": len(rejected),
                "total": len(classified),
                "adversary": adv,
                "unjudged": {f"{adv}_on_claude": gem_unjudged, f"claude_on_{adv}": cla_unjudged},
            },
            "findings": classified,
        }
        with open(args.json_out, "w") as f:
            json.dump(output, f, indent=2)

    # Write markdown output
    if args.md:
        md_content = format_markdown(survivors, unconfirmed, rejected, adv)
        with open(args.md, "w") as f:
            f.write(md_content)


if __name__ == "__main__":
    main()
