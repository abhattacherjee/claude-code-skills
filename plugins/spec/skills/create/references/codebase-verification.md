# Codebase Verification (Phase 4.3 / 4.3b)

Reference detail for `SKILL.md` Phase 4 ("Generate Spec(s)"). Pulled out of the main
workflow to keep `SKILL.md` within the body-line budget — read this when executing
Phase 4.3 or 4.3b.

## 4.3 Codebase State verification gate (MANDATORY)

Before writing the spec, verify every name in the "Current Codebase State" section against
the actual codebase. This prevents the #1 spec quality issue: **fabricated module names**.

**What to verify:**
```bash
# Every file path listed under "What EXISTS" — must return a result
ls -la path/to/claimed/file.ts

# Every module/hook/context/service name — must exist as an export
grep -r "export.*ClaimedName" frontend/src/ backend/src/

# Every directory structure claim — must match reality
ls frontend/src/components/screens/    # Does this dir exist?

# Every type definition — must match actual values
grep -A5 "type ClaimedType" frontend/src/App.tsx

# Item counts — must be accurate
ls frontend/src/components/*.tsx | wc -l
```

**Common fabrication patterns to catch** (from Epic 15 post-mortems):

| Pattern | Example (fabricated → actual) | How to catch |
|---------|-------------------------------|--------------|
| Plausible module names | `apiService.ts` → `api.ts`, `mcpClient.js` → `mcpEventsClient.js` | `ls` + `grep` the actual directory |
| Assumed directory structure | `components/screens/` → screens are flat in `components/` | `ls` the parent dir |
| Wrong file extensions | `locales/en.json` → `en.ts` | `ls` the directory |
| Guessed type values | `'long'` → `'extended'`, `'first_time'` → month abbreviations | `grep -A5 "type TypeName"` |
| Inflated counts | "10+ screens" → 5 screens, "10+ MCP endpoints" → 0 | Count with `ls | wc -l` |
| Assumed endpoints/routes | `/api/mcp/*` proxy routes → no such routes exist | `grep -r "router\." src/routes/` |

**Rule: If you cannot verify a claim with a command, do NOT include it in the spec.**
Write "TBD — verify during implementation" instead of guessing.

## 4.3b Dependency Upgrade Pre-Flight (MANDATORY for dependency upgrade stories)

When the story involves upgrading a package to a new major version, verify module
system compatibility BEFORE writing the spec. This catches the #2 spec quality issue:
**assuming a major version bump is a drop-in replacement when it actually changes
the module system (CJS→ESM).**

```bash
# 1. Check project's module system
grep '"type"' package.json  # "module" = ESM, absent = CJS

# 2. Check how the package is imported
grep -rn "require.*<pkg>\|from ['\"]<pkg>" src/ --include="*.ts" --include="*.js"
# If require() is used → project NEEDS CJS support from the package

# 3. Check target version's exports field
npm view <pkg>@<target> exports type --json
# Look for "require" or "node.require" entry — if missing, CJS is NOT supported

# 4. Search for existing compatibility scripts
grep -rl "verify.*compat\|ERR_REQUIRE_ESM\|require.*<pkg>" scripts/ tests/
```

**Decision matrix:**

| Project uses | Target has `require` entry | Action |
|-------------|--------------------------|--------|
| `require()` | Yes | Safe to upgrade |
| `require()` | No (ESM-only) | **STOP** — upgrade infeasible without ESM migration |
| `import` (ESM) | N/A | Safe to upgrade |

**Common ESM-only packages** (post-2024): `chalk` v5+, `ora` v6+, `got` v12+,
`node-fetch` v3+, `execa` v6+, `uuid` v12+.

**Jest/Babel trap:** `require()` calls that fail in production Node.js can PASS in
Jest because Babel transpiles ESM→CJS at test time. If you find existing
compatibility guard scripts (step 4), they exist for a reason — read them.

If the target version is ESM-only and the project uses CJS, **do not write the spec**.
Instead, recommend closing the issue with a technical explanation and suggest the
prerequisite ESM migration scope.
