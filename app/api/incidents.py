from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.incidents.context import build_incident_context
from app.incidents.repository import load_incident, load_release_graph
from app.reproduction.repository import load_events, state_lookup
from app.reproduction.reproduce import build_reproduction
from app.orgs import available_orgs, load_org

router = APIRouter(prefix="/v1/incidents")

DEFAULT_ORG = "demo"


@router.get("/{sentry_issue_id}/context")
def get_incident_context(
    sentry_issue_id: str,
    org: str = Query(default=DEFAULT_ORG),
    session: Session = Depends(get_session),
) -> dict:
    if org not in available_orgs():
        raise HTTPException(status_code=400, detail=f"Unknown org: {org!r}")
    config = load_org(org)
    incident = load_incident(session, config, sentry_issue_id)
    if incident is None:
        # Unlike /v1/state (observations of any subject), an incident is a
        # concrete ingested Sentry issue: absent means not ingested.
        raise HTTPException(status_code=404, detail=f"Incident {sentry_issue_id!r} not ingested for org {org!r}")
    return build_incident_context(incident, load_release_graph(session, config)).model_dump(mode="json")


@router.get("/{sentry_issue_id}/reproduction")
def get_incident_reproduction(
    sentry_issue_id: str,
    org: str = Query(default=DEFAULT_ORG),
    session: Session = Depends(get_session),
) -> dict:
    if org not in available_orgs():
        raise HTTPException(status_code=400, detail=f"Unknown org: {org!r}")
    config = load_org(org)
    incident = load_incident(session, config, sentry_issue_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {sentry_issue_id!r} not ingested for org {org!r}")
    reproduction = build_reproduction(
        incident, load_events(session, config, sentry_issue_id), load_release_graph(session, config),
        state_lookup(session), config.repro,
    )
    return reproduction.model_dump(mode="json")
