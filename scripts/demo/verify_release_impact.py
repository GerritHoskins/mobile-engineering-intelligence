"""Live sweep: RI1-RI6 through a running API, against the planted ground truth.

    DATABASE_URL=... uv run python -m scripts.demo.verify_release_impact [--base-url http://localhost:8000]

Issue ids are assigned by Sentry, so they're mapped back to demo cases via
their `demo_case` tag in the ingested events (same database the API uses).
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
        case_of = {e.sentry_issue_id: e.tags.get("demo_case")
                   for e in session.scalars(select(IncidentEvent).where(IncidentEvent.org == args.org))}

    failures = 0
    for spec in sc.IMPACTS:
        response = httpx.get(f"{args.base_url}/v1/releases/{spec.release}/impact", params={"org": args.org})
        if response.status_code != spec.expected_status:
            failures += 1
            print(f"FAIL [{spec.case}] {spec.release}: HTTP {response.status_code}, expected {spec.expected_status}")
            continue
        if spec.expected_status != 200:
            print(f"OK   [{spec.case}] {spec.release}: HTTP {response.status_code}")
            continue
        body = response.json()
        crash_free = body["health"]["crash_free"]
        checks = {
            "release state": (body["release"]["state"], spec.expected_release_state),
            "crash free": (crash_free if isinstance(crash_free, str) else round(crash_free, 4),
                           spec.expected_crash_free),
            "findings": (tuple(f["code"] for f in body["findings"]), spec.expected_findings),
            "new issues": (tuple(case_of.get(i["id"]) for i in body["new_issues"]), spec.expected_new_issues),
            "regressed": (tuple(case_of.get(i["id"]) for i in body["regressed_issues"]),
                          spec.expected_regressed_issues),
        }
        bad = {name: got for name, (got, want) in checks.items() if got != want}
        if bad:
            failures += 1
            print(f"FAIL [{spec.case}] {spec.release}: {bad}")
        else:
            delta = body["delta_pp"]
            print(f"OK   [{spec.case}] {spec.release}: crash-free {checks['crash free'][0]}, delta {delta}, "
                  f"findings {checks['findings'][0]}, new {checks['new issues'][0]}, "
                  f"regressed {checks['regressed'][0]}")
    print("---")
    print(f"{len(sc.IMPACTS) - failures}/{len(sc.IMPACTS)} release impact scenarios matched.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
