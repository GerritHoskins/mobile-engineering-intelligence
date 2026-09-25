"""Loader-boundary normalization of Sentry payloads: vendor shapes become
canonical rows here, and unknown shapes raise rather than silently defaulting."""

from app.orgs import OrgConfig


class UnrecognizedPayload(ValueError):
    pass


def normalize_frame(org: OrgConfig, raw: dict) -> dict:
    filename = raw.get("filename") or raw.get("absPath") or raw.get("abs_path")
    path = org.normalize_frame_path(filename)
    return {
        "raw_filename": filename,
        "path": path,  # None: can't be mapped to a repo path (e.g. minified bundle)
        "component": org.component_for(path) if path else None,
        "function": raw.get("function"),
        "lineno": raw.get("lineNo", raw.get("lineno")),
        "in_app": bool(raw.get("inApp", raw.get("in_app", False))),
    }


def _entry(event: dict, entry_type: str) -> dict | None:
    for entry in event.get("entries", []):
        if entry.get("type") == entry_type:
            return entry.get("data") or {}
    return None


def normalize_event(org: OrgConfig, event: dict) -> dict:
    """A Sentry issue event (from the events endpoint with full=true) as an
    incident_event row, without the org column."""
    for required in ("eventID", "groupID", "dateCreated"):
        if required not in event:
            raise UnrecognizedPayload(f"Sentry event without {required!r}: keys={sorted(event)}")

    tags = {t["key"]: t["value"] for t in event.get("tags", [])}
    exception = _entry(event, "exception") or {"values": []}
    values = exception.get("values") or []
    frames = [
        normalize_frame(org, frame)
        for value in values
        for frame in ((value.get("stacktrace") or {}).get("frames") or [])
    ]
    crumbs = (_entry(event, "breadcrumbs") or {}).get("values") or []
    last = values[-1] if values else {}
    return {
        "event_id": event["eventID"],
        "sentry_issue_id": str(event["groupID"]),
        "release": tags.get("release"),
        "occurred_at": event["dateCreated"],
        "user_id": (event.get("user") or {}).get("id"),
        "installation_id": tags.get("installation_id"),
        "exception": {"type": last.get("type"), "value": last.get("value")},
        "frames": frames,
        "breadcrumbs": crumbs,
        "contexts": event.get("contexts") or {},
        "tags": tags,
    }


def regression_release(issue: dict, events: list[dict]) -> str | None:
    """Sentry release in which the issue last regressed (was resolved, then
    seen again), or None if it never did.

    Prefers the release recorded on the latest `set_regression` activity. If
    Sentry didn't record one there, falls back to the release of the first
    event after the latest resolution (`events` are normalized event rows).
    """
    activity = issue.get("activity") or []
    for entry in activity:
        if "type" not in entry or "dateCreated" not in entry:
            raise UnrecognizedPayload(f"Sentry activity entry without type/dateCreated: keys={sorted(entry)}")
    regressions = sorted((a for a in activity if a["type"] == "set_regression"), key=lambda a: a["dateCreated"])
    if not regressions:
        return None
    version = (regressions[-1].get("data") or {}).get("version")
    if version:
        return version
    resolutions = [a["dateCreated"] for a in activity if a["type"] == "set_resolved"]
    after = max(resolutions) if resolutions else regressions[-1]["dateCreated"]
    later = sorted((e for e in events if str(e["occurred_at"]) > after), key=lambda e: str(e["occurred_at"]))
    return later[0]["release"] if later else None
