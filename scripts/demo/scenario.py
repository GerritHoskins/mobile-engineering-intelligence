"""Ground truth for the Slice F demo data.

Everything planted in the personal Jira / GitHub / Sentry accounts is defined
here once. The generator writes it, and the tests and live sweep assert
against it -- so the "right answer" for every scenario is known in advance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

# The README commit the user created; the planted history is built on top of it.
BASE_COMMIT = "66796e586a720eb66cc19a5c9610cb3c6523432a"

AUTHOR_NAME = "MEI Demo"
AUTHOR_EMAIL = "demo@mei-demo-app.invalid"
JIRA_LABEL = "mei-demo"

VERSIONS = ("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0")


# ---------------------------------------------------------------- Jira


@dataclass(frozen=True)
class TicketSpec:
    marker: str  # stable identity; Jira assigns the actual key
    summary: str
    issue_type: str
    component: str
    fix_version: str  # without the "v" -- Jira version names use the tag form

    @property
    def jira_summary(self) -> str:
        return f"[demo:{self.marker}] {self.summary}"


TICKETS = (
    TicketSpec("profile-email-validation", "Validate email format in profile", "Story", "profile", "1.1.0"),
    TicketSpec("search-results-paging", "Page search results", "Story", "search", "1.1.0"),
    TicketSpec("push-token-refresh", "Refresh push token when the app resumes", "Bug", "push", "1.2.0"),
    TicketSpec("profile-store-refactor", "Refactor profile store", "Task", "profile", "1.3.0"),
    TicketSpec("search-saved-search-tweak", "Tweak saved-search defaults", "Story", "search", "1.4.0"),
)


# ---------------------------------------------------------------- Git


@dataclass(frozen=True)
class CommitSpec:
    subject: str
    ticket: str | None  # TicketSpec.marker, or None for a commit without ticket
    files: dict[str, str]  # path -> line appended (created if missing)
    date: datetime


def _d(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)


SCAFFOLD_FILES = {
    "src/app/main.ts": "export function bootstrap() {}",
    "src/app/router.ts": "export const routes = []",
    "src/modules/push/registration.ts": "export function refreshToken() {}",
    "src/modules/push/permission.ts": "export function requestPermission() {}",
    "src/modules/profile/profile.store.ts": "export const profileStore = {}",
    "src/modules/profile/email.ts": "export function validateEmail() {}",
    "src/modules/search/saved-search.ts": "export function loadSavedSearches() {}",
    "src/modules/search/results.vue": "<template><div /></template>",
}

# version -> commits in that release, oldest first
RELEASE_COMMITS: dict[str, tuple[CommitSpec, ...]] = {
    "1.0.0": (CommitSpec("Scaffold app", None, SCAFFOLD_FILES, _d(1)),),
    "1.1.0": (
        CommitSpec("Validate email format in profile", "profile-email-validation",
                   {"src/modules/profile/email.ts": "// validate format"}, _d(3)),
        CommitSpec("Page search results", "search-results-paging",
                   {"src/modules/search/results.vue": "<!-- paging -->"}, _d(4)),
    ),
    "1.2.0": (
        CommitSpec("Refresh push token on resume", "push-token-refresh",
                   {"src/modules/push/registration.ts": "// refresh token on resume"}, _d(8)),
        CommitSpec("Clean up router", None,
                   {"src/app/router.ts": "// remove legacy routes"}, _d(9)),
    ),
    "1.3.0": (
        CommitSpec("Refactor profile store", "profile-store-refactor",
                   {"src/modules/profile/profile.store.ts": "// refactor"}, _d(14)),
    ),
    "1.4.0": (
        CommitSpec("Tweak saved-search defaults", "search-saved-search-tweak",
                   {"src/modules/search/saved-search.ts": "// new defaults"}, _d(18)),
    ),
}


def commit_message(spec: CommitSpec, ticket_keys: dict[str, str]) -> str:
    """Ticket key prefix when the commit has a ticket (Jira assigns the key)."""
    if spec.ticket is None:
        return spec.subject
    return f"{ticket_keys[spec.ticket]}: {spec.subject}"


# ---------------------------------------------------------------- Sentry


@dataclass(frozen=True)
class Frame:
    filename: str
    function: str
    lineno: int


@dataclass(frozen=True)
class Subject:
    """Pinned to real Module 1 seeded subjects so Slice P can look up state."""

    user_id: str  # account-case-*
    installation_id: str  # install-case-*


@dataclass(frozen=True)
class IncidentSpec:
    case: str  # F1..F5 -- also the Sentry fingerprint and the demo_case tag
    release: str  # Sentry release version (may have no git tag: F3)
    exception_type: str
    exception_value: str
    frames: tuple[Frame, ...]  # oldest first, crashing frame last
    breadcrumbs: tuple[dict, ...]
    subjects: tuple[Subject, ...]  # one event per subject
    flags: dict[str, str] = field(default_factory=dict)
    # Per-event breadcrumbs (aligned with `subjects`) when the paths differ;
    # otherwise every event uses `breadcrumbs`.
    event_breadcrumbs: tuple[tuple[dict, ...], ...] | None = None
    # Expected incident context (asserted by tests and the live sweep)
    expected_release_state: str = "KNOWN"
    expected_suspects: tuple[str, ...] | str = ()  # commit subjects, or "UNKNOWN"
    expected_findings: tuple[str, ...] = ()


def _nav(to: str, frm: str) -> dict:
    return {"type": "navigation", "category": "navigation", "data": {"from": frm, "to": to}}


def _tap(target: str) -> dict:
    return {"type": "user", "category": "ui.click", "message": target}


def _http(method: str, url: str, status: int) -> dict:
    return {"type": "http", "category": "xhr", "data": {"method": method, "url": url, "status_code": status}}


def _lifecycle(state: str) -> dict:
    return {"type": "navigation", "category": "app.lifecycle", "data": {"state": state}}


def breadcrumbs_for(spec: "IncidentSpec", index: int) -> tuple[dict, ...]:
    return spec.event_breadcrumbs[index] if spec.event_breadcrumbs else spec.breadcrumbs


_MAIN = Frame("app:///src/app/main.ts", "bootstrap", 12)
_ROUTER = Frame("app:///src/app/router.ts", "resolveRoute", 31)

INCIDENTS = (
    IncidentSpec(
        case="F1",
        release="1.2.0",
        exception_type="TypeError",
        exception_value="Cannot read properties of undefined (reading 'token')",
        frames=(_MAIN, Frame("app:///src/modules/push/registration.ts", "refreshToken", 42)),
        breadcrumbs=(
            _lifecycle("background"), _lifecycle("foreground"),
            _nav("/home", "/"), _nav("/settings/notifications", "/home"),
            _tap("button#enable-push"), _http("POST", "/api/push/register", 401),
        ),
        subjects=(
            Subject("account-case-p1", "install-case-a"),
            Subject("account-case-p3", "install-case-c"),
            Subject("account-case-p6", "install-case-i"),
        ),
        flags={"flag.new_push_flow": "on"},
        expected_suspects=("Refresh push token on resume",),
    ),
    IncidentSpec(
        case="F2",
        release="1.2.0",
        exception_type="RangeError",
        exception_value="Invalid saved-search index",
        frames=(_MAIN, Frame("app:///src/modules/search/saved-search.ts", "loadSavedSearches", 18)),
        breadcrumbs=(_nav("/search", "/home"), _tap("button#saved-searches")),
        subjects=(Subject("account-case-p2", "install-case-b"), Subject("account-case-p4", "install-case-d")),
        expected_suspects=(),
        expected_findings=("NO_SUSPECT_COMMIT",),
    ),
    IncidentSpec(
        case="F3",
        release="1.2.1",  # never tagged in git
        exception_type="Error",
        exception_value="Profile email mismatch after hotfix",
        frames=(_MAIN, Frame("app:///src/modules/profile/email.ts", "validateEmail", 9)),
        breadcrumbs=(_nav("/profile", "/home"), _tap("button#save-profile")),
        subjects=(Subject("account-case-p3", "install-case-e"), Subject("account-case-p9", "install-case-f")),
        expected_release_state="UNKNOWN",
        expected_suspects="UNKNOWN",  # no release -> can't know, never "none"
        expected_findings=("RELEASE_NOT_FOUND",),
    ),
    IncidentSpec(
        case="F4",
        release="1.3.0",
        exception_type="TypeError",
        exception_value="e is not a function",
        frames=(Frame("app:///main.3f9a1c.js", "a", 1), Frame("app:///main.3f9a1c.js", "n", 1)),
        breadcrumbs=(_nav("/home", "/"),),
        subjects=(Subject("account-case-p5", "install-case-g"), Subject("account-case-p7", "install-case-h")),
        expected_suspects="UNKNOWN",
        expected_findings=("FRAMES_UNMAPPABLE",),
    ),
    IncidentSpec(
        case="F5",
        release="1.2.0",
        exception_type="Error",
        exception_value="No route matches /legacy/inbox",
        frames=(_MAIN, _ROUTER),
        breadcrumbs=(_nav("/legacy/inbox", "/home"),),
        subjects=(Subject("account-case-p8", "install-case-j"), Subject("account-case-p10", "install-case-k")),
        expected_suspects=("Clean up router",),
        expected_findings=("SUSPECT_WITHOUT_TICKET",),
    ),
)


# Release-health sessions per release, for Slice R: (total, crashed).
SESSIONS: dict[str, tuple[int, int]] = {
    "1.1.0": (400, 4),  # healthy baseline, 99% crash-free
    "1.2.0": (400, 40),  # crash regression, 90%
    "1.3.0": (400, 3),  # clean
    "1.4.0": (15, 0),  # too few sessions to judge
}
SESSION_BUCKETS = 4  # spread each release's sessions over this many hours


# ---------------------------------------------------------------- Slice R

# One more F2 event, on 1.3.0, sent after the user resolved F2 in Sentry's UI:
# Sentry then marks the issue regressed in 1.3.0 (first release stays 1.2.0).
REGRESSION_CASE = "F2"
REGRESSION_RELEASE = "1.3.0"
REGRESSION_SUBJECT = Subject("account-case-p2", "install-case-l")


@dataclass(frozen=True)
class ImpactSpec:
    case: str  # RI1..RI6
    release: str
    expected_status: int = 200
    expected_release_state: str = "KNOWN"
    expected_crash_free: float | str | None = None  # rate, "UNKNOWN", or None when not asserted
    expected_findings: tuple[str, ...] = ()  # release-level + per-issue codes, in response order
    expected_new_issues: tuple[str, ...] = ()  # incident cases (F1..F5)
    expected_regressed_issues: tuple[str, ...] = ()


IMPACTS = (
    ImpactSpec("RI1", "1.1.0", expected_crash_free=0.99, expected_findings=("NO_BASELINE_HEALTH",)),
    ImpactSpec("RI2", "1.2.0", expected_crash_free=0.90,
               expected_findings=("CRASH_RATE_REGRESSION", "NEW_ISSUE_ATTRIBUTED", "NEW_ISSUE_UNATTRIBUTED",
                                  "NEW_ISSUE_ATTRIBUTED"),
               expected_new_issues=("F1", "F2", "F5")),
    ImpactSpec("RI3", "1.3.0", expected_crash_free=0.9925,
               expected_findings=("CRASH_RATE_IMPROVED", "NEW_ISSUE_ATTRIBUTION_UNKNOWN", "ISSUE_REGRESSED"),
               expected_new_issues=("F4",), expected_regressed_issues=("F2",)),
    ImpactSpec("RI4", "1.4.0", expected_crash_free="UNKNOWN", expected_findings=("INSUFFICIENT_ADOPTION",)),
    ImpactSpec("RI5", "1.2.1", expected_release_state="UNKNOWN", expected_crash_free="UNKNOWN",
               expected_findings=("RELEASE_NOT_FOUND", "NO_SESSION_DATA", "NEW_ISSUE_ATTRIBUTION_UNKNOWN"),
               expected_new_issues=("F3",)),
    ImpactSpec("RI6", "9.9.9", expected_status=404),
)


# ---------------------------------------------------------------- Slice P

# F6: sent separately (`sentry-repro`) so earlier Sentry steps are never
# re-sent. Three different paths into the same crash; all three installs have
# push OS permission DENIED in Module 1 (a real precondition), while the three
# accounts' profile states differ (consistent / inconsistent / unknown).
_F6_ENDING = (
    _nav("/settings/notifications", "/settings"),
    _tap("button#enable-push"),
    _http("POST", "/api/push/permission", 403),
)
MAX_BREADCRUMBS = 100

REPRO_INCIDENTS = (
    IncidentSpec(
        case="F6",
        release="1.4.0",
        exception_type="TypeError",
        exception_value="Cannot read properties of null (reading 'status')",
        frames=(_MAIN, Frame("app:///src/modules/push/permission.ts", "requestPermission", 27)),
        breadcrumbs=(),
        subjects=(
            Subject("account-case-p1", "install-case-c"),
            Subject("account-case-p3", "install-case-h"),
            Subject("account-case-p7", "install-case-m"),
        ),
        event_breadcrumbs=(
            (_nav("/home", "/"), _nav("/settings", "/home"), *_F6_ENDING),
            (_lifecycle("foreground"), _nav("/inbox", "/"), *_F6_ENDING),
            # A full trail: the start of this user's path is lost to the limit.
            tuple(_nav(f"/search/results?page={n + 1}", f"/search/results?page={n}")
                  for n in range(MAX_BREADCRUMBS - len(_F6_ENDING))) + _F6_ENDING,
        ),
        expected_suspects=(),  # 1.4.0 only touched saved-search
        expected_findings=("NO_SUSPECT_COMMIT",),
    ),
)
ALL_INCIDENTS = INCIDENTS + REPRO_INCIDENTS


@dataclass(frozen=True)
class ReproSpec:
    case: str  # RP1..RP7
    incident: str  # F1..F6, or an id that was never ingested
    expected_status: int = 200
    expected_steps: tuple[str, ...] = ()  # "KIND target"
    expected_variants: int = 0
    expected_preconditions: dict = field(default_factory=dict)  # subset: key -> value
    expected_varies: tuple[str, ...] = ()  # subset of keys
    expected_gaps: tuple[str, ...] = ()  # exact codes, in response order
    expected_suspects: tuple[str, ...] | str = ()  # commit subjects, or "UNKNOWN"


REPROS = (
    ReproSpec("RP1", "F1",
              expected_steps=("LIFECYCLE background", "LIFECYCLE foreground", "NAVIGATE /home",
                              "NAVIGATE /settings/notifications", "TAP button#enable-push",
                              "BACKEND_CALL POST /api/push/register 401"),
              expected_preconditions={"flag.new_push_flow": "on", "app.version": "1.2.0", "os.name": "iOS",
                                      "device.model": "iPhone15,2"},
              # Not push.deliverable: it depends on wall-clock registration freshness,
              # which would make this expectation change on a date instead of a code change.
              expected_varies=("push.os_permission", "push.provider_registration", "profile.consistent"),
              expected_suspects=("Refresh push token on resume",)),
    ReproSpec("RP2", "F6",
              expected_steps=("NAVIGATE /settings/notifications", "TAP button#enable-push",
                              "BACKEND_CALL POST /api/push/permission 403"),
              expected_variants=3,
              expected_preconditions={"push.os_permission": "DENIED", "push.deliverable": False,
                                      "app.version": "1.4.0"},
              expected_varies=("profile.consistent",),
              expected_gaps=("BREADCRUMBS_TRUNCATED",)),
    ReproSpec("RP3", "F4", expected_steps=("NAVIGATE /home",), expected_gaps=("CULPRIT_UNMAPPABLE",),
              expected_suspects="UNKNOWN"),
    ReproSpec("RP4", "F3", expected_steps=("NAVIGATE /profile", "TAP button#save-profile"),
              expected_preconditions={"app.version": "1.2.1"}, expected_suspects="UNKNOWN"),
    ReproSpec("RP5", "F2", expected_steps=("NAVIGATE /search", "TAP button#saved-searches"),
              expected_varies=("app.version",)),
    ReproSpec("RP6", "F5", expected_steps=("NAVIGATE /legacy/inbox",), expected_suspects=("Clean up router",)),
    ReproSpec("RP7", "never-ingested", expected_status=404),
)
