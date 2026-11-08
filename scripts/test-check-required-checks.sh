#!/usr/bin/env bash
set -euo pipefail

# test-check-required-checks.sh — workflow guard fixtures (#291).
# Usage: bash scripts/test-check-required-checks.sh (CHECKER=<path> overrides)
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKER="${CHECKER:-$REPO_ROOT/scripts/check-required-checks.py}"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

[[ -f "$CHECKER" ]] || { echo "FATAL: check-required-checks.py not found at $CHECKER" >&2; exit 1; }

base() {
  cat > "$TMP/workflow.yml" <<'YAML'
name: Validate
on:
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo build

  # This comment is not a job.
  test: # Tests count as one job, regardless of matrix size.
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.9', '3.12']
    steps:
      - run: echo test
YAML
}

# fixture <needs text> [<if text>]: complete workflow, preserving literal newlines.
fixture() {
  base
  printf '%s\n' '  required-checks:' "$1" "${2-    if: always()}" >> "$TMP/workflow.yml"
  cat >> "$TMP/workflow.yml" <<'YAML'
    runs-on: ubuntu-latest
    steps:
      - run: echo complete
YAML
}

run() {
  python3 "$CHECKER" "$@" > "$TMP/stdout" 2> "$TMP/stderr" && RC=0 || RC=$?
  OUT="$(cat "$TMP/stdout")"
  ERR="$(cat "$TMP/stderr")"
}
clean() {
  [[ $RC -eq 0 && "$OUT" == 'required-checks: needs covers all 2 jobs' && -z "$ERR" ]] \
    && ok "$1" || bad "$1" "rc=$RC stdout=$OUT stderr=$ERR"
}
reported() {
  local label="$1" t; shift
  [[ $RC -eq 1 && -z "$OUT" ]] || { bad "$label" "rc=$RC stdout=$OUT stderr=$ERR"; return 0; }
  for t in "$@"; do
    [[ "$ERR" == *"$t"* ]] || { bad "$label" "stderr lacks [$t]: $ERR"; return 0; }
  done
  ok "$label"
}

fixture '    needs: [build, test]'; run "$TMP/workflow.yml"
clean 'complete flow list; nested keys are not jobs'

fixture '    needs:
      - build
      - test'; run "$TMP/workflow.yml"
clean 'complete block list'

fixture '    needs: [build,
      test]'; run "$TMP/workflow.yml"
clean 'flow list spanning two lines'

fixture '    needs: [
      build,
      test
    ]'; run "$TMP/workflow.yml"
clean 'flow list with closing bracket at four spaces'

fixture '    needs: [build]'; run "$TMP/workflow.yml"
reported 'missing job' 'missing from needs: test'

fixture '    needs: [build, test, typo]'; run "$TMP/workflow.yml"
reported 'unknown job' 'unknown job in needs: typo'

base; run "$TMP/workflow.yml"
reported 'no required-checks job' 'no required-checks job'

fixture '    needs: [build, test]' ''; run "$TMP/workflow.yml"
reported 'missing always condition' 'no if: always()'

fixture '    needs: [build, test]' '    if: ${{ always() }}'; run "$TMP/workflow.yml"
clean 'always expression'

fixture "    needs: ['build', \"test\"] # dependencies" "    if: '\${{ always() }}'"; run "$TMP/workflow.yml"
clean 'quoted values, matrix job and comments between jobs'

fixture '    needs: [build, test, required-checks]'; run "$TMP/workflow.yml"
reported 'self dependency' 'required-checks lists itself in needs'

fixture '    needs: [build, test, build]'; run "$TMP/workflow.yml"
reported 'duplicate dependency' 'duplicate id in needs: build'

fixture ''; run "$TMP/workflow.yml"
reported 'no needs' 'no needs in required-checks' 'missing from needs: build' 'missing from needs: test'

fixture '    needs: []'; run "$TMP/workflow.yml"
reported 'empty needs' 'empty needs in required-checks'

fixture '    needs: [build, test]' '    if: success()'; run "$TMP/workflow.yml"
reported 'wrong condition' 'no if: always()'

# Job declarations the guard cannot read must fail closed (X-001).
fixture '    needs: [build, test]'
sed 's/^  build:$/  "build":/' "$TMP/workflow.yml" > "$TMP/w2.yml"; run "$TMP/w2.yml"
reported 'quoted job id' 'unrecognized job declaration: "build":'

fixture '    needs: [build, test]'
printf '%s\n' '  extra: {runs-on: ubuntu-latest}' > "$TMP/inline"
sed '/^  test:/r '"$TMP/inline" "$TMP/workflow.yml" > "$TMP/w2.yml"; run "$TMP/w2.yml"
reported 'inline mapping job' 'unrecognized job declaration: extra: {runs-on: ubuntu-latest}'

fixture '    needs: [build, test]'
sed 's/^  build:$/ build:/' "$TMP/workflow.yml" > "$TMP/w2.yml"; run "$TMP/w2.yml"
reported 'one-space job indent' 'unrecognized job declaration: build:'

fixture '    needs: [build, test]'
sed 's/^  build:$/   build:/' "$TMP/workflow.yml" > "$TMP/w2.yml"; run "$TMP/w2.yml"
reported 'three-space job indent' 'unrecognized job declaration: build:'

# Trailing comments on block list items are stripped (C-003).
fixture '    needs:
      - build
      - test # the tests'; run "$TMP/workflow.yml"
clean 'block list item with trailing comment'

# Valid YAML forms (C-005).
fixture '    needs:
    - build
    - test'; run "$TMP/workflow.yml"
clean 'block list at the key indent'

printf '%s\n' 'name: Validate' 'jobs:' '  build:' '    runs-on: ubuntu-latest' \
  '  required-checks:' '    needs: build' '    if: always()' '    runs-on: ubuntu-latest' > "$TMP/workflow.yml"
run "$TMP/workflow.yml"
[[ $RC -eq 0 && "$OUT" == 'required-checks: needs covers all 1 jobs' && -z "$ERR" ]] \
  && ok 'scalar needs with one job' || bad 'scalar needs with one job' "rc=$RC stdout=$OUT stderr=$ERR"

fixture '    needs: build'; run "$TMP/workflow.yml"
reported 'scalar needs missing the other job' 'missing from needs: test'

fixture '    needs: [build, test'; run "$TMP/workflow.yml"
reported 'unclosed flow list' 'invalid needs: unclosed flow list'

fixture '    needs: {build: x}'; run "$TMP/workflow.yml"
reported 'invalid needs value' 'invalid needs'

cat > "$TMP/workflow.yml" <<'YAML'
name: Validate
on:
  pull_request:
YAML
run "$TMP/workflow.yml"
reported 'no jobs section' 'no jobs: section'

run "$TMP/missing.yml"
[[ $RC -eq 2 && "$ERR" == *"missing.yml"* && -z "$OUT" ]] \
  && ok 'missing file' || bad 'missing file' "rc=$RC stdout=$OUT stderr=$ERR"

run
[[ $RC -eq 2 && "$ERR" == *'Usage:'* && -z "$OUT" ]] \
  && ok 'no arguments' || bad 'no arguments' "rc=$RC stdout=$OUT stderr=$ERR"

# The real workflow must pass: this is the same command the required-checks job runs.
run "$REPO_ROOT/.github/workflows/validate-skill.yml"
[[ $RC -eq 0 && "$OUT" == 'required-checks: needs covers all '*' jobs' && -z "$ERR" ]] \
  && ok 'real workflow' || bad 'real workflow' "rc=$RC stdout=$OUT stderr=$ERR"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
