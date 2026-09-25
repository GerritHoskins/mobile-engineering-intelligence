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
    assert set(replayed) == {spec.case for spec in sc.ALL_INCIDENTS}
    assert len(set(replayed.values())) == 6  # the fingerprints kept each case its own issue


@pytest.mark.parametrize("spec", sc.ALL_INCIDENTS, ids=lambda s: s.case)
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


# ----------------------------------------------------- Slice R on real data


@pytest.mark.parametrize("spec", sc.IMPACTS, ids=lambda s: s.case)
def test_release_impact_on_real_payloads(client: TestClient, replayed: dict[str, str], spec: sc.ImpactSpec) -> None:
    response = client.get(f"/v1/releases/{spec.release}/impact")
    assert response.status_code == spec.expected_status
    if spec.expected_status != 200:
        return
    body = response.json()
    case_of = {issue_id: case for case, issue_id in replayed.items()}
    assert body["release"]["state"] == spec.expected_release_state
    if spec.expected_crash_free == "UNKNOWN":
        assert body["health"]["crash_free"] == "UNKNOWN"
    else:
        assert body["health"]["crash_free"] == pytest.approx(spec.expected_crash_free)
    assert [f["code"] for f in body["findings"]] == list(spec.expected_findings)
    assert [case_of[i["id"]] for i in body["new_issues"]] == list(spec.expected_new_issues)
    assert [case_of[i["id"]] for i in body["regressed_issues"]] == list(spec.expected_regressed_issues)


def test_real_regression_keeps_first_release(client: TestClient, replayed: dict[str, str]) -> None:
    from app.db import SessionLocal
    from app.models import Incident

    with SessionLocal() as session:
        f2 = session.get(Incident, ("demo", replayed[sc.REGRESSION_CASE]))
    assert (f2.first_release, f2.regressed_release, f2.substatus) == (
        "mei-demo-app@1.2.0", "mei-demo-app@1.3.0", "regressed")


# ----------------------------------------------------- Slice P on real data


@pytest.mark.usefixtures("_truncate_state_observation")
@pytest.mark.parametrize("spec", sc.REPROS, ids=lambda s: s.case)
def test_reproduction_on_real_payloads(client: TestClient, replayed: dict[str, str], spec: sc.ReproSpec) -> None:
    from app.seed import seed

    seed()  # Module 1 subjects the real events point at
    issue_id = replayed.get(spec.incident, spec.incident)  # RP7's id was never ingested
    response = client.get(f"/v1/incidents/{issue_id}/reproduction")
    assert response.status_code == spec.expected_status
    if spec.expected_status != 200:
        return
    body = response.json()
    assert [f"{s['kind']} {s['target']}" for s in body["steps"]] == list(spec.expected_steps)
    assert len(body["variants"]) == spec.expected_variants
    preconditions = {p["key"]: p["value"] for p in body["preconditions"]}
    for key, value in spec.expected_preconditions.items():
        assert preconditions.get(key) == value, key
    assert set(spec.expected_varies) <= {v["key"] for v in body["varies"]}
    assert [g["code"] for g in body["gaps"]] == list(spec.expected_gaps)
    suspects = body["expected_failure"]["suspects"]
    if spec.expected_suspects == "UNKNOWN":
        assert suspects == "UNKNOWN"
    else:
        assert [s["message"].split(": ", 1)[-1] for s in suspects] == list(spec.expected_suspects)
