---
name: spec-implement
description: "Implements a previously created and reviewed story spec end-to-end: reads the spec, creates a feature branch, implements all sub-tasks with progress tracking, validates acceptance criteria, updates tracking files, and creates a PR. Optionally delegates to separately-installed brainstorming, frontend-design, and ui-from-requirements skills for complex UI work. Use when: (1) user says /spec-implement or 'implement this spec', (2) a story spec has been created and reviewed and is ready for implementation, (3) user provides a spec file path to implement."
metadata:
  version: 1.0.0
---

# Spec Implement

> **Path convention:** `./scripts/…` and `./references/…` below are relative to this skill's own base directory — announced as "Base directory for this skill" when the skill is invoked. A Bash tool call's working directory is the user's project, not the skill directory, so prefix these with that base directory when running them. Paths written without the leading `./` (for example `scripts/` or `tests/` inside a search over the codebase) refer to the **target project** being worked on, not to this skill.

Implements a reviewed story spec end-to-end — from branch creation to PR.

## Usage

```
/spec-implement <spec-file-path>
/spec-implement specs/stories/epic-0/story-0.1-touch-targets-accessibility.md
```

## Progress Tracking (MANDATORY)

Before starting, determine workflow and create the task checklist:

```bash
./scripts/task-manifest.sh standard    # Default
./scripts/task-manifest.sh ui-heavy    # If spec adds new DS components or pages
```

**Standard workflow (7 tasks):**

| # | Task | Active form |
|---|------|------------|
| 1 | Read spec and discover project conventions | Reading spec and project conventions |
| 2 | Create feature branch | Creating feature branch |
| 3 | Implement sub-tasks | Implementing sub-tasks |
| 4 | Validate build and lint | Validating build and lint |
| 5 | Verify acceptance criteria | Verifying acceptance criteria |
| 6 | Update tracking and changelog | Updating tracking files |
| 7 | Create PR | Creating pull request |

**UI-heavy workflow (9 tasks):** adds "Assess complexity and invoke design skills" after branch creation and "Update ComponentShowcase" before validation.

**Update rules:**
- Create all tasks from manifest at start (TaskCreate)
- Mark `in_progress` before starting each task, `completed` after
- If a task fails, keep it `in_progress` and report the error
- On abort, mark remaining as `deleted`

## Workflow

### Phase 1: Read Spec & Discover Conventions

**TaskUpdate: task 1 `in_progress`**

1. **Read the spec file** — extract: title, epic, sub-tasks, acceptance criteria, files to modify, DS components used, i18n requirements, mock data requirements
2. **Read project CLAUDE.md files** — understand branching strategy, commit conventions, deployment commands
3. **Read design guidelines** if spec references them — `specs/design-guidelines.md`
4. **Identify tracking file** — typically `specs/mvp-ux-tracking.md`
5. **Determine workflow type:**
   - **UI-heavy** if spec: adds new DS components, creates new pages, or references `frontend-design` / `ui-from-requirements`
   - **Standard** otherwise

**TaskUpdate: task 1 `completed`**

### Phase 2: Create Feature Branch

