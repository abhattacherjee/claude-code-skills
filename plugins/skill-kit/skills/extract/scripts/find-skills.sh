#!/usr/bin/env bash
# find-skills.sh — list or search the skills installed for this project (skill-kit:extract Step 1).
#
# Searches, in order: ./.claude/skills, ~/.claude/skills, ~/.codex/skills, then the
# ACTIVE plugin installs only. Plugin installs come from
# ~/.claude/plugins/installed_plugins.json (each install's installPath, user scope or
# the scope of the project you run this from, or a subdirectory of it). The rest of
# ~/.claude/plugins/cache and ~/.claude/plugins/marketplaces holds old versions and
# plugins that are not installed, so it is skipped. Only directories that exist are
# searched.

set -u

usage() {
  cat <<'EOF'
Usage: find-skills.sh                 list every SKILL.md in the skill directories
       find-skills.sh <rg-args...>    run rg with these arguments over the skill directories
       find-skills.sh --dirs          print the skill directories, one per line

Examples:
  find-skills.sh -i "keyword1|keyword2"        # keywords, any case
  find-skills.sh -F "exact error message"      # an exact error message
  find-skills.sh -i "next.config.js|prisma"    # context markers: files, functions, config keys

Run it from the project directory. Needs ripgrep (rg) and python3.
Exit: 0 found, 1 nothing found, 2 cannot run (a missing tool or no skill directory).
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

# A missing tool must stop the run: an empty result would read as "nothing related".
command -v rg >/dev/null || { echo "find-skills.sh: ripgrep (rg) is not installed. Install it, then re-run." >&2; exit 2; }
command -v python3 >/dev/null || { echo "find-skills.sh: python3 is not installed. Install it, then re-run." >&2; exit 2; }

SKILL_DIRS=()
for d in ".claude/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  [ -d "$d" ] && SKILL_DIRS+=("$d")
done
while IFS= read -r d; do
  [ -n "$d" ] && [ -d "$d" ] && SKILL_DIRS+=("$d")
done < <(python3 - "$HOME/.claude/plugins/installed_plugins.json" "$(pwd)" <<'EOF'
import json, os, sys
path, cwd = sys.argv[1], os.path.realpath(sys.argv[2])
try:
    with open(path, encoding="utf-8") as f:
        plugins = json.load(f).get("plugins", {})
except FileNotFoundError:
    sys.stderr.write("Note: %s not found; skipping plugin skills.\n" % path)
    sys.exit(0)
except (OSError, ValueError, AttributeError) as exc:
    sys.stderr.write("Note: cannot read %s (%s); skipping plugin skills.\n" % (path, exc))
    sys.exit(0)
for name, installs in plugins.items():
    for i in installs if isinstance(installs, list) else []:
        project = i.get("projectPath")
        p = os.path.realpath(project) if project else None
        if i.get("installPath") and (not p or cwd == p or cwd.startswith(p.rstrip("/") + "/")):
            print(i["installPath"])
EOF
)
[ "${#SKILL_DIRS[@]}" -gt 0 ] || { echo "find-skills.sh: no skill directories found." >&2; exit 2; }

if [ "${1:-}" = "--dirs" ]; then
  printf '%s\n' "${SKILL_DIRS[@]}"
  exit 0
fi
if [ "$#" -eq 0 ]; then
  rg --files -g 'SKILL.md' "${SKILL_DIRS[@]}"
else
  rg "$@" "${SKILL_DIRS[@]}"
fi
