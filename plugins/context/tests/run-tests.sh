#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts and agent wiring of the context plugin.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a temp
# project directory (never the skill directory), in a clean environment (`env -i`,
# so nothing leaks in from the caller's shell). HOME points at a temp dir, so the
# conversation search reads a fixture ~/.claude/projects and never the real one. The
# plugin is copied to a path with a space first, so a script that finds its files
# relative to its own location, or does not quote a path, fails here. Needs bash 3.2+,
# python3 (standard library) and jq. Nothing here touches the network or anything
# outside the temp dir.
#
# Usage: bash plugins/context/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy" "$TMP/home" "$TMP/proj"
cp -R "$PLUGIN/skills" "$TMP/plugin copy/skills"
cp -R "$PLUGIN/agents" "$TMP/plugin copy/agents"
# SKILLS and AGENTS may each be set by the caller to test another copy of the skills or agents.
SKILLS="${SKILLS:-$TMP/plugin copy/skills}"
AGENTS="${AGENTS:-$TMP/plugin copy/agents}"

SHIELD="$SKILLS/shield/scripts"
SEARCH="$SKILLS/search/scripts"
PROJ="$TMP/proj"
HOME_DIR="$TMP/home"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

# run_in <dir> <cmd...>: run in a clean env from <dir>; sets OUT (stdout), ERR (stderr), RC.
run_in() {
  local dir="$1"
  shift
  RC=0
  OUT="$(cd "$dir" && env -i PATH="$PATH" HOME="$HOME_DIR" "$@" 2>"$TMP/err")" || RC=$?
  ERR="$(cat "$TMP/err")"
}

# check <label> <want-rc|nonzero> [stdout-regex [stderr-regex]]  (uses OUT ERR RC from run_in)
check() {
  local label="$1" want="$2" ore="${3:-}" ere="${4:-}"
  if [[ "$want" == nonzero ]]; then
    if [[ "$RC" == 0 ]]; then
      bad "$label" "exit 0, want non-zero. stdout: $(printf '%s' "$OUT" | head -2)"
      return 0
    fi
  elif [[ "$RC" != "$want" ]]; then
    bad "$label" "exit $RC, want $want. stdout: $(printf '%s' "$OUT" | head -2) stderr: $(printf '%s' "$ERR" | head -2)"
    return 0
  fi
  if [[ -n "$ore" ]] && ! printf '%s' "$OUT" | grep -Eq -- "$ore"; then
    bad "$label" "stdout lacks /$ore/: $(printf '%s' "$OUT" | head -4)"
  elif [[ -n "$ere" ]] && ! printf '%s' "$ERR" | grep -Eq -- "$ere"; then
    bad "$label" "stderr lacks /$ere/: $(printf '%s' "$ERR" | head -4)"
  else
    ok "$label"
  fi
}

# json_is <label> <python-expr over d>: OUT must be valid JSON and the expression true.
# The expressions are literals written in this file, never input, so eval is safe here.
json_is() {
  local label="$1" expr="$2" res
  if res="$(printf '%s' "$OUT" | python3 -c 'import json,sys
d = json.load(sys.stdin)
print("yes" if eval(sys.argv[1]) else "no")' "$expr" 2>&1)" && [[ "$res" == "yes" ]]; then
    ok "$label"
  else
    bad "$label" "JSON check failed ($expr): $res; stdout: $(printf '%s' "$OUT" | head -c 300)"
  fi
}

# The scripts start with `#!/usr/bin/env bash`. EXPECT_BASH_MAJOR (set by CI) pins the version.
echo "bash under test: $BASH_VERSION"
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

echo "validate-skill.sh (search ships the repo-root validator)"
ROOT_VALIDATOR="$PLUGIN/../../scripts/validate-skill.sh"
if [[ -f "$ROOT_VALIDATOR" ]]; then
  cmp -s "$ROOT_VALIDATOR" "$SEARCH/validate-skill.sh" && ok "search: validate-skill.sh is byte-identical to the repo-root copy" || bad "search: validate-skill.sh is byte-identical to the repo-root copy" "they differ"
else
  # A skipped check reads as a pass, so a missing root validator fails the run.
  bad "search: validate-skill.sh can be compared with the repo-root copy" "no scripts/validate-skill.sh at $ROOT_VALIDATOR (run the tests from a checkout of the repo)"
