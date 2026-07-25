# Design Simplification Checklist

Patterns where story specs commonly over-engineer. Use during Phase 2 (Design Simplifier agent)
to identify simpler alternatives.

## Table of Contents

1. [Unnecessary Abstractions](#unnecessary-abstractions)
2. [Redundant Infrastructure](#redundant-infrastructure)
3. [Over-Scoped Changes](#over-scoped-changes)
4. [Backward Compatibility Overkill](#backward-compatibility-overkill)
5. [Simplification Decision Tree](#simplification-decision-tree)

---

## Unnecessary Abstractions

### Pattern 1: New Wrapper for Existing Delegation
**Symptom**: Spec creates `FooManager` or `FooWrapper` that just calls an existing service.
**Question**: Does the existing service already handle this via internal routing?
```bash
# Check if delegation already exists in the target service
grep -n "switch\|if.*locale\|dispatch\|delegate" <service-file>
```
**Simplification**: Call the existing service directly. Remove the wrapper sub-task.

### Pattern 2: New Utility for One-Time Use
**Symptom**: Spec creates `utils/fooHelper.ts` with a single exported function used once.
**Question**: Can this be an inline function or a method on the existing service?
**Simplification**: Add the logic directly where it's used. Three similar lines > premature abstraction.

### Pattern 3: New Type for Simple Shape
**Symptom**: Spec defines `interface FooBarResult { success: boolean; data: T; error?: string }`.
**Question**: Can you use an existing type or a simple tuple/union?
**Simplification**: Use existing error handling patterns (try/catch, HTTP status codes).

### Pattern 4: New Config File for Few Constants
**Symptom**: Spec creates `config/fooConfig.js` with 2-3 values.
**Question**: Can these constants live where they're used?
**Simplification**: Add constants to the existing relevant config file or inline them.

## Redundant Infrastructure

### Pattern 5: New Cache Layer When One Exists
**Symptom**: Spec adds a cache to a service that's already cached upstream.
**Question**: Is this data already cached by an upstream service or middleware?
```bash
# Check existing cache layers
grep -rn "Cache\|cache\|NodeCache\|lru-cache\|redis" <service-directories>
```
**Simplification**: Reuse existing cache. Document cache TTL chain instead of adding layers.

### Pattern 6: New Endpoint When Existing One Suffices
**Symptom**: Spec creates `GET /api/foo/bar` when `GET /api/foo?type=bar` would work.
**Question**: Can the existing endpoint accept a query parameter or filter?
**Simplification**: Add a query parameter to the existing endpoint. Update API tests.

### Pattern 7: New Tool/Plugin for Subset of Existing
**Symptom**: Spec creates a new tool that duplicates functionality of an existing one.
**Question**: Does the existing tool accept the needed parameters?
```bash
# Check existing tool parameters
grep -A10 "schema\|params\|arguments" <tool-definition-files>
```
**Simplification**: Use existing tool with appropriate parameters.

### Pattern 8: Separate Locale Implementations
**Symptom**: Spec creates `buildPromptEN()` and `buildPromptPT()` separately.
**Question**: Can a single function take locale as parameter?
**Simplification**: Single function with locale parameter, bilingual content from data source.

## Over-Scoped Changes

### Pattern 9: Refactoring Adjacent Code
**Symptom**: Spec includes "also refactor X while we're in this file."
**Question**: Is the refactoring necessary for the feature to work?
**Simplification**: Remove refactoring sub-tasks. Create a separate story if needed.

### Pattern 10: Adding Observability for Non-Production Features
**Symptom**: Spec adds tracking, metrics, or analytics for a small local feature.
**Question**: Is this a production-critical path that needs monitoring?
**Simplification**: Skip observability for local-only or low-traffic features.

### Pattern 11: Feature Flags for Irreversible Changes
**Symptom**: Spec adds feature flag toggle for something that could just be deployed.
**Question**: Can this be rolled back by reverting the commit?
**Simplification**: Deploy directly. Git revert is the rollback mechanism.

### Pattern 12: Multi-Phase Rollout for Internal Tool
**Symptom**: Spec defines Phase 1 (shadow mode), Phase 2 (10% rollout), Phase 3 (full).
**Question**: Is this a customer-facing change with high risk?
**Simplification**: Single deployment for internal/low-risk features.

## Backward Compatibility Overkill

### Pattern 13: Keeping Dead Code Paths
**Symptom**: Spec keeps old implementation behind `if (useLegacy)` flag.
**Question**: Is there any consumer of the old path? How recently was it added?
**Simplification**: Replace directly. No legacy path needed for recently-added code.

### Pattern 14: Re-Exporting Moved Types
**Symptom**: Spec moves types to new file but re-exports from old location.
**Question**: How many imports need updating?
```bash
grep -rn "from.*oldFile" --include="*.ts" --include="*.js" | wc -l
```
**Simplification**: Update all imports directly. No re-export shim.

### Pattern 15: Deprecation Warnings for Internal APIs
**Symptom**: Spec adds `console.warn('Deprecated: use newMethod()')` to internal functions.
**Question**: Is this called by external consumers?
**Simplification**: Just rename/replace. Internal APIs don't need deprecation periods.

## Simplification Decision Tree

```
Does the spec create a new file?
├── YES → Is there an existing file that could absorb this logic?
│   ├── YES → Simplify: add to existing file
│   └── NO → Keep the new file (but verify it has 2+ uses)
└── NO → Continue

Does the spec add a new abstraction layer?
├── YES → Is it called from 2+ places?
│   ├── YES → Keep (justified abstraction)
│   └── NO → Simplify: inline the logic
└── NO → Continue

Does the spec add backward compatibility?
├── YES → Is the old API used by external consumers?
│   ├── YES → Keep compat layer
│   └── NO → Simplify: replace directly
└── NO → Continue

Does the spec touch 3+ layers for a single feature?
├── YES → Can the feature be contained in fewer layers?
│   ├── YES → Simplify: reduce layer span
│   └── NO → Keep (verified cross-layer need)
└── NO → Looks appropriately scoped
```

## Red Flags in Specs

When reviewing, flag these for simplification discussion:
- Sub-task count > 10 for a feature (may be over-scoped)
- New files > 3 (may need consolidation)
- "Also while we're here..." language (scope creep)
- "For future extensibility..." (YAGNI)
- "Phase 1 of N" without clear Phase 2 timeline
- Backward compat for code added within the same sprint
