# Story Spec Template

Canonical template derived from analysis of 50+ story specs across Epics 1-12.
Sections marked **REQUIRED** must appear in every spec. Others are contextual.

## Table of Contents

1. [Title and Metadata](#1-title-and-metadata)
2. [User Story](#2-user-story)
3. [Context](#3-context)
4. [Solution Overview](#4-solution-overview)
5. [Current Codebase State](#5-current-codebase-state)
6. [Acceptance Criteria](#6-acceptance-criteria)
7. [Success Metrics](#7-success-metrics)
8. [File Structure Map](#8-file-structure-map)
9. [Implementation Tasks](#9-implementation-tasks)
10. [Testing Checklist](#10-testing-checklist)
11. [Definition of Done](#11-definition-of-done)

---

## 1. Title and Metadata (REQUIRED)

```markdown
# Story X.Y: Descriptive Name

**Epic:** N — Epic Title
**Priority:** P0 | P1 | P2
**Status:** Not Started
**Estimate:** X-Yh
**Depends On:** Story A.B (if any)
```

**Numbering**: `{epic}.{story}` — e.g., `12.3` = Epic 12, Story 3.

---

## 2. User Story (REQUIRED)

```markdown
## User Story

**As a** [role], **I want** [feature] **so that** [benefit].
```

One sentence. Describes user-facing value, not implementation.

---

## 3. Context (REQUIRED)

```markdown
## Context

[Problem description with specific evidence:]
- UAT findings, user feedback, or production data
- Root cause analysis
- Why this matters now
```

Optional sub-sections: `### Background`, `### Current Behavior`, `### Target Behavior`.

---

## 4. Solution Overview (RECOMMENDED for complex stories)

```markdown
## Solution Overview

[1-2 sentence approach summary]

[ASCII diagram showing data flow or architecture change]

**Key design decisions:**
- **Choice A over B** — rationale
- **Layer X only** — reasoning
```

---

## 5. Current Codebase State (REQUIRED when modifying existing code)

```markdown
## Current Codebase State

**What EXISTS (do NOT recreate):**
- `path/to/file.ext` — `functionName(params): ReturnType` (line XX)

**What needs to be MODIFIED:**
- `path/to/file.ext` — [specific change]

**What needs to be CREATED:**
- `path/to/new-file.ext` — [purpose]
```

---

## 6. Acceptance Criteria (REQUIRED)

```markdown
## Acceptance Criteria

### AC1: Component/Feature Name
- [ ] Specific, measurable, verifiable criterion
- [ ] Can be checked with: `command` or test assertion
- [ ] Includes success criteria (numbers, behavior, output)

### AC2: Another Group
- [ ] ...
```

Group related criteria with `###` subheadings. Each criterion independently verifiable.

---

## 7. Success Metrics (RECOMMENDED)

```markdown
## Success Metrics

| Metric | Type | Current | Target | Capture Method |
|--------|------|---------|--------|---------------|
| Share link crash rate | error_rate | ~22 events/week | 0 | Sentry error count (VACATION-AGENT-FRONTEND-A) |
| Tips field present after restart | boolean | false | always true | Bruno assertion + unit test |
| Recommendation load time | latency | 8.2s p50 | < 7s p50 | Sentry span `recommendation.generate` |

### Existing Instrumentation
- `setAttribute('feasibility.codes', ...)` — already tracks recommendation quality codes
- `metrics.distribution('recommendation.tokens', ...)` — tracks token usage

### New Instrumentation Needed
- Add `setAttribute('share.fields_normalized', count)` to track normalization events
- Add Bruno assertion: `expect(rec.tips).to.be.an('array')` for contract validation
```

**Rules:**
- Every story should move at least one metric (even if it's "crash count → 0")
- Prefer reusing existing instrumentation over adding new metrics
- Include both the capture method AND where to query it (Sentry Explore, dashboard, Bruno)
- If the story is purely a refactor with no metric impact, state that explicitly

---

## 8. File Structure Map (REQUIRED)

Before defining tasks, map out all files that will be created or modified. This locks in
decomposition decisions and gives the implementer a bird's-eye view before diving in.

```markdown
## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `path/to/tests/feature.test.js` | CREATE | TDD tests (written first) |
| `path/to/service.js:43` | MODIFY | Core fix — normalize fields |
| `path/to/Component.tsx:2480` | MODIFY | Frontend guards |
| `path/to/types.ts:265-268` | MODIFY | Make types optional |
| `path/to/api-test.bru` | MODIFY | API contract assertions |
```

**Rules:**
- Include line numbers where known (from codebase research)
- Tests listed first (TDD — written before implementation)
- Group by dependency order (foundation files before consumers)

---

## 9. Implementation Tasks (REQUIRED)

Each task is decomposed into **bite-sized TDD steps** (2-5 minutes each). The implementer
should be able to follow these with zero prior codebase context.

````markdown
## Implementation Tasks

### Task X.Y.1: Task Name

**Files:**
- Test: `tests/path/to/test.js` (CREATE | MODIFY)
- Impl: `src/path/to/file.js:43` (MODIFY)

- [ ] **Step 1: Write the failing test**

```javascript
it('should normalize tips to [] when absent', async () => {
  setupSheetsWithStrippedRec();
  shareService.clearCache();
  await shareService.warmShareCache();
  const result = await shareService.getSharedRecommendation('token');
  expect(result.recommendation.tips).toEqual([]);
});
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && npm test -- tests/unit/services/shareService.test.js --testNamePattern="normalize"``
Expected: FAIL with `received undefined`

- [ ] **Step 3: Write minimal implementation**

```javascript
// After JSON.parse in reassembleRecommendation()
parsed.tips = Array.isArray(parsed.tips) ? parsed.tips : [];
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && npm test -- tests/unit/services/shareService.test.js --testNamePattern="normalize"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/services/shareService.test.js src/services/shareService.js
git commit -m "fix(share): normalize tips after Sheets roundtrip"
```

### Task X.Y.2: Next Task
...
````

**Per-task rules:**
- **Files** — list test file first, then implementation file(s) with line numbers
- **Complete code** — never write "add validation here"; include the actual code
- **Exact run commands** — with the `cd` into the right directory
- **Expected output** — what success/failure looks like (error messages, pass counts)
- **Commit after each logical unit** — not after every step, but after each task
- **TDD sequence** — test first, run to confirm fail, implement, run to confirm pass

**Step granularity guide:**

| Complexity | Steps per task | Code per step |
|-----------|---------------|---------------|
| S (< 1h) | 3-5 | 1-10 lines |
| M (1-2h) | 5-8 | 5-20 lines |
| L (> 2h) | 8-12 | 10-30 lines |

---

## 10. Testing Checklist (REQUIRED)

```markdown
## Testing Checklist

- [ ] Unit tests: `npm test -- <file>` (90%+ coverage)
- [ ] Bruno test in `<folder>/` for [feature]
- [ ] Playwright E2E: `npx playwright test <spec>`
- [ ] Lint: `npm run lint` in [package]
- [ ] Full regression: `npm run test:coverage` passes
```

---

## 11. Definition of Done (REQUIRED)

```markdown
## Definition of Done

- [ ] All acceptance criteria verified with evidence
- [ ] Unit tests pass (90%+ coverage on new code)
- [ ] Lint passes across all affected packages
- [ ] No test regressions
- [ ] Bruno API tests pass (if API changes)
- [ ] PR merged to develop
- [ ] Tracking file updated
```

---

## Optional Sections (add as needed)

| Section | When to Include |
|---------|----------------|
| `## Architecture` | Multi-layer stories, complex data flow |
| `## Prerequisites` | External dependencies, setup requirements |
| `## Sentry Metrics` | Observability additions |
| `## Bruno API Test Plan` | Stories with API changes (added by /spec-review) |
| `## Design Simplification Notes` | After review (added by /spec-review) |
| `## Verification` | Specific commands to prove completion |

---

## Complexity Calibration

| Estimate | Sub-tasks | Files | Typical Story |
|----------|-----------|-------|---------------|
| 0.5-1h   | 1-2       | 1-2   | Config change, i18n key |
| 1-2h     | 2-4       | 2-4   | Single-layer feature |
| 2-4h     | 4-6       | 3-6   | Cross-layer feature |
| 4-6h     | 6-10      | 5-10  | Multi-service feature |
| 6h+      | 10+       | 10+   | Consider splitting |

**Red flag**: > 10 sub-tasks or > 10 files — the story likely needs splitting.