fi
run_in "$PROJ" "$SEARCH/validate-skill.sh" "$SKILLS/search"
check "search: validate-skill.sh passes on its own skill" 0 'Result: PASS'
[[ ! -e "$SKILLS/shield/scripts/validate-skill.sh" ]] && ok "shield ships no validator of its own" || bad "shield ships no validator of its own" "scripts/validate-skill.sh exists"

echo "manage-manifest.sh (shield)"
OUTDIR="$TMP/cs run"
# The command as shield/SKILL.md writes it, with <OUTPUT_DIR> filled in (here a path with a space).
run_in "$PROJ" "$SHIELD/manage-manifest.sh" create --task "Analyze designs" --output-dir "$OUTDIR" --batch-size 2 \
  "url:https://example.com/a,label=Page A" \
  "figma:fileKey=abc,nodeId=1:2,label=Hero" \
  "file:specs/story.md,label=Spec"
check "create exits 0 and reports 3 sources in 2 batches" 0 'Sources: 3'
check "create reports the batch count" 0 'Batches: 2 \(batch size: 2\)'
M="$OUTDIR/manifest.json"
[[ -f "$M" ]] && ok "create writes manifest.json under the output dir" || bad "create writes manifest.json under the output dir" "missing $M"
OUT="$(cat "$M" 2>/dev/null || true)"
json_is "manifest has the task and three pending sources, figma coordinates parsed" 'd["task"] == "Analyze designs" and len(d["sources"]) == 3 and all(s["status"] == "pending" for s in d["sources"]) and d["sources"][1]["extra"] == {"fileKey": "abc", "nodeId": "1:2"}'
MM="$SHIELD/manage-manifest.sh"
run_in "$PROJ" "$MM" status --manifest "$M"
check "status: nothing done yet" 0 'Progress:   0/3 done \(3 pending, 0 failed\)'
check "status says IN PROGRESS" 0 'STATUS: IN PROGRESS — 3 items remaining'
run_in "$PROJ" "$MM" next-batch --manifest "$M"
json_is "next-batch returns the first 2 pending sources" 'len(d) == 2 and d[0]["label"] == "Page A" and d[1]["label"] == "Hero"'
json_is "next-batch adds the manifest task to every item (the distiller reads it)" 'all(i["task"] == "Analyze designs" for i in d)'
run_in "$PROJ" "$MM" mark-done --manifest "$M" --index 0 --summary "page A is blue"
check "mark-done exits 0" 0 'Marked done: \[0\] Page A'
run_in "$PROJ" "$MM" status --manifest "$M"
check "status after the first mark-done counts 1 done" 0 'Progress:   1/3 done \(2 pending'
run_in "$PROJ" "$MM" summaries --manifest "$M"
check "summaries (partial) lists the done source" 0 'page A is blue'
check "summaries (partial) says items are still pending" 0 '2 items still pending'
printf '%s' "$OUT" | grep -q 'Hero' && bad "summaries (partial) leaves out a pending source" "Hero is listed" || ok "summaries (partial) leaves out a pending source"
run_in "$PROJ" "$MM" next-batch --manifest "$M"
json_is "next-batch skips the done source" 'len(d) == 2 and d[0]["label"] == "Hero"'

# Bad indexes must fail and leave the manifest untouched.
before="$(cksum < "$M")"
for badidx in 5 -1 abc 1.5; do
  run_in "$PROJ" "$MM" mark-done --manifest "$M" --index "$badidx" --summary "x"
  check "mark-done --index '$badidx' exits non-zero with a message" nonzero "" 'Index must be an integer from 0 to 2'
  [[ "$(cksum < "$M")" == "$before" ]] && ok "mark-done --index '$badidx' leaves manifest.json byte-identical" || bad "mark-done --index '$badidx' leaves manifest.json byte-identical" "manifest changed"
done
run_in "$PROJ" "$MM" mark-done --manifest "$M" --index "" --summary "x"
check "mark-done --index '' exits non-zero with a message" nonzero "" '--index is required'
run_in "$PROJ" "$MM" mark-failed --manifest "$M" --index 3 --reason "x"
check "mark-failed --index 3 (out of range) exits non-zero with a message" nonzero "" 'Index must be an integer from 0 to 2'
run_in "$PROJ" "$MM" mark-failed --manifest "$M" --index -1 --reason "x"
check "mark-failed --index -1 exits non-zero with a message" nonzero "" 'Index must be an integer from 0 to 2'
run_in "$PROJ" "$MM" mark-failed --manifest "$M" --index 1
check "mark-failed without --reason exits non-zero with a message" nonzero "" '--reason is required'
[[ "$(cksum < "$M")" == "$before" ]] && ok "mark-failed with a bad index or no reason leaves manifest.json byte-identical" || bad "mark-failed with a bad index or no reason leaves manifest.json byte-identical" "manifest changed"

