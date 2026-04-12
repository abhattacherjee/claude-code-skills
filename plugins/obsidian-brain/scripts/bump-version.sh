#!/bin/bash
# bump-version.sh — Semantic versioning (targets .claude-plugin/plugin.json)
# Usage: ./scripts/bump-version.sh <major|minor|patch|X.Y.Z>
#
# Installed by /harden-repo
# Version file targets customized during installation.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

print_info()    { echo -e "${BLUE}info${NC} $1"; }
print_success() { echo -e "${GREEN}success${NC} $1"; }
print_warning() { echo -e "${YELLOW}warning${NC} $1"; }
print_error()   { echo -e "${RED}error${NC} $1"; }

show_usage() {
  echo "Usage: $0 <major|minor|patch|X.Y.Z>"
  echo ""
  echo "  major    Bump major version (1.0.0 -> 2.0.0)"
  echo "  minor    Bump minor version (1.0.0 -> 1.1.0)"
  echo "  patch    Bump patch version (1.0.0 -> 1.0.1)"
  echo "  X.Y.Z    Set specific version"
}

TYPE=$1
if [[ -z "$TYPE" ]]; then
  print_error "Missing version type"
  show_usage
  exit 1
fi

# ══════════════════════════════════════════════════════════════
# VERSION FILES — customized by /harden-repo during installation
# ══════════════════════════════════════════════════════════════

VERSION_SOURCE="$PROJECT_ROOT/.claude-plugin/plugin.json"

# ── Read current version ──────────────────────────────────────

read_version() {
  local file="$1"
  case "$file" in
    *.json)
      python3 -c "import json; print(json.load(open('$file'))['version'])" 2>/dev/null || \
      node -e "console.log(require('$file').version)" 2>/dev/null
      ;;
    *pyproject.toml)
      grep -m1 '^version\s*=' "$file" | sed 's/.*"\(.*\)".*/\1/'
      ;;
    *Cargo.toml)
      awk '/^\[package\]/,/^\[/' "$file" | grep -m1 '^version\s*=' | sed 's/.*"\(.*\)".*/\1/'
      ;;
    *version.txt)
      tr -d '[:space:]' < "$file"
      ;;
  esac
}

CURRENT_VERSION=$(read_version "$VERSION_SOURCE")
if [[ -z "$CURRENT_VERSION" ]]; then
  print_error "Could not read version from $VERSION_SOURCE"
  exit 1
fi
print_info "Current version: $CURRENT_VERSION"

# ── Calculate new version ─────────────────────────────────────

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$TYPE" in
  major) NEW_VERSION="$((MAJOR + 1)).0.0" ;;
  minor) NEW_VERSION="$MAJOR.$((MINOR + 1)).0" ;;
  patch) NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))" ;;
  *)
    if [[ ! "$TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      print_error "Invalid version format: $TYPE (expected X.Y.Z)"
      exit 1
    fi
    NEW_VERSION="$TYPE"
    ;;
esac

print_info "New version: $NEW_VERSION"

# ── Update version files ─────────────────────────────────────

update_version() {
  local file="$1"
  local version="$2"

  if [[ ! -f "$file" ]]; then
    print_warning "Skipping $file (not found)"
    return
  fi

  case "$file" in
    *.json)
      if command -v python3 &>/dev/null; then
        python3 -c "
import json, pathlib
p = pathlib.Path('$file')
d = json.loads(p.read_text())
d['version'] = '$version'
p.write_text(json.dumps(d, indent=2) + '\n')
"
      elif command -v node &>/dev/null; then
        node -e "
          const fs = require('fs');
          const pkg = JSON.parse(fs.readFileSync('$file', 'utf-8'));
          pkg.version = '$version';
          fs.writeFileSync('$file', JSON.stringify(pkg, null, 2) + '\n');
        "
      else
        print_error "Need python3 or node to update JSON files"
        exit 1
      fi
      ;;
    *pyproject.toml)
      sed -i.bak "s/^version\s*=\s*\".*\"/version = \"$version\"/" "$file" && rm -f "${file}.bak"
      ;;
    *Cargo.toml)
      python3 -c "
import re, pathlib
p = pathlib.Path('$file')
content = p.read_text()
content = re.sub(
    r'(^\[package\].*?^version\s*=\s*)\"[^\"]+\"',
    r'\g<1>\"$version\"',
    content, count=1, flags=re.MULTILINE | re.DOTALL
)
p.write_text(content)
"
      ;;
    *version.txt)
      echo "$version" > "$file"
      ;;
  esac

  print_success "Updated $(basename "$file") to $version"
}

