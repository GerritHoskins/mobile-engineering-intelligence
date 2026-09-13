from datetime import datetime, timedelta, timezone

import pytest

from app.reconciliation.push_state import (
    RawObservation,
    UnrecognizedObservationValue,
    evaluate_push_state,
    normalize,
)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
FRESH = NOW - timedelta(days=1)
STALE = NOW - timedelta(days=45)


def obs(source: str, key: str, value, observed_at: datetime = FRESH) -> RawObservation:
    return RawObservation(source=source, key=key, value=value, observed_at=observed_at)


def backend(value, observed_at: datetime = FRESH) -> RawObservation:
    return obs("backend", "enabled", value, observed_at)


def os_permission(value, observed_at: datetime = FRESH) -> RawObservation:
    return obs("os", "permission", value, observed_at)


def braze(value, observed_at: datetime = FRESH) -> RawObservation:
    return obs("braze", "registration", value, observed_at)


# Case -> (observations, expected deliverable, expected issue codes)
SCENARIOS = {
    "A": ([backend(True), os_permission("allowed"), braze("registered")], True, []),
    "B": ([backend(False), os_permission("allowed"), braze("registered")], False, []),
    "C": ([backend(True), os_permission("denied"), braze("registered")], False, ["OS_PERMISSION_BLOCKS_PUSH"]),
    "D": ([backend(True), os_permission("allowed")], False, ["PROVIDER_REGISTRATION_MISSING"]),
    "E": (
        [backend(True), os_permission("allowed"), braze("not_registered")],
        False,
        ["BACKEND_PROVIDER_STATE_DIVERGED"],
    ),
    "F": ([backend(True), braze("registered")], None, []),
    "G": ([os_permission("allowed"), braze("registered")], None, []),
    "H": ([backend(False), os_permission("denied"), braze("registered")], False, []),
    "I": (
        [backend(True), os_permission("allowed"), braze("registered", STALE)],
        False,
        ["PROVIDER_REGISTRATION_STALE"],
    ),
    "J": ([backend(True), os_permission("allowed"), braze("registered")], True, []),
    "K": (
        [backend(False), os_permission("denied"), braze("registered", STALE)],
        False,
        [],
    ),
    "L": ([os_permission("denied"), braze("registered")], False, ["OS_PERMISSION_BLOCKS_PUSH"]),
    "M": (
        [backend(True), os_permission("denied"), braze("registered", STALE)],
        False,
        ["OS_PERMISSION_BLOCKS_PUSH", "PROVIDER_REGISTRATION_STALE"],
    ),
}


@pytest.mark.parametrize("case", sorted(SCENARIOS))
def test_scenario(case: str) -> None:
    observations, expected_deliverable, expected_codes = SCENARIOS[case]

    evaluation = evaluate_push_state(observations, now=NOW)

    assert evaluation.effective_state["deliverable"] == expected_deliverable
    assert [issue.code for issue in evaluation.consistency_issues] == expected_codes


def test_all_scenarios_covered() -> None:
    assert set(SCENARIOS) == set("ABCDEFGHIJKLM")


def test_case_k_disabled_suppresses_stale_registration() -> None:
    evaluation = evaluate_push_state(SCENARIOS["K"][0], now=NOW)
    assert evaluation.desired_state["push_enabled"] == "DISABLED"
    assert evaluation.effective_state["deliverable"] is False
    assert evaluation.consistency_issues == []


def test_case_l_known_blocker_outranks_unknown_intent() -> None:
    evaluation = evaluate_push_state(SCENARIOS["L"][0], now=NOW)
    assert evaluation.desired_state["push_enabled"] == "UNKNOWN"
    assert evaluation.effective_state["deliverable"] is False


def test_case_m_coexisting_issues_both_collected() -> None:
    evaluation = evaluate_push_state(SCENARIOS["M"][0], now=NOW)
    codes = {issue.code for issue in evaluation.consistency_issues}
    assert codes == {"OS_PERMISSION_BLOCKS_PUSH", "PROVIDER_REGISTRATION_STALE"}


def test_cases_f_and_g_preserve_unknown_without_issues() -> None:
    for case in ("F", "G"):
        evaluation = evaluate_push_state(SCENARIOS[case][0], now=NOW)
        assert evaluation.effective_state["deliverable"] is None
        assert evaluation.consistency_issues == []


@pytest.mark.parametrize("case", sorted(SCENARIOS))
def test_every_finding_has_complete_fields(case: str) -> None:
    evaluation = evaluate_push_state(SCENARIOS[case][0], now=NOW)
    for issue in evaluation.consistency_issues:
        assert issue.code
        assert issue.severity
        assert issue.remediation
        assert len(issue.evidence) > 0


def test_dedup_uses_only_the_newest_observation_per_key() -> None:
    older = backend(True, NOW - timedelta(days=2))
    newer = backend(False, NOW - timedelta(days=1))

    evaluation = evaluate_push_state(
        [older, newer, os_permission("allowed"), braze("registered")], now=NOW
    )

    # Newer row (False / DISABLED) must win over the older (True / ENABLED) row.
    assert evaluation.desired_state["push_enabled"] == "DISABLED"
    assert evaluation.effective_state["deliverable"] is False


def test_normalize_rejects_unrecognized_raw_token() -> None:
    with pytest.raises(UnrecognizedObservationValue):
        normalize([backend("maybe")], now=NOW)