# The failure path: a 404 or login wall is recorded as failed, not stored as a summary.
run_in "$PROJ" "$MM" mark-failed --manifest "$M" --index 1 --reason "404 not found"
check "mark-failed exits 0" 0 'Marked failed: \[1\] Hero'
OUT="$(cat "$M")"
json_is "mark-failed stores status failed and the reason, and no summary" 'd["sources"][1]["status"] == "failed" and d["sources"][1]["reason"] == "404 not found" and d["sources"][1]["summary"] is None'
run_in "$PROJ" "$MM" status --manifest "$M"
check "status counts the failed source" 0 'Progress:   1/3 done \(1 pending, 1 failed\)'
run_in "$PROJ" "$MM" next-batch --manifest "$M"
json_is "next-batch does not return a failed source" 'len(d) == 1 and d[0]["label"] == "Spec"'
run_in "$PROJ" "$MM" mark-done --manifest "$M" --index 2 --summary "spec says X"
run_in "$PROJ" "$MM" status --manifest "$M"
check "status says BLOCKED when only failed sources remain" 0 'STATUS: BLOCKED — 1 failed items need retry'
run_in "$PROJ" "$MM" summaries --manifest "$M"
check "summaries lists the failed source with its reason" 0 '\[1\] Hero.*404 not found'
printf '%s' "$OUT" | grep -q '^## \[1\] Hero' && bad "summaries does not present a failed source as a summary" "Hero has a summary heading" || ok "summaries does not present a failed source as a summary"
run_in "$PROJ" "$MM" mark-done --manifest "$M" --index 1 --summary "hero is wide"
OUT="$(cat "$M")"
json_is "a retry with mark-done clears the failure" '"reason" not in d["sources"][1] and d["sources"][1]["status"] == "done"'
run_in "$PROJ" "$MM" status --manifest "$M"
check "status says COMPLETE when every source is done" 0 'STATUS: COMPLETE'
run_in "$PROJ" "$MM" summaries --manifest "$M"
check "summaries lists a done source with its summary" 0 '## \[0\] Page A \(url\)'
check "summaries includes the third summary" 0 'spec says X'
run_in "$PROJ" "$MM" mark-failed --manifest "$M" --index 0 --reason "gone"
run_in "$PROJ" "$MM" reset --manifest "$M"
check "reset exits 0" 0 'Reset all items to pending'
OUT="$(cat "$M")"
json_is "reset clears every summary and failure reason" 'all(s["summary"] is None and s["status"] == "pending" and "reason" not in s for s in d["sources"])'
run_in "$PROJ" "$MM" status --manifest "$M"
check "after reset the run is IN PROGRESS again" 0 'STATUS: IN PROGRESS — 3 items'
run_in "$PROJ" "$SHIELD/manage-manifest.sh" status --manifest "$TMP/no-such-manifest.json"
check "status: missing manifest exits 1 with a message" 1 "" 'Manifest not found'
run_in "$PROJ" "$SHIELD/manage-manifest.sh" status
check "status: no --manifest exits 1 with a message" 1 "" '--manifest is required'
run_in "$PROJ" "$SHIELD/manage-manifest.sh" frobnicate
check "unknown command exits 1 with a message" 1 "" 'Unknown command: frobnicate'
run_in "$PROJ" "$SHIELD/manage-manifest.sh" create --task "x" --output-dir "$TMP/cs-bad" "ftp:somewhere"
check "create: unknown source type exits 1 with a message" 1 "" "Unknown source type 'ftp'"
run_in "$PROJ" "$SHIELD/manage-manifest.sh" create --task "x" --output-dir "$TMP/cs-bad2"
check "create: no sources exits 1 with a message" 1 "" 'At least one source is required'
run_in "$PROJ" "$MM" --help
check "--help exits 0" 0 'Usage: manage-manifest\.sh'
check "--help lists mark-failed" 0 'mark-failed'

