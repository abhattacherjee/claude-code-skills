#!/usr/bin/env bash
set -euo pipefail

# test-commit-preflight.sh — tests for scripts/commit-preflight.sh and the
# token it writes for .claude/hooks/require-preflight.py (#335).
#
# Every case runs the real script and the real hook in a throwaway clone. The
# token path hashes the clone's git common dir, so it differs from this
# repo's: the developer's own token is never read, written or removed.
#
# Usage: bash scripts/test-commit-preflight.sh
#   PREFLIGHT_UNDER_TEST=<path> tests another copy of commit-preflight.sh.
#   PREFLIGHT_TEST_DETACH=1 detaches HEAD in every clone (as CI's checkout is).

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
PREFLIGHT_SRC="${PREFLIGHT_UNDER_TEST:-$REPO_ROOT/scripts/commit-preflight.sh}"
HOOK_SRC="$REPO_ROOT/.claude/hooks/require-preflight.py"
export PYTHONDONTWRITEBYTECODE=1
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

[[ -f "$PREFLIGHT_SRC" ]] || { echo "FATAL: commit-preflight.sh not found at $PREFLIGHT_SRC" >&2; exit 1; }
[[ -f "$HOOK_SRC" ]] || { echo "FATAL: require-preflight.py not found at $HOOK_SRC" >&2; exit 1; }

TMP="$(mktemp -d)"
TOKENS=()
HOLDER_PID=""
cleanup() {
  local t
  # Case 8's lock holder releases only on a signal file, with no timer, so a
  # test that dies early must stop it here.
  if [[ -n "$HOLDER_PID" ]]; then kill "$HOLDER_PID" 2>/dev/null || true; fi
  # "$t".* also takes the lock file and any temp token a killed writer left
  # (mkstemp names it <token>.<random> next to the token).
  # Cleanup never aborts the exit trap: a stray directory matching the glob
  # must not leave the clones behind.
  for t in ${TOKENS[@]+"${TOKENS[@]}"}; do rm -f "$t" "$t".* 2>/dev/null || true; done
  rm -rf "$TMP"
}
trap cleanup EXIT

PASS=0
FAIL=0
CASES=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

COMMIT_VERB="com""mit"
# checks_run the full path writes for one staged docs file in the clone: the
# secrets scan only (observed by running case 7 once on this repo).
FULL_CHECKS_RUN="secrets"
n=0
# setup: a fresh clone in $C with the working-tree script and hook committed.
# Sets C and TOKEN (the clone's own token path, removed on exit).
setup() {
  n=$((n + 1))
  C="$TMP/clone$n"
  git clone -q --no-hardlinks "$REPO_ROOT" "$C"
  [[ "${PREFLIGHT_TEST_DETACH:-}" == 1 ]] && git -C "$C" checkout -q --detach HEAD
  git -C "$C" config user.email t@example.com
  git -C "$C" config user.name t
  cp "$PREFLIGHT_SRC" "$C/scripts/commit-preflight.sh"
  cp "$HOOK_SRC" "$C/.claude/hooks/require-preflight.py"
  git -C "$C" add scripts/commit-preflight.sh .claude/hooks/require-preflight.py
  git -C "$C" "$COMMIT_VERB" -q --no-verify --allow-empty -m "use code under test"
  local key hash
  key="$(cd "$(git -C "$C" rev-parse --path-format=absolute --git-common-dir)" && pwd -P)"
  hash="$(python3 -c "import hashlib, sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:8])" "$key")"
  TOKEN="/tmp/.preflight-token-$hash"
  TOKENS+=("$TOKEN")
  rm -f "$TOKEN" "$TOKEN.lock"
}
preflight_full() { OUT="$(cd "$C" && ./scripts/commit-preflight.sh 2>&1)" && RC=0 || RC=$?; }
preflight() { OUT="$(cd "$C" && ./scripts/commit-preflight.sh --skip-tests "test" 2>&1)" && RC=0 || RC=$?; }
# preflight with a deadline in seconds: past it, the whole process group is
# killed and RC is 124, so a writer that blocks on the lock fails the case
# instead of hanging it. macOS has no timeout(1), so python3 does the timing.
preflight_deadline() {
  OUT="$(cd "$C" && python3 -c '
import os, signal, subprocess, sys
p = subprocess.Popen(["./scripts/commit-preflight.sh", "--skip-tests", "test"],
                     stdout=sys.stdout, stderr=subprocess.STDOUT, start_new_session=True)
try:
    sys.exit(p.wait(timeout=float(sys.argv[1])))
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    print("DEADLINE: preflight still running after %s s" % sys.argv[1])
    sys.exit(124)' "$1" 2>&1)" && RC=0 || RC=$?
}
hook() {
  local payload
  payload="$(printf '{"tool_name":"Bash","tool_input":{"command":"git %s -m t"},"cwd":"%s","hook_event_name":"PreToolUse"}' "$COMMIT_VERB" "$C")"
  HOUT="$(cd "$C" && printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$C" python3 "$C/.claude/hooks/require-preflight.py" 2>&1)" && HRC=0 || HRC=$?
}
# decision: the hook's permissionDecision from its stdout JSON, or <unparseable>.
decision() { printf '%s' "$HOUT" | python3 -c "import json, sys
try: print(json.load(sys.stdin)['hookSpecificOutput'].get('permissionDecision', '<none>'))
except Exception: print('<unparseable>')"; }
tokfield() { python3 -c "import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], '<missing>'))" "$TOKEN" "$1"; }
stage_doc() { printf 'line\n' > "$C/docs/$1"; git -C "$C" add "docs/$1"; }

# 1. Skip-tests path writes a token bound to HEAD, tree and checkout.
CASES=$((CASES + 1)); setup; stage_doc zz-test.md; preflight
if [[ "$RC" == 0 && -f "$TOKEN" ]]; then
  want_tree="$(git -C "$C" write-tree)"; want_head="$(git -C "$C" rev-parse HEAD)"
  want_wt="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$C")"
  if [[ "$(tokfield tree)" == "$want_tree" && "$(tokfield head)" == "$want_head" \
     && "$want_head" =~ ^[0-9a-f]{40}$ && "$(tokfield worktree)" == "$want_wt" \
     && "$(tokfield checks_run)" == "skipped" && "$(tokfield skip_reason)" == "test" ]]; then
    ok "1 skip-tests: exit 0, token has tree, head, worktree, checks_run, skip_reason"
  else bad "1 skip-tests: token fields wrong" "$(cat "$TOKEN")"; fi
