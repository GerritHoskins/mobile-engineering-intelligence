"""Module 1 state evaluation, usable in-process by other modules (e.g. the
Reproduction Assistant) as well as by the /v1/state API."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import StateObservation
from app.reconciliation.common import RawObservation
from app.reconciliation.profile_state import empty_field_states, evaluate_profile_state
from app.reconciliation.push_state import evaluate_push_state


def _load_latest_raw_observations(
    session: Session, subject_type: str, subject_id: str, domain: str
) -> list[RawObservation]:
    """Latest-per-key load: ROW_NUMBER() OVER (... ORDER BY observed_at DESC) = 1,
    resolved in SQL rather than loaded-then-filtered in Python, per the vault's
    locked dedup contract."""
    row_number = (
        func.row_number()
        .over(
            partition_by=(
                StateObservation.subject_type,
                StateObservation.subject_id,
                StateObservation.domain,
                StateObservation.source,
                StateObservation.key,
            ),
            order_by=StateObservation.observed_at.desc(),
        )
        .label("rn")
    )
    subquery = (
        select(
            StateObservation.source,
            StateObservation.key,
            StateObservation.value,
            StateObservation.observed_at,
            row_number,
        )
        .where(
            StateObservation.subject_type == subject_type,
            StateObservation.subject_id == subject_id,
            StateObservation.domain == domain,
        )
        .subquery()
    )
    stmt = select(
        subquery.c.source, subquery.c.key, subquery.c.value, subquery.c.observed_at
    ).where(subquery.c.rn == 1)

    return [
        RawObservation(source=row.source, key=row.key, value=row.value, observed_at=row.observed_at)
        for row in session.execute(stmt).all()
    ]


def _empty_push_state() -> dict:
    """A subject with zero observations at all is distinct from a subject with
    some observations but a specific key missing (e.g. scenario D's missing
    braze registration, which is a genuine PROVIDER_REGISTRATION_MISSING
    warning). With literally nothing reported yet, every state is UNKNOWN and
    there are no issues to report -- there's no `subjects` table to distinguish
    "doesn't exist" from "hasn't reported yet", so the API doesn't pretend to."""
    return {
        "desired_state": {"push_enabled": "UNKNOWN"},
        "capability_state": {"os_permission": "UNKNOWN"},
        "registration_state": {"provider_registration": "UNKNOWN"},
        "effective_state": {"deliverable": None},
    }


def _push_state(observations: list[RawObservation]) -> dict:
    evaluation = evaluate_push_state(observations)
    return {
        "desired_state": evaluation.desired_state,
        "capability_state": evaluation.capability_state,
        "registration_state": evaluation.registration_state,
        "effective_state": evaluation.effective_state,
        "consistency_issues": evaluation.consistency_issues,
    }


def _empty_profile_state() -> dict:
    """Same zero-observation contract as push: every field UNKNOWN, no issues."""
    return {"field_states": empty_field_states(), "effective_state": {"consistent": None}}


def _profile_state(observations: list[RawObservation]) -> dict:
    evaluation = evaluate_profile_state(observations)
    return {
        "field_states": evaluation.field_states,
        "effective_state": evaluation.effective_state,
        "consistency_issues": evaluation.consistency_issues,
    }


@dataclass(frozen=True)
class DomainSpec:
    subject_type: str
    evaluate: Callable[[list[RawObservation]], dict]
    empty: Callable[[], dict]


# Each domain is scoped to exactly one subject type. Two entries, not a rules DSL.
DOMAINS: dict[str, DomainSpec] = {
    "push": DomainSpec("installation", _push_state, _empty_push_state),
    "profile": DomainSpec("account", _profile_state, _empty_profile_state),
}
VALID_SUBJECT_TYPES = {spec.subject_type for spec in DOMAINS.values()}


def evaluate_subject(session: Session, subject_type: str, subject_id: str, domain: str) -> dict | None:
    """Evaluated state for one subject, or None when it has no observations at
    all (the API reports that as the empty UNKNOWN contract)."""
    spec = DOMAINS[domain]
    if spec.subject_type != subject_type:
        raise ValueError(f"Domain {domain!r} requires subject_type {spec.subject_type!r}, got {subject_type!r}")
    observations = _load_latest_raw_observations(session, subject_type, subject_id, domain)
    return spec.evaluate(observations) if observations else None