# jq 1.6 (Debian 12, Ubuntu 22.04) rejects a keyword as an unquoted object key or as a --arg name ($label).
# This machine's jq may be newer, so look for them in the text.
jq_kw='label|if|then|reduce|foreach|def|import|include|as|and|or|not|try|catch|elif|else|end|__loc__'
kw_hits="$(grep -nE -- "--arg(json)? ($jq_kw) |[{,] *($jq_kw) *:" "$SHIELD/manage-manifest.sh" "$SEARCH/search-conversations.sh" || true)"
[[ -z "$kw_hits" ]] && ok "no jq keyword is an unquoted object key or a variable name in the scripts (jq 1.6)" || bad "a jq keyword is an unquoted object key or a variable name (syntax error in jq 1.6)" "$kw_hits"

echo "visualize.sh (shield)"
# The scenes shield/SKILL.md calls, with NO_COLOR so the output is plain text.
VIZ="$SHIELD/visualize.sh"
run_in "$PROJ" env NO_COLOR=1 "$VIZ" manifest --task "Analyze designs" --count 8
check "manifest scene exits 0" 0 'Sources: 8 items'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" dispatch --batch 1 --labels "Home,Search"
check "dispatch scene exits 0" 0 'BATCH 1: DISPATCHING 2 AGENTS'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" working --labels "Home,Search"
check "working scene exits 0" 0 'Agents working in isolation'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" return --batch 1 --labels "Home,Search"
check "return scene exits 0" 0 'BATCH 1: AGENTS RETURNING'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" ralph-iter --iteration 1 --remaining 4
check "ralph-iter scene exits 0" 0 'Iteration 1 complete'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" synthesize --done 8 --total 8
check "synthesize scene exits 0" 0 'Combining 8 distilled summaries'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" complete --task "Analyze designs"
check "complete scene exits 0" 0 'Task: Analyze designs'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" dispatch --batch 1 --labels ""
check "dispatch with empty --labels exits 0 (empty array under set -u, bash 3.2)" 0 'BATCH 1: DISPATCHING 0 AGENTS'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" working --labels ""
check "working with empty --labels exits 0" 0 'Agents working in isolation'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" --speed instant
check "only a global option, no scene, exits 1 with a message" 1 "" 'Unknown scene'
run_in "$PROJ" env NO_COLOR=1 "$VIZ" bogus-scene
check "unknown scene exits 1 with a message" 1 "" 'Unknown scene: bogus-scene'
run_in "$PROJ" "$VIZ" --help
check "--help exits 0" 0 'Usage: visualize\.sh'

echo "search-conversations.sh (search), against a fixture ~/.claude/projects under a temp HOME"
P1="$HOME_DIR/.claude/projects/-work-other"
P2="$HOME_DIR/.claude/projects/-work-my-app"
mkdir -p "$P1" "$P2"
S1=11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa
S2=22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb
S3=33333333-cccc-4ccc-8ccc-cccccccccccc
# S1: no index entry (an orphan), created 2025-02-17 23:59:59 UTC.
printf '%s\n' \
  '{"type":"user","timestamp":"2025-02-17T23:59:59.000Z","cwd":"/work/other","gitBranch":"main","message":{"role":"user","content":"How do I fix the catalog sync?"}}' \
  '{"type":"assistant","timestamp":"2025-02-18T00:00:05.000Z","message":{"role":"assistant","content":[{"type":"text","text":"Re-run the catalog import."}]}}' \
  > "$P1/$S1.jsonl"
# S2: indexed, created 2025-02-18 10:00 UTC. Its text holds a word the index does not (zebracorn)
# (the dot test below needs -F: without it, zebr.corn matches).
printf '%s\n' \
  '{"type":"user","timestamp":"2025-02-18T10:00:00.000Z","cwd":"/work/my-app","gitBranch":"feature/x","message":{"role":"user","content":"deploy to staging, mention zebracorn and foo(bar"}}' \
  '{"type":"assistant","timestamp":"2025-02-18T10:00:09.000Z","message":{"role":"assistant","content":[{"type":"text","text":"Deployed."}]}}' \
  > "$P2/$S2.jsonl"
# S3: indexed, created exactly 2025-02-19 00:00:00 (no zone suffix), a backslash in its prompt
# and in its branch name (hotfix\tmp).
printf '%s\n' \
  '{"type":"user","timestamp":"2025-02-19T00:00:00","cwd":"/work/my-app","gitBranch":"main","message":{"role":"user","content":"later session"}}' \
  > "$P2/$S3.jsonl"
cat > "$P2/sessions-index.json" <<EOF
{"version":1,"entries":[
 {"sessionId":"$S2","projectPath":"/work/my-app","firstPrompt":"deploy to staging","summary":"Deployment work","gitBranch":"feature/x","created":"2025-02-18T10:00:00.000Z","modified":"2025-02-18T10:00:09.000Z","messageCount":2},
 {"sessionId":"$S3","projectPath":"/work/my-app","firstPrompt":"path C:\\\\temp later","summary":"Late work","gitBranch":"hotfix\\\\tmp","created":"2025-02-19T00:00:00","modified":"2025-02-19T00:00:00","messageCount":1}
]}
EOF
SC="$SEARCH/search-conversations.sh"
ids_are() { # <label> <comma-separated 2-char id prefixes, sorted>: OUT is the --json list
  json_is "$1" "sorted(e['sessionId'][:2] for e in d) == '$2'.split(',')"
}

run_in "$PROJ" "$SC" list
check "list exits 0 and finds all 3 conversations" 0 'Found 3 conversations'
run_in "$PROJ" "$SC" list --json --limit 2
json_is "list --json --limit 2 is a JSON array of 2" 'len(d) == 2'
run_in "$PROJ" "$SC" list --json --limit 1
json_is "list --limit 1 still limits" 'len(d) == 1'
run_in "$PROJ" "$SC" search --topic deploy --json --limit 0
json_is "search --limit 0 returns an empty list" 'd == []'
for badlimit in 'abc' '-1' '' '1.5' '0] | {pwned: env.HOME} | .['; do
  run_in "$PROJ" "$SC" list --json --limit "$badlimit"
  check "list --limit '$badlimit' exits 2 with a message" 2 "" '--limit must be a non-negative integer'
  printf '%s' "$OUT" | grep -qF "$HOME_DIR" && bad "list --limit '$badlimit' runs no jq code" "stdout holds \$HOME: $OUT" || ok "list --limit '$badlimit' runs no jq code"
  run_in "$PROJ" "$SC" search --topic deploy --json --limit "$badlimit"
  check "search --limit '$badlimit' exits 2 with a message" 2 "" '--limit must be a non-negative integer'
  printf '%s' "$OUT" | grep -qF "$HOME_DIR" && bad "search --limit '$badlimit' runs no jq code" "stdout holds \$HOME: $OUT" || ok "search --limit '$badlimit' runs no jq code"
done
run_in "$PROJ" "$SC" list --limit abc
check "list (text) --limit abc exits 2 with a message" 2 "" '--limit must be a non-negative integer'
run_in "$PROJ" "$SC" show 22222222 --json --max-messages '1, pwned: 1'
check "show --max-messages that is not a number exits 2 with a message" 2 "" '--max-messages must be a non-negative integer'
run_in "$PROJ" "$SC" list --project "my-app" --json
ids_are "list --project filters on the project path" "22,33"
run_in "$PROJ" "$SC" search --topic "catalog" --json
ids_are "search --topic finds the orphan session by its first prompt" "11"
run_in "$PROJ" "$SC" search --topic "DEPLOY" --json
ids_are "search --topic is case-insensitive" "22"
run_in "$PROJ" "$SC" search --branch "feature" --json
ids_are "search --branch matches a substring of the branch" "22"
run_in "$PROJ" "$SC" search --topic "no-such-topic-anywhere"
check "search with no match exits 0 and says so" 0 'No conversations found'
run_in "$PROJ" "$SC" search --topic "zebracorn"
check "search without --deep does not look inside the conversation" 0 'No conversations found'
run_in "$PROJ" "$SC" search --topic "zebracorn" --deep --json
ids_are "search --deep finds a word that is only in the conversation text" "22"
run_in "$PROJ" "$SC" search --topic "no-such-topic-anywhere" --deep
check "search --deep with no match exits 0 and says so" 0 'No conversations found'
run_in "$PROJ" "$SC" search --topic "zebr.corn" --deep
check "search --deep does not read a dot in the topic as a regex wildcard" 0 'No conversations found'
run_in "$PROJ" "$SC" search --topic 'C:\temp' --json
ids_are "search --topic with a backslash matches the literal text" "33"
run_in "$PROJ" "$SC" search --topic '\("deploy")' --json
check "search --topic with a jq string interpolation is plain text and matches nothing" 0 '^\[\]$'
run_in "$PROJ" "$SC" search --branch '\("feature")' --json
check "search --branch with a jq string interpolation is plain text and matches nothing" 0 '^\[\]$'
run_in "$PROJ" "$SC" search --branch 'hotfix\tmp' --json
ids_are "search --branch with a backslash matches the literal text" "33"
run_in "$PROJ" "$SC" search --after 2025-02-18 --before 2025-02-19 --json
ids_are "a one-day range includes that day and excludes the next midnight" "22"
run_in "$PROJ" "$SC" search --after 2025-02-18 --json
ids_are "search --after includes the start date" "22,33"
run_in "$PROJ" "$SC" search --after 2025-02-18T09:59:59Z --json
ids_are "search --after accepts a full ISO timestamp" "22,33"
for baddate in garbage 2025-2-18 2025-13-01 2025-02-30x ""; do
  run_in "$PROJ" "$SC" search --after "$baddate" --topic deploy --json
  check "search --after '$baddate' exits 2 with a message, not an empty list" 2 "" 'Invalid date .*YYYY-MM-DD'
done
run_in "$PROJ" "$SC" search --before 2025-02-18T10 --json
check "search --before with a partial timestamp exits 2 with a message" 2 "" 'Invalid date .*YYYY-MM-DD'
run_in "$PROJ" "$SC" list --after garbage --json
check "list --after garbage exits 2 with a message" 2 "" 'Invalid date .*YYYY-MM-DD'
run_in "$PROJ" "$SC" list --after
check "list --after with no value exits 2 with a message" 2 "" 'Invalid date'
run_in "$PROJ" "$SC" search
check "search with no criterion exits 1 with a message" 1 "" 'At least one search criterion required'
run_in "$PROJ" "$SC" search --no-such-option
check "search: unknown option exits 2 with a message" 2 "" 'Unknown option: --no-such-option'
run_in "$PROJ" "$SC" list --no-such-option
check "list: unknown option exits 2 with a message" 2 "" 'Unknown option: --no-such-option'
run_in "$PROJ" "$SC" frobnicate
check "unknown command exits 2 with a message" 2 "" 'Unknown command: frobnicate'
run_in "$PROJ" "$SC" --no-color
check "--no-color alone prints the usage and exits 0" 0 'Usage: search-conversations\.sh'
run_in "$PROJ" "$SC" --help
check "--help exits 0" 0 'Usage: search-conversations\.sh'
# show: the way search/SKILL.md calls it, by session ID prefix. --json is what the summarizer receives.
run_in "$PROJ" "$SC" show 22222222 --json --max-messages 100
json_is "show --json is the object the summarizer reads: sessionId, metadata and 2 messages" \
  'd["sessionId"] == "'"$S2"'" and d["totalExtracted"] == 2 and [m["role"] for m in d["messages"]] == ["user", "assistant"] and d["messages"][1]["content"] == "Deployed." and d["metadata"]["gitBranch"] == "feature/x" and d["metadata"]["projectPath"] == "/work/my-app" and d["metadata"]["messageCount"] == 2'
run_in "$PROJ" "$SC" show 11111111 --json
json_is "show --json on an orphan session synthesizes its metadata" 'd["metadata"]["isOrphan"] is True and d["metadata"]["projectPath"] == "/work/other" and d["totalExtracted"] == 2'
run_in "$PROJ" "$SC" show 22222222 --max-messages 1
check "show (text) prints the header and the first message only" 0 'Conversation: 22222222-bbbb'
printf '%s' "$OUT" | grep -q 'ASSISTANT' && bad "show --max-messages 1 stops after one message" "the assistant message was printed" || ok "show --max-messages 1 stops after one message"
run_in "$PROJ" "$SC" show 99999999
check "show: no such session exits 1 with a message" 1 "" 'No conversation found matching session ID: 99999999'
run_in "$PROJ" "$SC" show
check "show: no session ID exits 1 with a message" 1 "" 'session ID required'
run_in "$PROJ" "$SC" show 22222222 --bogus
check "show: unknown option exits 1 with a message" 1 "" 'Unknown option: --bogus'
run_in "$PROJ" "$SC" stats --json
json_is "stats --json counts 3 conversations and 5 messages" 'd["totalConversations"] == 3 and d["totalMessages"] == 5'
# An empty HOME has no projects dir: every mode must still exit 0.
mkdir -p "$TMP/empty-home"
RC=0; OUT="$(cd "$PROJ" && env -i PATH="$PATH" HOME="$TMP/empty-home" "$SC" list 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
check "list with no ~/.claude/projects exits 0 and says so" 0 'No conversations found'
# A malformed sessions-index.json is skipped with one warning line; the rest still works.
BAD_HOME="$TMP/bad-home"
mkdir -p "$BAD_HOME/.claude/projects/-work-broken" "$BAD_HOME/.claude/projects/-work-fine"
printf '{"version":1,"entries":[{"sessionId":' > "$BAD_HOME/.claude/projects/-work-broken/sessions-index.json"
cp "$P1/$S1.jsonl" "$BAD_HOME/.claude/projects/-work-fine/$S1.jsonl"
RC=0; OUT="$(cd "$PROJ" && env -i PATH="$PATH" HOME="$BAD_HOME" "$SC" list --json 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
check "list with a malformed sessions-index.json still exits 0 and lists the good session" 0 'sessionId' 'warning: skipping unreadable .*-work-broken/sessions-index\.json'
[[ "$(printf '%s\n' "$ERR" | grep -c 'warning: skipping unreadable')" == 1 ]] && ok "the warning for a malformed index is one line" || bad "the warning for a malformed index is one line" "stderr: $ERR"

echo "every script named in a SKILL.md exists, is executable and answers --help"
# Pull each "${CLAUDE_SKILL_DIR}/scripts/<name>" out of a SKILL.md, resolve it against that
# skill's directory in the plugin copy, and run it with --help from the project dir.
for skill in shield search; do
  names="$(python3 - "$SKILLS/$skill/SKILL.md" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
seen = []
for m in re.finditer(r'"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_.-]+\.(?:sh|py))"', text):
    if m.group(1) not in seen:
        seen.append(m.group(1))
print("\n".join(seen))
EOF
)"
  n=0
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    n=$((n + 1))
    if [[ ! -x "$SKILLS/$skill/scripts/$name" ]]; then
      bad "$skill SKILL.md names scripts/$name" "missing or not executable"
      continue
    fi
    run_in "$PROJ" "$SKILLS/$skill/scripts/$name" --help
    check "$skill SKILL.md command runs: scripts/$name --help" 0
  done <<< "$names"
  [[ "$n" -ge 1 ]] && ok "$skill SKILL.md: found $n script command(s) to run" || bad "$skill SKILL.md: found no script commands to run" "the extractor matched nothing"
