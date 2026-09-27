"""Delete what an org's retention window no longer covers.

    python -m app.retention --org demo [--dry-run]

Removes incident events (the rows holding breadcrumbs, contexts and tags) and
generated LLM text older than `retention_days` from config/org.<name>.yaml.
Incidents, releases, commits and tickets stay: they describe the software,
not the people using it. Re-ingesting can bring events back only while the
vendor still holds them, and only inside the ingest window.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import IncidentEvent, LlmOutput
from app.orgs import OrgConfig, load_org


@dataclass(frozen=True)
class Purge:
    cutoff: datetime | None
    incident_events: int
    llm_outputs: int


def purge(session: Session, org: OrgConfig, now: datetime | None = None, dry_run: bool = False) -> Purge:
    if org.retention_days is None:
        return Purge(cutoff=None, incident_events=0, llm_outputs=0)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=org.retention_days)
    targets = (
        (IncidentEvent, IncidentEvent.occurred_at),
        (LlmOutput, LlmOutput.created_at),
    )
    counts = []
    for model, stamp in targets:
        where = (model.org == org.name, stamp < cutoff)
        if dry_run:
            counts.append(session.scalar(select(func.count()).select_from(model).where(*where)))
        else:
            counts.append(session.execute(delete(model).where(*where)).rowcount)
    if not dry_run:
        session.commit()
    return Purge(cutoff=cutoff, incident_events=counts[0], llm_outputs=counts[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True)
    parser.add_argument("--dry-run", action="store_true", help="count what would be deleted")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = purge(session, load_org(args.org), dry_run=args.dry_run)
    if result.cutoff is None:
        print(f"org {args.org!r} has no retention_days: nothing deleted")
        return
    verb = "would delete" if args.dry_run else "deleted"
    print(f"org {args.org!r}, cutoff {result.cutoff:%Y-%m-%d %H:%M}Z: {verb} "
          f"{result.incident_events} incident events, {result.llm_outputs} LLM outputs")


if __name__ == "__main__":
    main()