else bad "1 skip-tests: rc=$RC, token present: $([[ -f "$TOKEN" ]] && echo yes || echo no)" "$OUT"; fi

# 2. Hook positive arm: the same token lets the commit through.
CASES=$((CASES + 1))
hook
# The hook's success path prints one JSON document with additionalContext
# "Preflight verified: ..." and no permissionDecision. Unparseable output never passes.
if [[ "$HRC" == 0 && "$(decision)" != "<unparseable>" && "$(decision)" != deny && "$HOUT" == *"Preflight verified"* ]]; then
  ok "2 hook allows a commit that matches the token (exit 0, parseable JSON, not deny, success text)"
else bad "2 hook denied a matching commit (rc=$HRC)" "$HOUT"; fi

# 3. Hook negative arm: the staged tree moved after the token.
CASES=$((CASES + 1)); setup; stage_doc zz-test.md; preflight
stage_doc zz-test2.md; hook
if [[ "$RC" == 0 && "$(decision)" == deny && "$HOUT" == *"The staged files changed since preflight ran"* ]]; then
  ok "3 hook denies when the staged tree moved (tree-changed reason)"
else bad "3 hook did not deny a moved tree (preflight rc=$RC, hook rc=$HRC)" "$HOUT"; fi

# 4. Hook negative arm: an old-format token.
CASES=$((CASES + 1)); setup; stage_doc zz-test.md
now="$(date +%s)"
printf '{"created":%s,"expires":%s,"staged_files":1,"checks_run":"lint"}\n' "$now" "$((now + 300))" > "$TOKEN"
hook
if [[ "$(decision)" == deny && "$HOUT" == *"old format"* ]]; then
  ok "4 hook denies an old-format token (old-format reason)"
else bad "4 hook did not deny an old-format token (rc=$HRC)" "$HOUT"; fi

# 5. A check stages a file mid-run: exit 1, and the older token is removed.
CASES=$((CASES + 1)); setup
now="$(date +%s)"
printf '{"created":%s,"expires":%s,"staged_files":1,"checks_run":"lint"}\n' "$now" "$((now + 300))" > "$TOKEN"
printf '#!/usr/bin/env bash\necho x > zz-mid.txt && git add zz-mid.txt\nexit 0\n' > "$C/scripts/check-docs.sh"
git -C "$C" add scripts/check-docs.sh
git -C "$C" "$COMMIT_VERB" -q --no-verify -m "stub docs guard that stages a file"
stage_doc zz-test.md; preflight
if [[ "$RC" == 1 && "$OUT" == *"the staged files changed while preflight ran"* && ! -e "$TOKEN" ]]; then
  ok "5 mid-run staging: exit 1, message printed, older token removed"
else bad "5 mid-run staging: rc=$RC, token present: $([[ -e "$TOKEN" ]] && echo yes || echo no)" "$OUT"; fi

