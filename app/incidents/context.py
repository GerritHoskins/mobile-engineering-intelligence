"""Incident context (vault milestone M1): Sentry issue -> release -> commits ->
changed files -> tickets, plus suspect commits whose changes overlap the
incident's stack frames.

Pure logic over already-ingested data: no database, no HTTP. The same
UNKNOWN discipline as Module 1 -- a missing release or unmappable frames is
reported as UNKNOWN with a finding, never coerced into "no suspects".
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel


# ------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    message: str
    files: tuple[tuple[str, str | None], ...]  # (path, component)
    ticket_keys: tuple[str, ...]


@dataclass(frozen=True)
class TicketInfo:
    key: str
    summary: str | None
    issue_type: str | None
    status: str | None
    missing_in_jira: bool = False


@dataclass(frozen=True)
class IncidentInfo:
    sentry_issue_id: str
    title: str
    culprit: str | None
    first_release: str | None  # Sentry release name
    first_release_version: str | None  # parsed via org config; None if not this app's naming
    frames: tuple[dict, ...]  # normalized frames (see app.incidents.normalize)


@dataclass(frozen=True)
class ReleaseGraph:
    tagged_versions: tuple[str, ...]  # semver order, oldest first
    commits: dict[str, tuple[CommitInfo, ...]] = field(default_factory=dict)  # version -> commits
    tickets: dict[str, TicketInfo] = field(default_factory=dict)


# ----------------------------------------------------------------- outputs


class Finding(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    evidence: list[dict]


class Suspect(BaseModel):
    sha: str
    message: str
    ticket_keys: list[str]
    overlapping_files: list[str]
    evidence_frames: list[dict]


class IncidentContext(BaseModel):
    incident: dict
    release: dict
    commits: list[dict]
    tickets: list[dict]
    suspects: list[Suspect] | Literal["UNKNOWN"]
    findings: list[Finding]


def semver_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in version.replace("-", ".").split("."))


def build_incident_context(incident: IncidentInfo, graph: ReleaseGraph) -> IncidentContext:
    findings: list[Finding] = []
    header = {
        "id": incident.sentry_issue_id,
        "title": incident.title,
        "culprit": incident.culprit,
        "first_release": incident.first_release,
    }

    # Step 1 - resolve the release where the incident first appeared. A release
    # without a git tag is UNKNOWN: never fall back to a guessed release.
    version = incident.first_release_version
    if version is None or version not in graph.tagged_versions:
        findings.append(Finding(
            code="RELEASE_NOT_FOUND", severity="WARNING",
            evidence=[{"source": "sentry", "key": "first_release", "value": incident.first_release}],
        ))
        return IncidentContext(
            incident=header, release={"version": version, "state": "UNKNOWN", "previous": None},
            commits=[], tickets=[], suspects="UNKNOWN", findings=findings,
        )

    index = graph.tagged_versions.index(version)
    previous = graph.tagged_versions[index - 1] if index > 0 else None
    commits = graph.commits.get(version, ())
    ticket_keys = sorted({k for c in commits for k in c.ticket_keys})
    tickets = [graph.tickets[k] for k in ticket_keys if k in graph.tickets]

    # Step 2 - map the stack to repo paths. No mappable frame at all means
    # suspects are UNKNOWN (e.g. a minified bundle without source maps).
    mapped = [f for f in incident.frames if f.get("path")]
    if not mapped:
        findings.append(Finding(
            code="FRAMES_UNMAPPABLE", severity="WARNING",
            evidence=[{"source": "sentry", "key": "frame", "value": f.get("raw_filename")}
                      for f in incident.frames] or [{"source": "sentry", "key": "frames", "value": None}],
        ))
        suspects: list[Suspect] | Literal["UNKNOWN"] = "UNKNOWN"
    else:
        # Step 3 - suspects: commits in this release touching a file in the
        # stack, ranked by how close to the crash the matching frame is
        # (frames are oldest-first; the crashing frame is last).
        depth = {f["path"]: i for i, f in enumerate(mapped)}
        ranked = []
        for commit in commits:
            overlap = sorted({p for p, _ in commit.files} & depth.keys(), key=lambda p: -depth[p])
            if overlap:
                ranked.append((max(depth[p] for p in overlap), commit, overlap))
        ranked.sort(key=lambda item: -item[0])
        suspects = [
            Suspect(
                sha=commit.sha, message=commit.message, ticket_keys=list(commit.ticket_keys),
                overlapping_files=overlap,
                evidence_frames=[
                    {k: f.get(k) for k in ("path", "function", "lineno")} for f in mapped if f["path"] in overlap
                ],
            )
            for _, commit, overlap in ranked
        ]
        if not suspects:
            findings.append(Finding(
                code="NO_SUSPECT_COMMIT", severity="INFO",
                evidence=[{"source": "sentry", "key": "frame_path", "value": f["path"]} for f in mapped],
            ))
        for suspect in suspects:
            if not suspect.ticket_keys:
                findings.append(Finding(
                    code="SUSPECT_WITHOUT_TICKET", severity="INFO",
                    evidence=[{"source": "git", "key": "commit", "value": suspect.sha}],
                ))

    return IncidentContext(
        incident=header,
        release={"version": version, "state": "KNOWN", "previous": previous},
        commits=[
            {"sha": c.sha, "message": c.message, "ticket_keys": list(c.ticket_keys),
             "files": [{"path": p, "component": comp} for p, comp in c.files]}
            for c in commits
        ],
        tickets=[
            {"key": t.key, "summary": t.summary, "issue_type": t.issue_type, "status": t.status,
             "missing_in_jira": t.missing_in_jira}
            for t in tickets
        ],
        suspects=suspects,
        findings=findings,
    )
