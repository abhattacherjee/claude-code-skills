# Local Testing via the Plugin Marketplace

How to test this monorepo's plugins from your **local clone** instead of the published GitHub marketplace.

> These are interactive `/plugin` commands you run inside a Claude Code session. A **session restart** is usually needed for marketplace/plugin changes to take effect (the catalog is cached at `~/.claude/plugins/plugin-catalog-cache.json`).

## The name-collision gotcha

This repo's `.claude-plugin/marketplace.json` is named **`claude-code-skills`** — the **same name** as the published marketplace (GitHub `abhattacherjee/claude-code-skills`). Claude Code can't register two marketplaces with the same name, so you must **remove the remote first**, then add the local clone.

## Switch to the local marketplace

```
# 1. Inspect current marketplaces
/plugin marketplace list

# 2. Remove (disable) the remote
/plugin marketplace remove claude-code-skills

# 3. Add this local clone (reads .claude-plugin/marketplace.json from disk)
/plugin marketplace add /absolute/path/to/claude-code-skills

# 4. Install / test a plugin from the local source
/plugin install adversarial-review@claude-code-skills

# 5. After editing files locally, refresh the catalog
/plugin marketplace update claude-code-skills
```

## Caveats

- **Branch matters.** A `directory` marketplace reflects your **currently checked-out branch / working tree**. A plugin only on a feature branch (e.g. `adversarial-review` on `feature/adversarial-review-plugin`) is only available while that branch is checked out. Switching branches changes what the marketplace exposes.
- **Restart the session** after changing marketplaces/plugins if they don't appear.
- **Re-point installed plugins.** Plugins previously installed from the remote (e.g. `obsidian-brain@claude-code-skills`) lose their source when you remove the remote; reinstall them from the local marketplace if you need them: `/plugin install <name>@claude-code-skills`.

## Restore the remote marketplace

```
/plugin marketplace remove claude-code-skills
/plugin marketplace add abhattacherjee/claude-code-skills
```

## Notes

- A `directory`-source marketplace stays in sync with disk (same mechanism as the `obsidian-brain-repo` local marketplace).
- Each plugin's `source` in `marketplace.json` is a path relative to the repo root (e.g. `./plugins/adversarial-review`), which resolves correctly for both local-directory and GitHub marketplace sources.
