"""F1-F5 against the pure incident-context logic, with inputs derived from the
same scenario definitions the demo generator plants (scripts/demo/scenario.py)."""

import pytest

from app.incidents.context import (
    CommitInfo, IncidentInfo, ReleaseGraph, TicketInfo, build_incident_context,
)
from app.incidents.normalize import UnrecognizedPayload, normalize_event, normalize_frame
from app.orgs import load_org
from scripts.demo import scenario as sc

ORG = load_org("demo")
KEYS = {t.marker: f"MEI-{n}" for n, t in enumerate(sc.TICKETS, start=1)}  # stand-in for Jira-assigned keys


def _sha(spec: sc.CommitSpec) -> str:
    return f"sha-{spec.subject.lower().replace(' ', '-')}"


def _graph() -> ReleaseGraph:
    commits = {
        version: tuple(
            CommitInfo(
                sha=_sha(spec),
                message=sc.commit_message(spec, KEYS),
                files=tuple((path, ORG.component_for(path)) for path in spec.files),
                ticket_keys=tuple(ORG.ticket_keys(sc.commit_message(spec, KEYS))),
            )
            for spec in specs
        )
        for version, specs in sc.RELEASE_COMMITS.items()
    }
    tickets = {KEYS[t.marker]: TicketInfo(KEYS[t.marker], t.jira_summary, t.issue_type, "To Do") for t in sc.TICKETS}
    return ReleaseGraph(tagged_versions=sc.VERSIONS, commits=commits, tickets=tickets)


def _incident(spec: sc.IncidentSpec) -> IncidentInfo:
    release = ORG.sentry_release_for(spec.release)
    return IncidentInfo(
        sentry_issue_id=spec.case,
        title=f"{spec.exception_type}: {spec.exception_value}",
        culprit=None,
        first_release=release,
        first_release_version=ORG.version_from_sentry_release(release),
        frames=tuple(
            normalize_frame(ORG, {"filename": f.filename, "function": f.function, "lineno": f.lineno, "in_app": True})
            for f in spec.frames
        ),
    )


CASES = {spec.case: spec for spec in sc.INCIDENTS}
SUBJECT_TO_SHA = {spec.subject: _sha(spec) for specs in sc.RELEASE_COMMITS.values() for spec in specs}


def test_all_cases_covered() -> None:
    assert set(CASES) == {"F1", "F2", "F3", "F4", "F5"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_scenario(case: str) -> None:
    spec = CASES[case]
    context = build_incident_context(_incident(spec), _graph())

    assert context.release["state"] == spec.expected_release_state
    if spec.expected_suspects == "UNKNOWN":
        assert context.suspects == "UNKNOWN"
    else:
        assert [s.sha for s in context.suspects] == [SUBJECT_TO_SHA[s] for s in spec.expected_suspects]
    assert [f.code for f in context.findings] == list(spec.expected_findings)


def test_f1_suspect_carries_ticket_and_frame_evidence() -> None:
    context = build_incident_context(_incident(CASES["F1"]), _graph())
    (suspect,) = context.suspects
    assert suspect.ticket_keys == [KEYS["push-token-refresh"]]
    assert suspect.overlapping_files == ["src/modules/push/registration.ts"]
    assert suspect.evidence_frames == [
        {"path": "src/modules/push/registration.ts", "function": "refreshToken", "lineno": 42}
    ]
    assert context.release == {"version": "1.2.0", "state": "KNOWN", "previous": "1.1.0"}
    assert [t["key"] for t in context.tickets] == [KEYS["push-token-refresh"]]


def test_f3_unknown_release_has_no_commits_and_no_guess() -> None:
    context = build_incident_context(_incident(CASES["F3"]), _graph())
    assert context.release["version"] == "1.2.1"
    assert context.commits == [] and context.tickets == []


def test_f4_unknown_suspects_differs_from_no_suspects() -> None:
    f4 = build_incident_context(_incident(CASES["F4"]), _graph())
    f2 = build_incident_context(_incident(CASES["F2"]), _graph())
    assert f4.suspects == "UNKNOWN" and f2.suspects == []
    assert [e["value"] for e in f4.findings[0].evidence] == ["app:///main.3f9a1c.js"] * 2


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_finding_has_evidence(case: str) -> None:
    for finding in build_incident_context(_incident(CASES[case]), _graph()).findings:
        assert finding.code and finding.severity and finding.evidence


def test_first_release_suspects_are_unknown_not_empty() -> None:
    """Ingestion stores no change set for the first tag (nothing to diff
    against), so the graph has no 1.0.0 commits -- as in production."""
    spec = sc.IncidentSpec(case="X", release="1.0.0", exception_type="E", exception_value="v",
                           frames=(sc.Frame("app:///src/app/main.ts", "bootstrap", 1),), breadcrumbs=(), subjects=())
    graph = _graph()
    graph.commits.pop("1.0.0")
    context = build_incident_context(_incident(spec), graph)
    assert context.release == {"version": "1.0.0", "state": "KNOWN", "previous": None}
    assert context.suspects == "UNKNOWN"
    assert [f.code for f in context.findings] == ["NO_PREVIOUS_RELEASE"]


# ------------------------------------------------------------ normalization

API_EVENT = {  # shape of GET /issues/{id}/events/?full=true (verified against recordings in PR B)
    "eventID": "abc123", "groupID": "4501", "dateCreated": "2026-09-25T10:00:00Z",
    "user": {"id": "account-case-p3"},
    "tags": [{"key": "release", "value": "mei-demo-app@1.2.0"}, {"key": "installation_id", "value": "install-case-c"},
             {"key": "demo_case", "value": "F1"}],
    "contexts": {"os": {"name": "iOS"}},
    "entries": [
        {"type": "exception", "data": {"values": [{"type": "TypeError", "value": "boom", "stacktrace": {"frames": [
            {"filename": "app:///src/app/main.ts", "function": "bootstrap", "lineNo": 12, "inApp": True},
            {"filename": "app:///main.3f9a1c.js", "function": "n", "lineNo": 1, "inApp": True},
        ]}}]}},
        {"type": "breadcrumbs", "data": {"values": [{"category": "navigation", "data": {"to": "/home"}}]}},
    ],
}


def test_normalize_event_maps_api_shape() -> None:
    row = normalize_event(ORG, API_EVENT)
    assert row["release"] == "mei-demo-app@1.2.0"
    assert (row["user_id"], row["installation_id"]) == ("account-case-p3", "install-case-c")
    assert row["exception"] == {"type": "TypeError", "value": "boom"}
    assert [(f["path"], f["component"]) for f in row["frames"]] == [("src/app/main.ts", "app"), (None, None)]
    assert row["breadcrumbs"] == [{"category": "navigation", "data": {"to": "/home"}}]


def test_normalize_event_rejects_unknown_shape() -> None:
    with pytest.raises(UnrecognizedPayload):
        normalize_event(ORG, {"id": "x"})
