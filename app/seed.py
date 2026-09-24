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


# Profile domain (account-scoped). Mirrors the P1-P10 table in
# tests/test_profile_state_reconciliation.py. Only the *ordering* of copy vs
# authoritative observed_at matters here, so unlike push there is no
# wall-clock drift.
PROFILE_SUBJECT_PREFIX = "account-case-"
BEFORE = SEED_REFERENCE_TIME - timedelta(days=3)
AUTHORITY_AT = SEED_REFERENCE_TIME - timedelta(days=2)
AFTER = SEED_REFERENCE_TIME - timedelta(days=1)

EMAIL = "anna@example.de"
OTHER_EMAIL = "anna.old@example.de"
POSTAL = "01067"
OTHER_POSTAL = "10115"


def _auth_email(value: object = EMAIL) -> ObservationSpec:
    return ObservationSpec("auth", "email", value, AUTHORITY_AT)


def _backend_field(key: str, value: object, observed_at: datetime) -> ObservationSpec:
    return ObservationSpec("backend", key, value, observed_at)


def _job_profile(key: str, value: object) -> ObservationSpec:
    return ObservationSpec("job_profile", key, value, AFTER)


_BACKEND_POSTAL = _backend_field("postal_code", POSTAL, AUTHORITY_AT)

PROFILE_SCENARIOS: dict[str, list[ObservationSpec]] = {
    "p1": [_auth_email(), _backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", EMAIL), _job_profile("postal_code", POSTAL)],
    "p2": [_auth_email("Anna@Example.DE"), _backend_field("email", "  anna@example.de ", AFTER),
           _BACKEND_POSTAL, _job_profile("email", "ANNA@example.de"), _job_profile("postal_code", f" {POSTAL}")],
    "p3": [_auth_email(), _backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", OTHER_EMAIL), _job_profile("postal_code", POSTAL)],
    "p4": [_auth_email(), _backend_field("email", OTHER_EMAIL, BEFORE), _BACKEND_POSTAL,
           _job_profile("email", EMAIL), _job_profile("postal_code", POSTAL)],
    "p5": [_auth_email(), _backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL],  # no job profile
    "p6": [_auth_email(), _backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", EMAIL)],  # job profile has no postal_code
    "p7": [_backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", OTHER_EMAIL), _job_profile("postal_code", POSTAL)],  # no auth
    "p8": [_backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", EMAIL), _job_profile("postal_code", OTHER_POSTAL)],
    "p9": [_auth_email(), _backend_field("email", EMAIL, AFTER), _BACKEND_POSTAL,
           _job_profile("email", OTHER_EMAIL)],
    "p10": [_auth_email(), _backend_field("email", OTHER_EMAIL, BEFORE), _BACKEND_POSTAL,
            _job_profile("email", "anna.new@example.de"), _job_profile("postal_code", POSTAL)],
}

# (subject_type, domain, subject_id prefix, scenarios)
SEED_SETS = [
    ("installation", "push", SUBJECT_PREFIX, SCENARIOS),
    ("account", "profile", PROFILE_SUBJECT_PREFIX, PROFILE_SCENARIOS),
]


def seed() -> None:
    session = SessionLocal()
    try:
        for subject_type, domain, prefix, scenarios in SEED_SETS:
            for case, specs in scenarios.items():
                subject_id = f"{prefix}{case}"
                session.query(StateObservation).filter_by(
                    subject_type=subject_type, subject_id=subject_id, domain=domain
                ).delete()
                for spec in specs:
                    session.add(
                        StateObservation(
                            subject_type=subject_type,
                            subject_id=subject_id,
                            domain=domain,
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
    print(
        f"Seeded {len(PROFILE_SCENARIOS)} accounts "
        f"({PROFILE_SUBJECT_PREFIX}p1 .. {PROFILE_SUBJECT_PREFIX}p10)."
    )
