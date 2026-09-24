#!/usr/bin/env bash
# Deterministic curl+jq sweep over all 13 seeded A-M installations, per the
# vault's A-M table (F/G corrected to "none"), plus the 10 P1-P10 profile accounts. Run after `app.seed` has been
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

# Profile domain (account-scoped): P1-P10 from the second-domain plan.
check_profile() {
  local case="$1" expr="$2"
  local body
  body=$(curl -s "$BASE_URL/v1/state/account/account-case-$case?domain=profile")
  if ! echo "$body" | jq -e "$expr" >/dev/null 2>&1; then
    echo "FAIL [$case]: $expr"
    echo "  body: $body"
    FAILURES=$((FAILURES + 1))
  else
    echo "OK   [$case]"
  fi
}

fields() { echo "(.field_states.email.status == \"$1\") and (.field_states.postal_code.status == \"$2\")"; }

check_profile p1  "$(fields CONSISTENT CONSISTENT) and (.effective_state.consistent == true) and $no_issues"
check_profile p2  "$(fields CONSISTENT CONSISTENT) and (.effective_state.consistent == true) and $no_issues"
check_profile p3  "$(fields DIVERGED CONSISTENT) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_DIVERGED"]')"
check_profile p4  "$(fields SYNC_PENDING CONSISTENT) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_SYNC_PENDING"]')"
check_profile p5  "$(fields CONSISTENT CONSISTENT) and (.effective_state.consistent == true) and $no_issues"
check_profile p6  "$(fields CONSISTENT MISSING_IN_COPY) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_MISSING"]')"
check_profile p7  "$(fields UNKNOWN CONSISTENT) and (.effective_state.consistent == null) and $no_issues"
check_profile p8  "$(fields UNKNOWN DIVERGED) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_DIVERGED"]')"
check_profile p9  "$(fields DIVERGED MISSING_IN_COPY) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_DIVERGED", "PROFILE_FIELD_MISSING"]')"
check_profile p10 "$(fields DIVERGED CONSISTENT) and (.effective_state.consistent == false) and $(codes '["PROFILE_FIELD_SYNC_PENDING", "PROFILE_FIELD_DIVERGED"]')"

echo "---"
if [ "$FAILURES" -eq 0 ]; then
  echo "All 13 push scenarios (A-M) and 10 profile scenarios (P1-P10) matched."
  exit 0
else
  echo "$FAILURES scenario(s) did not match."
  exit 1
fi
