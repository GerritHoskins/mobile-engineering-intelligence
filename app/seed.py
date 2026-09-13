"""Deterministic, idempotent seed fixtures for scenarios A-M.

Concurrency caveat (plannotator review, P1): this uses a delete-then-insert
strategy per subject, all within one transaction. That is idempotent for
serial/manual runs (re-running produces identical rows) but is NOT race-safe
if two runs overlap -- a concurrent reader could observe a momentarily empty
window between delete and insert. Serial/manual execution is expected; this
is not a production seeding path.

Drift note (plannotator review, P2): fresh/stale below are relative to
SEED_REFERENCE_TIME, not to wall-clock "now" at query time -- evaluate_push_state
compares observed_at against real time, so these seeded "fresh" rows will
themselves read as stale once enough real time passes after seeding. That is
expected seed-data behavior, not a bug in the reconciliation logic.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import StateObservation

SEED_REFERENCE_TIME = datetime(2026, 9, 13, tzinfo=timezone.utc)
FRESH = SEED_REFERENCE_TIME - timedelta(days=1)
STALE = SEED_REFERENCE_TIME - timedelta(days=45)

SUBJECT_PREFIX = "install-case-"


@dataclass(frozen=True)
class ObservationSpec:
    source: str
    key: str
    value: object
    observed_at: datetime


def _backend(value: object, observed_at: datetime = FRESH) -> ObservationSpec:
    return ObservationSpec("backend", "enabled", value, observed_at)


def _os(value: object, observed_at: datetime = FRESH) -> ObservationSpec:
    return ObservationSpec("os", "permission", value, observed_at)


def _braze(value: object, observed_at: datetime = FRESH) -> ObservationSpec:
    return ObservationSpec("braze", "registration", value, observed_at)


# Mirrors the A-M scenario table in the vault's mvp_plan.md and the fixtures in
# tests/test_push_state_reconciliation.py -- kept as the single source of truth
# for both so seed data and tests can't silently drift apart.
SCENARIOS: dict[str, list[ObservationSpec]] = {
    "a": [_backend(True), _os("allowed"), _braze("registered")],
    "b": [_backend(False), _os("allowed"), _braze("registered")],
    "c": [_backend(True), _os("denied"), _braze("registered")],
    "d": [_backend(True), _os("allowed")],  # no braze observation -> MISSING
    "e": [_backend(True), _os("allowed"), _braze("not_registered")],
    "f": [_backend(True), _braze("registered")],  # no os observation -> capability UNKNOWN
    "g": [_os("allowed"), _braze("registered")],  # no backend observation -> desired UNKNOWN
    "h": [_backend(False), _os("denied"), _braze("registered")],
    "i": [_backend(True), _os("allowed"), _braze("registered", STALE)],
    "j": [_backend(True), _os("allowed"), _braze("registered")],
    "k": [_backend(False), _os("denied"), _braze("registered", STALE)],
    "l": [_os("denied"), _braze("registered")],  # no backend observation -> desired UNKNOWN
    "m": [_backend(True), _os("denied"), _braze("registered", STALE)],
}


def seed() -> None:
    session = SessionLocal()
    try:
        for case, specs in SCENARIOS.items():
            subject_id = f"{SUBJECT_PREFIX}{case}"
            session.query(StateObservation).filter_by(
                subject_type="installation", subject_id=subject_id, domain="push"
            ).delete()
            for spec in specs:
                session.add(
                    StateObservation(
                        subject_type="installation",
                        subject_id=subject_id,
                        domain="push",
                        source=spec.source,
                        key=spec.key,
                        value=spec.value,
                        observed_at=spec.observed_at,
                    )
                )
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    seed()
    print(f"Seeded {len(SCENARIOS)} installations ({SUBJECT_PREFIX}a .. {SUBJECT_PREFIX}m).")
