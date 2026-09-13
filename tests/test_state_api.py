from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("_truncate_state_observation")


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _add_observation(session, subject_id: str, source: str, key: str, value, observed_at) -> None:
    from app.models import StateObservation

    session.add(
        StateObservation(
            subject_type="installation",
            subject_id=subject_id,
            domain="push",
            source=source,
            key=key,
            value=value,
            observed_at=observed_at,
        )
    )
    session.commit()


@pytest.fixture()
def db_session():
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_invalid_subject_type_returns_400(client: TestClient) -> None:
    response = client.get("/v1/state/device/install-case-a")
    assert response.status_code == 400


def test_omitted_domain_defaults_to_push(client: TestClient, db_session) -> None:
    _add_observation(
        db_session, "install-case-a", "backend", "enabled", True, datetime.now(timezone.utc)
    )
    response = client.get("/v1/state/installation/install-case-a")
    assert response.status_code == 200
    assert response.json()["domain"] == "push"


def test_explicit_domain_push_matches_omitted_default(client: TestClient, db_session) -> None:
    _add_observation(
        db_session, "install-case-a", "backend", "enabled", True, datetime.now(timezone.utc)
    )
    omitted = client.get("/v1/state/installation/install-case-a").json()
    explicit = client.get("/v1/state/installation/install-case-a?domain=push").json()
    assert omitted == explicit


def test_invalid_domain_returns_400(client: TestClient) -> None:
    response = client.get("/v1/state/installation/install-case-a?domain=profile")
    assert response.status_code == 400


def test_empty_observation_subject_returns_200_with_unknown_contract(client: TestClient) -> None:
    response = client.get("/v1/state/installation/install-case-nonexistent")
    assert response.status_code == 200
    body = response.json()
    assert body["desired_state"] == {"push_enabled": "UNKNOWN"}
    assert body["capability_state"] == {"os_permission": "UNKNOWN"}
    assert body["registration_state"] == {"provider_registration": "UNKNOWN"}
    assert body["effective_state"] == {"deliverable": None}
    assert body["consistency_issues"] == []


@pytest.mark.parametrize(
    # Values containing "/" or "." segments are deliberately excluded: httpx's
    # own RFC 3986 path normalization rewrites those before the request even
    # reaches our server, so they'd test client-side URL normalization rather
    # than our subject_id handling.
    "subject_id",
    ["   ", "x" * 500, "🙂-install", "install_case_0"],
)
def test_unusual_subject_id_still_follows_empty_observation_contract(
    client: TestClient, subject_id: str
) -> None:
    response = client.get(f"/v1/state/installation/{subject_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["effective_state"] == {"deliverable": None}
    assert body["consistency_issues"] == []


def test_scenario_c_style_subject_returns_expected_issue(client: TestClient, db_session) -> None:
    now = datetime.now(timezone.utc)
    _add_observation(db_session, "install-case-c", "backend", "enabled", True, now)
    _add_observation(db_session, "install-case-c", "os", "permission", "denied", now)
    _add_observation(db_session, "install-case-c", "braze", "registration", "registered", now)

    response = client.get("/v1/state/installation/install-case-c")
    assert response.status_code == 200
    body = response.json()
    assert body["effective_state"] == {"deliverable": False}
    assert [issue["code"] for issue in body["consistency_issues"]] == ["OS_PERMISSION_BLOCKS_PUSH"]
