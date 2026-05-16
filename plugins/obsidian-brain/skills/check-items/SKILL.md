---
name: check-items
description: Triage open `- [ ]` items across your Obsidian vault with evidence-grounded AI classification. Auto-closes items shipped by merged PRs, surfaces items needing external action (e.g. `gh issue close`), hides stale items by default. Replaces the old token-overlap heuristic with a two-pass AI pipeline backed by a persistence cache. Use when: (1) sweeping a project for done work, (2) auditing what's still actionable, (3) recovering from /recall deferral fatigue.
---

# /check-items

## Invocation

```
/check-items                     # current project, 14d window (default)
/check-items <project>           # named project, 14d window
/check-items all                 # every project with open items in window
/check-items 30d                 # current project, widen window
/check-items --show-all          # include LOW-confidence + STALE
/check-items --dry-run           # run pipeline, write report, skip edit-confirm loop
/check-items --no-cache          # force re-classification of every group
```

Arguments are order-independent and combinable: `/check-items all 30d --show-all`.

## Step 1 — Parse arguments and resolve scope

Run this bash block. It parses `$ARGUMENTS` per the invocation contract above (positional project / `all` / `Nd`, plus the three flags). Output goes to a temp directory under `~/.claude/obsidian-brain/`; the printed path is captured in `$scope_path` and passed to every subsequent step as `"$scope_path"`.

Each step below is a bash block; the embedded Python reads its inputs from `$1`, `$2`, … via `sys.argv`. Pass `"$scope_path"` captured here as the first arg, and any previous step's output path as subsequent args.

```bash
ARGUMENTS="${ARGUMENTS:-}"
scope_path=$(python3 -c "
import sys, os, glob, json, tempfile
sys.path.insert(0, max(
    glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks')),
    default='hooks'
))
from check_items_args import parse_scope

argv = sys.argv[1:]
scope_obj = parse_scope(argv)
scope = {
    'mode': scope_obj.mode,
    'project': scope_obj.project,
    'window_days': scope_obj.window_days,
    'show_all': scope_obj.show_all,
    'dry_run': scope_obj.dry_run,
    'no_cache': scope_obj.no_cache,
}

workdir = tempfile.mkdtemp(prefix='check-items-', dir=os.path.expanduser('~/.claude/obsidian-brain'))
os.chmod(workdir, 0o700)
scope_path = os.path.join(workdir, 'scope.json')
with open(scope_path, 'w') as f:
    json.dump(scope, f)
os.chmod(scope_path, 0o600)
print(scope_path)
" $ARGUMENTS)

echo "scope_path=$scope_path"
cat "$scope_path"
```

Save the printed `scope.json` path in `$scope_path`; pass it to every subsequent step as the first arg.

Note: `window_days` in scope controls how many sessions' files to pass as `basenames` in Step 5. The `collect_open_items` helper itself scans by `max_sessions` count (not calendar days); to apply a window filter, limit the basenames list to files dated within the window before passing to `deep_analysis_pipeline`.

## Step 2 — Collect open items (Stage 1)

