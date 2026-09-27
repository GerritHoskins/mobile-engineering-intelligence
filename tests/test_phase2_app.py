"""AWS phase 2, application side: personal-data minimisation at ingest,
retention, identifier-free request logs, /healthz and the LLM provider switch."""

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.incidents.normalize import normalize_event
from app.llm.client import AnthropicLLM, LLMMisconfigured, sdk_client
from app.main import app
from app.models import IncidentEvent, LlmOutput
from app.observability import log as access_log
from app.orgs import load_org
from app.privacy import REDACTED_EMAIL, minimise
from app.retention import purge

ORG = load_org("demo")
NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)

# ------------------------------------------------------------- minimisation


def test_minimise_redacts_people_and_query_strings_but_keeps_routes() -> None:
    crumbs = [
        {"category": "xhr", "data": {"method": "GET", "url": "https://api.example.de/api/jobs?token=abc&q=anna",
                                     "status_code": 200}},
        {"category": "navigation", "data": {"from": "/search", "to": "/search/results?page=2"}},
        {"category": "console", "message": "saved profile for anna.meier@example.de"},
        {"category": "user", "data": {"email": "anna@example.de", "username": "anna"}},
    ]
    out = minimise(crumbs)

    assert out[0]["data"]["url"] == "https://api.example.de/api/jobs"
    assert out[1]["data"]["to"] == "/search/results?page=2"  # part of the reproduction path
    assert out[2]["message"] == f"saved profile for {REDACTED_EMAIL}"
    assert out[3]["data"] == {"email": "<scrubbed>", "username": "<scrubbed>"}
    assert "@" not in json.dumps(out)


def test_release_names_are_not_mistaken_for_emails() -> None:
    assert minimise({"release": "mei-demo-app@1.2.0"}) == {"release": "mei-demo-app@1.2.0"}


def test_normalize_event_stores_only_minimised_payloads() -> None:
    event = {
        "eventID": "e1", "groupID": 7, "dateCreated": "2026-09-25T10:00:00Z",
        "user": {"id": "account-case-p1", "email": "anna@example.de", "ip_address": "10.0.0.1"},
        "tags": [{"key": "release", "value": "mei-demo-app@1.2.0"}, {"key": "installation_id", "value": "install-a"},
                 {"key": "url", "value": "https://app.example.de/profile?session=xyz"}],
        "contexts": {"device": {"model": "iPhone15,2"}, "user": {"email": "anna@example.de"}},
        "entries": [
            {"type": "exception", "data": {"values": [{"type": "Error", "value": "bad input from anna@example.de"}]}},
            {"type": "breadcrumbs", "data": {"values": [
                {"category": "xhr", "data": {"url": "https://api.example.de/api/push?token=t", "status_code": 401}}]}},
        ],
    }
    row = normalize_event(ORG, event)

    # Pseudonymous ids stay: Module 1 lookups key on them. The LLM never sees them.
    assert row["user_id"] == "account-case-p1" and row["installation_id"] == "install-a"
    assert row["release"] == "mei-demo-app@1.2.0"
    assert row["tags"]["url"] == "https://app.example.de/profile"
    assert row["breadcrumbs"][0]["data"]["url"] == "https://api.example.de/api/push"
    assert row["contexts"]["user"]["email"] == "<scrubbed>"
    assert row["exception"]["value"] == f"bad input from {REDACTED_EMAIL}"
    stored = json.dumps({k: v for k, v in row.items() if k not in ("user_id", "installation_id")})
    assert "example.de" not in stored.replace("api.example.de", "").replace("app.example.de", "")


# ----------------------------------------------------------------- retention

db = pytest.mark.usefixtures("_truncate_incident_tables", "_truncate_state_observation")


def _event(event_id: str, age_days: int) -> IncidentEvent:
    return IncidentEvent(org="demo", event_id=event_id, sentry_issue_id="1",
                         occurred_at=NOW - timedelta(days=age_days))


def _llm(subject: str, age_days: int) -> LlmOutput:
    return LlmOutput(org="demo", kind="repro_narrative", subject=subject, input_hash="h", model="m",
                     served_by="m", prompt_version="v", output={}, created_at=NOW - timedelta(days=age_days))


@db
def test_retention_deletes_only_rows_older_than_the_window() -> None:
    assert ORG.retention_days == 30
    with SessionLocal() as session:
        session.add_all([_event("old", 31), _event("new", 29), _llm("old", 40), _llm("new", 1)])
        session.commit()

        preview = purge(session, ORG, now=NOW, dry_run=True)
        assert (preview.incident_events, preview.llm_outputs) == (1, 1)
        assert session.query(IncidentEvent).count() == 2  # dry run deletes nothing

        result = purge(session, ORG, now=NOW)
        assert (result.incident_events, result.llm_outputs) == (1, 1)
        assert [e.event_id for e in session.query(IncidentEvent)] == ["new"]
        assert [o.subject for o in session.query(LlmOutput)] == ["new"]


@db
def test_no_retention_window_deletes_nothing() -> None:
    with SessionLocal() as session:
        session.add(_event("ancient", 400))
        session.commit()
        result = purge(session, ORG.model_copy(update={"retention_days": None}), now=NOW)
        assert result.cutoff is None and session.query(IncidentEvent).count() == 1


# ------------------------------------------------------- logging and health


@pytest.fixture()
def access_lines():
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    access_log.addHandler(handler)
    yield buffer
    access_log.removeHandler(handler)


def test_request_log_holds_the_route_template_not_the_ids(access_lines) -> None:
    client = TestClient(app)
    client.get("/v1/incidents/secret-issue-4711/context", params={"org": "no-such-org"})
    client.get("/v1/nowhere/install-case-secret")

    lines = access_lines.getvalue().splitlines()
    assert lines[0].startswith("GET /v1/incidents/{sentry_issue_id}/context 400 ")
    assert lines[1].startswith("GET <unmatched> 404 ")
    assert "secret" not in access_lines.getvalue()


@db
def test_healthz_checks_the_database() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


# ------------------------------------------------------------ LLM provider


def test_provider_switch_builds_the_matching_sdk_client() -> None:
    assert type(sdk_client("anthropic", api_key="test")) is anthropic.Anthropic
    aws = sdk_client("aws", aws_region="eu-central-1", workspace_id="wrkspc_test",
                     aws_access_key="AKIATEST", aws_secret_key="secret")
    assert isinstance(aws, anthropic.AnthropicAWS)
    with pytest.raises(LLMMisconfigured):
        sdk_client("bedrock")


def test_aws_permission_errors_are_a_configuration_problem() -> None:
    request = httpx2.Request("POST", "https://aws-external-anthropic.eu-central-1.api.aws/v1/messages")
    error = anthropic.PermissionDeniedError("forbidden", response=httpx2.Response(403, request=request), body=None)

    def create(**kwargs):
        raise error

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(LLMMisconfigured):
        AnthropicLLM(sdk).generate(system="s", user="u", schema={})
