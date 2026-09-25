"""RI1-RI6 against the pure release-impact logic, with inputs derived from the
demo scenario (scripts/demo/scenario.py) -- the same ground truth the live
sweep checks."""

import pytest

from app.orgs import ImpactConfig, load_org
from app.releases.impact import IssueInput, SessionTotals, build_release_impact, health_of
from scripts.demo import scenario as sc
from tests.test_incident_context import _graph, _incident

ORG = load_org("demo")
CASES = {spec.case: spec for spec in sc.INCIDENTS}
TOTALS = {v: SessionTotals(sessions=t, crashed=c) for v, (t, c) in sc.SESSIONS.items()}


def _issues(version: str) -> tuple[list[IssueInput], list[IssueInput]]:
    new = [IssueInput(_incident(s), len(s.subjects)) for s in sc.INCIDENTS if s.release == version]
    regressed = ([IssueInput(_incident(CASES[sc.REGRESSION_CASE]), 1)]
                 if version == sc.REGRESSION_RELEASE else [])
    return new, regressed


def _impact(version: str):
    new, regressed = _issues(version)
    return build_release_impact(version, _graph(), ORG.impact, TOTALS, new, regressed)


IMPACTS = {spec.case: spec for spec in sc.IMPACTS if spec.expected_status == 200}


@pytest.mark.parametrize("case", sorted(IMPACTS))
def test_scenario(case: str) -> None:
    spec = IMPACTS[case]
    impact = _impact(spec.release)

    assert impact.release["state"] == spec.expected_release_state
    if spec.expected_crash_free == "UNKNOWN":
        assert impact.health.crash_free == "UNKNOWN"
    else:
        assert impact.health.crash_free == pytest.approx(spec.expected_crash_free)
    assert [f.code for f in impact.findings] == list(spec.expected_findings)
    assert [i.id for i in impact.new_issues] == list(spec.expected_new_issues)
    assert [i.id for i in impact.regressed_issues] == list(spec.expected_regressed_issues)


def test_ri2_regression_delta_and_attribution() -> None:
    impact = _impact("1.2.0")
    assert impact.baseline == {"version": "1.1.0"}
    assert impact.delta_pp == pytest.approx(-9.0)
    attribution = {i.id: i.attribution for i in impact.new_issues}
    assert [s["message"] for s in attribution["F1"]] == ["MEI-3: Refresh push token on resume"]
    assert [s["message"] for s in attribution["F5"]] == ["Clean up router"]
    assert attribution["F2"] == []  # checked, nothing touched the stack
    assert impact.error_volume_per_1k == pytest.approx(7 / 400 * 1000)  # F1 3 + F2 2 + F5 2 events


def test_ri3_regressed_issue_is_attributed_against_this_release() -> None:
    (regressed,) = _impact("1.3.0").regressed_issues
    assert regressed.id == "F2" and regressed.attribution == []  # 1.3.0 only touched the profile store


def test_ri4_small_sample_reports_no_rate_and_no_delta() -> None:
    impact = _impact("1.4.0")
    assert impact.health.sessions == 15 and impact.health.crash_free == "UNKNOWN"
    assert impact.delta_pp == "UNKNOWN" and impact.error_volume_per_1k == "UNKNOWN"
    assert [c["message"] for c in impact.change_set["commits"]] == ["MEI-5: Tweak saved-search defaults"]


def test_ri5_untagged_release_has_unknown_change_set_and_no_baseline() -> None:
    impact = _impact("1.2.1")
    assert impact.change_set == "UNKNOWN" and impact.baseline is None
    assert [i.attribution for i in impact.new_issues] == ["UNKNOWN"]


def test_explicit_baseline_overrides_previous_release() -> None:
    new, regressed = _issues("1.3.0")
    impact = build_release_impact("1.3.0", _graph(), ORG.impact, TOTALS, new, regressed, baseline_version="1.1.0")
    assert impact.baseline == {"version": "1.1.0"}
    assert impact.delta_pp == pytest.approx(0.25)  # within threshold: no CRASH_RATE_* finding
    assert not [f for f in impact.findings if f.code.startswith("CRASH_RATE")]


@pytest.mark.parametrize("totals, expected", [
    (None, ("UNKNOWN", "NO_SESSION_DATA")),
    (SessionTotals(0, 0, pending_buckets=2), ("PENDING", "HEALTH_PENDING")),
    (SessionTotals(99, 0), ("UNKNOWN", "INSUFFICIENT_ADOPTION")),
    (SessionTotals(100, 1), (0.99, None)),
])
def test_health_gates(totals, expected) -> None:
    health, problem = health_of(totals, ImpactConfig(min_sessions=100))
    assert (health.crash_free, problem) == expected


@pytest.mark.parametrize("case", sorted(IMPACTS))
def test_every_finding_has_evidence(case: str) -> None:
    for finding in _impact(IMPACTS[case].release).findings:
        assert finding.code and finding.severity and finding.evidence
