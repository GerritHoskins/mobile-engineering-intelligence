"""Loads the pure release-impact inputs (app.releases.impact) from the database."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.incidents.repository import load_incident
from app.models import Incident, IncidentEvent, Release, ReleaseSessionCount
from app.orgs import OrgConfig
from app.releases.impact import IssueInput, SessionTotals


def release_exists(session: Session, org: OrgConfig, version: str) -> bool:
    return session.get(Release, (org.name, version)) is not None


def load_session_totals(session: Session, org: OrgConfig, now: datetime) -> dict[str, SessionTotals]:
    """Per version: sessions/crashed over settled hourly buckets only. A bucket
    is settled once it has ended and `settle_minutes` have passed, because
    Sentry's crash counts can arrive after its session counts."""
    settled_before = now - timedelta(hours=1, minutes=org.impact.settle_minutes)
    sessions, crashed, pending = defaultdict(int), defaultdict(int), defaultdict(set)
    for row in session.scalars(select(ReleaseSessionCount).where(ReleaseSessionCount.org == org.name)):
        version = org.version_from_sentry_release(row.sentry_release)
        if version is None:
            continue
        if row.bucket_start > settled_before:
            pending[version].add(row.bucket_start)
            continue
        sessions[version] += row.sessions
        if row.status == "crashed":
            crashed[version] += row.sessions
    return {v: SessionTotals(sessions[v], crashed[v], len(pending[v])) for v in set(sessions) | set(pending)}


def _issue_inputs(session: Session, org: OrgConfig, ids: list[str], sentry_release: str) -> list[IssueInput]:
    counts = dict(session.execute(
        select(IncidentEvent.sentry_issue_id, func.count())
        .where(IncidentEvent.org == org.name, IncidentEvent.release == sentry_release)
        .group_by(IncidentEvent.sentry_issue_id)
    ).all())
    return [IssueInput(load_incident(session, org, i), counts.get(i, 0)) for i in ids]


def load_release_issues(session: Session, org: OrgConfig, version: str) -> tuple[list[IssueInput], list[IssueInput]]:
    """(issues first seen in `version`, issues that regressed in `version`),
    each ordered by first seen, then id."""
    name = org.sentry_release_for(version)
    order = (Incident.first_seen, Incident.sentry_issue_id)
    new_ids = list(session.scalars(select(Incident.sentry_issue_id).where(
        Incident.org == org.name, Incident.first_release == name).order_by(*order)))
    regressed_ids = list(session.scalars(select(Incident.sentry_issue_id).where(
        Incident.org == org.name, Incident.regressed_release == name).order_by(*order)))
    return _issue_inputs(session, org, new_ids, name), _issue_inputs(session, org, regressed_ids, name)
