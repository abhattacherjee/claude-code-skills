# github-board

GitHub workflow skills in one install: create a board from a template, triage issues, plan milestones, plan the week, move cards, promote shipped work to Done, and prune stale branches.

```shell
/plugin install github-board@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/github-board:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `create-board` | `create-gh-board` | Copies a template ProjectV2 board onto a repo, links it, backfills issues and verifies the copy. Audits boards for drift. |
| `triage-issues` | `github-issue-triage` | Audits, updates, labels and closes open issues against the code. |
| `plan-milestones` | `github-milestone-planning` | Keeps each milestone small and themed; defers the rest. |
| `plan-week` | `weekly-focus` | Keeps a cross-repo "Weekly Focus" board current and answers "what do I work on next". |
| `move-card` | `github-board-move` | Moves an issue or PR card to any Status column. |
| `promote-shipped` | `github-release-board-promote` | Moves shipped cards to Done after a release or hotfix. |
| `prune-branches` | `git-branch-cleanup` | Finds and deletes stale local and remote branches. |

## Agents

Dispatched by `create-board` only, as `github-board:<agent>`: `template-inspector` (Phase 1), `board-creator` (Phases 2, 3 and 5), `workflow-syncer` (Phase 4), `board-verifier` (Phase 6). They were `gh-board-*`; the old agents keep their names, so both sets can be installed at once.

## Configuration

Per-user values live outside the plugin, so upgrades never touch them and launchd can read them:

`${XDG_CONFIG_HOME:-~/.config}/github-board/config.json`

```json
{
  "version": 1,
  "owner": "<login>",
  "plan_week": {
    "board_title": "Weekly Focus",
    "lanes": [
      {"name": "Security", "labels_containing": ["security"]},
      {"name": "Tooling", "repos": ["<repo>", "<repo>"]}
    ],
    "default_lane": "Product",
    "schedule": null,
    "frozen": ["<repo>"],
    "always": ["<repo>#<n>"],
    "capacity": {"max_repos_besides_security": 3, "hours": [10, 20]},
    "launchd": {"enabled": true, "times": ["07:00", "18:00"], "label_prefix": "dev.github-board.plan-week"}
  },
  "create_board": {"template_owner": "<login>", "template_number": 1}
}
```

- Write it with `/github-board:plan-week init` and `/github-board:create-board init`. Both ask a few questions with suggestions fetched from GitHub, show the file, and write it only after you confirm.
- Lane rules match in order; the first match wins, else `default_lane`. `schedule` is `null` (no fixed days) or `{"mon": [lanes], …}`.
- No config: every `plan-week` command except `init` exits 4, and so does a config that has no `plan_week` section yet (for example one written by `create-board init`); the message names the init to run. An invalid file, or a config path that is a dangling symlink, exits 2 and names the key or the file.
- Optional `"prune_branches": {"tracking_issue_authors": ["<login>", "app/<bot>"]}`: logins besides the repo owner whose issues `prune-branches` accepts as tracking issues for a Dependabot PR. Without it, only the owner counts; `prune-branches` needs no config.
- To seed from an existing setup, write the same shape to a file outside the repo and run `python3 <plan-week>/scripts/weekly-focus.py init --from <file>`. Do not commit that file.

## Metadata cache

Board numbers, node ids, field and option ids, and each repo's linked boards are cached in `${XDG_CACHE_HOME:-~/.cache}/github-board/` for 7 days. An empty lookup is never cached. When a `plan-week` or `move-card` command fails while cached ids are in use (for `move-card` also: the card is not on the cached board, or the target column is not in the cached options), it drops them and runs once more with fresh lookups, never for a rate-limit or missing-scope error. A missing-scope error in `plan-week` also drops every entry that run wrote. Keys are tuples (`owner`, `repo`, …) hashed into the file name, so `a-b/c` and `a/b-c` never share an entry. `promote-shipped` drops a cached board list whose board id no longer resolves. A board linked to a repo while its list is cached shows up when the entry ages out; pass `--no-cache` right after linking one. Deleting the directory is always safe.

## Background sync (macOS)

`plan-week` can run `sync` from launchd. `install-launchd.sh` copies the plan-week scripts and `lib/` into `~/.local/share/github-board/<version>/` (`$GITHUB_BOARD_HOME`) and points the stable link `~/.local/share/github-board/current` at that copy; the plists run the scripts through the link, never from the plugin cache. Upgrading or removing the plugin cannot break the jobs. **Re-run `install-launchd.sh` after a plugin update to move the jobs to the new code** (`--check` says `STALE COPY` until then).

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh"            # copy + link + both jobs
"$PW/scripts/install-launchd.sh" --check    # link, copy up to date, plists, loaded
```

