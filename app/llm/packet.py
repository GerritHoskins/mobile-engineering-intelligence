"""Evidence packets: the ONLY input the model sees.

Built from the deterministic outputs (release impact, reproduction). Every
citable fact gets a stable id derived from position or natural keys, so the
same data always yields the same packet -- and the same cache key. Fields are
whitelisted: user/installation/event identifiers never enter the packet.
"""

import hashlib
import json

from app.releases.impact import ReleaseImpact
from app.reproduction.reproduce import Reproduction


def _sha(sha: str) -> str:
    return sha[:7]


def _sanitize_evidence(evidence: list[dict]) -> list[dict]:
    """Keep what the facts are, drop who they are about."""
    allowed = ("source", "key", "value")
    return [{k: e[k] for k in allowed if k in e} for e in evidence]


def release_packet(impact: ReleaseImpact) -> dict:
    items: list[dict] = [
        {"id": "release", "version": impact.release["version"], "state": impact.release["state"],
         "previous": impact.release["previous"],
         "baseline": impact.baseline["version"] if impact.baseline else None},
        {"id": "metric-health", **impact.health.model_dump()},
        {"id": "metric-baseline_health",
         **(impact.baseline_health.model_dump() if impact.baseline_health else {"crash_free": "UNKNOWN"})},
        {"id": "metric-delta_pp", "value": impact.delta_pp if impact.delta_pp is not None else "NOT_COMPUTED"},
        {"id": "metric-error_volume_per_1k", "value": impact.error_volume_per_1k},
    ]
    if impact.change_set == "UNKNOWN":
        items.append({"id": "change_set", "value": "UNKNOWN"})
    else:
        for commit in impact.change_set["commits"]:
            items.append({"id": f"commit-{_sha(commit['sha'])}", "message": commit["message"],
                          "tickets": [f"ticket-{k}" for k in commit["ticket_keys"]]})
        for key in impact.change_set["tickets"]:
            items.append({"id": f"ticket-{key}", "key": key})
        items.append({"id": "components", "value": impact.change_set["components"]})
    for kind, issues in (("new", impact.new_issues), ("regressed", impact.regressed_issues)):
        for issue in issues:
            attribution = (issue.attribution if issue.attribution == "UNKNOWN"
                           else [f"commit-{_sha(s['sha'])}" for s in issue.attribution])
            items.append({"id": f"issue-{issue.id}", "kind": kind, "title": issue.title, "attribution": attribution})
    for n, finding in enumerate(impact.findings, start=1):
        items.append({"id": f"finding-{n}", "code": finding.code, "severity": finding.severity,
                      "evidence": _sanitize_evidence(finding.evidence)})
    return {"kind": "release_summary", "items": items}


def repro_packet(repro: Reproduction) -> dict:
    items: list[dict] = [
        {"id": "incident", "title": repro.incident["title"], "events_considered": repro.events_considered},
    ]
    for n, step in enumerate(repro.steps, start=1):
        items.append({"id": f"step-{n}", "kind": step.kind, "target": step.target, "support": step.support})
    for n, variant in enumerate(repro.variants, start=1):
        prefix = variant.prefix
        shown = prefix if len(prefix) <= 6 else prefix[:3] + [f"... {len(prefix) - 6} more steps ..."] + prefix[-3:]
        items.append({"id": f"variant-{n}", "prefix_length": len(prefix), "prefix": shown,
                      "events": len(variant.events)})
    for p in repro.preconditions:
        items.append({"id": f"precondition-{p.key}", "key": p.key, "value": p.value, "support": p.support,
                      "source": p.source})
    for v in repro.varies:
        items.append({"id": f"varies-{v.key}", "key": v.key,
                      "values": [{"value": c.value, "events": c.count} for c in v.values]})
    for n, gap in enumerate(repro.gaps, start=1):
        items.append({"id": f"gap-{n}", "code": gap.code, "events_affected": len(gap.event_ids),
                      **({"keys": gap.keys} if gap.keys else {})})
    failure = repro.expected_failure
    items.append({"id": "failure", "exception": failure.exception, "culprit_frame": failure.culprit_frame})
    if failure.suspects == "UNKNOWN":
        items.append({"id": "suspects", "value": "UNKNOWN"})
    else:
        for s in failure.suspects:
            items.append({"id": f"suspect-{_sha(s['sha'])}", "message": s["message"],
                          "overlapping_files": s["overlapping_files"]})
        if not failure.suspects:
            items.append({"id": "suspects", "value": "NONE_FOUND"})
    return {"kind": "repro_narrative", "items": items}


def canonical(packet: dict) -> str:
    return json.dumps(packet, sort_keys=True, separators=(",", ":"), default=str)


def input_hash(packet: dict, model: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt_version}\n{canonical(packet)}".encode()).hexdigest()


def ids(packet: dict) -> set[str]:
    return {item["id"] for item in packet["items"]}
