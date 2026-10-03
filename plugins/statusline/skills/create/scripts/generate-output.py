#!/usr/bin/env python3
"""Generate the output section (echo -e lines) for a statusline script."""
import sys

items = sys.argv[1].split(',')
lines = int(sys.argv[2])

identity = {
    'model': '${BOLD}${MAGENTA}${MODEL}${R}',
    'model-full': '${BOLD}${MAGENTA}${MODEL}${R}',
    'dir': '📁 ${CYAN}${DIR_SHORT}${R}',
    'git': '🌿 ${GREEN}${BRANCH}${R}${GIT_CHANGES}',
    'git-sync': '${SYNC}',
    'git-link': '🔗 ${GIT_LINK}',
    'worktree': '${WORKTREE}',
    'vim-mode': '${VIM}',
    'agent': '${AGENT}',
    'session-id': '${DIM}${SID}${R}',
    'style': '${DIM}${STYLE}${R}',
}
context = {
    'context-bar': '${CTX_C}${bar}${R} ${CTX_C}${PCT}%${R}',
    'context-pct': 'ctx:${PCT}%',
    'tokens': 'in:${IN_K} out:${OUT_K}',
    'warn-200k': '${WARN}',
}
metrics = {
    'cost': '💰 ${COST_FMT}',
    'cost-color': '💰 ${COST_C}${COST_FMT}${R}',
    'duration': '⏱️ ${DUR_M}m ${DUR_S}s',
    'api-duration': 'api:${API_M}m ${API_S}s',
    'lines-changed': '${GREEN}+${ADDED}${R} ${RED}-${REMOVED}${R}',
}

sep = ' ${DIM}│${R} '

def join_parts(item_list, mapping):
    parts = [mapping[i] for i in item_list if i in mapping]
    return sep.join(parts) if parts else ''

if lines == 1:
    all_maps = {**identity, **context, **metrics}
    line = join_parts(items, all_maps)
    if line:
        print(f'echo -e "{line}"')
elif lines == 2:
    l1 = join_parts(items, identity)
    l2 = join_parts(items, {**context, **metrics})
    if l1:
        print(f'echo -e "{l1}"')
    if l2:
        print(f'echo -e "{l2}"')
else:
    l1 = join_parts(items, identity)
    l2 = join_parts(items, context)
    l3 = join_parts(items, metrics)
    if l1:
        print(f'echo -e "{l1}"')
    if l2:
        print(f'echo -e "{l2}"')
    if l3:
        print(f'echo -e "{l3}"')