```bash
raw_path=$(python3 -c "
import sys, os, glob, json, itertools
sys.path.insert(0, max(
    glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks')),
    default='hooks'
))
from open_item_dedup import collect_open_items

scope_path = sys.argv[1]
scope = json.load(open(scope_path))
config_path = os.path.expanduser('~/.claude/obsidian-brain-config.json')
try:
    config = json.load(open(config_path))
    vault_path = config.get('vault_path')
    if not vault_path:
        raise ValueError('vault_path missing from config')
except (OSError, json.JSONDecodeError, ValueError) as exc:
    print(f'ERROR: obsidian-brain config not loadable ({exc}); run /obsidian-setup', file=sys.stderr)
    sys.exit(1)
sessions_folder = config.get('sessions_folder', 'claude-sessions')

# Resolve project list from scope
if scope['mode'] == 'vault':
    # All projects: collect from all session notes without project filter.
    # We use a sentinel to indicate vault-wide scan below.
    projects = None
elif scope['mode'] == 'project' and scope['project']:
    projects = [scope['project']]
else:
    # current: derive project name from cwd git repo name
    import subprocess
    res = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        print('ERROR: /check-items current-project mode requires running inside a git repo.\n'
              'Use /check-items all (vault-wide) or /check-items <project>.', file=sys.stderr)
        sys.exit(1)
    cwd_proj = os.path.basename(res.stdout.strip()) if res.returncode == 0 else None
    projects = [cwd_proj] if cwd_proj else None

raw_items = []
if projects is None:
    # vault-wide: scan all session files, no project filter
    # collect_open_items requires a project arg; use per-project discovery
    sessions_dir = os.path.join(vault_path, sessions_folder)
    if os.path.isdir(sessions_dir):
        seen_projects = set()
        for fname in os.listdir(sessions_dir):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(sessions_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    for line in itertools.islice(f, 20):
                        if line.strip().startswith('project:'):
                            proj = line.strip().split(':', 1)[1].strip().strip('\"').strip(\"'\")
                            if proj:
                                seen_projects.add(proj)
                            break
            except OSError:
                continue
        for proj in sorted(seen_projects):
            items = collect_open_items(
                vault_path=vault_path,
                sessions_folder=sessions_folder,
                project=proj,
                max_sessions=50,
            )
            for fpath, line_num, item_text in items:
                raw_items.append({
                    'file': os.path.basename(fpath),
                    'path': fpath,
                    'line': line_num,
                    'text': item_text,
                    'project': proj,
                })
else:
    for proj in projects:
        if proj is None:
            continue
        items = collect_open_items(
            vault_path=vault_path,
            sessions_folder=sessions_folder,
            project=proj,
            max_sessions=50,
        )
        for fpath, line_num, item_text in items:
            raw_items.append({
                'file': os.path.basename(fpath),
                'path': fpath,
                'line': line_num,
                'text': item_text,
                'project': proj,
            })

out_path = os.path.join(os.path.dirname(scope_path), 'raw_items.json')
with open(out_path, 'w') as f:
    json.dump(raw_items, f, indent=2)
os.chmod(out_path, 0o600)
print(out_path)
" "$scope_path")

echo "raw_path=$raw_path"
```

## Step 3 — Coarse-group + cache partition (Stage 2a + cache load)

Convention: each step is a `bash` block. Steps 1-2 use `python3 -c "..."` with positional argv tokens (inputs passed as `sys.argv` args, e.g. `python3 -c "..." "$scope_path"`). Steps 3-10 use `python3 << 'PYEOF' ... PYEOF` heredoc with inputs passed via environment variables (e.g. `SCOPE_PATH="$scope_path" python3 << 'PYEOF' ... PYEOF`); the Python reads them via `os.environ["VAR_NAME"]` — never via `sys.argv`. Both patterns produce a runnable shell block — never paste raw `python3` blocks that rely on `sys.argv` without an argv-passing wrapper, and never use env-var heredoc style for Steps 1-2 which expect positional args.

