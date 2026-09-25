"""Live grounding check for the LLM layer. CALLS THE REAL CLAUDE API (costs a
few cents), so run it only deliberately.

    DATABASE_URL=... uv run python -m scripts.demo.verify_llm [--base-url http://localhost:8000]

Checks grounding, not style: RI2's summary must cite the CRASH_RATE_REGRESSION
finding and F1's suspect commit; RP2's narrative must cite the
push.os_permission precondition and the truncation gap; no sentence may be
rejected by the citation check; a second request must be served from storage.
"""

import argparse
import sys

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import IncidentEvent


def _check(name: str, body: dict, must_cite: dict[str, str]) -> bool:
    cited = set(body["sources"])
    missing = {label: item_id for label, item_id in must_cite.items() if item_id not in cited}
    ok = not missing and not body["rejected_claims"]
    print(f"{'OK  ' if ok else 'FAIL'} {name}: served_by={body['served_by']} usage={body['usage']} "
          f"cited={len(cited)} rejected={len(body['rejected_claims'])}"
          + (f" missing={missing}" if missing else ""))
    for field, value in body["output"].items():
        for entry in (value if isinstance(value, list) else [value] if value else []):
            print(f"       [{field}] {entry['text']}  <- {', '.join(entry['cites'])}")
    for rejected in body["rejected_claims"]:
        print(f"       REJECTED ({rejected['reason']}) {rejected['text']}  <- {rejected['cites']}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    http = httpx.Client(base_url=args.base_url, timeout=600)

    with SessionLocal() as session:
        ids = {e.tags.get("demo_case"): e.sentry_issue_id for e in session.scalars(select(IncidentEvent))}

    impact = http.get("/v1/releases/1.2.0/impact").json()
    regression = next(n for n, f in enumerate(impact["findings"], 1) if f["code"] == "CRASH_RATE_REGRESSION")
    f1 = next(i for i in impact["new_issues"] if i["id"] == ids["F1"])
    summary_ok = _check("RI2 release summary (1.2.0)", http.get("/v1/releases/1.2.0/summary").json(), {
        "regression finding": f"finding-{regression}",
        "F1 suspect commit": f"commit-{f1['attribution'][0]['sha'][:7]}",
    })

    repro = http.get(f"/v1/incidents/{ids['F6']}/reproduction").json()
    truncation = next(n for n, g in enumerate(repro["gaps"], 1) if g["code"] == "BREADCRUMBS_TRUNCATED")
    narrative_ok = _check("RP2 reproduction narrative (F6)", http.get(f"/v1/incidents/{ids['F6']}/narrative").json(), {
        "OS permission precondition": "precondition-push.os_permission",
        "truncation gap": f"gap-{truncation}",
    })

    cached = (http.get("/v1/releases/1.2.0/summary").json()["cached"],
              http.get(f"/v1/incidents/{ids['F6']}/narrative").json()["cached"])
    print(f"{'OK  ' if all(cached) else 'FAIL'} repeat requests served from storage: {cached}")
    sys.exit(0 if summary_ok and narrative_ok and all(cached) else 1)


if __name__ == "__main__":
    main()
