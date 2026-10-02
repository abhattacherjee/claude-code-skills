---
name: triage-issues
description: "Reviews, triages, updates, prioritizes, and closes open GitHub issues against the current codebase state. Use when: (1) open issues have accumulated and need audit, (2) user asks to clean up or review GitHub issues, (3) after a release to close resolved issues, (4) periodic backlog grooming to identify stale or duplicate issues, (5) need to prioritize open issues by impact and effort, (6) 'github issue triage' or /github-issue-triage (the old name of this skill)."
metadata:
  version: 2.0.0
---

# GitHub Issue Triage

## Problem

GitHub issues accumulate stale entries over time: resolved issues stay open because no single commit formally "fixes" them, duplicates fragment discussion, and descriptions reference outdated file paths or line numbers. Manual review is slow because each issue requires cross-referencing the current codebase to determine if work has been done.

## Quick Start

Run the 5-phase workflow below. Each phase can be run independently, but the full sequence produces the most thorough audit.

## Workflow: 5-Phase Issue Audit

### Phase 1: Inventory and Duplicate Detection

```bash
# Get compact issue list with labels
gh issue list --state open --limit 100 --json number,title,labels \
  --jq '.[] | "#\(.number)\t[\(.labels | map(.name) | join(", "))]\t\(.title)"' \
  | sort -t'#' -k2 -n

# Check existing labels
gh label list --json name,description
```

**Duplicate detection strategy:**
- Sort issues by title keywords — duplicates often have similar phrasing
- Look for issue pairs that reference the same file, function, or CSP directive
- Check for issues that are subsets of broader tracking issues

**When closing duplicates:**
```bash
gh issue close <NUMBER> --comment "Closing as duplicate of #<OTHER>. [reason]"
gh issue edit <NUMBER> --add-label "duplicate"
```

### Phase 2: Codebase Verification (Parallel)

This is the most important phase. Launch parallel sub-agents to verify each issue against the codebase. Group issues by area for efficient searching.

**Verification patterns — what to search for each issue type:**

| Issue Type | What to Search | How to Verify |
|-----------|----------------|---------------|
| "Add tests for X" | `grep -r "describe.*X" tests/` | Count matching test cases |
| "Add feature X" | `grep -r "functionName" src/` | Check if function exists |
| "Fix bug in X" | Read the file, check if pattern is fixed | Compare against issue description |
| "Update dependency X" | `grep "X" package.json` | Compare version numbers |
| "Add docs for X" | `ls docs/` + read content | Check if documentation exists |
| "Refactor X" | Read function, count lines | Compare against issue's description |
| "Security: tighten X" | Read config file | Check if config was tightened |

**Key principle: Evidence-based closure only.** For each issue, find the exact file, line number, and code that proves it's resolved. Never close based on "I think this was done."

**Issue resolution verdicts:**
- **RESOLVED** — Implementation matches issue requirements. Close with evidence.
- **PARTIALLY ADDRESSED** — Some work done. Update description with "What EXISTS / What REMAINS."
- **STILL OPEN** — No relevant changes found. Leave open, may update description.
- **DUPLICATE** — Same scope as another issue. Close with cross-reference.
- **OBSOLETE** — The referenced code/feature/PR no longer exists. Close with explanation.

### Phase 3: Close Resolved Issues

Close with a comment that includes evidence:

```bash
gh issue close <NUMBER> --comment "$(cat <<'EOF'
**Closing as resolved.**

[Evidence: file paths, function names, line numbers proving the work is done]

_Closed during open issue audit (YYYY-MM-DD)._
EOF
)"
```

**Closure comment patterns:**

| Verdict | Comment Template |
|---------|-----------------|
| Resolved | "Closing as resolved. [Evidence]. _Closed during audit._" |
| Duplicate | "Closing as duplicate of #N. Both describe [scope]. Consolidating." |
| Obsolete | "Closing as obsolete. [Original context no longer applies because...]" |
| Subset | "Closing — partially resolved and remaining work tracked by #N." |

### Phase 4: Update Descriptions

For issues that remain open, update descriptions with a **"Current Codebase State"** section:

```markdown
## Current Codebase State (as of YYYY-MM-DD)

### What EXISTS:
- `path/to/file.js:123` — [description of what's implemented]
- Function `nameHere()` at line N — [what it does]

### What REMAINS:
- [Specific gap 1]
- [Specific gap 2]
```