```bash
part_path=$(SCOPE_PATH="$scope_path" RAW_PATH="$raw_path" python3 << 'PYEOF'
import sys, os, glob, json, subprocess
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import find_duplicates, cross_project_dedup
from check_items_cache import canonical_hash, load_cache, partition
from obsidian_utils import get_workspace_roots

scope_path = os.environ["SCOPE_PATH"]
raw_path = os.environ["RAW_PATH"]
scope = json.load(open(scope_path))
raw_items = json.load(open(raw_path))

# Build coarse groups per project using per-candidate find_duplicates loop.
# find_duplicates(candidate_text, existing_items, threshold=5) is per-candidate.
by_project = {}
for it in raw_items:
    by_project.setdefault(it.get("project", "unknown"), []).append(it)

coarse_by_proj = {}
for proj, items in by_project.items():
    # Convert to the (fpath, line_num, item_text) tuples that find_duplicates expects
    tuples = [(it["path"], it["line"], it["text"]) for it in items]
    seen_grouped = set()
    groups = []
    for idx, (fpath, line_num, item_text) in enumerate(tuples):
        if idx in seen_grouped:
            continue
        others = [(f, l, t) for j, (f, l, t) in enumerate(tuples) if j != idx]
        dupes = find_duplicates(item_text, others)
        members = [{"file": os.path.basename(fpath), "line": line_num, "text": item_text,
                     "mtime": os.path.getmtime(fpath) if os.path.exists(fpath) else 0}]
        for df, dl, dt, dc in dupes:
            for j, (f2, l2, t2) in enumerate(tuples):
                if os.path.abspath(f2) == os.path.abspath(df) and l2 == dl:
                    seen_grouped.add(j)
            members.append({"file": os.path.basename(df), "line": dl,
                             "text": dt, "confidence": dc,
                             "mtime": os.path.getmtime(df) if os.path.exists(df) else 0})
        seen_grouped.add(idx)
        import uuid
        g = {
            "group_id": str(uuid.uuid4())[:8],
            "project": proj,
            "representative": item_text,
            "members": members,
            "canonical_hash": canonical_hash(item_text),
        }
        groups.append(g)
    coarse_by_proj[proj] = groups

flat_groups = cross_project_dedup(coarse_by_proj) if scope["mode"] == "vault" else \
              [g for v in coarse_by_proj.values() for g in v]

# Cache partition (per project).
cache = load_cache()
known, needs = [], []
for proj, groups in coarse_by_proj.items():
    repo_path = None
    for _root in get_workspace_roots():
        _candidate = os.path.join(_root, proj)
        if os.path.isdir(os.path.join(_candidate, ".git")):
            repo_path = _candidate
            break
    if not repo_path:
        print(f"[check-items] no repo found for {proj} in {get_workspace_roots()}; forcing reclassify",
              file=sys.stderr)
        for g in groups:
            g["_reason"] = "head_unavailable"  # ensure Step 6 includes these in to_classify
        needs.extend(groups)
        continue
    head_proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        print(f"[check-items] no HEAD for {proj} ({repo_path}); forcing reclassify",
              file=sys.stderr)
        for g in groups:
            g["_reason"] = "head_unavailable"  # ensure Step 6 includes these in to_classify
        needs.extend(groups)
        continue
    head = head_proc.stdout.strip()
    k, n = partition(groups, cache, project=proj, head_sha=head, force=scope["no_cache"])
    known.extend(k)
    needs.extend(n)

out = os.path.join(os.path.dirname(scope_path), "partition.json")
with open(out, "w") as f:
    json.dump({"flat_groups": flat_groups, "known": known, "needs": needs}, f, indent=2)
os.chmod(out, 0o600)
print(out)
PYEOF
)

echo "part_path=$part_path"
```

## Step 4 — Semantic merge on needs-reclassification set (Stage 2b)

```bash
merged_path=$(SCOPE_PATH="$scope_path" PART_PATH="$part_path" python3 << 'PYEOF'
import sys, os, glob, json
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import merge_groups_semantically, get_last_semantic_merge_mode

scope_path = os.environ["SCOPE_PATH"]
part_path = os.environ["PART_PATH"]
data = json.load(open(part_path))
needs = data["needs"]
known = data["known"]

# Run semantic merge only over needs-reclassification groups so that known
# (already-classified) groups are never absorbed into a canonical group and
# silently lose their _reason flag. Step 6 filters to groups with _reason set;
# if a needs-group were merged into a known canonical, it would be skipped.
needs_by_proj = {}
for g in needs:
    needs_by_proj.setdefault(g["project"], []).append(g)

# merge_groups_semantically accepts dict {project: [groups]}; returns same shape.
merged_needs_by_proj = merge_groups_semantically(needs_by_proj) if needs_by_proj else {}
mode = get_last_semantic_merge_mode()

# Splice known (untouched) back in after merge so Step 6 can iterate all groups.
merged_by_proj = {}
for proj, groups in merged_needs_by_proj.items():
    merged_by_proj.setdefault(proj, []).extend(groups)
for g in known:
    merged_by_proj.setdefault(g["project"], []).append(g)

out = os.path.join(os.path.dirname(scope_path), "merged.json")
with open(out, "w") as f:
    json.dump({"merged_by_proj": merged_by_proj, "mode": mode}, f, indent=2)
os.chmod(out, 0o600)
print(out)
PYEOF
)

echo "merged_path=$merged_path"
```


## Step 5 — Gather evidence (Stage 3)

