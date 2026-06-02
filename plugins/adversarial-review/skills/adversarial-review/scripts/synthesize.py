#!/usr/bin/env python3
"""
synthesize.py — merge R1/R2/R3 adversarial review rounds, classify findings.

Usage:
  synthesize.py --r1 <r1.json> --r2 <r2.json> --r3 <r3.json>
                [--md <out.md>] [--json <out.json>] [--help]

Exit codes:
  0  Success
  1  Error
  2  Usage error
"""

import argparse
import json
import sys
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synthesize three rounds of Claude↔Gemini adversarial review into "
            "a classified finding report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Finding classification rules:
  origin=claude:
    gemini_verdict=confirm                        → SURVIVOR
    gemini_verdict=refute AND defends=false       → REJECTED (killed_by=gemini)
    gemini_verdict=refute AND defends=true        → UNCONFIRMED
    gemini_verdict=null/missing                   → UNCONFIRMED

  origin=gemini:
    claude_verdict=confirm                        → SURVIVOR
    claude_verdict=refute                         → REJECTED (killed_by=claude)
    claude_verdict=missing                        → UNCONFIRMED

Exit codes:
  0  Success
  1  Error (file not found, parse error, etc.)
  2  Usage error
""",
    )
    parser.add_argument("--r1", required=True, metavar="FILE",
                        help="R1 Claude findings JSON (list of findings, origin=claude)")
    parser.add_argument("--r2", required=True, metavar="FILE",
                        help="R2 Gemini response JSON ({verdicts:[...], new_findings:[...]})")
    parser.add_argument("--r3", required=True, metavar="FILE",
                        help="R3 Claude response JSON ({defends:[...], gemini_finding_verdicts:[...]})")
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


def classify_findings(
    r1_findings: list[dict],
    r2: dict,
    r3: dict,
) -> list[dict]:
    """Apply the both-confirm survivor rule and return findings with status filled in."""

    # Build lookup maps (skip entries missing a non-empty "id" to avoid KeyError)
    gemini_verdicts: dict[str, dict] = {
        v["id"]: v for v in r2.get("verdicts", []) if v.get("id")
    }
    gemini_new: list[dict] = [
        f for f in r2.get("new_findings", []) if f.get("id")
    ]

    defends_map: dict[str, bool] = {
        d["id"]: bool(d.get("defends", False))
        for d in r3.get("defends", []) if d.get("id")
    }
    r3_gemini_verdicts: dict[str, dict] = {
        v["id"]: v for v in r3.get("gemini_finding_verdicts", []) if v.get("id")
    }

    classified: list[dict] = []

    # --- Process R1 Claude findings (origin=claude) ---
    for finding in r1_findings:
        f = dict(finding)
        if not f.get("id"):
            continue  # skip id-less entries gracefully (AR-001)
        f.setdefault("origin", "claude")
        f.setdefault("killed_by", None)
        f.setdefault("kill_reason", None)
        f.setdefault("claude_verdict", None)
        f.setdefault("gemini_verdict", None)
        f.setdefault("status", None)

        fid = f["id"]
        g_verdict = gemini_verdicts.get(fid)

        if g_verdict is None:
            # gemini_verdict=null/missing
            f["gemini_verdict"] = None
            f["status"] = "unconfirmed"
        elif g_verdict.get("gemini_verdict") == "confirm":
            f["gemini_verdict"] = "confirm"
            f["status"] = "survivor"
        elif g_verdict.get("gemini_verdict") == "refute":
            f["gemini_verdict"] = "refute"
            defended = defends_map.get(fid, False)
            if defended:
                # Claude defended in R3 → UNCONFIRMED (neither model's view prevails)
                f["status"] = "unconfirmed"
            else:
                # Refuted and not defended → REJECTED
                f["status"] = "rejected"
                f["killed_by"] = "gemini"
                f["kill_reason"] = g_verdict.get("reason", "")
        else:
            # Unexpected value — treat as unconfirmed
            f["gemini_verdict"] = g_verdict.get("gemini_verdict")
            f["status"] = "unconfirmed"

        classified.append(f)

    # --- Process R2 Gemini new findings (origin=gemini) ---
    for finding in gemini_new:
        f = dict(finding)
        if not f.get("id"):
            continue  # skip id-less entries gracefully (AR-001)
        f.setdefault("origin", "gemini")
        f.setdefault("killed_by", None)
        f.setdefault("kill_reason", None)
        f.setdefault("claude_verdict", None)
        f.setdefault("gemini_verdict", None)
        f.setdefault("status", None)

        fid = f["id"]
        r3_verdict = r3_gemini_verdicts.get(fid)

        if r3_verdict is None:
            f["claude_verdict"] = None
            f["status"] = "unconfirmed"
        elif r3_verdict.get("claude_verdict") == "confirm":
            f["claude_verdict"] = "confirm"
            f["status"] = "survivor"
        elif r3_verdict.get("claude_verdict") == "refute":
            f["claude_verdict"] = "refute"
            f["status"] = "rejected"
            f["killed_by"] = "claude"
            f["kill_reason"] = r3_verdict.get("reason", "")
        else:
            f["claude_verdict"] = r3_verdict.get("claude_verdict")
            f["status"] = "unconfirmed"

        classified.append(f)

    return classified


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
) -> str:
    lines: list[str] = []

    lines.append("# Adversarial PR Review — Synthesis Report")
    lines.append("")
    lines.append(
        f"**Summary:** {len(survivors)} survivors | "
        f"{len(unconfirmed)} unconfirmed (single-model) | "
        f"{len(rejected)} rejected"
    )
    lines.append("")
    lines.append("> Both-confirm rule: only findings confirmed by *both* Claude and Gemini are survivors.")
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
            loc = f"{path}:{line}" if line else path
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
            loc = f"{path}:{line}" if line else path
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
            loc = f"{path}:{line}" if line else path
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

    r1_raw = load_json(args.r1, "R1")
    r2_raw = load_json(args.r2, "R2")
    r3_raw = load_json(args.r3, "R3")

    # Validate / unwrap R1 — accept both a bare array and {"findings": [...]} (AR-002)
    if isinstance(r1_raw, dict) and isinstance(r1_raw.get("findings"), list):
        r1_raw = r1_raw["findings"]
    if not isinstance(r1_raw, list):
        print("Error: R1 must be a JSON array of findings (or an object with a 'findings' list)", file=sys.stderr)
        sys.exit(1)
    if not isinstance(r2_raw, dict):
        print("Error: R2 must be a JSON object with 'verdicts' and 'new_findings' keys", file=sys.stderr)
        sys.exit(1)
    if not isinstance(r3_raw, dict):
        print("Error: R3 must be a JSON object with 'defends' and 'gemini_finding_verdicts' keys", file=sys.stderr)
        sys.exit(1)

    classified = classify_findings(r1_raw, r2_raw, r3_raw)

    survivors = [f for f in classified if f.get("status") == "survivor"]
    unconfirmed = [f for f in classified if f.get("status") == "unconfirmed"]
    rejected = [f for f in classified if f.get("status") == "rejected"]

    # Print summary counts to stdout
    print(f"survivors={len(survivors)} unconfirmed={len(unconfirmed)} rejected={len(rejected)}")

    # Write JSON output
    if args.json_out:
        output = {
            "summary": {
                "survivors": len(survivors),
                "unconfirmed": len(unconfirmed),
                "rejected": len(rejected),
                "total": len(classified),
            },
            "findings": classified,
        }
        with open(args.json_out, "w") as f:
            json.dump(output, f, indent=2)

    # Write markdown output
    if args.md:
        md_content = format_markdown(survivors, unconfirmed, rejected)
        with open(args.md, "w") as f:
            f.write(md_content)


if __name__ == "__main__":
    main()
