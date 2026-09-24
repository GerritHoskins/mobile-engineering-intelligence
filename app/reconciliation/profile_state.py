"""Profile consistency: copies of the same account fact compared against a
per-field authoritative source.

Where push *combines* independent signals (intent x capability x
registration), profile *compares* copies of one fact. Both run on the same
generic state_observation rows -- this domain exists to prove that schema
generalizes.
"""

import re
from typing import Any

from pydantic import BaseModel

from app.reconciliation.common import (
    ConsistencyIssue,
    RawObservation,
    UnrecognizedObservationValue,
    evidence_from,
    latest_per_key,
)

# field -> (authoritative source, copy sources in reporting order)
FIELD_AUTHORITY: dict[str, tuple[str, tuple[str, ...]]] = {
    "email": ("auth", ("backend", "job_profile")),
    "postal_code": ("backend", ("job_profile",)),
}

# Worst first: a field's status is its worst copy result.
_STATUS_RANK = {"DIVERGED": 3, "SYNC_PENDING": 2, "MISSING_IN_COPY": 1, "CONSISTENT": 0}
_INCONSISTENT_STATUSES = {"DIVERGED", "SYNC_PENDING", "MISSING_IN_COPY"}

_POSTAL_CODE = re.compile(r"\d{5}")


class ProfileEvaluation(BaseModel):
    domain: str = "profile"
    field_states: dict
    effective_state: dict
    consistency_issues: list[ConsistencyIssue]


def _normalize_email(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().casefold()
    raise UnrecognizedObservationValue(f"Unrecognized email value: {value!r}")


def _normalize_postal_code(value: Any) -> str:
    # A JSON number is rejected rather than coerced: 1067 has already lost the
    # leading zero of "01067", so there is no safe way to recover it.
    if isinstance(value, str) and _POSTAL_CODE.fullmatch(value.strip()):
        return value.strip()
    raise UnrecognizedObservationValue(f"Unrecognized postal_code value: {value!r}")


_NORMALIZERS = {"email": _normalize_email, "postal_code": _normalize_postal_code}


def normalize(observations: list[RawObservation]) -> dict[tuple[str, str], str]:
    """Load-boundary normalization: every known field is normalized (and
    unrecognized raw values raise) whether or not it ends up compared."""
    return {
        (source, key): _NORMALIZERS[key](obs.value)
        for (source, key), obs in latest_per_key(observations).items()
        if key in _NORMALIZERS
    }


def empty_field_states() -> dict:
    return {
        field: {"authority": authority, "status": "UNKNOWN"}
        for field, (authority, _) in FIELD_AUTHORITY.items()
    }


def _presence_evidence(latest: dict[tuple[str, str], RawObservation], source: str) -> RawObservation:
    """Any observation from `source`, chosen deterministically, proving the
    source is present even though the compared field is missing from it."""
    return latest[min(k for k in latest if k[0] == source)]


def evaluate_profile_state(observations: list[RawObservation]) -> ProfileEvaluation:
    normalized = normalize(observations)
    latest = latest_per_key(observations)
    present_sources = {source for source, _ in latest}

    field_states: dict = {}
    issues: list[ConsistencyIssue] = []

    for field, (authority, copies) in FIELD_AUTHORITY.items():
        authoritative = latest.get((authority, field))

        # Step 1 - no reference value: nothing to compare against, and an
        # unknown signal alone is not a reportable issue.
        if authoritative is None:
            field_states[field] = {"authority": authority, "status": "UNKNOWN"}
            continue

        # Step 2 - compare every copy independently; all issues are reported.
        copy_statuses: list[str] = []
        for copy in copies:
            # A source that never reported anything for this subject is out of
            # scope (e.g. no job profile created), not a missing field.
            if copy not in present_sources:
                continue

            copy_obs = latest.get((copy, field))
            if copy_obs is None:
                copy_statuses.append("MISSING_IN_COPY")
                issues.append(
                    ConsistencyIssue(
                        code="PROFILE_FIELD_MISSING",
                        severity="WARNING",
                        remediation="BACKEND_SYNC_NEEDED",
                        evidence=[
                            evidence_from(authoritative),
                            evidence_from(_presence_evidence(latest, copy)),
                        ],
                    )
                )
            elif normalized[(copy, field)] == normalized[(authority, field)]:
                copy_statuses.append("CONSISTENT")
            else:
                # A copy observed before the authoritative value may just not
                # have caught up yet; one observed at/after it is a real split.
                diverged = copy_obs.observed_at >= authoritative.observed_at
                copy_statuses.append("DIVERGED" if diverged else "SYNC_PENDING")
                issues.append(
                    ConsistencyIssue(
                        code="PROFILE_FIELD_DIVERGED" if diverged else "PROFILE_FIELD_SYNC_PENDING",
                        severity="ERROR" if diverged else "WARNING",
                        remediation="BACKEND_SYNC_NEEDED",
                        evidence=[evidence_from(authoritative), evidence_from(copy_obs)],
                    )
                )

        status = max(copy_statuses, key=_STATUS_RANK.__getitem__, default="CONSISTENT")
        field_states[field] = {"authority": authority, "status": status}

    # Step 3 - FALSE > UNKNOWN > TRUE, same precedence as push's deliverable.
    statuses = {state["status"] for state in field_states.values()}
    if statuses & _INCONSISTENT_STATUSES:
        consistent: bool | None = False
    elif "UNKNOWN" in statuses:
        consistent = None
    else:
        consistent = True

    return ProfileEvaluation(
        field_states=field_states,
        effective_state={"consistent": consistent},
        consistency_issues=issues,
    )
