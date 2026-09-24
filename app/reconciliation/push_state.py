from datetime import datetime
from typing import Any

from pydantic import BaseModel

# Shared types live in common.py; re-exported here so existing imports keep working.
from app.reconciliation.common import (
    ConsistencyIssue,
    Evidence,
    RawObservation,
    UnrecognizedObservationValue,
    evidence_for as _evidence_for,
    latest_per_key,
)

__all__ = [
    "ConsistencyIssue",
    "Evidence",
    "PushEvaluation",
    "RawObservation",
    "UnrecognizedObservationValue",
    "evaluate_push_state",
    "normalize",
]

DESIRED_VALUES = {"ENABLED", "DISABLED", "UNKNOWN"}
CAPABILITY_VALUES = {"ALLOWED", "DENIED", "UNKNOWN"}
REGISTRATION_VALUES = {"REGISTERED", "NOT_REGISTERED", "MISSING", "STALE"}

STALE_REGISTRATION_THRESHOLD_DAYS = 30


class PushEvaluation(BaseModel):
    domain: str = "push"
    desired_state: dict
    capability_state: dict
    registration_state: dict
    effective_state: dict
    consistency_issues: list[ConsistencyIssue]


def _normalize_desired(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool):
        return "ENABLED" if value else "DISABLED"
    if isinstance(value, str):
        token = value.strip().upper()
        if token in DESIRED_VALUES:
            return token
    raise UnrecognizedObservationValue(f"Unrecognized desired_state value: {value!r}")


def _normalize_capability(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, str):
        token = value.strip().upper()
        if token in ("ALLOWED", "GRANTED"):
            return "ALLOWED"
        if token == "DENIED":
            return "DENIED"
        if token == "UNKNOWN":
            return "UNKNOWN"
    raise UnrecognizedObservationValue(f"Unrecognized capability value: {value!r}")


def _normalize_registration(value: Any, observed_at: datetime, *, now: datetime) -> str:
    if value is None:
        return "MISSING"
    if isinstance(value, str):
        token = value.strip().upper()
        if token == "REGISTERED":
            age_days = (now - observed_at).total_seconds() / 86400
            return "STALE" if age_days > STALE_REGISTRATION_THRESHOLD_DAYS else "REGISTERED"
        if token == "NOT_REGISTERED":
            return "NOT_REGISTERED"
        if token == "UNKNOWN":
            return "MISSING"
    raise UnrecognizedObservationValue(f"Unrecognized registration value: {value!r}")


def normalize(
    observations: list[RawObservation], *, now: datetime | None = None
) -> tuple[str, str, str]:
    """Load-boundary normalization: raw per-source facts -> canonical enums.

    Reads only the latest observation per (source, key) - callers are expected
    to already have deduped via the `observed_at DESC` window (done in SQL in
    production; tests pass already-deduped fixtures directly).
    """
    now = now or datetime.now(observations[0].observed_at.tzinfo) if observations else datetime.now()

    latest = latest_per_key(observations)

    backend_enabled = latest.get(("backend", "enabled"))
    os_permission = latest.get(("os", "permission"))
    braze_registration = latest.get(("braze", "registration"))

    desired = _normalize_desired(backend_enabled.value if backend_enabled else None)
    capability = _normalize_capability(os_permission.value if os_permission else None)
    registration = (
        _normalize_registration(braze_registration.value, braze_registration.observed_at, now=now)
        if braze_registration
        else "MISSING"
    )

    return desired, capability, registration


def evaluate_push_state(
    observations: list[RawObservation], *, now: datetime | None = None
) -> PushEvaluation:
    desired, capability, registration = normalize(observations, now=now)

    desired_state = {"push_enabled": desired}
    capability_state = {"os_permission": capability}
    registration_state = {"provider_registration": registration}

    # Step 1 - intent short-circuit. DISABLED is a complete, self-sufficient
    # explanation for non-delivery: nothing else is worth reporting.
    if desired == "DISABLED":
        return PushEvaluation(
            desired_state=desired_state,
            capability_state=capability_state,
            registration_state=registration_state,
            effective_state={"deliverable": False},
            consistency_issues=[],
        )

    # Step 2 - collect ALL applicable issues independently, not just the first match.
    issues: list[ConsistencyIssue] = []
    if capability == "DENIED":
        issues.append(
            ConsistencyIssue(
                code="OS_PERMISSION_BLOCKS_PUSH",
                severity="INFO",
                remediation="USER_ACTION_REQUIRED",
                evidence=(
                    _evidence_for(observations, "os", "permission")
                    + _evidence_for(observations, "backend", "enabled")
                ),
            )
        )
    if registration == "MISSING":
        issues.append(
            ConsistencyIssue(
                code="PROVIDER_REGISTRATION_MISSING",
                severity="WARNING",
                remediation="BACKEND_SYNC_NEEDED",
                evidence=_evidence_for(observations, "backend", "enabled"),
            )
        )
    if registration == "NOT_REGISTERED":
        issues.append(
            ConsistencyIssue(
                code="BACKEND_PROVIDER_STATE_DIVERGED",
                severity="ERROR",
                remediation="BACKEND_SYNC_NEEDED",
                evidence=(
                    _evidence_for(observations, "backend", "enabled")
                    + _evidence_for(observations, "braze", "registration")
                ),
            )
        )
    if registration == "STALE":
        issues.append(
            ConsistencyIssue(
                code="PROVIDER_REGISTRATION_STALE",
                severity="WARNING",
                remediation="BACKEND_SYNC_NEEDED",
                evidence=_evidence_for(observations, "braze", "registration"),
            )
        )

    # Step 3 - deliverable precedence is FALSE > UNKNOWN > TRUE.
    is_blocked = capability == "DENIED" or registration in ("MISSING", "NOT_REGISTERED", "STALE")
    is_unknown = desired == "UNKNOWN" or capability == "UNKNOWN"
    deliverable = False if is_blocked else (None if is_unknown else True)

    return PushEvaluation(
        desired_state=desired_state,
        capability_state=capability_state,
        registration_state=registration_state,
        effective_state={"deliverable": deliverable},
        consistency_issues=issues,
    )