done

echo "shield and search never show the substituted path tokens in prose"
# Claude Code replaces "${CLAUDE_SKILL_DIR}" and "${CLAUDE_PLUGIN_ROOT}" everywhere in a SKILL.md,
# prose and inline code included, before the model reads it. In a fenced code block the token is a
# real command for this skill's own scripts, which is what we want. Outside one the model would read
# this skill's absolute path where the text says something else. So outside fenced blocks the token
# must not appear.
for skill in shield search; do
  hits="$(python3 - "$SKILLS/$skill/SKILL.md" <<'EOF'
import re, sys
fence = None  # (char, length) of the open fence, or None
for no, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    line = re.sub(r'^\s*(>\s*)*', '', line)  # a fence may sit inside a blockquote
    m = re.match(r'(`{3,}|~{3,})', line)
    if m:
        tok = m.group(1)
        if fence is None:
            fence = (tok[0], len(tok))
            continue
        if tok[0] == fence[0] and len(tok) >= fence[1] and not line.strip()[len(tok):]:
            fence = None
            continue
    if fence is None and re.search(r'\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}', line):
        print(f"line {no}: {line.strip()[:100]}")
if fence is not None:
    print("unclosed code fence")
EOF
)"
  [[ -z "$hits" ]] && ok "$skill SKILL.md: no path token outside code blocks" \
    || bad "$skill SKILL.md: path token outside a code block (it is substituted, so the model sees an absolute path)" "$hits"