```bash
evidence_path=$(SCOPE_PATH="$scope_path" MERGED_PATH="$merged_path" python3 << 'PYEOF'
import sys, os, glob, json, datetime
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import deep_analysis_pipeline

scope_path = os.environ["SCOPE_PATH"]
merged_path = os.environ["MERGED_PATH"]
scope = json.load(open(scope_path))
data = json.load(open(merged_path))
_config_path = os.path.expanduser("~/.claude/obsidian-brain-config.json")
try:
    config = json.load(open(_config_path))
    vault_path = config.get("vault_path")
    if not vault_path:
        raise ValueError("vault_path missing from config")
except (OSError, json.JSONDecodeError, ValueError) as exc:
    print(f"ERROR: obsidian-brain config not loadable ({exc}); run /obsidian-setup", file=sys.stderr)
    sys.exit(1)
sessions_folder = config.get("sessions_folder", "claude-sessions")
insights_folder = config.get("insights_folder", "claude-insights")

# Collect session file basenames within window_days to scope evidence gathering.
window_days = scope.get("window_days", 14)
cutoff = (datetime.date.today() - datetime.timedelta(days=window_days)).isoformat()
sessions_dir = os.path.join(vault_path, sessions_folder)
basenames = []
if os.path.isdir(sessions_dir):
    for fname in sorted(os.listdir(sessions_dir), reverse=True):
        if not fname.endswith(".md"):
            continue
        # Filenames are YYYY-MM-DD-* — date prefix determines recency
        if len(fname) < 10 or fname[4] != "-" or fname[7] != "-":
            continue
        date_prefix = fname[:10]
        if date_prefix < cutoff:
            break  # sorted reverse-chronological; once below cutoff we're done
        basenames.append(fname)

projects = list(data["merged_by_proj"].keys()) if isinstance(data["merged_by_proj"], dict) else []
output_path = os.path.join(os.path.dirname(scope_path), "pipeline_evidence.json")

# deep_analysis_pipeline(basenames, projects_json, output_path, vault_path,
#                        sessions_folder, insights_folder, db_path=None)
# Returns "OK:<total>:<groups>:<N>" status string; data is written to output_path.
status = deep_analysis_pipeline(
    basenames=basenames,
    projects_json=json.dumps(projects),
    output_path=output_path,
    vault_path=vault_path,
    sessions_folder=sessions_folder,
    insights_folder=insights_folder,
)
if not status.startswith("OK"):
    print(f"WARNING: deep_analysis_pipeline returned: {status}", file=sys.stderr)

# Read the written evidence from output_path for downstream use.
try:
    pipeline_data = json.load(open(output_path))
    evidence = pipeline_data.get("evidence", {})
except (OSError, json.JSONDecodeError) as e:
    print(f"WARNING: could not read pipeline output: {e}", file=sys.stderr)
    evidence = {}

out = os.path.join(os.path.dirname(scope_path), "evidence.json")
with open(out, "w") as f:
    json.dump(evidence, f, default=str, indent=2)
os.chmod(out, 0o600)
print(out)
PYEOF
)

echo "evidence_path=$evidence_path"
```

## Step 6 — Classify (Stage 4) with fallback chain

```bash
classifications_path=$(SCOPE_PATH="$scope_path" MERGED_PATH="$merged_path" EVIDENCE_PATH="$evidence_path" python3 << 'PYEOF'
import sys, os, glob, json
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import (
    classify_groups_with_agent, classify_groups_heuristic, get_last_classifier_mode
)

scope_path = os.environ["SCOPE_PATH"]
merged_path = os.environ["MERGED_PATH"]
evidence_path = os.environ["EVIDENCE_PATH"]
data = json.load(open(merged_path))
evidence = json.load(open(evidence_path))

# Filter to needs-reclassification only (groups with _reason set).
all_merged = [g for v in data["merged_by_proj"].values() for g in v] \
             if isinstance(data["merged_by_proj"], dict) \
             else data["merged_by_proj"]
to_classify = [g for g in all_merged if g.get("_reason")]

primary = classify_groups_with_agent(to_classify, evidence)
mode = get_last_classifier_mode()
if mode == "heuristic-fallback":
    primary = classify_groups_heuristic(to_classify, evidence)

# Merge cached classifications (known_unchanged) with fresh.
classifications = list(primary)
for g in all_merged:
    if g.get("_cached_classification"):
        classifications.append({
            "group_id": g.get("group_id"),
            "classification": g["_cached_classification"],
            "confidence": g.get("_cached_confidence", "LOW"),
            "canonical_text": g.get("representative", ""),
            "evidence_citation": g.get("_cached_evidence_citation"),
            "action_required": g.get("_cached_action_required"),
            "project": g.get("project"),
        })

out = os.path.join(os.path.dirname(scope_path), "classifications.json")
with open(out, "w") as f:
    json.dump({"classifications": classifications, "classifier_mode": mode}, f, indent=2)
os.chmod(out, 0o600)
print(out)
PYEOF
)

echo "classifications_path=$classifications_path"
```

