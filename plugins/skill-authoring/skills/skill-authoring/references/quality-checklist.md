# Quality Checklist

Pre-publish verification for Claude Code skills. Run through before committing.

## Frontmatter

- [ ] `name`: ≤64 chars, lowercase letters + numbers + hyphens only
- [ ] `name`: no reserved words (`anthropic`, `claude`)
- [ ] `description`: non-empty, ≤1024 characters
- [ ] `description`: written in third person (not "I help..." or "You can...")
- [ ] `description`: includes what it does AND when to use it
- [ ] `description`: has numbered trigger conditions `Use when: (1)...(2)...`
- [ ] `description`: includes specific terms for semantic matching (error messages, tool names)
- [ ] `version`: present, follows semver
- [ ] No non-standard fields (no `author`, `date`, `tags`, `allowed-tools`, `category`)

## Content

- [ ] SKILL.md body ≤ 500 lines
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

## Scripts (if present)

- [ ] All scripts support `--help` / `-h` flag
- [ ] Scripts validate inputs before operating
- [ ] Scripts use meaningful exit codes (0=success, 1=error, 2=usage)
- [ ] Scripts are executable (`chmod +x`)
- [ ] Scripts use portable shebang (`#!/usr/bin/env bash`)
- [ ] Scripts handle error conditions (missing deps, files, permissions)
- [ ] Scripts referenced from SKILL.md with usage examples

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
# Line count
wc -l SKILL.md  # Must be ≤ 500

# Description length
awk '/^description:/{found=1;next} found && /^[a-z]/{exit} found{print}' SKILL.md | wc -c  # Must be ≤ 1024

# Non-standard frontmatter fields
awk '/^---$/{c++;next} c==1{print}' SKILL.md | grep -vE '^(name|description|version|  )' # Should be empty

# Script executability
ls -la scripts/*.sh scripts/*.py 2>/dev/null  # Check x bit

# Cross-reference validation
grep -oE '\(references/[^)]+\)' SKILL.md | tr -d '()' | while read f; do
  [ -f "$f" ] && echo "OK  $f" || echo "MISS $f"
done

# Stale cross-references (search for skill names that don't exist)
grep -oE '`[a-z][-a-z]*`' SKILL.md | tr -d '`' | sort -u
```
