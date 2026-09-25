from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.incidents.repository import load_release_graph
from app.orgs import available_orgs, load_org
from app.llm.client import LLMClient, LLMError
from app.llm.packet import release_packet
from app.llm.service import default_client, explain
from app.releases.impact import build_release_impact
from app.releases.repository import load_release_issues, load_session_totals, release_exists

router = APIRouter(prefix="/v1/releases")

DEFAULT_ORG = "demo"


def _impact(session: Session, org: str, version: str, baseline: str | None):
    if org not in available_orgs():
        raise HTTPException(status_code=400, detail=f"Unknown org: {org!r}")
    config = load_org(org)
    if not release_exists(session, config, version):
        raise HTTPException(status_code=404, detail=f"Release {version!r} not ingested for org {org!r}")
    graph = load_release_graph(session, config)
    if baseline is not None and baseline not in graph.tagged_versions:
        raise HTTPException(status_code=400, detail=f"Baseline {baseline!r} is not a tagged release")
    new, regressed = load_release_issues(session, config, version)
    return config, build_release_impact(
        version, graph, config.impact, load_session_totals(session, config, datetime.now(timezone.utc)),
        new, regressed, baseline_version=baseline,
    )


def llm_client() -> LLMClient:
    return default_client()


@router.get("/{version}/summary")
def get_release_summary(
    version: str,
    org: str = Query(default=DEFAULT_ORG),
    regenerate: bool = Query(default=False, description="Ignore the stored summary and ask the model again"),
    session: Session = Depends(get_session),
    client: LLMClient = Depends(llm_client),
) -> dict:
    """Claude's prose summary of /impact. Every sentence cites packet ids; the
    deterministic /impact endpoint stays the source of truth."""
    config, impact = _impact(session, org, version, None)
    try:
        return explain(session, config, "release_summary", version, release_packet(impact), client, regenerate)
    except LLMError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@router.get("/{version}/impact")
def get_release_impact(
    version: str,
    org: str = Query(default=DEFAULT_ORG),
    baseline: str | None = Query(default=None, description="Tagged version to compare against; default: previous"),
    session: Session = Depends(get_session),
) -> dict:
    return _impact(session, org, version, baseline)[1].model_dump(mode="json")