## Step 7 — Apply tier rules + present review (Stage 5)

```bash
buckets_path=$(SCOPE_PATH="$scope_path" CLASSIFICATIONS_PATH="$classifications_path" python3 << 'PYEOF'
import sys, os, glob, json
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import assign_tier, partition_for_review

scope_path = os.environ["SCOPE_PATH"]
classifications_path = os.environ["CLASSIFICATIONS_PATH"]
scope = json.load(open(scope_path))
data = json.load(open(classifications_path))
for item in data["classifications"]:
    item["tier"] = assign_tier(item.get("evidence_citation"), item.get("canonical_text"))

buckets = partition_for_review(data["classifications"], show_all=scope["show_all"])
# Format: HIGH first, MED next, LOW (only if show_all). DONE preselected [x],
# NEEDS-ACTION [ ] with action_required command surfaced.
print("\n=== Review ===", file=sys.stderr)
for item in sorted(buckets["review"],
                   key=lambda x: ("HIGH MED LOW".split().index(x.get("tier", "LOW")),
                                  x.get("classification"))):
    mark = "[x]" if item["classification"] == "DONE" and item["tier"] == "HIGH" else "[ ]"
    print(f"  {mark} ({item['classification']}/{item['tier']}) {item['canonical_text']}", file=sys.stderr)
    print(f"      evidence: {item.get('evidence_citation')}", file=sys.stderr)
    if item.get("action_required"):
        print(f"      action:   {item['action_required']}", file=sys.stderr)

out = os.path.join(os.path.dirname(scope_path), "buckets.json")
with open(out, "w") as f:
    json.dump(buckets, f, indent=2)
os.chmod(out, 0o600)
print(out)
PYEOF
)

echo "buckets_path=$buckets_path"
```

If `scope.dry_run` is true OR the user types `none` at the confirm prompt: skip Step 8 (Edit + cascade) and go straight to Step 9 (dashboard). The dashboard is ALWAYS written.

## Step 8 — Apply confirmed checkoffs (Stage 6) + cascade (Stage 7)

For each item the user kept selected (default-selected for HIGH+DONE, opt-in for everything else):

1. Read the target line via Read tool.
2. Verify the line matches the preview (memory `feedback_open_item_checkoff_verify_before_edit`).
3. If mismatch: surface the diff, ABORT this item (do not flip), continue with the next.
4. If match: use Edit tool to flip `- [ ]` → `- [x]` on that line only. After a successful flip, append `[full_file_path, line_number]` to a `source_skips` tracking list.

After the user-confirmed batch, write the source-skips tracking list to a tempfile and run cascade via `cascade_group_members` (which consumes the Step-3/Step-4 grouping output directly, so textually-divergent siblings clustered by distinctive tokens are also flipped — not just text-search re-discovery matches):