**TaskUpdate: task 2 `in_progress`**

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<story-slug>
```

Branch name: `feature/story-{epic}.{story}-{kebab-slug}` (e.g., `feature/story-0.1-touch-targets-accessibility`).

**TaskUpdate: task 2 `completed`**

### Phase 3: Assess Complexity (UI-heavy only)

**TaskUpdate: task 3 `in_progress`** (ui-heavy only)

If the spec involves:
- **New pages with significant UI** — invoke `Skill(superpowers:brainstorming)` or `Skill(frontend-design:frontend-design)` for aesthetic direction before coding
- **New DS components + pages + data** — invoke `Skill(ui-from-requirements)` for full pipeline
- **Incremental fixes to existing pages** — skip, implement directly

Most Epic 0 (compliance) stories are standard. Epics 1-5 (new features) are more likely UI-heavy.

**TaskUpdate: task 3 `completed`** (ui-heavy only)

### Phase 4: Implement Sub-Tasks

**TaskUpdate: task 3/4 `in_progress`** (depending on workflow)

For each sub-task in the spec:

1. **Read the target file(s)** — understand current state before modifying
2. **Implement the changes** described in the sub-task
3. **Check off acceptance criteria** — edit the spec file to mark each criterion:
   ```markdown
   - [x] Bell, logout, collapse toggles compute >= 44px  ✅ verified via grep
   - [x] No `p-1.5` remaining on interactive icon buttons  ✅ zero matches
   ```
4. **Run `npm run lint`** after each sub-task if changes are substantial (catch errors early)

**Implementation rules (from CLAUDE.md):**
- Import DS components from `@/design-system` (never direct paths)
- Use `th-*` tokens for colors (never `text-white`, `bg-black`)
- Use `font-[Orbitron]` or `font-[Rajdhani]` only (never `font-sans`)
- All mock data in `src/data/` with TypeScript interfaces (never inline arrays)
- All user-facing strings via `import { t } from '@/i18n'` (never hardcoded)
- Use `cn()` from `@/lib/utils` for conditional classnames

**Parallelization:** If sub-tasks modify independent files with no shared state, use parallel `Agent` calls to implement 2-3 sub-tasks simultaneously. Only parallelize when files don't overlap. **Verify each dispatched sub-task's claims before advancing (MANDATORY).** A parallel `Agent` narrates its result back to you; that narration is a claim, not evidence. Verify each against ground truth in *your own* context per `./references/delegated-verification.md` — a Write/Edit sub-agent can return "done" without writing the file (`test -f <path> && grep -Fc "<change-unique sentinel>" <path>`), and background agents must be told to SendMessage their result (an idle-completion notification is not a deliverable). Self-implemented sub-tasks don't narrate a claim and are covered by Phase 6's existing verification — do not duplicate this step there.

**TaskUpdate: task 3/4 `completed`**

### Phase 4b: Update ComponentShowcase (UI-heavy only)

**TaskUpdate: task 5 `in_progress`** (ui-heavy only)

If any new DS component was added to `packages/design-system/src/components.tsx`, add a corresponding section to `src/components/sportsbook/ComponentShowcase.tsx` with:
- Live preview of the component
- Copyable code snippet

**TaskUpdate: task 5 `completed`** (ui-heavy only)

### Phase 5: Validate Build & Lint

**TaskUpdate: task 4/6 `in_progress`**

```bash
npm run build    # TypeScript check + Vite build
npm run lint     # ESLint
```

Both must pass with zero errors. If either fails:
- Read the error output
- Fix the issue
- Re-run until clean

**TaskUpdate: task 4/6 `completed`**

### Phase 6: Verify Acceptance Criteria & Execute Test Plan

**TaskUpdate: task 5/7 `in_progress`**

**6a. Acceptance criteria check-off** — walk through **every** acceptance criterion in the spec. For each:

1. Run a verification command (grep, read, or build) to confirm the change
2. **Edit the spec file** to check off the criterion and add evidence:
   ```markdown
   - [x] All 10 files use `<SectionHeader>`  ✅ grep confirms zero custom h2 headers
   - [x] Visual output identical  ⏳ requires manual browser check
   ```
3. Criteria needing manual browser verification: mark with ⏳ and add to PR test plan

**6b. Execute test plan** — walk through the spec's Test Plan section. For each item:

1. Run the verification (grep, build, lint, or note as browser-only)
2. **Edit the spec file** to check off each test plan item:
   ```markdown
   - [x] `npm run build` passes  ✅
   - [x] `npm run lint` passes  ✅
   - [x] DevTools: all icon buttons >= 44×44px  ⏳ browser manual
   ```
3. Output a results table summarizing pass/fail/manual for each item

**6c. Check off Definition of Done** — edit the spec file's Definition of Done section:
   ```markdown
   - [x] All sub-tasks complete
   - [x] `npm run build` passes
   - [x] `npm run lint` passes
   - [x] Responsive: verified at 375px, 768px, 1280px  ⏳ browser manual
   - [x] PR created and reviewed
   ```

**TaskUpdate: task 5/7 `completed`**

### Phase 7: Update Tracking & Changelog

**TaskUpdate: task 6/8 `in_progress`**

1. **Update tracking file** — edit `specs/mvp-ux-tracking.md`:
   - Change story status from `Not Started` to `Complete`
   - Add PR number to the PR column
   - Update the epic-level summary (stories completed count, progress percentage)

2. **Update CHANGELOG.md** — add entry under `[Unreleased]`:
   ```markdown
   ### Changed
   - Story 0.1: Touch targets increased to 44px minimum, semantic HTML landmarks, ARIA tablist pattern
   ```

3. **Update spec status** — edit the spec file's metadata:
   ```markdown
   **Status**: Complete
   ```

4. **Commit tracking updates** separately from implementation (clean history):
   ```bash
   git add specs/ CHANGELOG.md
   git commit -m "docs: update tracking for Story {E}.{S} completion"
   ```

**TaskUpdate: task 6/8 `completed`**

### Phase 8: Create PR

**TaskUpdate: task 7/9 `in_progress`**

1. **Stage and commit** — use conventional commit format:
```bash
git add -A
git commit -m "feat: <story title> (Story {E}.{S})

<Summary of changes>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

2. **Push and create PR:**
```bash
git push -u origin feature/<story-slug>
gh pr create --base develop --title "feat: <story title> (Story {E}.{S})" --body "..."
```

3. **PR body must include:**
   - Summary of changes (from spec sub-tasks)
   - Link to spec file: `**Spec**: specs/stories/epic-{E}/story-{E}.{S}-*.md`
   - Test plan (from spec's Test Plan section)
   - Files changed count

4. **Return the PR URL** to the user.

**TaskUpdate: task 7/9 `completed`**

## Skill Delegation Matrix

> All skills in this matrix are optional external plugins that ship separately from this one. If a skill is not installed, implement that step directly and note the skip.

| Spec characteristic | Delegate to | When |
|-------------------|------------|------|
| New pages with creative UI | `Skill(superpowers:brainstorming)` | Before coding, to align on design direction |
| New DS components + full page build | `Skill(ui-from-requirements)` | When spec describes a complete new UI surface |
| Frontend aesthetic decisions | `Skill(frontend-design:frontend-design)` | When spec says "design a new page" without specific wireframes |
| Multiple independent sub-tasks | `Agent` (parallel) | When sub-tasks touch different files with no overlap |
| Post-implementation code review | `Skill(superpowers:verification-before-completion)` | Before claiming work is done |

## Error Recovery

| Error | Recovery |
|-------|---------|
| Build fails after implementation | Read error, fix, re-run build |
| Lint fails | Read error, fix, re-run lint |
| Merge conflict with develop | `git pull origin develop --rebase`, resolve conflicts |
| Spec references file that doesn't exist | Check if file was renamed; grep for the component/function name |
| Acceptance criterion can't be met | Report to user with explanation; don't skip silently |

## See Also

> These are separate skills that may not be installed alongside this plugin.

- `spec-creator` — creates the specs this skill implements
- `spec-review` — reviews specs for accuracy before implementation
- `finish` — merges the feature branch after PR approval
- `ui-pr-review` — reviews the PR for design system compliance
- `ui-from-requirements` — full UI build pipeline for complex specs
