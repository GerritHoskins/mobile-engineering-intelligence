"""Loads the pure context inputs (app.incidents.context) from the database."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.context import CommitInfo, IncidentInfo, ReleaseGraph, TicketInfo, semver_key
from app.models import ChangedFile, Commit, CommitTicket, Incident, IncidentEvent, Release, ReleaseCommit, Ticket
from app.orgs import OrgConfig


def load_incident(session: Session, org: OrgConfig, sentry_issue_id: str) -> IncidentInfo | None:
    incident = session.get(Incident, (org.name, sentry_issue_id))
    if incident is None:
        return None
    events = session.scalars(
        select(IncidentEvent).where(IncidentEvent.org == org.name, IncidentEvent.sentry_issue_id == sentry_issue_id)
        .order_by(IncidentEvent.occurred_at, IncidentEvent.event_id)
    ).all()
    # Frames of the issue's events, de-duplicated in stack order.
    seen, frames = set(), []
    for event in events:
        for frame in event.frames:
            key = (frame.get("raw_filename"), frame.get("function"), frame.get("lineno"))
            if key not in seen:
                seen.add(key)
                frames.append(frame)
    return IncidentInfo(
        sentry_issue_id=incident.sentry_issue_id, title=incident.title, culprit=incident.culprit,
        first_release=incident.first_release,
        first_release_version=org.version_from_sentry_release(incident.first_release or ""),
        frames=tuple(frames),
    )


def load_release_graph(session: Session, org: OrgConfig) -> ReleaseGraph:
    tagged = sorted(
        (r.version for r in session.scalars(select(Release).where(Release.org == org.name, Release.tag.is_not(None)))),
        key=semver_key,
    )
    files, keys = defaultdict(list), defaultdict(list)
    for f in session.scalars(select(ChangedFile).where(ChangedFile.org == org.name).order_by(ChangedFile.path)):
        files[f.sha].append((f.path, f.component))
    for ct in session.scalars(select(CommitTicket).where(CommitTicket.org == org.name)):
        keys[ct.sha].append(ct.ticket_key)

    commits = defaultdict(list)
    rows = session.execute(
        select(ReleaseCommit.version, Commit)
        .join(Commit, (Commit.org == ReleaseCommit.org) & (Commit.repo == ReleaseCommit.repo)
              & (Commit.sha == ReleaseCommit.sha))
        .where(ReleaseCommit.org == org.name)
        .order_by(ReleaseCommit.version, ReleaseCommit.position)
    )
    for version, commit in rows:
        # Ticket keys in message order, as the commit states them.
        ordered = [k for k in org.ticket_keys(commit.message) if k in keys[commit.sha]]
        commits[version].append(CommitInfo(commit.sha, commit.message, tuple(files[commit.sha]), tuple(ordered)))

    tickets = {
        t.key: TicketInfo(t.key, t.summary, t.issue_type, t.status, t.missing_in_jira)
        for t in session.scalars(select(Ticket).where(Ticket.org == org.name))
    }
    return ReleaseGraph(tuple(tagged), {v: tuple(c) for v, c in commits.items()}, tickets)
