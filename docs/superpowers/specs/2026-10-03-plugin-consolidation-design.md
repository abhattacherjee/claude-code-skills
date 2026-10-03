# Plugin consolidation: one plugin per workflow, no bare copies

Approved 2026-10-03. Follows the `github-board` pattern (#146, #147). Epic: #156.

## Problem

- The monorepo ships 16 plugins and also keeps 11 top-level bare skill directories. Seven of the bare directories duplicate a plugin, and the copies drift. `skill-authoring` is 2.6.1 as a skill but 2.3.1 in its `plugin.json`. The bare `figma-ui-designer` is 3.2.0 but the plugin is 3.1.0.
- `plugins/obsidian-brain` is a 2.5.1 mirror of a plugin that ships from its own repo (3.7.0) and its own marketplace. Two entries with one name invite a stale install.
- Three plugins (`context-bar`, `custom-statusline`, `statusline-creator`) all install or build a statusline.
- Four skills also live in their own GitHub repos (`changelog-keeper`, `claudeception`, `conversation-search`, `worktree`), so each has three copies: that repo, the monorepo, and the live `~/.claude/skills` clone.
- `skill-publishing` builds plugins *from* bare skills, which is why the bare directories exist at all.

## Design

One plugin per workflow. Skills drop words the plugin prefix already says, as `github-board` did. Per-user values live outside the plugin (XDG config), never in the skill text.

| Plugin | Replaces | Skills | Issue |
|---|---|---|---|
| `review` | `deep-review`, `adversarial-review` (+ 3 agents) | `deep`, `adversarial` | #159 |
| `spec` | `spec-creator`, `spec-review`, `spec-implement` | `create`, `review`, `implement` | #160 |
| `skill-kit` | `skill-authoring`, `skill-publishing`, `claudeception` | `author`, `publish`, `extract` | #161 |
| `statusline` | `context-bar`, `custom-statusline`, `statusline-creator` | `install`, `create`, `context-bar` | #158 |
| `demo-video` | `smart-screen-recorder`, `product-video-creation` (+ 9 agents) | `record`, `produce` | #162 |
| `context` | `context-shield`, `conversation-search` | `shield`, `search` | #163 |
| `ui-design` | `figma-ui-designer` | `figma` | #164 |
| `dev-flow` | `worktree`, `changelog-keeper` | `worktree`, `changelog` | #165 |
| `github-board` | done in v3.20.0 | — | #146 |

- `plugins/obsidian-brain` is removed from this marketplace (#166). The plugin installs from `obsidian-brain-repo`.
- `statusline`: confirm the three plugins really overlap before merging them. If `context-bar` is a separate feature, it stays a separate skill inside the plugin.
- Out of scope: personal skills that live only in `~/.claude/skills` and claude-code-config (`ship`, `kickoff`, `boot-doctor`, `test-vacuity-audit` and others).

## Migration, per plugin

The same runbook as #146 and #147:

1. Inventory every caller of the old names across all of `~/.claude` and every repo before starting. Example callers: `deep-review` dispatches `adversarial-review:*` agents; `/ship` calls `/deep-review`.
2. Build `plugins/<group>/` as the only source. Rename agents to `<group>:<agent>`.
3. Keep the old marketplace entries for one release, with descriptions that say "Deprecated: moved to `<group>:<skill>`". Remove them in the next release.
4. Bump `plugin.json` for every change, because `/plugin update` compares versions only.
5. Live cut-over: install the plugin, diff each loose `~/.claude/skills` copy against it and carry over local edits, move callers first, then delete the loose copy. Long-lived jobs must point at a copy the plugin owns, never the versioned cache.

## Removing the bare directories (#167)

- `skill-publishing` treats `plugins/<group>/skills/<name>/` as the source (#105). It no longer assembles plugins from bare skills.
- `scripts/validate-skill.sh`, the CI workflow and `scripts/test-sync-hygiene.sh` scan `plugins/*/skills/*`.
- The 11 top-level skill directories are deleted.
- #84, #92 and #93 stop applying, because they're about the bare-directory scan or the bare-to-plugin build. Close each one when its code is deleted.

## Archiving the standalone repos (#157)

`changelog-keeper`, `claudeception`, `conversation-search` and `worktree` are archived on GitHub after their content is in the monorepo:

- Content only in the standalone repo comes in first: claudeception's `examples/` and `resources/`.
- Content only in the live clone comes in too: `worktree`'s note on Python virtualenvs, made generic (no private repo names).
- `CONTRIBUTING.md` and `WARP.md` are per-repo tooling and are not carried over.
- Each repo's description points at the monorepo before it is archived. None has open issues, open PRs or extra branches (checked 2026-10-03).
- Archiving is reversible (`gh repo unarchive`).

## Order

1. Consolidate and archive the four standalone repos (#157).
2. `statusline` (lowest risk, 3 → 1).
3. `review`, then `spec` (most callers).
4. `skill-kit`, together with #105.
5. `demo-video`, `context`, `ui-design`, `dev-flow`.
6. Drop the `obsidian-brain` mirror.
7. Delete the top-level bare directories once every group has moved.