# 6. git write-tree fails (unmerged index): exit 1, and the older token is removed.
CASES=$((CASES + 1)); setup
now="$(date +%s)"
printf '{"created":%s,"expires":%s,"staged_files":1,"checks_run":"lint"}\n' "$now" "$((now + 300))" > "$TOKEN"
git -C "$C" switch -q -c zz-main
base=zz-main
printf 'base\n' > "$C/zz-conflict.txt"; git -C "$C" add zz-conflict.txt
git -C "$C" "$COMMIT_VERB" -q --no-verify -m "base"
git -C "$C" checkout -q -b zz-side; printf 'side\n' > "$C/zz-conflict.txt"
git -C "$C" "$COMMIT_VERB" -q --no-verify -am "side"
git -C "$C" checkout -q "$base"; printf 'main\n' > "$C/zz-conflict.txt"
git -C "$C" "$COMMIT_VERB" -q --no-verify -am "main side"
git -C "$C" merge -q zz-side >/dev/null 2>&1 || true
preflight
if [[ "$RC" == 1 && "$OUT" == *"cannot read the staged tree"* && ! -e "$TOKEN" ]]; then
  ok "6 write-tree failure: exit 1, message printed, older token removed"
else bad "6 write-tree failure: rc=$RC, token present: $([[ -e "$TOKEN" ]] && echo yes || echo no)" "$OUT"; fi

# 7. Full path (no --skip-tests): a docs-only change writes a complete token.
CASES=$((CASES + 1)); setup; stage_doc zz-test.md; preflight_full
if [[ "$RC" == 0 && -f "$TOKEN" ]]; then
  want_tree="$(git -C "$C" write-tree)"; want_head="$(git -C "$C" rev-parse HEAD)"
  want_wt="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$C")"
  tokcheck=0
  python3 - "$TOKEN" "$(date +%s)" "$FULL_CHECKS_RUN" <<'PY' || tokcheck=1
import json, sys
t = json.load(open(sys.argv[1])); now = int(sys.argv[2])
c = t.get("created")
if not (isinstance(c, int) and abs(now - c) <= 60): sys.exit(1)
if t.get("expires") != c + 300: sys.exit(1)
if t.get("staged_files") != 1: sys.exit(1)
if t.get("checks_run") != sys.argv[3]: sys.exit(1)
if "skip_reason" in t: sys.exit(1)
PY
  if [[ "$tokcheck" == 0 && "$(tokfield tree)" == "$want_tree" && "$(tokfield head)" == "$want_head" \
     && "$want_head" =~ ^[0-9a-f]{40}$ && "$(tokfield worktree)" == "$want_wt" ]]; then
    ok "7 full path: exit 0, token has created, expires, staged_files, checks_run, no skip_reason"
  else bad "7 full path: token fields wrong" "$(cat "$TOKEN")"; fi
else bad "7 full path: rc=$RC, token present: $([[ -f "$TOKEN" ]] && echo yes || echo no)" "$OUT"; fi

# 8. Token lock held by another process: exit 1, and the existing token stays
# byte for byte. The holder releases only when told to, after preflight returns.
CASES=$((CASES + 1)); setup; stage_doc zz-test.md
now="$(date +%s)"
printf '{"created":%s,"expires":%s,"staged_files":1,"checks_run":"lint"}\n' "$now" "$((now + 300))" > "$TOKEN"
cp "$TOKEN" "$TMP/token.before"
rm -f "$TMP/release" "$TMP/holder.out"
python3 -c "
import fcntl, os, sys, time
fd = os.open(sys.argv[1] + '.lock', os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
print('held', flush=True)
while not os.path.exists(sys.argv[2]):
    time.sleep(0.05)" "$TOKEN" "$TMP/release" > "$TMP/holder.out" &
holder=$!
HOLDER_PID=$holder  # cleanup() kills it if the test exits before the release
for _ in $(seq 1 100); do grep -q held "$TMP/holder.out" 2>/dev/null && break; sleep 0.1; done
preflight_deadline 60
: > "$TMP/release"
holder_rc=0; wait "$holder" || holder_rc=$?
HOLDER_PID=""
if [[ "$holder_rc" == 0 ]] && grep -q held "$TMP/holder.out" && [[ "$RC" == 1 && "$OUT" == *"locked by a commit in progress"* ]] \
   && [[ -f "$TOKEN" ]] && cmp -s "$TOKEN" "$TMP/token.before"; then
  ok "8 lock timeout: exit 1, message printed, existing token kept byte for byte"
else bad "8 lock timeout: rc=$RC, holder rc=$holder_rc, token present: $([[ -f "$TOKEN" ]] && echo yes || echo no), same bytes: $(cmp -s "$TOKEN" "$TMP/token.before" && echo yes || echo no)" "$OUT"; fi

# Positive control: every case ran.
if [[ "$CASES" == 8 ]]; then ok "positive control: 8 cases ran"; else bad "positive control: $CASES cases ran, want 8"; fi

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[[ "$FAIL" == 0 ]] || exit 1
