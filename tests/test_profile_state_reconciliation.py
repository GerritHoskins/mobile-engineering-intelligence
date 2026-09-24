from datetime import datetime, timedelta, timezone

import pytest

from app.reconciliation.profile_state import evaluate_profile_state, normalize
from app.reconciliation.common import RawObservation, UnrecognizedObservationValue

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
# Authoritative values are observed at AUTHORITY_AT; copies are either observed
# after it (a disagreement is a real split) or before it (may still be syncing).
BEFORE = NOW - timedelta(days=3)
AUTHORITY_AT = NOW - timedelta(days=2)
AFTER = NOW - timedelta(days=1)

EMAIL = "anna@example.de"
OTHER_EMAIL = "anna.old@example.de"
POSTAL = "01067"
OTHER_POSTAL = "10115"


def obs(source: str, key: str, value, observed_at: datetime) -> RawObservation:
    return RawObservation(source=source, key=key, value=value, observed_at=observed_at)


def auth_email(value=EMAIL, observed_at: datetime = AUTHORITY_AT) -> RawObservation:
    return obs("auth", "email", value, observed_at)


def backend(key: str, value, observed_at: datetime) -> RawObservation:
    return obs("backend", key, value, observed_at)


def job_profile(key: str, value, observed_at: datetime = AFTER) -> RawObservation:
    return obs("job_profile", key, value, observed_at)


def consistent_account() -> list[RawObservation]:
    return [
        auth_email(),
        backend("email", EMAIL, AFTER),
        backend("postal_code", POSTAL, AUTHORITY_AT),
        job_profile("email", EMAIL),
        job_profile("postal_code", POSTAL),
    ]


