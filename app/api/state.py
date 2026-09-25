from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.reconciliation.service import DOMAINS, VALID_SUBJECT_TYPES, _load_latest_raw_observations

router = APIRouter(prefix="/v1/state")


@router.get("/{subject_type}/{subject_id}")
def get_state(
    subject_type: str,
    subject_id: str,
    domain: str = Query(default="push"),
    session: Session = Depends(get_session),
) -> dict:
    if subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported subject_type: {subject_type!r}")
    spec = DOMAINS.get(domain)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unsupported domain: {domain!r}")
    if spec.subject_type != subject_type:
        raise HTTPException(
            status_code=400,
            detail=f"Domain {domain!r} requires subject_type {spec.subject_type!r}, got {subject_type!r}",
        )

    raw_observations = _load_latest_raw_observations(session, subject_type, subject_id, domain)

    if raw_observations:
        state = spec.evaluate(raw_observations)
    else:
        state = spec.empty() | {"consistency_issues": []}

    return {
        "subject": {"type": subject_type, "id": subject_id},
        "domain": domain,
        **state,
        "consistency_issues": [issue.model_dump(mode="json") for issue in state["consistency_issues"]],
    }
