"""Live sweep: RP1-RP7 through a running API, against the planted ground truth.

    DATABASE_URL=... uv run python -m scripts.demo.verify_reproduction [--base-url http://localhost:8000]

Issue ids are assigned by Sentry, so each case is found via its `demo_case`
tag in the ingested events (same database the API uses).
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
    for spec in sc.REPROS:
        issue_id = ids.get(spec.incident, spec.incident)
        response = httpx.get(f"{args.base_url}/v1/incidents/{issue_id}/reproduction", params={"org": args.org})
        if response.status_code != spec.expected_status:
            failures += 1
            print(f"FAIL [{spec.case}] {spec.incident}: HTTP {response.status_code}, expected {spec.expected_status}")
            continue
        if spec.expected_status != 200:
            print(f"OK   [{spec.case}] {spec.incident}: HTTP {response.status_code}")
            continue
        body = response.json()
        preconditions = {p["key"]: p["value"] for p in body["preconditions"]}
        suspects = body["expected_failure"]["suspects"]
        suspects = suspects if suspects == "UNKNOWN" else tuple(s["message"].split(": ", 1)[-1] for s in suspects)
        problems = {
            "steps": ([f"{s['kind']} {s['target']}" for s in body["steps"]], list(spec.expected_steps)),
            "variants": (len(body["variants"]), spec.expected_variants),
            "preconditions": ({k: preconditions.get(k) for k in spec.expected_preconditions},
                              spec.expected_preconditions),
            "varies": (set(spec.expected_varies) <= {v["key"] for v in body["varies"]}, True),
            "gaps": ([g["code"] for g in body["gaps"]], list(spec.expected_gaps)),
            "suspects": (suspects, spec.expected_suspects),
        }
        bad = {name: got for name, (got, want) in problems.items() if got != want}
        if bad:
            failures += 1
            print(f"FAIL [{spec.case}] {spec.incident} issue {issue_id}: {bad}")
        else:
            print(f"OK   [{spec.case}] {spec.incident} issue {issue_id}: {len(body['steps'])} steps, "
                  f"{len(body['variants'])} variants, preconditions {sorted(preconditions)}, "
                  f"varies {sorted(v['key'] for v in body['varies'])}, gaps {problems['gaps'][0]}")
    print("---")
    print(f"{len(sc.REPROS) - failures}/{len(sc.REPROS)} reproduction scenarios matched.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