```bash
# Write source_skips JSON — list of [full_path, line_number] pairs for lines
# the SKILL already primary-flipped above.  Replace the contents below with the
# actual list collected in the primary-flip loop.
_skips_file=$(python3 -c "
import tempfile, os, json, sys
d = os.path.expanduser('~/.claude/obsidian-brain')
os.makedirs(d, mode=0o700, exist_ok=True)
fd, path = tempfile.mkstemp(dir=d, prefix='check-items-source-skips-', suffix='.json')
with os.fdopen(fd, 'w') as f:
    json.dump(sys.argv[1:], f)   # placeholder — SKILL replaces with real list
os.chmod(path, 0o600)
print(path)
")
# ^^^ In practice, Claude writes the actual skips list by passing them as
# the JSON-serialised content written to $_skips_file after the primary-flip loop.

SCOPE_PATH="$scope_path" BUCKETS_PATH="$buckets_path" MERGED_PATH="$merged_path" SKIPS_FILE="$_skips_file" python3 << 'PYEOF'
import sys, os, glob, json, re
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from open_item_dedup import cascade_group_members

scope_path = os.environ["SCOPE_PATH"]
buckets_path = os.environ["BUCKETS_PATH"]
merged_path = os.environ["MERGED_PATH"]
skips_file = os.environ.get("SKIPS_FILE", "")

_config_path = os.path.expanduser("~/.claude/obsidian-brain-config.json")
try:
    config = json.load(open(_config_path))
    vault_path = config.get("vault_path")
    if not vault_path:
        raise ValueError("vault_path missing from config")
except (OSError, json.JSONDecodeError, ValueError) as exc:
    print(f"ERROR: obsidian-brain config not loadable ({exc}); run /obsidian-setup", file=sys.stderr)
    sys.exit(1)
sessions_folder = config.get("sessions_folder", "claude-sessions")
sessions_dir = os.path.join(vault_path, sessions_folder)

buckets = json.load(open(buckets_path))
scope = json.load(open(scope_path))

# Load merged groups so we can resolve group_id → members with full paths.
# Members in merged.json store basename only; resolve to full path via sessions_dir.
try:
    merged_data = json.load(open(merged_path))
    groups_by_id = {}
    for _gs in merged_data.get("merged_by_proj", {}).values():
        for _g in _gs:
            groups_by_id[_g.get("group_id")] = _g
except (OSError, json.JSONDecodeError) as exc:
    print(
        f"[check-items] FATAL: cannot load merged.json ({exc}) — skipping cascade to avoid corrupt cache",
        file=sys.stderr,
    )
    sys.exit(1)

# Load source_skips: set of (full_path, line_number) pairs already primary-flipped.
source_skips = set()
if skips_file and os.path.exists(skips_file):
    try:
        raw_skips = json.load(open(skips_file))
        for entry in raw_skips or []:
            if isinstance(entry, list) and len(entry) == 2:
                source_skips.add((str(entry[0]), int(entry[1])))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[check-items] WARNING: source_skips load failed ({exc}); cascade summary may be inaccurate", file=sys.stderr)
        source_skips = set()

# Build groups_to_cascade: DONE items from buckets["review"] that have members
# in merged.json. Resolve member basenames to full paths.
groups_to_cascade = []
for b in buckets["review"]:
    if b.get("classification") != "DONE":
        continue
    gid = b.get("group_id")
    merged_group = groups_by_id.get(gid) if gid else None
    if not merged_group:
        continue
    raw_members = merged_group.get("members", []) or []
    if not raw_members:
        continue
    resolved_members = []
    for m in raw_members:
        basename = m.get("file", "")
        line_num = m.get("line")
        if not basename or line_num is None:
            continue
        full_path = os.path.join(sessions_dir, basename)
        resolved_members.append({"file": full_path, "line": line_num, "text": m.get("text", "")})
    if resolved_members:
        groups_to_cascade.append({"members": resolved_members})

summary = cascade_group_members(groups_to_cascade, source_skips)
print(f"[cascade] {summary}")

# Extract count from summary for downstream use.
m = re.search(r"Cascaded (\d+)", summary)
cascade_total = int(m.group(1)) if m else 0
print(f"cascaded_total={cascade_total}")
PYEOF

# Clean up source-skips tempfile.
rm -f "$_skips_file"
```

**Note on primary-flip loop tracking:** After each successful Edit in steps 1–4, append the flipped item's full file path and line number as `[path, line]` to a Python list, then write that list as JSON to `$_skips_file` before running the cascade block. This prevents the cascade from double-flipping lines the SKILL already handled. `batch_cascade_checkoff` is retained for ad-hoc text-search use outside this SKILL flow.

## Step 9 — Write dashboard report (Stage 8) — ALWAYS

(Implemented in Task 22.) Call `write_check_items_dashboard()` with the scope, classifications, applied count, cascade count, semantic-merge mode, and classifier mode. Path: `<vault>/<check_items_folder>/check-items-<scope>-<YYYY-MM-DD>.md` (folder configurable, default `claude-check-items`).

## Step 10 — Persist cache updates

