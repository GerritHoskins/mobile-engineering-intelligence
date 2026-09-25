"""Shared HTTP plumbing: retries, Link-header pagination, and record/replay
transports so tests run offline against recorded (scrubbed) vendor payloads."""

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}
SCRUBBED = "<scrubbed>"
# Keys whose values identify people or carry auth; replaced when recording.
SCRUB_KEYS = {"emailAddress", "email", "accountId", "displayName", "avatarUrls", "avatarUrl", "self", "ip_address"}


def get_with_retry(client: httpx.Client, url: str, *, params=None, attempts: int = 4) -> httpx.Response:
    for attempt in range(attempts):
        response = client.get(url, params=params)
        if response.status_code not in RETRY_STATUSES or attempt == attempts - 1:
            return response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt)
    raise AssertionError("unreachable")


def iter_link_pages(client: httpx.Client, url: str, params=None) -> Iterator[httpx.Response]:
    """Follow rel="next" Link headers (GitHub and Sentry). Sentry always sends a
    next link and marks the last page with results="false"."""
    response = get_with_retry(client, url, params=params)
    while True:
        yield response
        nxt = response.links.get("next")
        if not nxt or nxt.get("results") == "false":
            return
        response = get_with_retry(client, nxt["url"])


# ------------------------------------------------------------ record/replay


def fixture_key(request: httpx.Request) -> str:
    query = urlencode(sorted(request.url.params.multi_items()))
    raw = f"{request.method} {request.url.host}{request.url.path}?{query}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def scrub(value):
    if isinstance(value, dict):
        return {k: (SCRUBBED if k in SCRUB_KEYS else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


class RecordingTransport(httpx.BaseTransport):
    """Passes requests through and saves scrubbed responses under `directory`."""

    def __init__(self, directory: Path, inner: httpx.BaseTransport | None = None):
        self.directory = directory
        self.inner = inner or httpx.HTTPTransport()
        directory.mkdir(parents=True, exist_ok=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        response.read()
        body = scrub(response.json()) if response.headers.get("content-type", "").startswith("application/json") else None
        record = {
            "request": f"{request.method} {request.url.path}",
            "params": sorted(request.url.params.multi_items()),
            "status": response.status_code,
            "link": response.headers.get("link"),
            "json": body,
        }
        (self.directory / f"{fixture_key(request)}.json").write_text(json.dumps(record, indent=1, sort_keys=True))
        return httpx.Response(response.status_code, headers=response.headers, content=response.content,
                              request=request)


class ReplayTransport(httpx.BaseTransport):
    """Serves recorded responses; an unrecorded request fails loudly."""

    def __init__(self, directory: Path):
        self.directory = directory

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = self.directory / f"{fixture_key(request)}.json"
        if not path.is_file():
            raise FileNotFoundError(f"No recorded fixture for {request.method} {request.url}")
        record = json.loads(path.read_text())
        headers = {"link": record["link"]} if record.get("link") else {}
        return httpx.Response(record["status"], headers=headers, json=record["json"], request=request)
