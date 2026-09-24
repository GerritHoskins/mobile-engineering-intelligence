"""Types and helpers shared by every consistency domain (push, profile)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class RawObservation(BaseModel):
    """Minimal shape the evaluators need from a StateObservation row."""

    source: str
    key: str
    value: Any
    observed_at: datetime


class Evidence(BaseModel):
    source: str
    key: str
    value: Any
    observed_at: datetime


class ConsistencyIssue(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    remediation: Literal["USER_ACTION_REQUIRED", "BACKEND_SYNC_NEEDED", "NONE"]
    evidence: list[Evidence]


class UnrecognizedObservationValue(ValueError):
    pass


def latest_per_key(observations: list[RawObservation]) -> dict[tuple[str, str], RawObservation]:
    """Newest observation per (source, key). Production callers already dedup
    via the `observed_at DESC` window in SQL; this keeps evaluators correct
    when handed un-deduped fixtures directly."""
    latest: dict[tuple[str, str], RawObservation] = {}
    for obs in observations:
        existing = latest.get((obs.source, obs.key))
        if existing is None or obs.observed_at > existing.observed_at:
            latest[(obs.source, obs.key)] = obs
    return latest


def evidence_from(obs: RawObservation) -> Evidence:
    return Evidence(source=obs.source, key=obs.key, value=obs.value, observed_at=obs.observed_at)


def evidence_for(observations: list[RawObservation], source: str, key: str) -> list[Evidence]:
    latest = latest_per_key(observations).get((source, key))
    return [evidence_from(latest)] if latest else []
