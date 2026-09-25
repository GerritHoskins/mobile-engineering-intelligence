"""Release Impact Analyzer: what changed in release X, what measurably
happened, and which change most likely caused it.

Pure logic over already-ingested data. Health comes from raw session counts
(never Sentry's crash_free_rate); a sample too small to judge is UNKNOWN,
never "fine". New-issue attribution reuses the incident context (Slice F).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.incidents.context import Finding, IncidentInfo, ReleaseGraph, build_incident_context
from app.orgs import ImpactConfig


@dataclass(frozen=True)
class SessionTotals:
    sessions: int  # settled buckets only
    crashed: int
    pending_buckets: int = 0  # buckets too recent to trust yet


@dataclass(frozen=True)
class IssueInput:
    incident: IncidentInfo
    event_count: int  # events of this issue in the analyzed release


class Health(BaseModel):
    sessions: int
    crashed: int
    crash_free: float | Literal["UNKNOWN", "PENDING"]


class IssueImpact(BaseModel):
    id: str
    title: str
    attribution: list[dict] | Literal["UNKNOWN"]


class ReleaseImpact(BaseModel):
    release: dict
    baseline: dict | None
    change_set: dict | Literal["UNKNOWN"]
    health: Health
    baseline_health: Health | None
    delta_pp: float | Literal["UNKNOWN"] | None
    error_volume_per_1k: float | Literal["UNKNOWN"]
    new_issues: list[IssueImpact]
    regressed_issues: list[IssueImpact]
    findings: list[Finding]


def health_of(totals: SessionTotals | None, config: ImpactConfig) -> tuple[Health, str | None]:
    """Health plus the finding code that explains an unusable sample, if any."""
    if totals is None or (totals.sessions == 0 and totals.pending_buckets == 0):
        return Health(sessions=0, crashed=0, crash_free="UNKNOWN"), "NO_SESSION_DATA"
    if totals.sessions == 0:
        return Health(sessions=0, crashed=0, crash_free="PENDING"), "HEALTH_PENDING"
    if totals.sessions < config.min_sessions:
        return Health(sessions=totals.sessions, crashed=totals.crashed, crash_free="UNKNOWN"), "INSUFFICIENT_ADOPTION"
    rate = round(1 - totals.crashed / totals.sessions, 6)
    return Health(sessions=totals.sessions, crashed=totals.crashed, crash_free=rate), None


def _health_evidence(version: str, health: Health) -> dict:
    return {"source": "sentry", "key": "release_health", "value": {"release": version, **health.model_dump()}}


def _attribution(context) -> tuple[list[dict] | Literal["UNKNOWN"], str]:
    if context.suspects == "UNKNOWN":
        return "UNKNOWN", "NEW_ISSUE_ATTRIBUTION_UNKNOWN"
    suspects = [s.model_dump() for s in context.suspects]
    return suspects, "NEW_ISSUE_ATTRIBUTED" if suspects else "NEW_ISSUE_UNATTRIBUTED"


def build_release_impact(
    version: str,
    graph: ReleaseGraph,
    config: ImpactConfig,
    totals: dict[str, SessionTotals],  # version -> settled totals
    new_issues: list[IssueInput],  # issues first seen in `version`
    regressed_issues: list[IssueInput],  # issues that regressed in `version`
    baseline_version: str | None = None,
) -> ReleaseImpact:
    findings: list[Finding] = []
    tagged = version in graph.tagged_versions

    # Step 1 - release and change set. An untagged release has no change set
    # (UNKNOWN), and is never used as someone's baseline.
    if tagged:
        index = graph.tagged_versions.index(version)
        previous = graph.tagged_versions[index - 1] if index > 0 else None
        commits = graph.commits.get(version, ())
        keys = sorted({k for c in commits for k in c.ticket_keys})
        change_set = {
            "commits": [{"sha": c.sha, "message": c.message, "ticket_keys": list(c.ticket_keys)} for c in commits],
            "tickets": [k for k in keys],
            "components": sorted({comp for c in commits for _, comp in c.files if comp}),
        }
    else:
        previous = None
        change_set = "UNKNOWN"
        findings.append(Finding(code="RELEASE_NOT_FOUND", severity="WARNING",
                                evidence=[{"source": "git", "key": "tag", "value": None, "release": version}]))
    baseline = baseline_version if baseline_version is not None else previous

    # Step 2 - health of this release, then of the baseline.
    health, health_problem = health_of(totals.get(version), config)
    if health_problem:
        severity = "INFO" if health_problem == "HEALTH_PENDING" else "WARNING"
        findings.append(Finding(code=health_problem, severity=severity, evidence=[_health_evidence(version, health)]))

    baseline_health = None
    delta: float | Literal["UNKNOWN"] | None = None
    if baseline is not None:
        baseline_health, baseline_problem = health_of(totals.get(baseline), config)
        known = isinstance(health.crash_free, float) and isinstance(baseline_health.crash_free, float)
        if known:
            delta = round((health.crash_free - baseline_health.crash_free) * 100, 4)
            evidence = [_health_evidence(version, health), _health_evidence(baseline, baseline_health)]
            if delta <= -config.crash_regression_pp:
                findings.insert(0, Finding(code="CRASH_RATE_REGRESSION", severity="ERROR", evidence=evidence))
            elif delta >= config.crash_regression_pp:
                findings.insert(0, Finding(code="CRASH_RATE_IMPROVED", severity="INFO", evidence=evidence))
        else:
            delta = "UNKNOWN"
            if baseline_problem and not health_problem:
                findings.append(Finding(code="NO_BASELINE_HEALTH", severity="INFO",
                                        evidence=[_health_evidence(baseline, baseline_health)]))

    # Step 3 - error volume, only when the sample is trustworthy.
    if isinstance(health.crash_free, float):
        events = sum(issue.event_count for issue in new_issues + regressed_issues)
        error_volume: float | Literal["UNKNOWN"] = round(events / health.sessions * 1000, 3)
    else:
        error_volume = "UNKNOWN"

    # Step 4 - new issues, attributed through their incident context.
    new: list[IssueImpact] = []
    for issue in new_issues:
        attribution, code = _attribution(build_incident_context(issue.incident, graph))
        new.append(IssueImpact(id=issue.incident.sentry_issue_id, title=issue.incident.title, attribution=attribution))
        findings.append(Finding(code=code, severity="INFO" if attribution == "UNKNOWN" else "WARNING", evidence=[
            {"source": "sentry", "key": "issue", "value": issue.incident.sentry_issue_id},
            *([{"source": "git", "key": "commit", "value": s["sha"]} for s in attribution]
              if attribution != "UNKNOWN" else []),
        ]))

    # Step 5 - regressed issues: attributed against THIS release's change set,
    # since that's where the regression appeared.
    regressed: list[IssueImpact] = []
    for issue in regressed_issues:
        as_of_this_release = IncidentInfo(
            sentry_issue_id=issue.incident.sentry_issue_id, title=issue.incident.title,
            culprit=issue.incident.culprit, first_release=issue.incident.first_release,
            first_release_version=version, frames=issue.incident.frames,
        )
        attribution, _ = _attribution(build_incident_context(as_of_this_release, graph))
        regressed.append(IssueImpact(id=issue.incident.sentry_issue_id, title=issue.incident.title,
                                     attribution=attribution))
        findings.append(Finding(code="ISSUE_REGRESSED", severity="WARNING", evidence=[
            {"source": "sentry", "key": "issue", "value": issue.incident.sentry_issue_id},
            {"source": "sentry", "key": "regressed_in", "value": version},
        ]))

    return ReleaseImpact(
        release={"version": version, "state": "KNOWN" if tagged else "UNKNOWN", "previous": previous},
        baseline={"version": baseline} if baseline is not None else None,
        change_set=change_set,
        health=health,
        baseline_health=baseline_health,
        delta_pp=delta,
        error_volume_per_1k=error_volume,
        new_issues=new,
        regressed_issues=regressed,
        findings=findings,
    )
