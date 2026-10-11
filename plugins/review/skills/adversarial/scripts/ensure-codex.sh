#!/usr/bin/env bash
# ensure-codex.sh — detect Codex CLI install and login status and emit KEY=VALUE hints
# Usage: ensure-codex.sh [--check] [--help]
# Exit codes: 0=status reported (always, for --check), 2=usage error
#
# Never installs anything and never starts a Codex session. `codex login status`
# only reads the local login. CODEX_STALE compares `codex --version` with two
# optional sources: client_version in ${CODEX_HOME:-~/.codex}/models_cache.json
# and the codex bundled with the ChatGPT app (#185).

set -eu

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_BIN="/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--check] [--help]

Detect whether the Codex CLI is installed and logged in. Emits eval-safe
KEY='value' lines on stdout. Never installs anything.

Options:
  --check   (default) Emit status lines and exit 0
  --help    Show this help and exit 0

Output lines (--check):
  CODEX_INSTALLED=yes|no
  CODEX_VERSION=<x.y.z>|-
  CODEX_AUTHED=yes|no|unknown     unknown when codex is not installed
  CODEX_INSTALL_HINT=<install command>
  CODEX_AUTH_HINT=<login command>
  CODEX_STALE=yes|no|unknown      yes: a source below has a newer version
  CODEX_NEWER_BIN=<path>|-        the bundled binary, when it is newer than
                                  codex and at least as new as the cache
  CODEX_STALE_HINT=<fix>|-        an ln -sfn command (codex is a link into the
                                  standalone installer's packages/ or to the
                                  app), else which install to update or how to
                                  reorder PATH, or which version to update to

