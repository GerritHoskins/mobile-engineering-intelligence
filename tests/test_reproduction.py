"""RP1-RP6 against the pure reproduction logic. Events come from the demo
scenario (scripts/demo/scenario.py); Module 1 state from the real seed
definitions (app/seed.py), evaluated at a fixed time so nothing here can
change on a date."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.orgs import ReproConfig, load_org
from app.reconciliation.common import RawObservation
from app.reconciliation.profile_state import evaluate_profile_state
from app.reconciliation.push_state import evaluate_push_state
from app.reproduction.reproduce import EventInput, Reproduction, build_reproduction, normalize_step
from app.seed import PROFILE_SCENARIOS, PROFILE_SUBJECT_PREFIX, SCENARIOS, SEED_REFERENCE_TIME, SUBJECT_PREFIX
from scripts.demo import scenario as sc
from tests.test_incident_context import SUBJECT_TO_SHA, _graph, _incident

ORG = load_org("demo")
NOW = SEED_REFERENCE_TIME + timedelta(days=1)
CASES = {spec.case: spec for spec in sc.ALL_INCIDENTS}


def _raw(specs) -> list[RawObservation]:
    return [RawObservation(source=s.source, key=s.key, value=s.value, observed_at=s.observed_at) for s in specs]


def lookup(subject_type: str, subject_id: str, domain: str) -> dict | None:
    if domain == "push":
        specs = SCENARIOS.get(subject_id.removeprefix(SUBJECT_PREFIX))
        return evaluate_push_state(_raw(specs), now=NOW).model_dump() if specs else None
    specs = PROFILE_SCENARIOS.get(subject_id.removeprefix(PROFILE_SUBJECT_PREFIX))
    return evaluate_profile_state(_raw(specs)).model_dump() if specs else None


def _event(spec: sc.IncidentSpec, index: int, subject: sc.Subject, release: str) -> EventInput:
    return EventInput(
        event_id=f"{spec.case}-{index}", release=ORG.sentry_release_for(release),
        user_id=subject.user_id, installation_id=subject.installation_id,
        exception={"type": spec.exception_type, "value": spec.exception_value},
        breadcrumbs=sc.breadcrumbs_for(spec, index),
        contexts={"device": {"family": "iOS", "model": "iPhone15,2"}, "os": {"name": "iOS", "version": "18.4"},
                  "app": {"app_version": release}},
        tags={"demo_case": spec.case, "installation_id": subject.installation_id, **spec.flags},
    )


def _events(spec: sc.IncidentSpec) -> list[EventInput]:
    events = [_event(spec, i, s, spec.release) for i, s in enumerate(spec.subjects)]
    if spec.case == sc.REGRESSION_CASE:  # the planted 1.3.0 regression event
        events.append(_event(spec, len(events), sc.REGRESSION_SUBJECT, sc.REGRESSION_RELEASE))
    return events


def _reproduce(case: str) -> Reproduction:
    spec = CASES[case]
    return build_reproduction(_incident(spec), _events(spec), _graph(), lookup, ORG.repro)


REPROS = {spec.case: spec for spec in sc.REPROS if spec.expected_status == 200}


@pytest.mark.parametrize("case", sorted(REPROS))
def test_scenario(case: str) -> None:
    spec = REPROS[case]
    repro = _reproduce(spec.incident)

    assert [s.key for s in repro.steps] == list(spec.expected_steps)
    assert len(repro.variants) == spec.expected_variants
    preconditions = {p.key: p.value for p in repro.preconditions}
    for key, value in spec.expected_preconditions.items():
        assert preconditions.get(key) == value, key
    varies = {v.key for v in repro.varies}
    assert set(spec.expected_varies) <= varies
    assert not set(spec.expected_varies) & set(preconditions)  # never both
    assert [g.code for g in repro.gaps] == list(spec.expected_gaps)
    suspects = repro.expected_failure.suspects
    if spec.expected_suspects == "UNKNOWN":
        assert suspects == "UNKNOWN"
    else:
        assert [s["sha"] for s in suspects] == [SUBJECT_TO_SHA[s] for s in spec.expected_suspects]


def test_rp2_variants_and_truncation_point_at_the_right_events() -> None:
    repro = _reproduce("F6")
    assert [v.events for v in repro.variants] == [["F6-0"], ["F6-1"], ["F6-2"]]
    assert repro.variants[0].prefix == ["NAVIGATE /home", "NAVIGATE /settings"]
    assert repro.variants[1].prefix == ["LIFECYCLE foreground", "NAVIGATE /inbox"]
    assert len(repro.variants[2].prefix) == sc.MAX_BREADCRUMBS - 3
    (gap,) = repro.gaps
    assert gap.event_ids == ["F6-2"]
    assert repro.expected_failure.culprit_frame == {
        "path": "src/modules/push/permission.ts", "function": "requestPermission", "lineno": 27}


def test_rp1_state_that_differs_between_events_is_never_a_precondition() -> None:
    repro = _reproduce("F1")
    os_permission = next(v for v in repro.varies if v.key == "push.os_permission")
    assert {(c.value, c.count) for c in os_permission.values} == {("ALLOWED", 2), ("DENIED", 1)}
    assert "push.os_permission" not in {p.key for p in repro.preconditions}


def test_single_event_and_missing_breadcrumbs_are_gaps() -> None:
    spec = CASES["F5"]
    event = _events(spec)[0]
    empty = EventInput(**{**event.__dict__, "event_id": "empty", "breadcrumbs": ()})
    repro = build_reproduction(_incident(spec), [empty], _graph(), lookup, ORG.repro)
    assert [g.code for g in repro.gaps] == ["NO_BREADCRUMBS", "SINGLE_EVENT"]
    assert repro.steps == []


def test_unknown_subjects_are_a_gap_not_a_guess() -> None:
    spec = CASES["F5"]
    events = [EventInput(**{**e.__dict__, "user_id": None, "installation_id": "install-nobody"}) for e in _events(spec)]
    repro = build_reproduction(_incident(spec), events, _graph(), lookup, ORG.repro)
    (gap,) = [g for g in repro.gaps if g.code == "ACCOUNT_STATE_UNKNOWN"]
    assert set(gap.keys) == {"push.deliverable", "push.os_permission", "push.provider_registration",
                             "profile.consistent"}
    assert not [p for p in repro.preconditions if p.source.startswith("module1")]


def test_softer_min_support_turns_a_majority_into_a_precondition() -> None:
    spec = CASES["F1"]
    repro = build_reproduction(_incident(spec), _events(spec), _graph(), lookup, ReproConfig(min_support=0.6))
    assert {p.key: p.value for p in repro.preconditions}["push.os_permission"] == "ALLOWED"


@pytest.mark.parametrize("crumb, key", [
    ({"category": "app.lifecycle", "data": {"state": "foreground"}}, "LIFECYCLE foreground"),
    ({"category": "navigation", "data": {"from": "/a", "to": "/b"}}, "NAVIGATE /b"),
    ({"category": "ui.click", "message": "button#x"}, "TAP button#x"),
    ({"category": "xhr", "data": {"method": "GET", "url": "https://api.x/v1/a?q=1", "status_code": 500}},
     "BACKEND_CALL GET /v1/a 500"),
    ({"category": "console", "message": "hi"}, "UNMAPPED console"),
])
def test_normalize_step(crumb: dict, key: str) -> None:
    assert normalize_step(crumb).key == key


def test_committed_schema_matches_the_model() -> None:
    """Exporters rely on reproduction.v1: any model change must regenerate the
    committed schema (and bump the version if it isn't backwards compatible)."""
    committed = json.loads((Path(__file__).parents[1] / "app/reproduction/reproduction.v1.schema.json").read_text())
    generated = {**Reproduction.model_json_schema(), "$id": "reproduction.v1"}
    assert committed == generated
