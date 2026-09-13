from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import StateObservation
from app.reconciliation.push_state import RawObservation, evaluate_push_state

router = APIRouter(prefix="/v1/state")

VALID_SUBJECT_TYPES = {"installation"}
VALID_DOMAINS = {"push"}


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


def _empty_observation_response(subject_type: str, subject_id: str, domain: str) -> dict:
    """A subject with zero observations at all is distinct from a subject with
    some observations but a specific key missing (e.g. scenario D's missing
    braze registration, which is a genuine PROVIDER_REGISTRATION_MISSING
    warning). With literally nothing reported yet, every state is UNKNOWN and
    there are no issues to report -- there's no `subjects` table to distinguish
    "doesn't exist" from "hasn't reported yet", so the API doesn't pretend to."""
    return {
        "subject": {"type": subject_type, "id": subject_id},
        "domain": domain,
        "desired_state": {"push_enabled": "UNKNOWN"},
        "capability_state": {"os_permission": "UNKNOWN"},
        "registration_state": {"provider_registration": "UNKNOWN"},
        "effective_state": {"deliverable": None},
        "consistency_issues": [],
    }


@router.get("/{subject_type}/{subject_id}")
def get_state(
    subject_type: str,
    subject_id: str,
    domain: str = Query(default="push"),
    session: Session = Depends(get_session),
) -> dict:
    if subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported subject_type: {subject_type!r}")
    if domain not in VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unsupported domain: {domain!r}")

    raw_observations = _load_latest_raw_observations(session, subject_type, subject_id, domain)

    if not raw_observations:
        return _empty_observation_response(subject_type, subject_id, domain)

    evaluation = evaluate_push_state(raw_observations)

    return {
        "subject": {"type": subject_type, "id": subject_id},
        "domain": evaluation.domain,
        "desired_state": evaluation.desired_state,
        "capability_state": evaluation.capability_state,
        "registration_state": evaluation.registration_state,
        "effective_state": evaluation.effective_state,
        "consistency_issues": [issue.model_dump(mode="json") for issue in evaluation.consistency_issues],
    }
