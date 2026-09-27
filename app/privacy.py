"""Personal-data minimisation at ingest.

Sentry events carry free-form breadcrumbs, contexts and tags, which can hold
emails, names and URLs with tokens in their query strings. Everything the
analysis needs survives this: breadcrumb categories, routes and URL paths,
device/OS/app contexts, and the pseudonymous user and installation ids that
Module 1 lookups key on. Recorded test fixtures are scrubbed separately
(app.connectors.http.scrub); this runs on live ingest.
"""

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.connectors.http import SCRUB_KEYS, SCRUBBED

# A letter TLD, so release names like "app@1.2.0" are not mistaken for emails.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
REDACTED_EMAIL = "<email>"
# HTTP breadcrumb and request URLs. Navigation routes ("to"/"from") are kept
# as-is: their query strings are part of the reproduction path (e.g. paging).
URL_KEYS = {"url"}


def strip_query(url: str) -> str:
    """scheme://host/path only: query strings and fragments often carry tokens."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def minimise(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: (SCRUBBED if k in SCRUB_KEYS else minimise(v, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [minimise(v, key) for v in value]
    if isinstance(value, str):
        if key in URL_KEYS:
            value = strip_query(value)
        return EMAIL.sub(REDACTED_EMAIL, value)
    return value
