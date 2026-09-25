"""Live sweep: F1-F5 through a running API, against the planted ground truth.

    DATABASE_URL=... uv run python -m scripts.demo.verify_incident_context [--base-url http://localhost:8000]

Issue ids are assigned by Sentry, so each case is found via its `demo_case`
tag in the ingested events (same database the API serves from).
"""

import argparse
import sys

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import IncidentEvent
from scripts.demo import scenario as sc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--org", default="demo")
    args = parser.parse_args()

    with SessionLocal() as session:
        ids = {e.tags.get("demo_case"): e.sentry_issue_id
               for e in session.scalars(select(IncidentEvent).where(IncidentEvent.org == args.org))}

    failures = 0
    for spec in sc.INCIDENTS:
        issue_id = ids.get(spec.case)
        if issue_id is None:
            print(f"FAIL [{spec.case}] not ingested")
            failures += 1
            continue
        body = httpx.get(f"{args.base_url}/v1/incidents/{issue_id}/context", params={"org": args.org}).json()
        suspects = body["suspects"] if body["suspects"] == "UNKNOWN" else tuple(
            s["message"].split(": ", 1)[-1] for s in body["suspects"])
        checks = {
            "release state": (body["release"]["state"], spec.expected_release_state),
            "suspects": (suspects, spec.expected_suspects),
            "findings": (tuple(f["code"] for f in body["findings"]), spec.expected_findings),
        }
        bad = {name: got for name, (got, want) in checks.items() if got != want}
        if bad:
            failures += 1
            print(f"FAIL [{spec.case}] issue {issue_id}: {bad}")
        else:
            print(f"OK   [{spec.case}] issue {issue_id}: release {body['release']['version']} "
                  f"{body['release']['state']}, suspects {suspects}, findings {checks['findings'][0]}")
    print("---")
    print(f"{len(sc.INCIDENTS) - failures}/{len(sc.INCIDENTS)} incident scenarios matched.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
