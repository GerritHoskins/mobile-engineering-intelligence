from datetime import datetime, timezone

import httpx

from app.connectors.http import get_with_retry, iter_link_pages


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class SentryClient:
    def __init__(self, base_url: str, org: str, project: str, token: str,
                 transport: httpx.BaseTransport | None = None):
        self.org, self.project = org, project
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {token}"},
                                   timeout=30, transport=transport)

    def get_project(self) -> dict:
        return get_with_retry(self.client, f"/api/0/projects/{self.org}/{self.project}/").json()

    def list_issues(self, start: datetime, end: datetime, query: str = "") -> list[dict]:
        """Always explicit: an empty query (all statuses) and a fixed window.
        The API's defaults (unresolved only, short window) would hide issues."""
        params = {"query": query, "start": _iso(start), "end": _iso(end), "limit": 100}
        issues: list[dict] = []
        for page in iter_link_pages(self.client, f"/api/0/projects/{self.org}/{self.project}/issues/", params):
            issues.extend(page.json())
        return issues

    def get_issue(self, issue_id: str) -> dict:
        return get_with_retry(self.client, f"/api/0/organizations/{self.org}/issues/{issue_id}/").json()

    def list_issue_events(self, issue_id: str) -> list[dict]:
        events: list[dict] = []
        url = f"/api/0/organizations/{self.org}/issues/{issue_id}/events/"
        for page in iter_link_pages(self.client, url, {"full": "true"}):
            events.extend(page.json())
        return events

    def list_releases(self) -> list[dict]:
        releases: list[dict] = []
        for page in iter_link_pages(self.client, f"/api/0/organizations/{self.org}/releases/", {"per_page": 100}):
            releases.extend(page.json())
        return releases

    def session_counts(self, project_id: str, start: datetime, end: datetime) -> list[dict]:
        """Raw hourly session counts per (release, session.status). Deliberately
        not crash_free_rate: the probe showed it can be wrong for some windows."""
        params = [
            ("field", "sum(session)"), ("groupBy", "release"), ("groupBy", "session.status"),
            ("interval", "1h"), ("start", _iso(start)), ("end", _iso(end)), ("project", project_id),
        ]
        data = get_with_retry(self.client, f"/api/0/organizations/{self.org}/sessions/", params=params).json()
        rows = []
        for group in data.get("groups", []):
            for bucket_start, count in zip(data["intervals"], group["series"]["sum(session)"]):
                if count:
                    rows.append({"release": group["by"]["release"], "status": group["by"]["session.status"],
                                 "bucket_start": bucket_start, "sessions": count})
        return rows