```bash
SCOPE_PATH="$scope_path" CLASSIFICATIONS_PATH="$classifications_path" PARTITION_PATH="$part_path" python3 << 'PYEOF'
import sys, os, glob, json, time, subprocess
sys.path.insert(0, max(
    glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks")),
    default="hooks"
))
from check_items_cache import load_cache, save_cache, update_cache, canonical_hash
from obsidian_utils import get_workspace_roots

scope_path = os.environ["SCOPE_PATH"]
classifications_path = os.environ["CLASSIFICATIONS_PATH"]
partition_path = os.environ["PARTITION_PATH"]
scope = json.load(open(scope_path))
data = json.load(open(classifications_path))
part = json.load(open(partition_path))

# Re-derive project list and HEAD shas for cache update.
all_groups = part["flat_groups"]

# Build a lookup from merged.json so we can attach members + mtime to each
# fresh classification. members are required by partition() for mtime
# invalidation; empty members causes every group to look mtime_changed next run.
merged_path_for_step10 = os.path.join(os.path.dirname(scope_path), "merged.json")
try:
    merged_data = json.load(open(merged_path_for_step10))
    all_merged = merged_data
except (OSError, json.JSONDecodeError) as exc:
    print(
        f"[check-items] FATAL: cannot load merged.json ({exc}) — skipping cache update to avoid corrupt cache",
        file=sys.stderr,
    )
    sys.exit(1)

groups_by_id = {}
for _proj, _gs in all_merged.get("merged_by_proj", {}).items():
    for _g in _gs:
        groups_by_id[_g.get("group_id")] = _g

fresh_classifications = []
for c in data["classifications"]:
    gid = c.get("group_id")
    group = groups_by_id.get(gid, {})
    fresh_classifications.append({
        "canonical_hash": group.get("canonical_hash") or canonical_hash(c.get("canonical_text", "")),
        "canonical_text": c.get("canonical_text", ""),
        "members": group.get("members", []),  # file/line/mtime preserved for mtime invalidation
        "classification": c.get("classification"),
        "confidence": c.get("confidence"),
        "evidence_citation": c.get("evidence_citation"),
        "classified_ts": int(time.time()),
        "_group_project": group.get("project", "unknown"),  # carried for fresh_by_proj attribution
    })

# Group by project for per-project update_cache calls.
groups_by_proj = {}
for g in all_groups:
    groups_by_proj.setdefault(g.get("project", "unknown"), []).append(g)
fresh_by_proj = {}
for fc in fresh_classifications:
    # Derive project from the looked-up group (groups_by_id[gid]["project"]), not hash matching,
    # so same canonical text in multiple projects is attributed correctly.
    proj = fc.pop("_group_project", "unknown")
    fresh_by_proj.setdefault(proj, []).append(fc)

cache = load_cache()
_workspace_roots = get_workspace_roots()
for proj, proj_groups in groups_by_proj.items():
    repo_path = None
    for _root in _workspace_roots:
        _candidate = os.path.join(_root, proj)
        if os.path.isdir(os.path.join(_candidate, ".git")):
            repo_path = _candidate
            break
    if not repo_path:
        print(f"[check-items] no repo found for {proj} in {_workspace_roots}; skipping cache update",
              file=sys.stderr)
        continue
    head_proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        print(f"[check-items] no HEAD for {proj} ({repo_path}); skipping cache update",
              file=sys.stderr)
        continue
    head = head_proc.stdout.strip()
    cache = update_cache(
        cache=cache,
        project=proj,
        all_groups=proj_groups,
        fresh_classifications=fresh_by_proj.get(proj, []),
        head_sha=head,
    )

save_cache(cache)
print("cache updated")
PYEOF
```

## Output format

```
✓ /check-items obsidian-brain (14d)
  Raw: 225  Groups: 40  Merged: 24
  Mode: semantic+classifier  Cached: 8 reused, 16 fresh
  Result: 3 DONE (auto-checked), 2 NEEDS-ACTION (commands below), 19 ACTIVE (silent)
  Report: ~/Obsidian/claude-check-items/check-items-obsidian-brain-2026-05-11.md
  Cascaded: 2 sibling notes
```

## Notes

- All sub-agent prompts live in `hooks/check_items_cli.py` (the semantic-merge and classifier prompt constants). Do NOT inline those prompts in this SKILL.md.
- The cache file is at `~/.claude/obsidian-brain/check-items-classifications.json` (0o600). Safe to delete for a full reset.
- `/recall` no longer surfaces checkoff candidates. If you used to invoke `/recall → "skip"`, just run `/check-items` directly.