# Case -> (observations, expected field statuses (email, postal_code), consistent, issue codes)
SCENARIOS = {
    "P1": (consistent_account(), ("CONSISTENT", "CONSISTENT"), True, []),
    "P2": (
        [
            auth_email("Anna@Example.DE"),
            backend("email", "  anna@example.de ", AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", "ANNA@example.de"),
            job_profile("postal_code", f" {POSTAL}"),
        ],
        ("CONSISTENT", "CONSISTENT"),
        True,
        [],
    ),
    "P3": (
        [
            auth_email(),
            backend("email", EMAIL, AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", OTHER_EMAIL),
            job_profile("postal_code", POSTAL),
        ],
        ("DIVERGED", "CONSISTENT"),
        False,
        ["PROFILE_FIELD_DIVERGED"],
    ),
    "P4": (
        [
            auth_email(),
            backend("email", OTHER_EMAIL, BEFORE),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", EMAIL),
            job_profile("postal_code", POSTAL),
        ],
        ("SYNC_PENDING", "CONSISTENT"),
        False,
        ["PROFILE_FIELD_SYNC_PENDING"],
    ),
    "P5": (
        [auth_email(), backend("email", EMAIL, AFTER), backend("postal_code", POSTAL, AUTHORITY_AT)],
        ("CONSISTENT", "CONSISTENT"),
        True,
        [],
    ),
    "P6": (
        [
            auth_email(),
            backend("email", EMAIL, AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", EMAIL),
        ],
        ("CONSISTENT", "MISSING_IN_COPY"),
        False,
        ["PROFILE_FIELD_MISSING"],
    ),
    "P7": (
        [
            backend("email", EMAIL, AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", OTHER_EMAIL),
            job_profile("postal_code", POSTAL),
        ],
        ("UNKNOWN", "CONSISTENT"),
        None,
        [],
    ),
    "P8": (
        [
            backend("email", EMAIL, AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", EMAIL),
            job_profile("postal_code", OTHER_POSTAL),
        ],
        ("UNKNOWN", "DIVERGED"),
        False,
        ["PROFILE_FIELD_DIVERGED"],
    ),
    "P9": (
        [
            auth_email(),
            backend("email", EMAIL, AFTER),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", OTHER_EMAIL),
        ],
        ("DIVERGED", "MISSING_IN_COPY"),
        False,
        ["PROFILE_FIELD_DIVERGED", "PROFILE_FIELD_MISSING"],
    ),
    "P10": (
        [
            auth_email(),
            backend("email", OTHER_EMAIL, BEFORE),
            backend("postal_code", POSTAL, AUTHORITY_AT),
            job_profile("email", "anna.new@example.de"),
            job_profile("postal_code", POSTAL),
        ],
        ("DIVERGED", "CONSISTENT"),
        False,
        ["PROFILE_FIELD_SYNC_PENDING", "PROFILE_FIELD_DIVERGED"],
    ),
}


@pytest.mark.parametrize("case", sorted(SCENARIOS))
def test_scenario(case: str) -> None:
    observations, (email_status, postal_status), expected_consistent, expected_codes = SCENARIOS[case]

    evaluation = evaluate_profile_state(observations)

    assert evaluation.field_states["email"] == {"authority": "auth", "status": email_status}
    assert evaluation.field_states["postal_code"] == {"authority": "backend", "status": postal_status}
    assert evaluation.effective_state["consistent"] is expected_consistent
    assert [issue.code for issue in evaluation.consistency_issues] == expected_codes


def test_all_scenarios_covered() -> None:
    assert set(SCENARIOS) == {f"P{n}" for n in range(1, 11)}


def test_p2_representation_difference_is_not_a_contradiction() -> None:
    evaluation = evaluate_profile_state(SCENARIOS["P2"][0])
    assert evaluation.consistency_issues == []


def test_p5_absent_source_is_out_of_scope_not_missing() -> None:
    evaluation = evaluate_profile_state(SCENARIOS["P5"][0])
    assert "MISSING_IN_COPY" not in {s["status"] for s in evaluation.field_states.values()}


def test_p8_known_divergence_outranks_unknown_field() -> None:
    evaluation = evaluate_profile_state(SCENARIOS["P8"][0])
    assert evaluation.field_states["email"]["status"] == "UNKNOWN"
    assert evaluation.effective_state["consistent"] is False


def test_p10_worst_status_wins_but_every_issue_is_reported() -> None:
    evaluation = evaluate_profile_state(SCENARIOS["P10"][0])
    assert evaluation.field_states["email"]["status"] == "DIVERGED"
    by_code = {issue.code: issue for issue in evaluation.consistency_issues}
    assert by_code["PROFILE_FIELD_SYNC_PENDING"].severity == "WARNING"
    assert by_code["PROFILE_FIELD_DIVERGED"].severity == "ERROR"
    assert {e.source for e in by_code["PROFILE_FIELD_SYNC_PENDING"].evidence} == {"auth", "backend"}
    assert {e.source for e in by_code["PROFILE_FIELD_DIVERGED"].evidence} == {"auth", "job_profile"}


@pytest.mark.parametrize("case", sorted(SCENARIOS))
def test_every_finding_has_complete_fields(case: str) -> None:
    evaluation = evaluate_profile_state(SCENARIOS[case][0])
    for issue in evaluation.consistency_issues:
        assert issue.code
        assert issue.severity
        assert issue.remediation
        assert len(issue.evidence) > 0


def test_missing_in_copy_evidence_proves_copy_source_is_present() -> None:
    evaluation = evaluate_profile_state(SCENARIOS["P6"][0])
    (issue,) = evaluation.consistency_issues
    assert [e.source for e in issue.evidence] == ["backend", "job_profile"]


def test_dedup_newer_copy_row_resolves_older_divergence() -> None:
    observations = consistent_account() + [
        job_profile("email", OTHER_EMAIL, AUTHORITY_AT - timedelta(hours=1))
    ]
    evaluation = evaluate_profile_state(observations)
    assert evaluation.effective_state["consistent"] is True
    assert evaluation.consistency_issues == []


def test_normalize_rejects_numeric_postal_code() -> None:
    with pytest.raises(UnrecognizedObservationValue):
        normalize([backend("postal_code", 1067, AUTHORITY_AT)])


def test_normalize_rejects_malformed_email() -> None:
    with pytest.raises(UnrecognizedObservationValue):
        normalize([auth_email("   ")])