If a plist with the same label already runs another copy's scripts, the install refuses with exit 3 and names that copy. `--takeover` hands the jobs to the plugin. `install-launchd.sh --check` exits 1 when the link, the copy, a plist or a loaded job is missing, wrong or out of date. With `plan_week.launchd.enabled` false the jobs never reinstall each other. If the config is missing or invalid, both jobs record it in `~/.local/state/weekly-focus/last-error` and send a "config error" notification at most once per 6 hours.

## Running next to the old bare skills

While both are installed, `/weekly-focus` and `/github-board:plan-week` read and write the same state (`~/.local/state/weekly-focus`, `~/Library/Logs/weekly-focus`) and the same board. Set `launchd.label_prefix` to the prefix the bare copy's labels use, so a later takeover replaces those same jobs. The bare copy keeps owning the launchd jobs until Phase 3.

## Phase 3: hand the launchd jobs to the plugin

Run by hand on the machine that has the bare `weekly-focus` jobs:

```bash
PW="$(ls -d ~/.claude/plugins/cache/*/github-board/*/skills/plan-week | sort -V | tail -1)"
"$PW/scripts/install-launchd.sh" --takeover
"$PW/scripts/install-launchd.sh" --check
python3 "$PW/scripts/weekly-focus.py" sync --json
```

Then set the `restart_command` of the two plan-week entries in `~/.claude/skills/boot-doctor/services.json` to `~/.local/share/github-board/current/skills/plan-week/scripts/install-launchd.sh`.

Rollback, only while the bare copy still exists (before Phase 4): `~/.claude/skills/weekly-focus/scripts/install-launchd.sh` rewrites both plists to point back at itself. After Phase 4 the bare copy is gone; to repair the jobs, re-run the plugin's `install-launchd.sh`, adding `--takeover` if a plist still names the bare copy.

## Phase 4: remove the bare copies

1. Before anything else, move the callers of the old names (see the last line of this section), so nothing calls a deleted skill, and confirm the plugin's `install-launchd.sh --check` exits 0, so no job still runs the bare copy. Then, in claude-code-config, drop `weekly-focus`, `create-gh-board` and `github-release-board-promote` from `sync.sh`'s `SKILLS` array, so a sync cannot bring them back.
2. Diff each bare copy against the plugin; expect only the renames and the config changes:

   ```bash
   P="$(ls -d ~/.claude/plugins/cache/*/github-board/* | sort -V | tail -1)"
   for pair in create-gh-board:create-board github-issue-triage:triage-issues \
       github-milestone-planning:plan-milestones weekly-focus:plan-week \
       github-board-move:move-card github-release-board-promote:promote-shipped \
       git-branch-cleanup:prune-branches; do
     diff -r ~/.claude/skills/"${pair%%:*}" "$P/skills/${pair##*:}"
   done
   ```

3. Delete the bare skills and agents:

   ```bash
   rm -rf ~/.claude/skills/{create-gh-board,github-issue-triage,github-milestone-planning,weekly-focus,github-board-move,github-release-board-promote,git-branch-cleanup}
   rm -f ~/.claude/agents/gh-board-{creator,template-inspector,verifier,workflow-syncer}.md
   ```

4. Confirm only `github-board:` names remain: `ls ~/.claude/skills ~/.claude/agents` shows none of the old names, and `/help` lists the `github-board:` skills.

Callers of the old names in claude-code-config, git-flow, obsidian-brain and codex-config move in one small PR per repo.

## Tests

```bash
python3 -m pytest plugins/github-board/tests -q -p no:cacheprovider
bash plugins/github-board/tests/smoke-clean-home.sh
```

Everything runs offline: `gh`, `launchctl` and `osascript` are fakes, and the config, cache and link paths point into a temp dir.