done

echo "the skills reach their agents as plugin agent types, and nothing points at ~/.claude/agents"
grep -Fq 'subagent_type: "context:content-distiller"' "$SKILLS/shield/SKILL.md" && ok "shield starts subagent_type context:content-distiller" || bad "shield starts subagent_type context:content-distiller" "line not found in shield/SKILL.md"
grep -Fq 'subagent_type: "context:conversation-summarizer"' "$SKILLS/search/SKILL.md" && ok "search starts subagent_type context:conversation-summarizer" || bad "search starts subagent_type context:conversation-summarizer" "line not found in search/SKILL.md"
grep -Eq '^Task\(' "$SKILLS/search/SKILL.md" && bad "search starts its agent with Agent(...), not the old Task(...)" "a Task( line is still there" || ok "search starts its agent with Agent(...), not the old Task(...)"
grep -Fq 'manage-manifest.sh" mark-failed' "$SKILLS/shield/SKILL.md" && ok "shield Step 3 tells the model how to record a failed source (mark-failed)" || bad "shield Step 3 tells the model how to record a failed source (mark-failed)" "no mark-failed command in shield/SKILL.md"
grep -Fq 'FAILED:' "$AGENTS/content-distiller.md" && grep -Fq 'FAILED:' "$SKILLS/shield/SKILL.md" && ok "the distiller and shield Step 3 agree on the FAILED: prefix" || bad "the distiller and shield Step 3 agree on the FAILED: prefix" "FAILED: missing from agents/content-distiller.md or shield/SKILL.md"
grep -Fq 'subagent_type: "general-purpose"' "$SKILLS/shield/SKILL.md" && bad "shield no longer starts a general-purpose agent for the distiller" "found subagent_type general-purpose" || ok "shield no longer starts a general-purpose agent for the distiller"
# (The README may say where the old loose copies lived, so it is not checked here.)
for f in "$SKILLS/shield/SKILL.md" "$SKILLS/search/SKILL.md" "$AGENTS/content-distiller.md" "$AGENTS/conversation-summarizer.md"; do
  if grep -Fq '~/.claude/agents' "$f"; then
    bad "$(basename "$(dirname "$f")")/$(basename "$f") does not mention ~/.claude/agents" "$(grep -Fn '~/.claude/agents' "$f" | head -2)"
  else
    ok "$(basename "$(dirname "$f")")/$(basename "$f") does not mention ~/.claude/agents"
  fi