**What to update in descriptions:**
- File paths that have moved (e.g., `recommendationPrompt.js` → `prompts/templates/static-prefix.en.js`)
- Line numbers that have shifted
- Function names that were renamed
- Counts that have changed (e.g., "75+ icons" → "60 icons")
- Status of partially-addressed work

### Phase 5: Labeling and Prioritization

**Create missing labels:**
```bash
gh label create "P1-high" --description "High priority" --color "B60205"
gh label create "P2-medium" --description "Medium priority" --color "D93F0B"
gh label create "P3-low" --description "Low priority" --color "FBCA04"
gh label create "P4-trivial" --description "Trivial" --color "C5DEF5"
gh label create "P5-not-needed" --description "Could be closed" --color "D4C5F9"
```

**Category labels to ensure exist:** `performance`, `security`, `accessibility`, `testing`, `dependabot`, `documentation`, `infrastructure`

**Batch-apply labels:**
```bash
for i in <number1> <number2> <number3>; do
  gh issue edit $i --add-label "<label>"
done
```

## Prioritization Framework

Score each issue on three axes:

| Axis | High (3) | Medium (2) | Low (1) |
|------|----------|-----------|---------|
| **User impact** | Visible to users, affects UX | Developer experience | Cosmetic or internal |
| **Tech debt risk** | Compounds if postponed | Moderate accumulation | Static, no compounding |
| **Effort-to-value** | Easy fix, high value | Moderate effort | High effort, low value |

**Priority mapping:**

| Score | Priority | Action |
|-------|----------|--------|
| 7-9 | P1-high | Schedule for next sprint |
| 5-6 | P2-medium | Plan for upcoming work |
| 3-4 | P3-low | Backlog, do when convenient |
| 2 | P4-trivial | Accept or close as wontfix |
| 1 | P5-not-needed | Close with explanation |

**Common priority assignments:**

| Issue Pattern | Typical Priority | Rationale |
|---------------|-----------------|-----------|
| Security gap (CSP, auth) | P1-high | User safety, easy fixes |
| Dependency major version lag | P1-P2 | Compounds over time |
| User-facing quality bug | P1-high | Direct UX impact |
| Feature expansion | P2-medium | User value but not urgent |
| Accessibility gaps | P2-medium | Compliance + inclusion |
| Performance optimization | P2-P3 | Depends on measured impact |
| Test coverage gaps | P3-low | Quality safety net |
| Code refactoring | P3-low | Maintainability only |
| Micro-optimization (<0.1%) | P4-trivial | Negligible impact |
| Cosmetic cleanup | P4-trivial | No functional change |
| Post-MVP/stale backlog | P5-not-needed | Likely never implemented |

## Key Lessons from Practice

### Issues from PR reviews accumulate silently
Issues created from PR review comments (e.g., "add clarifying comment", "add input validation") are often addressed in subsequent commits but never formally closed. These are the most common "already resolved" candidates.

### Partial resolution is the hardest to assess
Issues like "improve recommendation quality" get addressed across many stories over months. The "Current Codebase State" section is critical — it prevents future developers from re-investigating what's already been done.

### Dependabot issues need version pinning in descriptions
Always include the exact current version and target version from `package.json` with line numbers. Versions change, and stale descriptions cause confusion.

### Duplicate pairs often arise from different angles
Two people file issues about the same CSP directive but frame them differently ("tighten imgSrc" vs "restrict image sources"). Title-based scanning misses these — search by file path and config key.

### `--add-label` is additive and safe
`gh issue edit --add-label` never removes existing labels. This makes batch operations safe — you can label in parallel without worrying about overwriting.

## Notes

- Always use `gh issue list --json` for structured data, not plain text output
- The `--jq` flag enables inline JSON filtering without piping to `jq`
- Issue bodies over ~25KB need the `gh issue view <N> --json body` approach (one at a time)
- Batch `gh issue edit` calls in loops, not parallel, to avoid GitHub API rate limits
- Add `_Closed during open issue audit (YYYY-MM-DD)._` to all closure comments for traceability

## See Also

- `ci-security-issue-creator` — creates new issues from security alerts (complementary: this skill manages existing issues, that skill creates new ones) _(archived 2026-08-15 to `~/.claude/skills-archive/`)_
- `prune-branches` — complementary repo hygiene (branches instead of issues)
- `project-code-review` — code review skill that may generate new issues
- `plan-milestones` — decides where a *valid* issue belongs (which milestone), by theme rather than priority. Complementary and runs after this skill: triage decides whether an issue is still real, milestone-planning decides which release it lands in.
