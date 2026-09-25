import os
from pathlib import Path

from urllib.parse import urlparse

# Tests truncate tables, so they must never run against a real database.
# DATABASE_URL from the shell is deliberately ignored (a shell exported for the
# dev DB once made pytest wipe it); tests use TEST_DATABASE_URL, defaulting to
# mei_test, and refuse any database whose name doesn't end in "_test".
# Must be set before any `app.db` import happens (its engine is created at
# import time), so this runs before pytest collects the test modules.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://mei:mei@localhost:5432/mei_test")
if not urlparse(TEST_DATABASE_URL).path.rstrip("/").endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against a non-test database: {TEST_DATABASE_URL}")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def _migrate_test_database() -> None:
    """Runs the same Alembic-managed schema pytest and manual verification
    both use, per the vault's requirement that they can't silently drift
    apart. Not autouse: only tests that actually hit the DB (test_state_api.py)
    should depend on this."""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture()
def _truncate_state_observation(_migrate_test_database: None) -> None:
    """Function-scoped isolation (plannotator review, P1): test_state_api.py
    runs against a real, shared Postgres, so each test must not leak rows into
    the next one. Not autouse: opt in via pytestmark in test_state_api.py so
    pure reconciliation-logic tests keep no DB dependency."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        session.execute(text("TRUNCATE TABLE state_observation"))
        session.commit()
    finally:
        session.close()
    yield


INCIDENT_TABLES = (
    "release", "commit", "release_commit", "changed_file", "ticket", "commit_ticket",
    "incident", "incident_event", "release_session_count",
)


@pytest.fixture()
def _truncate_incident_tables(_migrate_test_database: None) -> None:
    """Same isolation as above, for the Slice F tables."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        session.execute(text(f"TRUNCATE TABLE {', '.join(INCIDENT_TABLES)}"))
        session.commit()
    finally:
        session.close()
    yield
