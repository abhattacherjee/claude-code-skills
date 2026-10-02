# Codebase Verification Patterns by Issue Type

## Testing Issues ("Add tests for X")

```bash
# Check if test file exists
find . -path "*/tests/*" -name "*X*" -type f

# Count test cases for a function
grep -c "it\|test(" path/to/test-file.test.ts

# Check specific function coverage
grep -n "describe.*functionName" tests/**/*.test.*
```

**Verdict criteria:**
- RESOLVED: Test file exists with test cases covering the scenarios listed in the issue
- PARTIALLY ADDRESSED: Some tests exist but not all scenarios covered
- STILL OPEN: No tests found

## Dependency Update Issues

```bash
# Check current version in package.json
grep '"dependency-name"' package.json

# Compare against issue target
# Issue says "uuid 8→13", package.json has "^8.3.2" → STILL OPEN
```

**Verdict criteria:**
- RESOLVED: package.json shows target version (or higher)
- STILL OPEN: package.json still shows old version

## Security/Config Issues ("Tighten X", "Add Y to CSP")

```bash
# Read the config section
grep -A5 "configKey" src/app.js

# Check if it changed from the issue's "Current State"
# Compare against issue's "Proposed Change"
```

**Verdict criteria:**
- RESOLVED: Config matches or exceeds the proposed change
- STILL OPEN: Config still matches the issue's "Current State"

## Refactoring Issues ("Break down X", "Extract Y")

```bash
# Count function lines
awk '/^function targetFunc/,/^}/' file.js | wc -l

# Check for extracted helpers
grep -n "function helper" file.js
```

**Verdict criteria:**
- RESOLVED: Function size matches target, helpers extracted
- PARTIALLY ADDRESSED: Some extraction done, function still large
- STILL OPEN: No structural changes

## Documentation Issues

```bash
# Check if doc file exists and has content
ls -la docs/path/to/doc.md
grep -c "## Troubleshooting" docs/path/to/doc.md
```

**Verdict criteria:**
- RESOLVED: Documentation exists with requested content
- PARTIALLY ADDRESSED: Doc exists but missing requested sections
- STILL OPEN: No documentation found

## Performance Issues

```bash
# Check for optimization patterns
grep -n "lazy\|preload\|memo\|useMemo\|useCallback" src/component.tsx

# Check bundle imports
grep -c "import.*from" src/component.tsx
```

**Verdict criteria:**
- RESOLVED: Optimization implemented and measurable
- PARTIALLY ADDRESSED: Some optimizations done, target metric unverified
- STILL OPEN: No optimization changes found