# ── Pre-bump marketplace validation (all-or-nothing guard) ──
# CRITICAL: validate marketplace.json has a matching entry BEFORE we
# write the new version into plugin.json. Otherwise a marketplace sync
# failure leaves plugin.json bumped but marketplace.json stale —
# reintroducing the exact drift this PR exists to prevent (Copilot
# iter-5 finding on PR #14). Read-only at this point; the actual
# write happens after plugin.json is updated.
MARKETPLACE_JSON="$PROJECT_ROOT/.claude-plugin/marketplace.json"
PLUGIN_JSON="$PROJECT_ROOT/.claude-plugin/plugin.json"
PLUGIN_NAME=""
if [[ -f "$MARKETPLACE_JSON" ]]; then
  # python-then-node fallback for the name extraction (stays in sync
  # with read_version()'s pattern). Each branch `|| true` so a failing
  # read leaves PLUGIN_NAME empty and falls through, with a final guard
  # printing a clear remediation if neither succeeds.
  if command -v python3 &>/dev/null; then
    PLUGIN_NAME=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
name = d.get('name')
if not name:
    sys.exit(1)
print(name)
" "$PLUGIN_JSON" 2>/dev/null || true)
  fi
  if [[ -z "$PLUGIN_NAME" ]] && command -v node &>/dev/null; then
    PLUGIN_NAME=$(node -e "
const d = require(process.argv[1]);
if (!d.name) process.exit(1);
console.log(d.name);
" "$PLUGIN_JSON" 2>/dev/null || true)
  fi
  if [[ -z "$PLUGIN_NAME" ]]; then
    print_error "Could not read plugin name from $PLUGIN_JSON (need python3 or node, and a valid 'name' field)"
    exit 1
  fi

  # Read-only verification that the entry exists. Same logic as the
  # write helper below but with no mutation. Aborts the bump if missing.
  if command -v python3 &>/dev/null; then
    if ! python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
plugins = data.get('plugins')
if not isinstance(plugins, list) or not plugins:
    sys.stderr.write(f'ERROR: {sys.argv[1]} has no plugins array\n')
    sys.exit(2)
matches = [p for p in plugins if p.get('name') == sys.argv[2]]
if not matches:
    sys.stderr.write(
        f\"ERROR: marketplace.json has no entry for plugin '{sys.argv[2]}'. \"
        f'Add an entry before releasing.\n'
    )
    sys.exit(1)
" "$MARKETPLACE_JSON" "$PLUGIN_NAME"; then
      print_error "Pre-bump marketplace validation failed — aborting before plugin.json is touched"
      exit 1
    fi
  elif command -v node &>/dev/null; then
    if ! node -e "
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(process.argv[1], 'utf-8'));
if (!Array.isArray(data.plugins) || data.plugins.length === 0) {
  process.stderr.write('ERROR: marketplace.json has no plugins array\n');
  process.exit(2);
}
const matches = data.plugins.filter((p) => p && p.name === process.argv[2]);
if (matches.length === 0) {
  process.stderr.write(\`ERROR: marketplace.json has no entry for plugin '\${process.argv[2]}'. Add an entry before releasing.\n\`);
  process.exit(1);
}
" "$MARKETPLACE_JSON" "$PLUGIN_NAME"; then
      print_error "Pre-bump marketplace validation failed — aborting before plugin.json is touched"
      exit 1
    fi
  fi
fi

update_version "$PROJECT_ROOT/.claude-plugin/plugin.json" "$NEW_VERSION"

# Now perform the actual marketplace.json write. By this point we already
# verified above that the entry exists, so the only failure modes left
# are I/O errors (disk full, permissions) which are vanishingly rare and
# would also affect the plugin.json write that just succeeded.
if [[ -f "$MARKETPLACE_JSON" ]]; then

  SYNC_EXIT=0
  if command -v python3 &>/dev/null; then
    python3 - "$MARKETPLACE_JSON" "$NEW_VERSION" "$PLUGIN_NAME" <<'PY' || SYNC_EXIT=$?
import json, os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
new_version = sys.argv[2]
plugin_name = sys.argv[3]

try:
    data = json.loads(path.read_text())
except Exception as e:
    sys.stderr.write(f"ERROR: could not parse {path}: {e}\n")
    sys.exit(2)

plugins = data.get("plugins")
if not isinstance(plugins, list) or not plugins:
    sys.stderr.write(f"ERROR: {path} has no 'plugins' array\n")
    sys.exit(2)

matches = [p for p in plugins if p.get("name") == plugin_name]
if not matches:
    sys.stderr.write(
        f"ERROR: marketplace.json has no entry for plugin '{plugin_name}'. "
        f"Add an entry before releasing, or the marketplace listing will "
        f"lie about the version.\n"
    )
    sys.exit(1)

changed = 0
for plugin in matches:
    if plugin.get("version") != new_version:
        plugin["version"] = new_version
        changed += 1

if changed:
    # Atomic write: temp file in same dir + os.replace. Mirrors the
    # write_vault_note() convention in hooks/obsidian_utils.py so a
    # SIGINT or disk-full mid-write cannot corrupt the registry pointer.
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    print(f"marketplace.json: updated {changed} entry for '{plugin_name}' to {new_version}")
    # Exit code 0 = updated, exit code 10 = already in sync. Bash caller
    # uses this to print a sync confirmation only when work was done.
    sys.exit(0)
else:
    print(f"marketplace.json: '{plugin_name}' already at {new_version}")
    sys.exit(10)
PY
  else
    node - "$MARKETPLACE_JSON" "$NEW_VERSION" "$PLUGIN_NAME" <<'JS' || SYNC_EXIT=$?
const fs = require('fs');
const [, , marketPath, newVersion, pluginName] = process.argv;

let data;
try {
  data = JSON.parse(fs.readFileSync(marketPath, 'utf-8'));
} catch (e) {
  process.stderr.write(`ERROR: could not parse ${marketPath}: ${e.message}\n`);
  process.exit(2);
}

if (!Array.isArray(data.plugins) || data.plugins.length === 0) {
  process.stderr.write(`ERROR: ${marketPath} has no 'plugins' array\n`);
  process.exit(2);
}

const matches = data.plugins.filter((p) => p && p.name === pluginName);
if (matches.length === 0) {
  process.stderr.write(
    `ERROR: marketplace.json has no entry for plugin '${pluginName}'. ` +
      `Add an entry before releasing, or the marketplace listing will lie ` +
      `about the version.\n`,
  );
  process.exit(1);
}

let changed = 0;
for (const p of matches) {
  if (p.version !== newVersion) {
    p.version = newVersion;
    changed += 1;
  }
}

if (changed > 0) {
  // Atomic write: tempfile in same dir + rename, mirroring the python branch.
  const tmp = `${marketPath}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n');
    fs.renameSync(tmp, marketPath);
  } catch (e) {
    try { fs.unlinkSync(tmp); } catch (_) {}
    throw e;
  }
  console.log(`marketplace.json: updated ${changed} entry for '${pluginName}' to ${newVersion}`);
  process.exit(0);
} else {
  console.log(`marketplace.json: '${pluginName}' already at ${newVersion}`);
  process.exit(10);
}
JS
  fi

  case "$SYNC_EXIT" in
    0)
      print_success "Synced marketplace.json entry for $PLUGIN_NAME to $NEW_VERSION"
      ;;
    10)
      # Already in sync — Python/Node already printed an informational
      # line; do not also print a misleading "Synced" success message
      # (Copilot iter-2 finding on PR #14).
      ;;
    *)
      # All-or-nothing rollback: marketplace sync failed AFTER plugin.json
      # was already updated. Restore plugin.json to CURRENT_VERSION so
      # the working tree is not left in a drifted state. The pre-bump
      # validation (above) catches the common "missing entry" case before
      # plugin.json is touched, but a runtime write failure (read-only
      # file, disk full, permissions change between validation and write)
      # can only be handled here (Copilot iter-6 finding on PR #14).
      print_warning "marketplace.json sync failed AFTER plugin.json was updated — rolling plugin.json back to $CURRENT_VERSION"
      if update_version "$PROJECT_ROOT/.claude-plugin/plugin.json" "$CURRENT_VERSION"; then
        print_info "plugin.json restored to $CURRENT_VERSION — working tree is consistent"
      else
        print_error "ROLLBACK FAILED: plugin.json is at $NEW_VERSION but marketplace.json is at $CURRENT_VERSION."
        print_error "Manually restore plugin.json to $CURRENT_VERSION before committing."
      fi
      print_error "Failed to sync marketplace.json — fix the underlying issue and re-run"
      exit 1
      ;;
  esac
fi

echo ""
print_success "Version bumped from $CURRENT_VERSION to $NEW_VERSION"
echo ""
print_info "Next steps:"
echo "  1. Update CHANGELOG.md with release notes"
echo "  2. Stage version files + CHANGELOG.md"
echo "  3. git commit -m \"chore(release): bump version to $NEW_VERSION\""
