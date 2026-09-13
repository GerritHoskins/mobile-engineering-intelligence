#!/usr/bin/env bash
# Deterministic curl+jq sweep over all 13 seeded A-M installations, per the
# vault's A-M table (F/G corrected to "none"). Run after `app.seed` has been
# applied and the API is serving on $BASE_URL (default localhost:8000).
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
FAILURES=0

check() {
  local case="$1" expr="$2"
  local body status
  body=$(curl -s "$BASE_URL/v1/state/installation/install-case-$case")
  if ! status=$(echo "$body" | jq -e "$expr" 2>&1); then
    echo "FAIL [$case]: $expr"
    echo "  body: $body"
    FAILURES=$((FAILURES + 1))
  else
    echo "OK   [$case]"
  fi
}

no_issues='(.consistency_issues | length) == 0'
codes() { echo "([.consistency_issues[].code] == $1)"; }

check a "(.effective_state.deliverable == true) and $no_issues"
check b "(.effective_state.deliverable == false) and $no_issues"
check c "(.effective_state.deliverable == false) and $(codes '["OS_PERMISSION_BLOCKS_PUSH"]')"
check d "(.effective_state.deliverable == false) and $(codes '["PROVIDER_REGISTRATION_MISSING"]')"
check e "(.effective_state.deliverable == false) and $(codes '["BACKEND_PROVIDER_STATE_DIVERGED"]')"
check f "(.effective_state.deliverable == null) and $no_issues"
check g "(.effective_state.deliverable == null) and $no_issues"
check h "(.effective_state.deliverable == false) and $no_issues"
check i "(.effective_state.deliverable == false) and $(codes '["PROVIDER_REGISTRATION_STALE"]')"
check j "(.effective_state.deliverable == true) and $no_issues"
check k "(.effective_state.deliverable == false) and $no_issues"
check l "(.effective_state.deliverable == false) and $(codes '["OS_PERMISSION_BLOCKS_PUSH"]')"
check m "(.effective_state.deliverable == false) and $(codes '["OS_PERMISSION_BLOCKS_PUSH", "PROVIDER_REGISTRATION_STALE"]')"

echo "---"
if [ "$FAILURES" -eq 0 ]; then
  echo "All 13 scenarios matched the vault's A-M table."
  exit 0
else
  echo "$FAILURES scenario(s) did not match."
  exit 1
fi
