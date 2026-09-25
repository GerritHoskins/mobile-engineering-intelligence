"""RP1-RP7 through ingestion (fake connectors incl. F6 and the regression)
and the /v1/incidents/{id}/reproduction API, with Module 1 seeded into the
real mei_test Postgres for the in-process state lookup."""

import pytest
from fastapi.testclient import TestClient

from scripts.demo import scenario as sc
from tests.test_incident_ingest_api import _ingest

pytestmark = pytest.mark.usefixtures("_truncate_incident_tables", "_truncate_state_observation")


@pytest.fixture()
def client() -> TestClient:
    from app.main import app
    from app.seed import seed

    seed()  # Module 1 subjects the events point at
    _ingest(sc.ALL_INCIDENTS)
    return TestClient(app)


@pytest.mark.parametrize("spec", sc.REPROS, ids=lambda s: s.case)
def test_reproduction_api_matches_scenario(client: TestClient, spec: sc.ReproSpec) -> None:
    response = client.get(f"/v1/incidents/{spec.incident}/reproduction")
    assert response.status_code == spec.expected_status
    if spec.expected_status != 200:
        return
    body = response.json()
    assert body["schema_version"] == "reproduction.v1"
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


def test_unknown_org_returns_400(client: TestClient) -> None:
    assert client.get("/v1/incidents/F1/reproduction?org=nope").status_code == 400
