# Quality Checklist

Pre-publish verification for Claude Code skills. Run through before committing.

## Contents

- Decomposition & Agents
- Frontmatter
- Content
- Progressive Disclosure
- Progress Tracking (if 3+ phases)
- Teams (optional)
- Scripts (if present)
- Cross-References
- Testing
- Verification Commands

## Decomposition & Agents

- [ ] Decomposition evaluated: can this be split into parallel sub-agents?
- [ ] If yes: orchestrator defined as pure delegator (never does the work itself)
- [ ] Independent agents launched in a SINGLE Task tool message (not sequentially)
- [ ] Each sub-agent has a single focused responsibility
- [ ] Sub-agents use an appropriate model tier (haiku/sonnet/opus)
- [ ] Agent definitions include a structured output format

## Frontmatter

- [ ] `name`: ≤64 chars, lowercase letters + numbers + hyphens only
- [ ] `name`: no reserved words (`anthropic`, `claude`)
- [ ] `description`: non-empty, ≤1024 characters, a double-quoted single line
- [ ] `description`: written in third person (not "I help..." or "You can...")
- [ ] `description`: includes what it does AND when to use it
- [ ] `description`: has numbered trigger conditions `Use when: (1)...(2)...`
- [ ] `description`: includes specific terms for semantic matching (error messages, tool names)
- [ ] `metadata.version`: present, follows semver (no top-level `version`)
- [ ] No non-standard fields (only `name`, `description`, `metadata`, plus `model` for a sub-agent skill and `disable-model-invocation` for a slash-command-only skill; `validate-skill.sh` rejects any other)

## Content

- [ ] SKILL.md body under 500 lines
- [ ] Only includes information Claude doesn't already know
- [ ] Consistent terminology throughout (one term per concept)
- [ ] No time-sensitive information (or uses "Current" / "Legacy" pattern)
- [ ] Examples are concrete, not abstract
- [ ] Workflows have clear sequential steps
- [ ] Decision points use conditional patterns ("If X → do Y")

## Progressive Disclosure

- [ ] SKILL.md contains decision workflow and trigger conditions
- [ ] Lookup tables, code examples, case studies in `references/`
- [ ] All reference files linked directly from SKILL.md (one level deep)
- [ ] Reference files > 100 lines have table of contents
- [ ] Descriptive filenames (`api-field-reference.md` not `ref1.md`)

## Progress Tracking (if 3+ phases)

- [ ] Task manifest evaluated: does the skill have 3+ sequential phases or run >2 minutes?
- [ ] If yes: `scripts/task-manifest.sh` created with one `case` per workflow
- [ ] Each workflow defines tasks with `subject` (imperative), `activeForm` (present continuous), `description`
- [ ] SKILL.md includes "Progress Tracking (MANDATORY)" section with task table
- [ ] Task update rules documented (in_progress → completed, abort → deleted)
- [ ] Gate/abort points identified (e.g., "if tests fail, delete remaining tasks")

## Teams (optional)

- [ ] Team mode evaluated: does this skill have multi-phase feedback loops?
- [ ] If yes: team pattern documented alongside the sub-agent pattern
- [ ] Conditional check for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` documented
- [ ] TeamDelete cleanup documented in the workflow

## Scripts (if present)

- [ ] All scripts support `--help` / `-h` flag
- [ ] Scripts validate inputs before operating
- [ ] Scripts use meaningful exit codes (0=success, 1=error, 2=usage)
- [ ] Scripts are executable (`chmod +x`)
- [ ] Scripts use portable shebang (`#!/usr/bin/env bash`)
- [ ] Scripts handle error conditions (missing deps, files, permissions)
- [ ] Scripts referenced from SKILL.md with usage examples
- [ ] If present: `--fix`/`--dry-run` support
- [ ] Scripts dry-run tested against real project data (2-3 varied inputs)

## Cross-References

- [ ] All `references/` links resolve to existing files
- [ ] All `scripts/` references point to existing executables
- [ ] `See Also` section lists related skills with brief descriptions
- [ ] No references to renamed/deleted skills (search for stale names)
- [ ] Links use forward slashes (not backslashes)

## Testing

- [ ] Skill tested with representative task
- [ ] Description triggers correctly (test with a prompt that should activate it)
- [ ] Scripts produce expected output
- [ ] Reference files contain complete information (no placeholders)

## Verification Commands

```bash
# Body line count (after the frontmatter)
awk 'c>=2{n++} /^---$/{c++} END{print n}' SKILL.md  # Must be under 500

# Description length
grep -m1 '^description:' SKILL.md | wc -c  # Must be ≤ 1040: 1024 plus the 'description: ""' wrapper and the newline

# Non-standard frontmatter fields
awk '/^---$/{c++;next} c==1{print}' SKILL.md | grep -vE '^(name|description|metadata|model|disable-model-invocation|  )' # Should be empty

# Script executability
ls -la scripts/*.sh scripts/*.py 2>/dev/null  # Check x bit

# Cross-reference validation
for f in $(grep -oE '\(references/[^)]+\)' SKILL.md | tr -d '()'); do
  [ -f "$f" ] && echo "OK  $f" || echo "MISS $f"
done

# Stale cross-references (search for skill names that don't exist)
grep -oE '`[a-z][-a-z]*`' SKILL.md | tr -d '`' | sort -u
```
