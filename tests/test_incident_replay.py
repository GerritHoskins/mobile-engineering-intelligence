"""F1-F5 end to end on REAL vendor payloads: the recorded (scrubbed) GitHub,
Jira and Sentry responses in tests/fixtures/vendors/demo are replayed through
the normal ingestion into mei_test, then checked through the API.

Re-record with `uv run python -m app.connectors.record --org demo`."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors.http import ReplayTransport
from scripts.demo import scenario as sc

pytestmark = pytest.mark.usefixtures("_truncate_incident_tables")

RECORDING = Path(__file__).parent / "fixtures" / "vendors" / "demo"
WINDOW = json.loads((RECORDING / "_window.json").read_text())


@pytest.fixture()
def replayed(monkeypatch) -> dict[str, str]:
    """Ingest the recording; returns demo_case -> Sentry issue id."""
    from app.db import SessionLocal
    from app.ingest import ingest
    from app.models import IncidentEvent

    # Replay never reaches the network, but the clients still require tokens.
    for name in ("GITHUB_READ_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN", "SENTRY_READ_TOKEN"):
        monkeypatch.setenv(name, "replay")
    ingest("demo", WINDOW["days"], transport=ReplayTransport(RECORDING), end=datetime.fromisoformat(WINDOW["end"]))
    with SessionLocal() as session:
        return {e.tags["demo_case"]: e.sentry_issue_id for e in session.scalars(select(IncidentEvent))}


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_recording_holds_every_planted_case(replayed: dict[str, str]) -> None:
    assert set(replayed) == {spec.case for spec in sc.INCIDENTS}
    assert len(set(replayed.values())) == 5  # the fingerprints kept each case its own issue


@pytest.mark.parametrize("spec", sc.INCIDENTS, ids=lambda s: s.case)
def test_context_on_real_payloads(client: TestClient, replayed: dict[str, str], spec: sc.IncidentSpec) -> None:
    body = client.get(f"/v1/incidents/{replayed[spec.case]}/context").json()

    assert body["release"]["state"] == spec.expected_release_state
    assert body["release"]["version"] == spec.release
    if spec.expected_suspects == "UNKNOWN":
        assert body["suspects"] == "UNKNOWN"
    else:
        # Real SHAs and Jira-assigned keys: compare by commit subject.
        subjects = [s["message"].split(": ", 1)[-1] for s in body["suspects"]]
        assert subjects == list(spec.expected_suspects)
    assert [f["code"] for f in body["findings"]] == list(spec.expected_findings)


def test_f1_real_suspect_links_real_ticket(client: TestClient, replayed: dict[str, str]) -> None:
    body = client.get(f"/v1/incidents/{replayed['F1']}/context").json()
    (suspect,) = body["suspects"]
    (ticket,) = [t for t in body["tickets"] if t["key"] in suspect["ticket_keys"]]
    assert ticket["summary"] == "[demo:push-token-refresh] Refresh push token when the app resumes"
    assert suspect["evidence_frames"] == [
        {"path": "src/modules/push/registration.ts", "function": "refreshToken", "lineno": 42}
    ]
    assert body["release"]["previous"] == "1.1.0"


def test_session_counts_match_planted_totals(replayed: dict[str, str]) -> None:
    from app.db import SessionLocal
    from app.models import ReleaseSessionCount

    totals: dict[str, list[int]] = {}
    with SessionLocal() as session:
        for row in session.scalars(select(ReleaseSessionCount)):
            total = totals.setdefault(row.sentry_release, [0, 0])
            total[0] += row.sessions
            total[1] += row.sessions if row.status == "crashed" else 0
    assert totals == {f"mei-demo-app@{v}": list(tc) for v, tc in sc.SESSIONS.items()}
