#!/usr/bin/env bash
# codex-review.sh — Codex adversarial review: --mode find | judge | counter, or --self-test.
# Usage: codex-review.sh --diff <file> --mode find|judge|counter [--findings <file>]
#                        [--prior <file>] [--id-start N] [--repo <dir>] [--out <file>]
#                        [--timeout <secs>] [--model <m>] [--strict] [--help]
#        codex-review.sh --self-test [--timeout <secs>]
# All logic is in codex_review.py so it can be unit tested; --help prints the full usage.
# Exit codes: 0=ok, 1=error, 2=usage, 3=adversary-unavailable (incl. a leaked isolation canary)
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/codex_review.py" "$@"
