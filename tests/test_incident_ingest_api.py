"""Ingestion + API end to end against the real mei_test Postgres, with fake
connectors serving API-shaped payloads generated from the demo scenario.
(Recorded real payloads replace the fakes' role in PR B.)"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ingest import ingest_git, ingest_jira, ingest_sentry
from app.orgs import load_org
from scripts.demo import scenario as sc

pytestmark = pytest.mark.usefixtures("_truncate_incident_tables")

ORG = load_org("demo")
KEYS = {t.marker: f"MEI-{n}" for n, t in enumerate(sc.TICKETS, start=1)}
NOW = datetime.now(timezone.utc)


def _sha(spec: sc.CommitSpec) -> str:
    return hashlib.sha1(spec.subject.encode()).hexdigest()


class FakeGitHub:
    def list_tags(self):
        # Includes a non-release tag, which must be ignored.
        return [{"name": ORG.tag_for(v)} for v in reversed(sc.VERSIONS)] + [{"name": "experiment"}]

    def compare_commits(self, base, head):
        version = ORG.version_from_tag(head)
        return [{"sha": _sha(spec)} for spec in sc.RELEASE_COMMITS[version]]

    def get_commit(self, sha):
        spec = next(s for specs in sc.RELEASE_COMMITS.values() for s in specs if _sha(s) == sha)
        return {"sha": sha, "commit": {"message": sc.commit_message(spec, KEYS), "author": {"date": spec.date.isoformat()}},
                "files": [{"filename": path, "status": "modified"} for path in spec.files]}


class FakeJira:
    def get_issue(self, key):
        ticket = next((t for t in sc.TICKETS if KEYS[t.marker] == key), None)
        if ticket is None:
            return None
        return {"key": key, "fields": {"summary": ticket.jira_summary, "issuetype": {"name": ticket.issue_type},
                                       "status": {"name": "To Do"}, "components": [{"name": ticket.component}],
                                       "fixVersions": [{"name": ORG.tag_for(ticket.fix_version)}]}}


class FakeSentry:
    def __init__(self, incidents=sc.ALL_INCIDENTS):
        self.issues = {spec.case: spec for spec in incidents}

    def list_issues(self, start, end):
        return [{"id": case} for case in self.issues]

    def get_issue(self, issue_id):
        spec = self.issues[issue_id]
        activity = [{"type": "first_seen", "data": {}, "dateCreated": (NOW - timedelta(days=1)).isoformat()}]
        if issue_id == sc.REGRESSION_CASE:  # resolved in the UI, then seen again in a later release
            activity += [
                {"type": "set_resolved", "data": {}, "dateCreated": (NOW - timedelta(hours=3)).isoformat()},
                {"type": "set_regression", "data": {"version": ORG.sentry_release_for(sc.REGRESSION_RELEASE)},
                 "dateCreated": (NOW - timedelta(hours=2)).isoformat()},
            ]
        return {"id": issue_id, "title": f"{spec.exception_type}: {spec.exception_value}", "culprit": None,
                "level": "error", "firstRelease": {"version": ORG.sentry_release_for(spec.release)},
                "firstSeen": (NOW - timedelta(days=1, minutes=-int(issue_id[1:]))).isoformat(),
                "lastSeen": NOW.isoformat(), "status": "unresolved",
                "substatus": "regressed" if issue_id == sc.REGRESSION_CASE else "new", "activity": activity}

    def list_issue_events(self, issue_id):
        spec = self.issues[issue_id]
        events = self._events(spec)
        if issue_id == sc.REGRESSION_CASE:
            regressed = sc.IncidentSpec(**{**spec.__dict__, "release": sc.REGRESSION_RELEASE,
                                           "subjects": (sc.REGRESSION_SUBJECT,)})
            events += [{**e, "eventID": f"{issue_id}-regression", "dateCreated": (NOW - timedelta(hours=1)).isoformat()}
                       for e in self._events(regressed)]
        return events

    def _events(self, spec):
        issue_id = spec.case
        return [{
            "eventID": f"{issue_id}-{n}", "groupID": issue_id, "dateCreated": (NOW - timedelta(minutes=n)).isoformat(),
            "user": {"id": s.user_id},
            "tags": [{"key": "release", "value": ORG.sentry_release_for(spec.release)},
                     {"key": "installation_id", "value": s.installation_id}, {"key": "demo_case", "value": spec.case},
                     *({"key": k, "value": v} for k, v in spec.flags.items())],
            # Same shape as scripts/demo/generate.py build_event.
            "contexts": {"device": {"family": "iOS", "model": "iPhone15,2"}, "os": {"name": "iOS", "version": "18.4"},
                         "app": {"app_version": spec.release}},
            "entries": [{"type": "exception", "data": {"values": [{
                "type": spec.exception_type, "value": spec.exception_value,
                "stacktrace": {"frames": [{"filename": f.filename, "function": f.function, "lineNo": f.lineno,
                                           "inApp": True} for f in spec.frames]}}]}},
                {"type": "breadcrumbs", "data": {"values": list(sc.breadcrumbs_for(spec, n))}}],
        } for n, s in enumerate(spec.subjects)]

    def get_project(self):
        return {"id": "1"}

    def session_counts(self, project_id, start, end):
        settled = (NOW - timedelta(days=1)).replace(minute=0, second=0, microsecond=0).isoformat()
        rows = []
        for version, (total, crashed) in sc.SESSIONS.items():
            for status, count in (("healthy", total - crashed), ("crashed", crashed)):
                if count:
                    rows.append({"release": ORG.sentry_release_for(version), "status": status,
                                 "bucket_start": settled, "sessions": count})
        return rows + [{"release": "probe-now", "status": "healthy", "bucket_start": settled, "sessions": 18}]


def _ingest(incidents=sc.ALL_INCIDENTS) -> None:
    from app.db import SessionLocal

    with SessionLocal() as session, session.begin():
        keys = ingest_git(session, ORG, FakeGitHub())
        ingest_jira(session, ORG, FakeJira(), keys + ["MEI-999"])  # one key Jira doesn't know
        ingest_sentry(session, ORG, FakeSentry(incidents), NOW - timedelta(days=14), NOW)


def _row_counts() -> dict[str, int]:
    from app.db import SessionLocal
    from app import models

    tables = [models.Release, models.Commit, models.ReleaseCommit, models.ChangedFile, models.Ticket,
              models.CommitTicket, models.Incident, models.IncidentEvent, models.ReleaseSessionCount]
    with SessionLocal() as session:
        return {t.__tablename__: session.scalar(select(func.count()).select_from(t)) for t in tables}


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_ingestion_is_idempotent() -> None:
    _ingest()
    first = _row_counts()
    _ingest()
    assert _row_counts() == first
    assert first["incident"] == 6 and first["incident_event"] == 15  # F1-F5 11 + regression 1 + F6 3
    assert first["release_session_count"] == 7  # healthy + non-zero crashed per release; probe skipped


def test_releases_include_untagged_sentry_release_but_not_probes() -> None:
    from app.db import SessionLocal
    from app.models import Release

    _ingest()
    with SessionLocal() as session:
        releases = {r.version: r.tag for r in session.scalars(select(Release))}
    assert releases == {**{v: ORG.tag_for(v) for v in sc.VERSIONS}, "1.2.1": None}


def test_unknown_jira_key_is_kept_as_missing() -> None:
    from app.db import SessionLocal
    from app.models import Ticket

    _ingest()
    with SessionLocal() as session:
        assert session.get(Ticket, ("demo", "MEI-999")).missing_in_jira is True


@pytest.mark.parametrize("spec", sc.ALL_INCIDENTS, ids=lambda s: s.case)
def test_context_api_matches_scenario(client: TestClient, spec: sc.IncidentSpec) -> None:
    _ingest()
    body = client.get(f"/v1/incidents/{spec.case}/context").json()
    assert body["release"]["state"] == spec.expected_release_state
    if spec.expected_suspects == "UNKNOWN":
        assert body["suspects"] == "UNKNOWN"
    else:
        by_sha = {_sha(s): s.subject for specs in sc.RELEASE_COMMITS.values() for s in specs}
        assert [by_sha[s["sha"]] for s in body["suspects"]] == list(spec.expected_suspects)
    assert [f["code"] for f in body["findings"]] == list(spec.expected_findings)


def test_unknown_org_returns_400(client: TestClient) -> None:
    response = client.get("/v1/incidents/F1/context?org=nope")
    assert response.status_code == 400 and "Unknown org" in response.json()["detail"]


def test_not_ingested_incident_returns_404(client: TestClient) -> None:
    response = client.get("/v1/incidents/does-not-exist/context")
    assert response.status_code == 404 and "not ingested" in response.json()["detail"]
