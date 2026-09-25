"""Input set for the reproduction-narrative eval: frozen evidence packets.

    uv run python -m evals.repro_narrative.build_cases --real       # RP1-RP6 from the dev DB (reads only)
    uv run python -m evals.repro_narrative.build_cases --synthetic  # S01-S14, offline

Every packet comes out of the real pipeline -- build_reproduction then
repro_packet -- never hand-written JSON. Real cases are frozen once because
push.deliverable depends on wall-clock registration freshness (the seeded push
data goes stale around 2026-10-12); synthetic cases feed designed incidents
through the same code, with Module 1 state from the seed definitions evaluated
at a fixed time.
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from app.incidents.context import CommitInfo, IncidentInfo, ReleaseGraph, TicketInfo
from app.incidents.normalize import normalize_frame
from app.llm.packet import repro_packet
from app.orgs import load_org
from app.reconciliation.common import RawObservation
from app.reconciliation.profile_state import evaluate_profile_state
from app.reconciliation.push_state import evaluate_push_state
from app.reproduction.reproduce import EventInput, build_reproduction
from app.seed import PROFILE_SCENARIOS, PROFILE_SUBJECT_PREFIX, SCENARIOS, SEED_REFERENCE_TIME, SUBJECT_PREFIX

CASES_DIR = Path(__file__).parent / "cases"
ORG = load_org("demo")

# RP1-RP6 (RP7 is the 404 case and never reaches the model): case -> Sentry demo_case
REAL = {"RP1": "F1", "RP2": "F6", "RP3": "F4", "RP4": "F3", "RP5": "F2", "RP6": "F5"}
REAL_NOTES = {
    "RP1": "Push token refresh crash; one suspect; Module 1 push/profile state varies between events.",
    "RP2": "Enable-push 403 with OS permission DENIED on all events; 3 paths in; truncated trail; no suspect.",
    "RP3": "Minified bundle: culprit unmappable, suspects UNKNOWN.",
    "RP4": "Release 1.2.1 has no git tag: suspects UNKNOWN.",
    "RP5": "Saved-search crash on two releases (app.version varies); no suspect.",
    "RP6": "Legacy route crash; suspect commit without ticket.",
}


def write_case(case_id: str, source: str, covers: list[str], note: str, packet: dict) -> None:
    body = {"id": case_id, "source": source, "covers": covers, "note": note, "packet": packet}
    (CASES_DIR / f"{case_id}.json").write_text(json.dumps(body, indent=1, sort_keys=True, default=str) + "\n")


# ------------------------------------------------------------------ real


def build_real() -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.incidents.repository import load_incident, load_release_graph
    from app.models import IncidentEvent
    from app.reproduction.repository import load_events, state_lookup

    with SessionLocal() as session:
        issue_ids = {e.tags.get("demo_case"): e.sentry_issue_id for e in session.scalars(select(IncidentEvent))}
        graph = load_release_graph(session, ORG)
        for case_id, demo_case in REAL.items():
            issue = issue_ids[demo_case]
            repro = build_reproduction(load_incident(session, ORG, issue), load_events(session, ORG, issue),
                                       graph, state_lookup(session), ORG.repro)
            packet = repro_packet(repro)
            write_case(case_id, "real", covers(packet), REAL_NOTES[case_id], packet)
            print(f"{case_id} ({demo_case}): {len(packet['items'])} items")


# ------------------------------------------------------------- synthetic

NOW = SEED_REFERENCE_TIME + timedelta(days=1)  # same fixed evaluation time as tests/test_reproduction.py
VERSIONS = ("3.0.0", "3.1.0", "3.2.0", "3.3.0")


def _raw(specs) -> list[RawObservation]:
    return [RawObservation(source=s.source, key=s.key, value=s.value, observed_at=s.observed_at) for s in specs]


def lookup(subject_type: str, subject_id: str, domain: str) -> dict | None:
    """Seed scenario letters (install-case-a..m, account-case-p1..p10); anything else has no observations."""
    if domain == "push":
        specs = SCENARIOS.get(subject_id.removeprefix(SUBJECT_PREFIX))
        return evaluate_push_state(_raw(specs), now=NOW).model_dump() if specs else None
    specs = PROFILE_SCENARIOS.get(subject_id.removeprefix(PROFILE_SUBJECT_PREFIX))
    return evaluate_profile_state(_raw(specs)).model_dump() if specs else None


def _commit(sha: str, message: str, files: tuple[str, ...], tickets: tuple[str, ...] = ()) -> CommitInfo:
    return CommitInfo(sha=sha, message=message, files=tuple((p, ORG.component_for(p)) for p in files),
                      ticket_keys=tickets)


GRAPH = ReleaseGraph(
    tagged_versions=VERSIONS,
    commits={
        "3.0.0": (_commit("c30a0000", "Initial job search app", ("src/app/main.ts",)),),
        "3.1.0": (
            _commit("c31a1111", "MEI-40: Apply to jobs from the detail page",
                    ("src/modules/jobs/apply.ts", "src/modules/jobs/detail.vue"), ("MEI-40",)),
            _commit("c31b2222", "MEI-41: Cache job detail responses",
                    ("src/modules/jobs/api.ts", "src/modules/jobs/apply.ts"), ("MEI-41",)),
            _commit("c31c3333", "Bump analytics SDK", ("src/app/analytics.ts",)),
        ),
        "3.2.0": (
            _commit("c32a4444", "MEI-52: Local news feed paging", ("src/modules/news/feed.ts",), ("MEI-52",)),
            _commit("c32b5555", "Sync profile postal code on save", ("src/modules/profile/profile.store.ts",)),
        ),
        "3.3.0": (
            _commit("c33a6666", "MEI-60: Weather widget on home", ("src/modules/weather/widget.vue",), ("MEI-60",)),
        ),
    },
    tickets={k: TicketInfo(k, s, "Story", "Done") for k, s in (
        ("MEI-40", "Apply from job detail"), ("MEI-41", "Cache job details"),
        ("MEI-52", "News feed paging"), ("MEI-60", "Weather widget"))},
)


def nav(to: str) -> dict:
    return {"type": "navigation", "category": "navigation", "data": {"from": "?", "to": to}}


def tap(target: str) -> dict:
    return {"type": "user", "category": "ui.click", "message": target}


def http(method: str, url: str, status: int) -> dict:
    return {"type": "http", "category": "xhr", "data": {"method": method, "url": url, "status_code": status}}


def life(state: str) -> dict:
    return {"type": "navigation", "category": "app.lifecycle", "data": {"state": state}}


def custom(category: str) -> dict:
    return {"type": "default", "category": category, "message": "sdk internal"}


IOS = {"os": {"name": "iOS", "version": "18.4"}, "device": {"model": "iPhone15,2"}}
ANDROID = {"os": {"name": "Android", "version": "15"}, "device": {"model": "Pixel 8"}}


@dataclass
class Ev:
    crumbs: tuple[dict, ...]
    install: str = "install-case-a"  # seed letter a..m, or an unknown id
    account: str = "account-case-p1"  # seed p1..p10, or an unknown id
    platform: dict = field(default_factory=lambda: IOS)
    release: str | None = None  # defaults to the incident's release
    tags: dict = field(default_factory=dict)
    exception: tuple[str, str] | None = None  # defaults to the incident's exception


@dataclass
class Synthetic:
    id: str
    note: str
    release: str
    exception: tuple[str, str]
    frames: tuple[tuple[str, str, int], ...]  # (filename, function, lineno), crashing frame last
    events: tuple[Ev, ...]


def build(s: Synthetic) -> dict:
    sentry_release = ORG.sentry_release_for(s.release)
    incident = IncidentInfo(
        sentry_issue_id=s.id, title=f"{s.exception[0]}: {s.exception[1]}", culprit=None,
        first_release=sentry_release, first_release_version=s.release,
        frames=tuple(normalize_frame(ORG, {"filename": f, "function": fn, "lineno": ln, "in_app": True})
                     for f, fn, ln in s.frames),
    )
    events = []
    for n, e in enumerate(s.events):
        release = e.release or s.release
        exc = e.exception or s.exception
        contexts = {k: v for k, v in e.platform.items() if v is not None}
        contexts["app"] = {"app_version": release}
        events.append(EventInput(
            event_id=f"{s.id}-{n}", release=ORG.sentry_release_for(release),
            user_id=e.account, installation_id=e.install,
            exception={"type": exc[0], "value": exc[1]}, breadcrumbs=e.crumbs, contexts=contexts, tags=e.tags,
        ))
    return repro_packet(build_reproduction(incident, events, GRAPH, lookup, ORG.repro))


MAIN = ("app:///src/app/main.ts", "bootstrap", 12)
APPLY = ("app:///src/modules/jobs/apply.ts", "submitApplication", 57)
API = ("app:///src/modules/jobs/api.ts", "fetchJob", 23)
DETAIL = ("app:///src/modules/jobs/detail.vue", "onApplyClick", 31)
FEED = ("app:///src/modules/news/feed.ts", "loadPage", 88)
PROFILE = ("app:///src/modules/profile/profile.store.ts", "savePostalCode", 140)
WEATHER = ("app:///src/modules/weather/widget.vue", "render", 19)
SETTINGS = ("app:///src/modules/settings/notifications.ts", "toggleTopic", 64)

APPLY_FLOW = (nav("/jobs"), tap("li.job-card"), nav("/jobs/detail"), tap("button#apply"),
              http("POST", "https://api.example.invalid/api/applications", 500))
FEED_FLOW = (life("foreground"), nav("/news"), tap("button#load-more"),
             http("GET", "https://api.example.invalid/api/news?page=2", 200))

SYNTHETIC = (
    Synthetic("S01", "Clean case: 4 identical events, unanimous context, one suspect. Nothing missing.",
              "3.1.0", ("TypeError", "Cannot read properties of undefined (reading 'jobId')"), (MAIN, DETAIL),
              tuple(Ev(APPLY_FLOW) for _ in range(4))),
    Synthetic("S02", "Clean on Android with two ranked suspects (both touch the stack).",
              "3.1.0", ("NullPointerException", "job.detail is null"), (MAIN, APPLY, API),
              tuple(Ev((nav("/jobs"), tap("li.job-card"), nav("/jobs/detail"),
                        http("GET", "https://api.example.invalid/api/jobs/42", 200)),
                       install="install-case-j", account="account-case-p2", platform=ANDROID) for _ in range(3))),
    Synthetic("S03", "Stack is mapped but no commit in 3.3.0 touches it: suspects NONE_FOUND; a feature flag varies.",
              "3.3.0", ("RangeError", "Invalid page index -1"), (MAIN, FEED),
              (Ev(FEED_FLOW, tags={"flag.news_v2": "on"}), Ev(FEED_FLOW, tags={"flag.news_v2": "on"}),
               Ev(FEED_FLOW, tags={"flag.news_v2": "off"}))),
    Synthetic("S04", "First tagged release (3.0.0): no earlier tag to diff, so suspects are UNKNOWN, not none.",
              "3.0.0", ("Error", "Bootstrap failed: config missing"), (MAIN,),
              tuple(Ev((life("launch"),)) for _ in range(2))),
    Synthetic("S05", "Minified bundle frames: culprit UNKNOWN and suspects UNKNOWN.",
              "3.2.0", ("TypeError", "t is undefined"),
              (("app:///main.9c1e2f.js", "a", 1), ("app:///main.9c1e2f.js", "r", 1)),
              tuple(Ev((nav("/news"), tap("button#share"))) for _ in range(3))),
    Synthetic("S06", "One issue, two different exception messages: exception is VARIES.",
              "3.1.0", ("TypeError", "Cannot read properties of null (reading 'title')"), (MAIN, APPLY),
              (Ev(APPLY_FLOW), Ev(APPLY_FLOW),
               Ev(APPLY_FLOW, exception=("TypeError", "Cannot read properties of null (reading 'company')")))),
    Synthetic("S07", "No common ending across events: no core steps, only whole-trail variants.",
              "3.2.0", ("Error", "Feed renderer crashed"), (MAIN, FEED),
              (Ev((nav("/news"), tap("button#load-more"))), Ev((nav("/news"), tap("a.article-link"))),
               Ev((life("foreground"), nav("/news/saved"))))),
    Synthetic("S08", "No event has any breadcrumbs: no steps, no variants at all.",
              "3.2.0", ("OutOfMemoryError", "Failed to allocate 8388608 bytes"), (MAIN, FEED),
              tuple(Ev((), platform=ANDROID, install="install-case-b") for _ in range(3))),
    Synthetic("S09", "One of three events has no breadcrumbs; another contains an SDK-internal crumb (UNMAPPED).",
              "3.1.0", ("TypeError", "Cannot read properties of undefined (reading 'jobId')"), (MAIN, APPLY),
              (Ev(APPLY_FLOW), Ev((custom("sdk.session"),) + APPLY_FLOW), Ev(()))),
    Synthetic("S10", "A single event: everything is a precondition by construction.",
              "3.3.0", ("Error", "Weather provider returned no data"), (MAIN, WEATHER),
              (Ev((life("foreground"), nav("/home"), http("GET", "https://api.example.invalid/api/weather", 204))),)),
    Synthetic("S11", "Long path (prefix > 6, packet shows a '... N more steps ...' placeholder) plus a trail at the 100-crumb limit.",
              "3.2.0", ("Error", "Article body parse failed"), (MAIN, FEED),
              (Ev(tuple(nav(f"/news/{n}") for n in range(12)) + (tap("a.article-link"), nav("/news/article"))),
               Ev(tuple(nav(f"/search/{n}") for n in range(98)) + (tap("a.article-link"), nav("/news/article"))),
               Ev((nav("/home"), tap("a.article-link"), nav("/news/article"))))),
    Synthetic("S12", "Crashing users have no Module 1 observations: push/profile state is a gap, not a guess.",
              "3.3.0", ("Error", "Weather widget: location undefined"), (MAIN, WEATHER),
              tuple(Ev((life("foreground"), nav("/home")), install=f"install-unknown-{n}",
                       account=f"account-unknown-{n}") for n in range(3))),
    Synthetic("S13", "Push is fine (deliverable, OS permission allowed) but the profile is inconsistent on every event.",
              "3.2.0", ("Error", "Postal code mismatch between backend and job profile"), (MAIN, PROFILE),
              (Ev((nav("/profile"), tap("button#save-profile"),
                   http("PUT", "https://api.example.invalid/api/profile", 409)), account="account-case-p3"),
               Ev((nav("/profile"), tap("button#save-profile"),
                   http("PUT", "https://api.example.invalid/api/profile", 409)), account="account-case-p9"))),
    Synthetic("S14", "Long 8-step core, few preconditions: OS, device, release, push permission and a flag all vary; one device model unknown.",
              "3.1.0", ("Error", "Topic toggle failed"), (MAIN, SETTINGS),
              tuple(Ev((life("foreground"), nav("/home"), nav("/settings"), nav("/settings/notifications"),
                        tap("switch#topic-jobs"), http("PUT", "https://api.example.invalid/api/topics", 200),
                        tap("switch#topic-news"), http("PUT", "https://api.example.invalid/api/topics", 500)),
                       install=inst, platform=plat, release=rel, tags={"flag.topics_v2": flag})
                    for inst, plat, rel, flag in (
                        ("install-case-a", IOS, "3.1.0", "on"),
                        ("install-case-c", ANDROID, "3.1.0", "on"),
                        ("install-case-e", {"os": {"name": "iOS", "version": "17.6"}, "device": None}, "3.2.0", "off"),
                        ("install-case-h", ANDROID, "3.2.0", "on")))),
)


def covers(packet: dict) -> list[str]:
    """Which repro_packet branches this packet exercises (used for the coverage count)."""
    items = packet["items"]
    by_prefix = lambda p: [i for i in items if i["id"].startswith(p)]
    out = []
    suspects = by_prefix("suspect")
    if any(i["id"] == "suspects" and i["value"] == "UNKNOWN" for i in items):
        out.append("suspects:UNKNOWN")
    elif any(i["id"] == "suspects" for i in items):
        out.append("suspects:NONE_FOUND")
    else:
        out.append(f"suspects:{'one' if len(suspects) == 1 else 'many'}")
    failure = next(i for i in items if i["id"] == "failure")
    if failure["culprit_frame"] == "UNKNOWN":
        out.append("culprit:UNKNOWN")
    if failure["exception"]["type"] == "VARIES":
        out.append("exception:VARIES")
    steps, variants = by_prefix("step-"), by_prefix("variant-")
    if not steps:
        out.append("steps:none+variants" if variants else "steps:none")
    if any(v["prefix_length"] > 6 for v in variants):
        out.append("variant:long_prefix")
    out += [f"gap:{g['code']}" for g in by_prefix("gap-")]
    if not by_prefix("gap-"):
        out.append("gaps:none")
    for kind in ("precondition", "varies"):
        out += [f"{kind}:{i['key']}" for i in by_prefix(f"{kind}-") if i["key"].startswith(("push.", "profile."))]
    return out


def build_synthetic() -> None:
    for s in SYNTHETIC:
        packet = build(s)
        write_case(s.id, "synthetic", covers(packet), s.note, packet)
        print(f"{s.id}: {len(packet['items'])} items  {covers(packet)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    CASES_DIR.mkdir(exist_ok=True)
    if args.real:
        build_real()
    if args.synthetic:
        build_synthetic()


if __name__ == "__main__":
    main()
