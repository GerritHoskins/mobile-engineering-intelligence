"""Loads the pure reproduction inputs (app.reproduction.reproduce) from the database."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IncidentEvent
from app.orgs import OrgConfig
from app.reconciliation.service import evaluate_subject
from app.reproduction.reproduce import EventInput, StateLookup


def load_events(session: Session, org: OrgConfig, sentry_issue_id: str) -> list[EventInput]:
    rows = session.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.org == org.name, IncidentEvent.sentry_issue_id == sentry_issue_id)
        .order_by(IncidentEvent.occurred_at, IncidentEvent.event_id)
    )
    return [
        EventInput(
            event_id=r.event_id, release=r.release, user_id=r.user_id, installation_id=r.installation_id,
            exception=r.exception, breadcrumbs=tuple(r.breadcrumbs), contexts=r.contexts, tags=r.tags,
        )
        for r in rows
    ]


def state_lookup(session: Session) -> StateLookup:
    """Module 1 state, in-process (same service, same database). A separate
    HTTP implementation fits this interface if Module 1 is ever split out."""
    cache: dict[tuple[str, str, str], dict | None] = {}

    def lookup(subject_type: str, subject_id: str, domain: str) -> dict | None:
        key = (subject_type, subject_id, domain)
        if key not in cache:
            cache[key] = evaluate_subject(session, subject_type, subject_id, domain)
        return cache[key]

    return lookup