done
for a in content-distiller conversation-summarizer; do
  [[ -f "$AGENTS/$a.md" ]] && ok "agents/$a.md is in the plugin" || bad "agents/$a.md is in the plugin" "missing"
  grep -Eq "^name: $a\$" "$AGENTS/$a.md" 2>/dev/null && ok "agents/$a.md keeps the bare name: $a" || bad "agents/$a.md keeps the bare name: $a" "no 'name: $a' line"
done
# Neither skill may carry an agents/ directory of its own: agents live at the plugin root.
for skill in shield search; do
  [[ ! -e "$SKILLS/$skill/agents" ]] && ok "$skill has no agents/ directory (agents live at the plugin root)" || bad "$skill has no agents/ directory" "skills/$skill/agents exists"
done

echo "the README lists every manage-manifest.sh command"
# The README's Scripts table is the only place a user sees the full command list, so a command the
# script gained or the README forgot shows up here.
run_in "$PROJ" "$SHIELD/manage-manifest.sh" --help
help_cmds="$(printf '%s\n' "$OUT" | sed -n '/^Commands:/,/^Options:/p' | grep -Eo '^  [a-z][a-z-]+' | tr -d ' ')"
readme_row="$(grep -F 'manage-manifest.sh' "$PLUGIN/README.md" | head -1)"
[[ -n "$help_cmds" && -n "$readme_row" ]] || bad "found the command list and the README row" "help: '$help_cmds' row: '$readme_row'"
for c in $help_cmds; do
  printf '%s' "$readme_row" | grep -Fq "$c" && ok "README row names manage-manifest.sh $c" || bad "README row names manage-manifest.sh $c" "row: $readme_row"
done

echo "search/SKILL.md date example names the right day"
# "last Tuesday" must be given as --after <that Tuesday> --before <the next day>.
res="$(python3 - "$SKILLS/search/SKILL.md" <<'EOF'
import datetime, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
rows = re.findall(r'last (\w+day)\?.*?--after (\d{4}-\d\d-\d\d) --before (\d{4}-\d\d-\d\d)', text)
if not rows:
    print("no weekday row found")
for name, a, b in rows:
    da = datetime.date.fromisoformat(a)
    db = datetime.date.fromisoformat(b)
    if da.strftime("%A") != name.capitalize():
        print(f"'last {name}' is given as --after {a}, which is a {da.strftime('%A')}")
    if db - da != datetime.timedelta(days=1):
        print(f"--before {b} is not the day after --after {a}")
EOF
)"
[[ -z "$res" ]] && ok "the 'last <weekday>' example uses that weekday and a one-day range" || bad "the 'last <weekday>' example uses that weekday and a one-day range" "$res"

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
