#!/usr/bin/env bash
set -euo pipefail

# test-discovery-guards.sh — Regression harness for the discovery scripts'
# glob/existence guards. Both scripts are covered: spec-creator's
# discover-conventions.sh and spec-review's discover-project-architecture.sh.
#
# Each script under test gets its own fixtures + assertions section below.
# `assert_eq` records a PASS/FAIL line and tracks a running failure count;
# the script exits non-zero at the end if any assertion failed.
#
# Usage:
#   ./test-discovery-guards.sh
#   DISCOVER_CONVENTIONS_SCRIPT=/tmp/pre.sh ./test-discovery-guards.sh   # point at a different script build

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISCOVER_CONVENTIONS_SCRIPT="${DISCOVER_CONVENTIONS_SCRIPT:-$REPO_ROOT/spec-creator/scripts/discover-conventions.sh}"
DISCOVER_ARCHITECTURE_SCRIPT="${DISCOVER_ARCHITECTURE_SCRIPT:-$REPO_ROOT/spec-review/scripts/discover-project-architecture.sh}"

# The harness runs under `set -euo pipefail`, so an unusable script under test
# would die with rc=127 and no summary — unhelpful for the documented
# "point this at a pre-fix build" workflow. Fail loudly instead.
for _script_var in DISCOVER_CONVENTIONS_SCRIPT DISCOVER_ARCHITECTURE_SCRIPT; do
    _script_path="${!_script_var}"
    if [[ ! -f "$_script_path" ]]; then
        echo "FATAL: $_script_var points at a nonexistent file: $_script_path" >&2
        exit 1
    fi
    if [[ ! -x "$_script_path" ]]; then
        echo "FATAL: $_script_var is not executable: $_script_path" >&2
        exit 1
    fi
done
unset _script_var _script_path

FAIL_COUNT=0

SCRATCH_DIR="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_DIR"' EXIT

