import httpx

from app.connectors.http import get_with_retry

TICKET_FIELDS = "summary,issuetype,status,components,fixVersions"


class JiraClient:
    """Read-only by construction: this client only issues GETs. (Jira Cloud API
    tokens have no scopes, so the token itself can't enforce read-only.)"""

    def __init__(self, base_url: str, email: str, token: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=base_url, auth=(email, token),
                                   headers={"Accept": "application/json"}, timeout=30, transport=transport)

    def search_jql(self, jql: str, fields: str = TICKET_FIELDS) -> list[dict]:
        issues: list[dict] = []
        token = None
        while True:
            params = {"jql": jql, "fields": fields, "maxResults": 100}
            if token:
                params["nextPageToken"] = token
            page = get_with_retry(self.client, "/rest/api/3/search/jql", params=params).json()
            issues.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token:
                return issues

    def get_issue(self, key: str, fields: str = TICKET_FIELDS) -> dict | None:
        """None when the key doesn't exist. Used for ingestion instead of
        `key in (...)` JQL, which fails the whole query on one unknown key."""
        response = self.client.get(f"/rest/api/3/issue/{key}", params={"fields": fields})
        if response.status_code == 404:
            return None
        if response.status_code in (429, 500, 502, 503, 504):
            response = get_with_retry(self.client, f"/rest/api/3/issue/{key}", params={"fields": fields})
        return response.raise_for_status().json()