CODEX_STALE compares MAJOR.MINOR.PATCH (a prerelease suffix is ignored) of
\`codex --version\` with two sources, each optional: client_version in
\${CODEX_HOME:-~/.codex}/models_cache.json, and the codex bundled with the
ChatGPT app (\$CODEX_APP_BIN, default
$DEFAULT_APP_BIN), run with
\`--version\`, stdin closed and a 10 s limit on its whole process group. no
needs at least one source read and the app binary, when it exists, read too;
unknown means a source that exists could not be read, or codex or its version
is missing. A stale CLI makes the server refuse new models ("is not
supported when using Codex with a ChatGPT account").

CODEX_AUTHED comes from the exit code of \`codex login status\`: 0 means logged
in. That command prints to stderr, so its output is never read.

Exit codes:
  0  Status reported
  2  Unknown argument
EOF
}

for arg in "$@"; do
  case "$arg" in
    --check) ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CODEX_INSTALLED="no"
CODEX_VERSION="-"
CODEX_AUTHED="unknown"

if command -v codex >/dev/null 2>&1; then
  CODEX_INSTALLED="yes"
  raw_ver="$(codex --version 2>/dev/null </dev/null || true)"
  ver_token="$(printf '%s' "$raw_ver" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  if [ -n "$ver_token" ]; then
    CODEX_VERSION="$ver_token"
  fi
  if codex login status </dev/null >/dev/null 2>&1; then
    CODEX_AUTHED="yes"
  else
    CODEX_AUTHED="no"
  fi
fi

# ---- stale CLI check (#185) ----
# The first MAJOR.MINOR.PATCH in $1, or nothing. A prerelease suffix is dropped.
semver() {
  printf '%s' "$1" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true
}

# Exit 0 when version $1 is lower than version $2 (both MAJOR.MINOR.PATCH).
ver_lt() {
  local a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF_V
$1
EOF_V
  IFS=. read -r b1 b2 b3 <<EOF_V
$2
EOF_V
  if [ "$((10#$a1))" -ne "$((10#$b1))" ]; then [ "$((10#$a1))" -lt "$((10#$b1))" ]; return; fi
  if [ "$((10#$a2))" -ne "$((10#$b2))" ]; then [ "$((10#$a2))" -lt "$((10#$b2))" ]; return; fi
  [ "$((10#$a3))" -lt "$((10#$b3))" ]
}

CODEX_STALE="unknown"
CODEX_NEWER_BIN="-"
CODEX_STALE_HINT="-"
if [ "$CODEX_INSTALLED" = "yes" ] && [ "$CODEX_VERSION" != "-" ]; then
  sources_read=0
  newest=""
  # models_cache.json: read with python3, never eval'd. Anything but a JSON object
  # with a string client_version counts as unread.
  cache_file="${CODEX_HOME:-$HOME/.codex}/models_cache.json"
  cache_ver=""
  cache_unread=0
  if [ -f "$cache_file" ]; then
    cache_unread=1
    cache_raw="$(python3 -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
v = d.get("client_version") if isinstance(d, dict) else None
print(v if isinstance(v, str) else "")' "$cache_file" 2>/dev/null </dev/null || true)"
    cache_ver="$(semver "$cache_raw")"
  fi
  if [ -n "$cache_ver" ]; then
    cache_unread=0
    sources_read=1
    if ver_lt "$CODEX_VERSION" "$cache_ver"; then newest="$cache_ver"; fi
  fi
  # The ChatGPT-bundled codex: --version only, stdin closed, through run_bounded.py
  # with a 10 s limit (macOS has no timeout). run_bounded.py kills the whole process
  # group; perl's alarm would kill only the binary, and a child of it holding the
  # output pipe would hang this script. A non-zero exit, a timeout, no version in
  # the output or a missing run_bounded.py leaves the app unread: then the result
  # is never "no", because the one source that drives the app hint was not checked.
  app_bin="${CODEX_APP_BIN:-$DEFAULT_APP_BIN}"
  app_ver=""
  app_unread=0
  if [ -e "$app_bin" ]; then
    app_unread=1
  fi
  if [ -f "$app_bin" ] && [ -x "$app_bin" ]; then
    app_tmp="$(mktemp -d /tmp/ensure-codex.XXXXXX 2>/dev/null || true)"
    if [ -n "$app_tmp" ]; then
      : > "$app_tmp/marker"
      if python3 "$SCRIPT_DIR/run_bounded.py" 10 /dev/null "$app_tmp/out" /dev/null "$app_tmp/marker" \
           "$app_bin" --version </dev/null >/dev/null 2>&1; then
        app_ver="$(semver "$(cat "$app_tmp/out" 2>/dev/null || true)")"
      fi
      rm -rf "$app_tmp"
    fi
  fi
  if [ -n "$app_ver" ]; then
    app_unread=0
    sources_read=1
    if ver_lt "$CODEX_VERSION" "$app_ver"; then
      if [ -z "$newest" ] || ver_lt "$newest" "$app_ver"; then newest="$app_ver"; fi
      # Point at the app only when nothing is newer than it: linking an app older
      # than the cache's client_version would leave the CLI stale.
      if ! ver_lt "$app_ver" "$newest"; then CODEX_NEWER_BIN="$app_bin"; fi
    fi
  fi
  if [ -n "$newest" ]; then
    CODEX_STALE="yes"
    if [ "$CODEX_NEWER_BIN" != "-" ]; then
      codex_path="$(command -v codex)"
      # ln -sfn only over a link this tool may re-point: one into the standalone
      # installer's ${CODEX_HOME:-~/.codex}/packages/, or one to the app binary.
      # npm and Homebrew install codex as a symlink too, and re-pointing their
      # link would break the next upgrade, so any other link or file gets the
      # update-or-PATH advice.
      link_kind="$(python3 -c 'import os, sys
path, home, app = sys.argv[1:4]
if not os.path.islink(path):
    print("file")
else:
    real = os.path.realpath(path)
    packages = os.path.join(os.path.realpath(home), "packages") + os.sep
    ok = real.startswith(packages) or real == os.path.realpath(app)
    print("ours" if ok else "managed")' "$codex_path" "${CODEX_HOME:-$HOME/.codex}" "$CODEX_NEWER_BIN" \
        2>/dev/null </dev/null || true)"
      if [ "$link_kind" = "ours" ]; then
        # Single-quote each path; a ' inside it becomes '\'' (built from
        # variables, as in emit(), so bash 3.2 gets it right).
        q="'" bs='\'
        q_new="${CODEX_NEWER_BIN//$q/$q$bs$q$q}"
        q_cur="${codex_path//$q/$q$bs$q$q}"
        CODEX_STALE_HINT="Codex CLI $CODEX_VERSION is older than the ChatGPT app's $app_ver. Point codex at it: ln -sfn '$q_new' '$q_cur'"
      else
        CODEX_STALE_HINT="Codex CLI $CODEX_VERSION ($codex_path) is older than the ChatGPT app's $app_ver at '$CODEX_NEWER_BIN'. Update that install, or put '$(dirname "$CODEX_NEWER_BIN")' before '$(dirname "$codex_path")' in PATH"
      fi
    else
      CODEX_STALE_HINT="Codex CLI $CODEX_VERSION is older than $newest (client_version in $cache_file); update the Codex CLI to $newest or later"
    fi
  elif [ "$app_unread" -eq 1 ] || [ "$cache_unread" -eq 1 ]; then
    CODEX_STALE="unknown"
  elif [ "$sources_read" -eq 1 ]; then
    CODEX_STALE="no"
  fi
fi

CODEX_INSTALL_HINT="npm install -g @openai/codex"
CODEX_AUTH_HINT="Run: codex login   (then re-run the review; the skill checks 'codex login status')"

# eval-safe: KEY='value' with embedded single quotes escaped. bash 3.2's
# ${var//pattern/replacement} does not collapse a lone backslash before a
# quote in the replacement text, so build the '\'' escape from variables
# instead of a literal \'\\\'\' (which round-trips wrong under bash 3.2).
emit() {
  local q="'" bs='\'
  local v="${2//$q/$q$bs$q$q}"
  printf "%s='%s'\n" "$1" "$v"
}

emit CODEX_INSTALLED    "$CODEX_INSTALLED"
emit CODEX_VERSION      "$CODEX_VERSION"
emit CODEX_AUTHED       "$CODEX_AUTHED"
emit CODEX_INSTALL_HINT "$CODEX_INSTALL_HINT"
emit CODEX_AUTH_HINT    "$CODEX_AUTH_HINT"
emit CODEX_STALE        "$CODEX_STALE"
emit CODEX_NEWER_BIN    "$CODEX_NEWER_BIN"
emit CODEX_STALE_HINT   "$CODEX_STALE_HINT"

exit 0
