import os
from pathlib import Path

# Must be set before any `app.db` import happens (its engine is created at
# import time), so this runs before pytest collects test_state_api.py.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://mei:mei@localhost:5432/mei_test")

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
