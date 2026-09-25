"""RI1-RI6 through ingestion (fake connectors, incl. the planted regression)
and the /v1/releases API on the real mei_test Postgres."""

import pytest
from fastapi.testclient import TestClient

from scripts.demo import scenario as sc
from tests.test_incident_ingest_api import _ingest

pytestmark = pytest.mark.usefixtures("_truncate_incident_tables")


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    _ingest()
    return TestClient(app)


@pytest.mark.parametrize("spec", sc.IMPACTS, ids=lambda s: s.case)
def test_impact_api_matches_scenario(client: TestClient, spec: sc.ImpactSpec) -> None:
    response = client.get(f"/v1/releases/{spec.release}/impact")
    assert response.status_code == spec.expected_status
    if spec.expected_status != 200:
        return
    body = response.json()
    assert body["release"]["state"] == spec.expected_release_state
    if spec.expected_crash_free == "UNKNOWN":
        assert body["health"]["crash_free"] == "UNKNOWN"
    else:
        assert body["health"]["crash_free"] == pytest.approx(spec.expected_crash_free)
    assert [f["code"] for f in body["findings"]] == list(spec.expected_findings)
    assert [i["id"] for i in body["new_issues"]] == list(spec.expected_new_issues)
    assert [i["id"] for i in body["regressed_issues"]] == list(spec.expected_regressed_issues)


def test_regression_is_ingested_with_its_release(client: TestClient) -> None:
    from app.db import SessionLocal
    from app.models import Incident

    with SessionLocal() as session:
        f2 = session.get(Incident, ("demo", sc.REGRESSION_CASE))
    assert (f2.first_release, f2.regressed_release, f2.substatus) == (
        "mei-demo-app@1.2.0", "mei-demo-app@1.3.0", "regressed")


def test_baseline_must_be_a_tagged_release(client: TestClient) -> None:
    response = client.get("/v1/releases/1.3.0/impact?baseline=1.2.1")
    assert response.status_code == 400 and "not a tagged release" in response.json()["detail"]


def test_unknown_org_returns_400(client: TestClient) -> None:
    assert client.get("/v1/releases/1.2.0/impact?org=nope").status_code == 400
