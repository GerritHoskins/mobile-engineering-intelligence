from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.incidents.repository import load_release_graph
from app.orgs import available_orgs, load_org
from app.releases.impact import build_release_impact
from app.releases.repository import load_release_issues, load_session_totals, release_exists

router = APIRouter(prefix="/v1/releases")

DEFAULT_ORG = "demo"


@router.get("/{version}/impact")
def get_release_impact(
    version: str,
    org: str = Query(default=DEFAULT_ORG),
    baseline: str | None = Query(default=None, description="Tagged version to compare against; default: previous"),
    session: Session = Depends(get_session),
) -> dict:
    if org not in available_orgs():
        raise HTTPException(status_code=400, detail=f"Unknown org: {org!r}")
    config = load_org(org)
    if not release_exists(session, config, version):
        raise HTTPException(status_code=404, detail=f"Release {version!r} not ingested for org {org!r}")
    graph = load_release_graph(session, config)
    if baseline is not None and baseline not in graph.tagged_versions:
        raise HTTPException(status_code=400, detail=f"Baseline {baseline!r} is not a tagged release")
    new, regressed = load_release_issues(session, config, version)
    impact = build_release_impact(
        version, graph, config.impact, load_session_totals(session, config, datetime.now(timezone.utc)),
        new, regressed, baseline_version=baseline,
    )
    return impact.model_dump(mode="json")