assert_eq() {
    local description="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$expected], got [$actual])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_contains() {
    local description="$1" needle="$2" haystack="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$haystack] to contain [$needle])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ============================================================
# discover-conventions.sh
# ============================================================

# --- Fixture: flat story-only layout (no epic-* dirs) ---
FLAT_DIR="$SCRATCH_DIR/flat-project"
mkdir -p "$FLAT_DIR/specs"
touch "$FLAT_DIR/specs/story-1.1-alpha.md" \
      "$FLAT_DIR/specs/story-1.2-beta.md" \
      "$FLAT_DIR/specs/story-2.1-gamma.md"

FLAT_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$FLAT_DIR" --json)
FLAT_EPIC_STRUCTURE=$(echo "$FLAT_JSON" | jq -r '.epicStructure')
FLAT_EPICS=$(echo "$FLAT_JSON" | jq -c '[.epics[].epic] | map(tonumber)')

assert_eq "flat story-only layout: epicStructure == flat" "flat" "$FLAT_EPIC_STRUCTURE"
assert_eq "flat story-only layout: epics == [1,2]" "[1,2]" "$FLAT_EPICS"

# --- Fixture: epic-* subdirs (positive control) ---
EPIC_SUBDIRS_DIR="$SCRATCH_DIR/epic-subdirs-project"
mkdir -p "$EPIC_SUBDIRS_DIR/specs/epic-1" "$EPIC_SUBDIRS_DIR/specs/epic-2"

EPIC_SUBDIRS_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$EPIC_SUBDIRS_DIR" --json)
EPIC_SUBDIRS_STRUCTURE=$(echo "$EPIC_SUBDIRS_JSON" | jq -r '.epicStructure')

assert_eq "epic-* subdirs (positive control): epicStructure == epic-subdirs" "epic-subdirs" "$EPIC_SUBDIRS_STRUCTURE"

# --- Fixture: numbered subdirs, no epic-* (positive control, guards line 77) ---
NUMBERED_SUBDIRS_DIR="$SCRATCH_DIR/numbered-subdirs-project"
mkdir -p "$NUMBERED_SUBDIRS_DIR/specs/1-foo" "$NUMBERED_SUBDIRS_DIR/specs/2-bar"

NUMBERED_SUBDIRS_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$NUMBERED_SUBDIRS_DIR" --json)
NUMBERED_SUBDIRS_STRUCTURE=$(echo "$NUMBERED_SUBDIRS_JSON" | jq -r '.epicStructure')

assert_eq "numbered subdirs, no epic-* (positive control): epicStructure == numbered-subdirs" "numbered-subdirs" "$NUMBERED_SUBDIRS_STRUCTURE"

# --- Fixture: empty specs/ ---
EMPTY_DIR="$SCRATCH_DIR/empty-project"
mkdir -p "$EMPTY_DIR/specs"

EMPTY_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$EMPTY_DIR" --json)
EMPTY_STRUCTURE=$(echo "$EMPTY_JSON" | jq -r '.epicStructure')

assert_eq "empty specs/: epicStructure == flat" "flat" "$EMPTY_STRUCTURE"

# ============================================================
# discover-project-architecture.sh
# ============================================================

# --- Fixture: markdown-only scratch project (negative) ---
# Hermetic: every negative case is asserted against scratch fixtures, never
# against the live monorepo, whose real content can flip a detector at any
# time (a single committed .js file calling `app.use(cors())` would turn a
# live-repo `security empty` assertion red for reasons unrelated to guard
# logic).
MARKDOWN_ONLY_DIR="$SCRATCH_DIR/markdown-only-project"
mkdir -p "$MARKDOWN_ONLY_DIR"
cat > "$MARKDOWN_ONLY_DIR/README.md" <<'EOF'
# Markdown-only project

No package.json, no source files — just docs.
EOF

MARKDOWN_ONLY_JSON=$("$DISCOVER_ARCHITECTURE_SCRIPT" "$MARKDOWN_ONLY_DIR" --json)
MARKDOWN_ONLY_DATA_FLOW=$(echo "$MARKDOWN_ONLY_JSON" | jq -r '.dataFlow')
MARKDOWN_ONLY_I18N=$(echo "$MARKDOWN_ONLY_JSON" | jq -r '.i18n')
MARKDOWN_ONLY_SECURITY=$(echo "$MARKDOWN_ONLY_JSON" | jq -r '.security')

assert_eq "markdown-only scratch project: dataFlow empty" "" "$MARKDOWN_ONLY_DATA_FLOW"
assert_eq "markdown-only scratch project: i18n empty" "" "$MARKDOWN_ONLY_I18N"
assert_eq "markdown-only scratch project: security empty" "" "$MARKDOWN_ONLY_SECURITY"

# --- Fixture: real markers outside node_modules (positive control) ---
# Covers all 13 previously-defective guards (plus the 4 that were already
# covered) so every guard has a fixture where its pattern is genuinely
# present and must fire — a guard hardcoded to report "nothing" (e.g.
# `if false && grep …`) is indistinguishable from a correctly-empty one
# unless some fixture proves it can also report "present".
POSITIVE_DIR="$SCRATCH_DIR/positive-architecture-project"
mkdir -p "$POSITIVE_DIR/src" "$POSITIVE_DIR/src/locales"
cat > "$POSITIVE_DIR/package.json" <<'EOF'
{
  "name": "positive-architecture-project",
  "dependencies": {
    "i18next": "^23.0.0",
    "vue-i18n": "^9.0.0",
    "graphql": "^16.0.0",
    "pg": "^8.11.0"
  }
}
EOF
cat > "$POSITIVE_DIR/src/server.ts" <<'EOF'
import helmet from "helmet";
import csurf from "csurf";
import cors from "cors";
import rateLimit from "express-rate-limit";
import { EventEmitter } from "events";

const bilingual: BilingualText = { en: "Hello", es: "Hola" };

app.use(helmet());
app.use(csurf());
app.use(cors());
app.use(rateLimit({ windowMs: 900000 }));

app.get("/health", (req, res) => {
  res.send("ok");
});

async function loadRemote() {
  return fetch("https://example.com/data");
}
EOF
cat > "$POSITIVE_DIR/vite.config.ts" <<'EOF'
export default {
  server: {
    proxy: { "/api": "http://localhost:3000" }
  }
}
EOF

POSITIVE_JSON=$("$DISCOVER_ARCHITECTURE_SCRIPT" "$POSITIVE_DIR" --json)
POSITIVE_DATA_FLOW=$(echo "$POSITIVE_JSON" | jq -r '.dataFlow')
POSITIVE_I18N=$(echo "$POSITIVE_JSON" | jq -r '.i18n')
POSITIVE_SECURITY=$(echo "$POSITIVE_JSON" | jq -r '.security')

# detect_data_flow — all 6 guards
assert_contains "positive control: dataFlow contains HTTP-inter-service" "HTTP-inter-service" "$POSITIVE_DATA_FLOW"
assert_contains "positive control: dataFlow contains Dev-proxy" "Dev-proxy" "$POSITIVE_DATA_FLOW"
assert_contains "positive control: dataFlow contains Event-messaging" "Event-messaging" "$POSITIVE_DATA_FLOW"
assert_contains "positive control: dataFlow contains Database" "Database" "$POSITIVE_DATA_FLOW"
assert_contains "positive control: dataFlow contains GraphQL" "GraphQL" "$POSITIVE_DATA_FLOW"
assert_contains "positive control: dataFlow contains REST-API" "REST-API" "$POSITIVE_DATA_FLOW"

# detect_i18n — all 4 markers, including LocaleFiles (already correct, but it
# needs a positive control like every other marker)
assert_contains "positive control: i18n contains i18next" "i18next" "$POSITIVE_I18N"
assert_contains "positive control: i18n contains vue-i18n" "vue-i18n" "$POSITIVE_I18N"
assert_contains "positive control: i18n contains BilingualText" "BilingualText" "$POSITIVE_I18N"
assert_contains "positive control: i18n contains LocaleFiles" "LocaleFiles" "$POSITIVE_I18N"

# detect_security_patterns — all 4 guards
assert_contains "positive control: security contains CSRF" "CSRF" "$POSITIVE_SECURITY"
assert_contains "positive control: security contains Helmet/CSP" "Helmet/CSP" "$POSITIVE_SECURITY"
assert_contains "positive control: security contains RateLimit" "RateLimit" "$POSITIVE_SECURITY"
assert_contains "positive control: security contains CORS" "CORS" "$POSITIVE_SECURITY"

# --- Fixture: same markers, but the sole copy lives under node_modules/
# (negative control — proves the node_modules filter still works after the
# guard-logic fix; the naive fix `grep -rl … | grep -qv node_modules` must
# still exclude vendored matches) ---
NODE_MODULES_ONLY_DIR="$SCRATCH_DIR/node-modules-only-project"
mkdir -p "$NODE_MODULES_ONLY_DIR/node_modules/some-pkg/src" \
         "$NODE_MODULES_ONLY_DIR/node_modules/some-vite-pkg"
cat > "$NODE_MODULES_ONLY_DIR/node_modules/package.json" <<'EOF'
{
  "name": "some-pkg",
  "dependencies": {
    "i18next": "^23.0.0",
    "graphql": "^16.0.0"
  }
}
EOF
cat > "$NODE_MODULES_ONLY_DIR/node_modules/some-pkg/src/server.ts" <<'EOF'
import helmet from "helmet";
import csurf from "csurf";
EOF
# Published packages ship their own vite.config.* — the Dev-proxy guard must
# filter node_modules like every other guard.
cat > "$NODE_MODULES_ONLY_DIR/node_modules/some-vite-pkg/vite.config.ts" <<'EOF'
export default { server: { proxy: { "/api": "http://localhost:3000" } } }
EOF

NODE_MODULES_ONLY_JSON=$("$DISCOVER_ARCHITECTURE_SCRIPT" "$NODE_MODULES_ONLY_DIR" --json)
NODE_MODULES_ONLY_DATA_FLOW=$(echo "$NODE_MODULES_ONLY_JSON" | jq -r '.dataFlow')
NODE_MODULES_ONLY_I18N=$(echo "$NODE_MODULES_ONLY_JSON" | jq -r '.i18n')
NODE_MODULES_ONLY_SECURITY=$(echo "$NODE_MODULES_ONLY_JSON" | jq -r '.security')

assert_eq "node_modules-only project (negative control): dataFlow empty" "" "$NODE_MODULES_ONLY_DATA_FLOW"
assert_eq "node_modules-only project (negative control): i18n empty" "" "$NODE_MODULES_ONLY_I18N"
assert_eq "node_modules-only project (negative control): security empty" "" "$NODE_MODULES_ONLY_SECURITY"

# ============================================================
# plugin copies
# ============================================================

# The assertions above exercise the top-level source scripts, but the
# plugins/** copies are what actually ship to installers. A guard fix that
# never reached the plugin copy is a fix nobody receives.
for _rel in spec-review/scripts/discover-project-architecture.sh \
            spec-creator/scripts/discover-conventions.sh; do
    _skill="${_rel%%/*}"
    _plugin_copy="$REPO_ROOT/plugins/$_skill/skills/$_skill/${_rel#*/}"
    assert_eq "plugin copy in sync: $_rel" "" \
        "$(diff -q "$REPO_ROOT/$_rel" "$_plugin_copy" >/dev/null 2>&1 || echo DIFFERS)"
done

echo ""
if [[ "$FAIL_COUNT" -eq 0 ]]; then
    echo "All assertions passed."
    exit 0
else
    echo "$FAIL_COUNT assertion(s) failed."
    exit 1
fi
