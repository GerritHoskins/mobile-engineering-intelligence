"""Production Reproduction Assistant: given an incident, the most likely
sequence and conditions that reproduce it, as a tool-neutral JSON scenario.

Pure logic over already-ingested events plus a Module 1 state lookup. The
same discipline as the other modules: a value only becomes a precondition if
every event agrees; what varies is reported as varying, and what can't be
known is a gap -- never a guess.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from app.incidents.context import IncidentInfo, ReleaseGraph, build_incident_context
from app.orgs import ReproConfig

SCHEMA_VERSION = "reproduction.v1"

# (subject_type, subject_id, domain) -> evaluated Module 1 state, or None when
# the subject has no observations at all.
StateLookup = Callable[[str, str, str], dict | None]


@dataclass(frozen=True)
class EventInput:
    event_id: str
    release: str | None
    user_id: str | None
    installation_id: str | None
    exception: dict
    breadcrumbs: tuple[dict, ...]
    contexts: dict
    tags: dict


class Step(BaseModel):
    kind: Literal["LIFECYCLE", "NAVIGATE", "TAP", "BACKEND_CALL", "UNMAPPED"]
    target: str
    support: float = 1.0

    @property
    def key(self) -> str:
        return f"{self.kind} {self.target}"


class Precondition(BaseModel):
    key: str
    value: Any
    support: float
    source: str


class ValueCount(BaseModel):
    value: Any
    count: int


class Varies(BaseModel):
    key: str
    values: list[ValueCount]


class Variant(BaseModel):
    prefix: list[str]
    events: list[str]


class Gap(BaseModel):
    code: str
    event_ids: list[str]
    keys: list[str] = []


class ExpectedFailure(BaseModel):
    exception: dict
    culprit_frame: dict | Literal["UNKNOWN"]
    suspects: list[dict] | Literal["UNKNOWN"]


class Reproduction(BaseModel):
    schema_version: Literal["reproduction.v1"] = SCHEMA_VERSION
    incident: dict
    events_considered: int
    preconditions: list[Precondition]
    varies: list[Varies]
    steps: list[Step]
    variants: list[Variant]
    expected_failure: ExpectedFailure
    gaps: list[Gap]
    evidence: list[dict]


# ------------------------------------------------------------------- steps


def normalize_step(crumb: dict) -> Step:
    category = crumb.get("category") or ""
    data = crumb.get("data") or {}
    if category == "app.lifecycle":
        return Step(kind="LIFECYCLE", target=str(data.get("state")))
    if category == "navigation":
        # Destination only: the origin differs between paths into the same screen.
        return Step(kind="NAVIGATE", target=str(data.get("to")))
    if category == "ui.click":
        return Step(kind="TAP", target=str(crumb.get("message")))
    if category in ("xhr", "fetch", "http") or crumb.get("type") == "http":
        path = urlparse(str(data.get("url", ""))).path or str(data.get("url"))
        return Step(kind="BACKEND_CALL", target=f"{data.get('method')} {path} {data.get('status_code')}")
    return Step(kind="UNMAPPED", target=category or str(crumb.get("type")))


def _common_suffix(sequences: list[list[Step]]) -> int:
    length = min(len(s) for s in sequences)
    n = 0
    while n < length and len({s[-1 - n].key for s in sequences}) == 1:
        n += 1
    return n


# ----------------------------------------------------------- preconditions

PUSH_KEYS = {
    "push.deliverable": lambda s: s["effective_state"]["deliverable"],
    "push.os_permission": lambda s: s["capability_state"]["os_permission"],
    "push.provider_registration": lambda s: s["registration_state"]["provider_registration"],
}
PROFILE_KEYS = {"profile.consistent": lambda s: s["effective_state"]["consistent"]}
UNKNOWN = "UNKNOWN"


def _event_values(event: EventInput, lookup: StateLookup) -> dict[str, tuple[Any, str]]:
    """key -> (value, source) for one event; missing values are UNKNOWN."""
    contexts = event.contexts or {}
    values: dict[str, tuple[Any, str]] = {
        "app.version": ((contexts.get("app") or {}).get("app_version", UNKNOWN), "sentry.contexts"),
        "os.name": ((contexts.get("os") or {}).get("name", UNKNOWN), "sentry.contexts"),
        "os.version": ((contexts.get("os") or {}).get("version", UNKNOWN), "sentry.contexts"),
        "device.model": ((contexts.get("device") or {}).get("model", UNKNOWN), "sentry.contexts"),
    }
    for key, value in sorted((event.tags or {}).items()):
        if key.startswith("flag."):
            values[key] = (value, "sentry.tags")
    push = lookup("installation", event.installation_id, "push") if event.installation_id else None
    for key, read in PUSH_KEYS.items():
        value = read(push) if push else None
        values[key] = (UNKNOWN if value is None else value, "module1.push")
    profile = lookup("account", event.user_id, "profile") if event.user_id else None
    for key, read in PROFILE_KEYS.items():
        value = read(profile) if profile else None
        values[key] = (UNKNOWN if value is None else value, "module1.profile")
    return values


# -------------------------------------------------------------------- build


def build_reproduction(
    incident: IncidentInfo,
    events: list[EventInput],
    graph: ReleaseGraph,
    lookup: StateLookup,
    config: ReproConfig,
) -> Reproduction:
    n = len(events)
    gaps: list[Gap] = []

    # Step 1 - steps per event, then consensus: the common suffix ending at the
    # crash is the core; what differs before it is a variant.
    sequences = {e.event_id: [normalize_step(c) for c in e.breadcrumbs] for e in events}
    with_steps = [eid for eid in sequences if sequences[eid]]
    without = [eid for eid in sequences if not sequences[eid]]
    if without:
        gaps.append(Gap(code="NO_BREADCRUMBS", event_ids=without))
    truncated = [e.event_id for e in events if len(e.breadcrumbs) >= config.max_breadcrumbs]
    if truncated:
        gaps.append(Gap(code="BREADCRUMBS_TRUNCATED", event_ids=truncated))

    steps: list[Step] = []
    variants: list[Variant] = []
    if with_steps:
        core = _common_suffix([sequences[eid] for eid in with_steps])
        support = round(len(with_steps) / n, 4)
        reference = sequences[with_steps[0]]
        steps = [s.model_copy(update={"support": support}) for s in reference[len(reference) - core:]] if core else []
        prefixes: dict[tuple[str, ...], list[str]] = {}
        for eid in with_steps:
            seq = sequences[eid]
            prefixes.setdefault(tuple(s.key for s in seq[:len(seq) - core]), []).append(eid)
        if any(prefixes):
            variants = [Variant(prefix=list(p), events=ids) for p, ids in prefixes.items()]
    unmapped = [eid for eid, seq in sequences.items() if any(s.kind == "UNMAPPED" for s in seq)]
    if unmapped:
        gaps.append(Gap(code="UNMAPPED_STEPS", event_ids=unmapped))
    if n == 1:
        gaps.append(Gap(code="SINGLE_EVENT", event_ids=[events[0].event_id]))

    # Step 2 - preconditions: unanimous (>= min_support) values only. Anything
    # that differs between events is reported under `varies`, not claimed.
    per_event = [_event_values(e, lookup) for e in events]
    keys = list(dict.fromkeys(k for values in per_event for k in values))
    preconditions: list[Precondition] = []
    varies: list[Varies] = []
    state_unknown: list[str] = []
    for key in keys:
        observed = [values.get(key, (UNKNOWN, ""))[0] for values in per_event]
        source = next(values[key][1] for values in per_event if key in values)
        counts = Counter(repr(v) for v in observed)
        first_value = {repr(v): v for v in reversed(observed)}
        top, count = counts.most_common(1)[0]
        value = first_value[top]
        if value == UNKNOWN and count == n:
            if source.startswith("module1"):
                state_unknown.append(key)
            continue
        if value != UNKNOWN and count / n >= config.min_support:
            preconditions.append(Precondition(key=key, value=value, support=round(count / n, 4), source=source))
        else:
            varies.append(Varies(key=key, values=[ValueCount(value=first_value[r], count=c)
                                                  for r, c in counts.most_common()]))
    if state_unknown:
        gaps.append(Gap(code="ACCOUNT_STATE_UNKNOWN", event_ids=[e.event_id for e in events], keys=state_unknown))

    # Step 3 - expected failure: exception, culprit frame, and Slice F's suspects.
    exceptions = {(e.exception.get("type"), e.exception.get("value")) for e in events}
    exception = ({"type": next(iter(exceptions))[0], "value": next(iter(exceptions))[1]}
                 if len(exceptions) == 1 else {"type": "VARIES", "value": sorted(map(str, exceptions))})
    mapped = [f for f in incident.frames if f.get("path")]
    if mapped:
        culprit: dict | Literal["UNKNOWN"] = {k: mapped[-1].get(k) for k in ("path", "function", "lineno")}
    else:
        culprit = "UNKNOWN"
        gaps.append(Gap(code="CULPRIT_UNMAPPABLE", event_ids=[e.event_id for e in events]))
    context = build_incident_context(incident, graph)
    suspects = "UNKNOWN" if context.suspects == "UNKNOWN" else [s.model_dump() for s in context.suspects]

    evidence = [{"source": "sentry", "key": "event", "value": e.event_id, "release": e.release,
                 "installation_id": e.installation_id, "user_id": e.user_id} for e in events]
    return Reproduction(
        incident={"id": incident.sentry_issue_id, "title": incident.title},
        events_considered=n,
        preconditions=preconditions,
        varies=varies,
        steps=steps,
        variants=variants,
        expected_failure=ExpectedFailure(exception=exception, culprit_frame=culprit, suspects=suspects),
        gaps=gaps,
        evidence=evidence,
    )
