---
name: extract
description: "Was the claudeception skill. Extracts reusable knowledge from work sessions and codifies it into Claude Code skills. Use when: (1) /skill-kit:extract (was /claudeception) to review session learnings, (2) save this as a skill or extract a skill from this, (3) what did we learn?, (4) after non-obvious debugging, workarounds, or trial-and-error discovery. Evaluates whether current work contains extractable knowledge, checks for existing skills, and creates or updates skills following the skill-kit:author best practices."
metadata:
  version: 1.2.0
---

# Claudeception

Extract reusable knowledge from a work session into a Claude Code skill. Be selective: not every task produces a skill.

## When to Extract a Skill

Invoke this skill right after a task when ANY of these apply:

1. **Non-obvious solution**: the fix took >10 minutes of investigation and was not in the documentation.
2. **Error resolution**: the error message was misleading or the root cause was not obvious.
3. **Workaround or trial and error**: you found a workaround for a tool or framework limitation, or tried several approaches before one worked.
4. **Project-specific pattern**: a convention, configuration or architectural decision in this codebase that differs from standard patterns and is not documented elsewhere.
5. **Tool integration knowledge**: how to use a tool, library or API in a way its documentation does not cover well.

Also invoke it when the user runs `/skill-kit:extract`, says "save this as a skill", or asks "what did we learn?".

## Skill Quality Criteria

Before extracting, verify the knowledge meets these criteria:

- **Reusable**: Will this help with future tasks? (Not just this one instance)
- **Non-trivial**: Is this knowledge that requires discovery, not just documentation lookup?
- **Specific**: Can you describe the exact trigger conditions and solution?
- **Verified**: Has this solution actually worked, not just theoretically?

## Extraction Process

### Step 1: Check for Existing Skills

**Goal:** Find related skills before creating. Decide: update or create new.

