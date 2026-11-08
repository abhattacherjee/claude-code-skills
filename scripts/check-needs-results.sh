#!/usr/bin/env bash
set -euo pipefail

# check-needs-results.sh — fail unless every needed job passed or was skipped (#291).
# Reads the JSON of toJSON(needs) from the RESULTS env var. Fails closed: unset,
# empty, invalid or {} input all exit non-zero.

if [[ -z "${RESULTS:-}" ]]; then
  echo "::error::RESULTS is unset or empty" >&2
  exit 1
fi
if ! printf '%s' "$RESULTS" | jq -e 'type == "object"' > /dev/null 2>&1; then
  echo "::error::RESULTS is not a JSON object" >&2
  exit 1
fi
if [[ "$(printf '%s' "$RESULTS" | jq 'length')" -eq 0 ]]; then
  echo "::error::no needed jobs in RESULTS" >&2
  exit 1
fi

printf '%s' "$RESULTS" | jq -r 'to_entries[] | "\(.key): \((.value | objects | .result) // "missing")"'
bad="$(printf '%s' "$RESULTS" | jq -r '[to_entries[] | select(((.value | objects | .result) // "missing") as $r | $r != "success" and $r != "skipped") | .key] | join(", ")')"
if [[ -n "$bad" ]]; then
  echo "::error::These jobs did not pass: $bad"
  exit 1
fi
