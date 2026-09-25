"""Ingest one org's GitHub / Jira / Sentry data into the Slice F tables.

    uv run python -m app.ingest --org demo [--days 14]

Idempotent: every write is an upsert on the table's primary key, so a re-run
yields identical rows. Read-only towards the vendors.
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.clients import build_clients
from app.db import SessionLocal
from app.incidents.context import semver_key
from app.incidents.normalize import normalize_event, regression_release
from app.models import (
    ChangedFile, Commit, CommitTicket, Incident, IncidentEvent, Release, ReleaseCommit, ReleaseSessionCount, Ticket,
)
from app.orgs import OrgConfig, load_org

log = logging.getLogger("ingest")


def upsert(session: Session, model, rows: list[dict]) -> None:
    if not rows:
        return
    keys = [c.name for c in model.__table__.primary_key.columns]
    stmt = insert(model).values(rows)
    updates = {c.name: stmt.excluded[c.name] for c in model.__table__.columns if c.name not in keys}
    session.execute(stmt.on_conflict_do_update(index_elements=keys, set_=updates) if updates
                    else stmt.on_conflict_do_nothing(index_elements=keys))


def ingest_git(session: Session, org: OrgConfig, github) -> list[str]:
    """Tags -> releases; commits between consecutive tags -> release contents.
    Returns ticket keys referenced by commit messages."""
    tagged = sorted(
        ((version, tag["name"]) for tag in github.list_tags() if (version := org.version_from_tag(tag["name"]))),
        key=lambda vt: semver_key(vt[0]),
    )
    upsert(session, Release, [
        {"org": org.name, "version": v, "tag": t, "sentry_release": org.sentry_release_for(v)} for v, t in tagged
    ])
    repo, referenced = org.github.repo, []
    # The first tag has no previous tag, so no computable change set.
    for (_, prev_tag), (version, tag) in zip(tagged, tagged[1:]):
        for position, entry in enumerate(github.compare_commits(prev_tag, tag)):
            commit = github.get_commit(entry["sha"])
            message = commit["commit"]["message"]
            keys = org.ticket_keys(message)
            referenced += keys
            upsert(session, Commit, [{"org": org.name, "repo": repo, "sha": commit["sha"], "message": message,
                                      "authored_at": commit["commit"]["author"]["date"]}])
            upsert(session, ReleaseCommit, [{"org": org.name, "version": version, "repo": repo,
                                             "sha": commit["sha"], "position": position}])
            upsert(session, ChangedFile, [
                {"org": org.name, "repo": repo, "sha": commit["sha"], "path": f["filename"],
                 "status": f["status"], "component": org.component_for(f["filename"])}
                for f in commit.get("files", [])
            ])
            upsert(session, CommitTicket, [
                {"org": org.name, "repo": repo, "sha": commit["sha"], "ticket_key": key} for key in keys
            ])
    return sorted(set(referenced))


def ingest_jira(session: Session, org: OrgConfig, jira, keys: list[str]) -> None:
    rows = []
    for key in keys:
        issue = jira.get_issue(key)
        if issue is None:
            rows.append({"org": org.name, "key": key, "summary": None, "issue_type": None, "status": None,
                         "components": [], "fix_versions": [], "missing_in_jira": True})
            continue
        fields = issue["fields"]
        rows.append({
            "org": org.name, "key": issue["key"], "summary": fields.get("summary"),
            "issue_type": (fields.get("issuetype") or {}).get("name"),
            "status": (fields.get("status") or {}).get("name"),
            "components": [c["name"] for c in fields.get("components") or []],
            "fix_versions": [v["name"] for v in fields.get("fixVersions") or []],
            "missing_in_jira": False,
        })
    upsert(session, Ticket, rows)


def ingest_sentry(session: Session, org: OrgConfig, sentry, start: datetime, end: datetime) -> None:
    known = {r.version for r in session.query(Release).filter_by(org=org.name)}

    def note_release(name: str | None) -> None:
        """This app's releases without a git tag are stored as tag=None (their
        context is UNKNOWN). Releases not following the naming are skipped."""
        if not name:
            return
        version = org.version_from_sentry_release(name)
        if version is None:
            log.info("skipping Sentry release %r: not this app's naming", name)
        elif version not in known:
            upsert(session, Release, [{"org": org.name, "version": version, "tag": None, "sentry_release": name}])
            known.add(version)

    for listed in sentry.list_issues(start, end):
        issue = sentry.get_issue(listed["id"])
        first_release = (issue.get("firstRelease") or {}).get("version")
        note_release(first_release)
        rows = [{"org": org.name, **normalize_event(org, event)} for event in sentry.list_issue_events(issue["id"])]
        upsert(session, Incident, [{
            "org": org.name, "sentry_issue_id": str(issue["id"]), "title": issue["title"],
            "culprit": issue.get("culprit"), "level": issue.get("level"), "first_release": first_release,
            "first_seen": issue.get("firstSeen"), "last_seen": issue.get("lastSeen"),
            "status": issue.get("status"), "substatus": issue.get("substatus"),
            "regressed_release": regression_release(issue, rows),
        }])
        for row in rows:
            note_release(row["release"])
        upsert(session, IncidentEvent, rows)

    project_id = str(sentry.get_project()["id"])
    upsert(session, ReleaseSessionCount, [
        {"org": org.name, "sentry_release": r["release"], "bucket_start": r["bucket_start"],
         "status": r["status"], "sessions": r["sessions"]}
        for r in sentry.session_counts(project_id, start, end)
        if org.version_from_sentry_release(r["release"])
    ])


def ingest(org_name: str, days: int = 14, transport=None, end: datetime | None = None) -> None:
    """`end` is fixed when replaying recorded fixtures (the Sentry window is
    part of each recorded request); live runs use now."""
    org = load_org(org_name)
    github, jira, sentry = build_clients(org, transport)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    with SessionLocal() as session, session.begin():
        keys = ingest_git(session, org, github)
        ingest_jira(session, org, jira, keys)
        ingest_sentry(session, org, sentry, start, end)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True)
    parser.add_argument("--days", type=int, default=14, help="Sentry lookback window")
    args = parser.parse_args()
    ingest(args.org, args.days)
    print(f"ingested org {args.org!r}")


if __name__ == "__main__":
    main()