Run `find-skills.sh` from the project directory. It searches the project's skills, the user's, and only the plugin installs that are active for this project. Exit 0 means found and 1 nothing found. Exit 2 means `rg` or `python3` is missing, and exit 3 means the search itself failed (a bad pattern or an unreadable file; `rg`'s error is on stderr). On 2 or 3, stop and fix it: an empty result would read as "nothing related".

```bash
"${CLAUDE_SKILL_DIR}/scripts/find-skills.sh"                                   # list all skills
"${CLAUDE_SKILL_DIR}/scripts/find-skills.sh" -i "keyword1|keyword2"            # search by keywords
"${CLAUDE_SKILL_DIR}/scripts/find-skills.sh" -F "exact error message"          # search by exact error message
"${CLAUDE_SKILL_DIR}/scripts/find-skills.sh" -i "getServerSideProps|next.config.js|prisma.schema"   # context markers
```

| Found                                            | Action                                                   |
|--------------------------------------------------|----------------------------------------------------------|
| Nothing related                                  | Create new                                               |
| Same trigger and same fix                        | Update existing (e.g., `version: 1.0.0` → `1.1.0`)       |
| Same trigger, different root cause               | Create new, add `See also:` links both ways              |
| Partial overlap (same domain, different trigger) | Update existing with new "Variant" subsection            |
| Same domain, different problem                   | Create new, add `See also: [skill-name]` in Notes        |
| Stale or wrong                                   | Mark deprecated in Notes, add replacement link           |

**Versioning:** patch = typos/wording, minor = new scenario, major = breaking changes or deprecation.

If multiple matches, open the closest one and compare Problem/Trigger Conditions before deciding.

**A match inside a plugin install is not edited in place.** Its installPath is a cache copy under `~/.claude/plugins/cache`, which the next plugin update overwrites. Read the plugin's marketplace in `~/.claude/plugins/known_marketplaces.json`. If its `source.source` is `"directory"`, `source.path` is a checkout the user owns: make "Update existing" there, in the plugin's own source, not in the cache. Otherwise (a `github` or `git` source) do not edit the plugin: tell the user the fix belongs in the plugin's source repo, and create a new user skill in `~/.claude/skills/` with a `See also:` link to the plugin skill.

### Step 2: Identify the Knowledge

Analyze what was learned:
- What was the problem or task?
- What was non-obvious about the solution?
- What would someone need to know to solve this faster next time?
- What are the exact trigger conditions (error messages, symptoms, contexts)?

### Step 3: Research Best Practices (When Appropriate)

Search the web for technology-specific best practices when the topic involves specific
frameworks, libraries, or tools. Skip for project-specific internal patterns.

**Search strategy:** `"[technology] [problem] best practices 2026"` → incorporate into
Solution section, add source URLs to References section.

### Step 4: Structure and Save the Skill

**Use the `skill-kit:author` skill** for the complete authoring workflow: frontmatter rules,
directory layout (SKILL.md + scripts/ + references/), description writing, template,
and quality checklist.

**Key rules (quick reference):**
- Frontmatter: only `name`, `description`, `metadata.version` (no author, date, tags)
- Description: third person, ≤1024 chars, numbered trigger conditions
- SKILL.md body: under 500 lines, extract lookup material to `references/`
- Scripts: add `--help`, error handling, `chmod +x`
- Save: project-specific → `.claude/skills/`, user-wide → `~/.claude/skills/`

### Step 5: Update Project Artifacts

After saving skill changes, update project-level artifacts that track changes:

1. **CHANGELOG.md** — Add entries under `[Unreleased]` for:
   - New skills → `### Added` section
   - Updated skills → `### Documentation` section
   - Script fixes bundled with skill updates → `### Fixed` section
2. **Commit message** — Use `docs(skills):` prefix for skill-only changes,
   or `fix(skills):` if a script bug was also fixed

**Why this step exists:** Skill extraction focuses on the SKILL.md files and scripts,
making it easy to forget that the project's CHANGELOG.md also needs to reflect these
changes. Without this step, skill updates get committed without any changelog entry,
violating project conventions.

## Retrospective Mode

When `/skill-kit:extract` is invoked at the end of a session:

1. **Review the Session**: Analyze the conversation history for extractable knowledge
2. **Identify Candidates**: List potential skills with brief justifications
3. **Prioritize**: Focus on the highest-value, most reusable knowledge
4. **Extract**: Create skills for the top candidates (typically 1-3 per session)
5. **Summarize**: Report what skills were created and why

## Quality Gates

**Use the `skill-kit:author` skill's quality checklist** for the full pre-publish verification.

Quick check before saving:
- [ ] Knowledge is reusable, non-trivial, specific, and verified
- [ ] No sensitive information (credentials, internal URLs)
- [ ] Doesn't duplicate existing skills (Step 1 search completed)
- [ ] SKILL.md follows `skill-kit:author` frontmatter and structure rules
- [ ] CHANGELOG.md `[Unreleased]` updated with skill changes (Step 5)

## Example: Complete Extraction Flow

**Scenario**: Discovered `getServerSideProps` errors don't appear in browser console.

1. **Identify**: Problem = server-side errors invisible in browser. Trigger = empty console + error page.
2. **Research**: Searched "Next.js getServerSideProps error handling 2026" → found official patterns.
3. **Structure**: Created `~/.claude/skills/nextjs-server-side-error-debugging/SKILL.md`
   with trigger conditions, solution steps, and References section linking to official docs.
4. **Verify**: Tested with real Next.js error → confirmed terminal shows stack trace.

Complete sample skills: [examples/nextjs-server-side-error-debugging/SKILL.md](examples/nextjs-server-side-error-debugging/SKILL.md), [examples/prisma-connection-pool-exhaustion/SKILL.md](examples/prisma-connection-pool-exhaustion/SKILL.md) and [examples/typescript-circular-dependency/SKILL.md](examples/typescript-circular-dependency/SKILL.md).

## See Also
- `skill-kit:author` — how to structure, write, and optimize skills (the HOW)
- `scaffold-backport` — propagates project fixes back to scaffold template (complementary auto-trigger)
- [resources/research-references.md](resources/research-references.md) — the research papers behind this skill's design (background for people; not needed to run it)
- Anthropic docs: [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
