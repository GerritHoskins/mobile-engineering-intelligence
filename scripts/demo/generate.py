"""Plant the Slice F demo data in the personal Jira / GitHub / Sentry accounts.

Each sub-command is one kind of external write, run separately and only with
the user's go-ahead. `--dry-run` prints what would be written, writes nothing.

    uv run python -m scripts.demo.generate jira [--dry-run]
    uv run python -m scripts.demo.generate git [--dry-run]
    uv run python -m scripts.demo.generate sentry-events [--dry-run]
    uv run python -m scripts.demo.generate sentry-sessions [--dry-run]

Credentials come from .env (see .env.example) and are never printed.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from app.orgs import load_org
from scripts.demo import scenario as sc

STATE_FILE = Path(__file__).with_name(".state.json")
ORG = load_org("demo")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set (see .env.example)")
    return value


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.is_file() else {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ jira


def _jira() -> httpx.Client:
    return httpx.Client(
        base_url=ORG.jira.base_url,
        auth=(_env("JIRA_EMAIL"), _env("JIRA_API_TOKEN")),
        headers={"Accept": "application/json"},
        timeout=30,
    )


def _find_ticket_by_marker(client: httpx.Client, spec: sc.TicketSpec) -> str | None:
    """Fallback only (search can lag right after creation): the state file is
    the primary key map."""
    jql = f'project = {ORG.jira.project_key} AND labels = "{sc.JIRA_LABEL}"'
    token = None
    while True:
        params = {"jql": jql, "fields": "summary", "maxResults": 100}
        if token:
            params["nextPageToken"] = token
        page = client.get("/rest/api/3/search/jql", params=params).raise_for_status().json()
        for issue in page.get("issues", []):
            if issue["fields"]["summary"].startswith(f"[demo:{spec.marker}]"):
                return issue["key"]
        token = page.get("nextPageToken")
        if not token:
            return None


def cmd_jira(dry_run: bool) -> None:
    state = load_state()
    keys: dict[str, str] = state.setdefault("jira_keys", {})
    client = _jira()
    project = client.get(f"/rest/api/3/project/{ORG.jira.project_key}").raise_for_status().json()
    existing_versions = {v["name"] for v in client.get(
        f"/rest/api/3/project/{ORG.jira.project_key}/versions").raise_for_status().json()}

    for version in sorted({t.fix_version for t in sc.TICKETS}):
        name = ORG.tag_for(version)
        if name in existing_versions:
            print(f"version {name}: exists")
        elif dry_run:
            print(f"version {name}: WOULD CREATE")
        else:
            client.post("/rest/api/3/version", json={"name": name, "projectId": int(project["id"])}).raise_for_status()
            print(f"version {name}: created")

    for spec in sc.TICKETS:
        key = keys.get(spec.marker) or _find_ticket_by_marker(client, spec)
        if key:
            keys[spec.marker] = key
            print(f"{spec.marker}: exists as {key}")
            continue
        if dry_run:
            print(f"{spec.marker}: WOULD CREATE {spec.issue_type} '{spec.jira_summary}' "
                  f"(component {spec.component}, fix version {ORG.tag_for(spec.fix_version)})")
            continue
        fields = {
            "project": {"key": ORG.jira.project_key},
            "summary": spec.jira_summary,
            "issuetype": {"name": spec.issue_type},
            "labels": [sc.JIRA_LABEL],
            "components": [{"name": spec.component}],
            "fixVersions": [{"name": ORG.tag_for(spec.fix_version)}],
        }
        created = client.post("/rest/api/3/issue", json={"fields": fields}).raise_for_status().json()
        keys[spec.marker] = created["key"]
        save_state(state)  # persist after every create: a crash must not cause duplicates
        print(f"{spec.marker}: created {created['key']}")

    if not dry_run:
        save_state(state)


# ------------------------------------------------------------------- git


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=repo, env={**os.environ, **(env or {})}, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _build_history(repo: Path, ticket_keys: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Deterministic history on top of BASE_COMMIT. Returns (head sha, tag -> sha)."""
    _git(repo, "checkout", "-q", "--detach", sc.BASE_COMMIT)
    tags: dict[str, str] = {}
    for version in sc.VERSIONS:
        for spec in sc.RELEASE_COMMITS[version]:
            for path, line in spec.files.items():
                file = repo / path
                file.parent.mkdir(parents=True, exist_ok=True)
                previous = file.read_text() if file.exists() else ""
                file.write_text(previous + line + "\n")
                _git(repo, "add", path)
            stamp = spec.date.strftime("%Y-%m-%dT%H:%M:%S+0000")
            identity = {
                "GIT_AUTHOR_NAME": sc.AUTHOR_NAME, "GIT_AUTHOR_EMAIL": sc.AUTHOR_EMAIL, "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": sc.AUTHOR_NAME, "GIT_COMMITTER_EMAIL": sc.AUTHOR_EMAIL,
                "GIT_COMMITTER_DATE": stamp,
            }
            _git(repo, "commit", "-q", "-m", sc.commit_message(spec, ticket_keys), env=identity)
        tag = ORG.tag_for(version)
        _git(repo, "tag", "-f", tag)  # lightweight: no tagger date, stays deterministic
        tags[tag] = _git(repo, "rev-parse", "HEAD")
    return _git(repo, "rev-parse", "HEAD"), tags


def cmd_git(dry_run: bool) -> None:
    state = load_state()
    ticket_keys = state.get("jira_keys", {})
    missing = [t.marker for t in sc.TICKETS if t.marker not in ticket_keys]
    if missing:
        sys.exit(f"Run the jira step first; no keys for: {missing}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        subprocess.run(["git", "clone", "-q", f"git@github.com:{ORG.github.repo}.git", str(repo)], check=True)
        remote_head = _git(repo, "rev-parse", "origin/main")
        head, tags = _build_history(repo, ticket_keys)
        print(f"planned head {head[:7]}; tags " + ", ".join(f"{t}={s[:7]}" for t, s in tags.items()))
        for line in _git(repo, "log", "--format=%h %s", f"{sc.BASE_COMMIT}..HEAD").splitlines():
            print(f"  {line}")

        if remote_head == head:
            print("remote main already has this history: nothing to push")
        elif remote_head != sc.BASE_COMMIT:
            sys.exit(f"remote main is {remote_head[:7]}, neither the README base nor the planned head; "
                     "refusing to push (no force-push, ever)")
        elif dry_run:
            print(f"WOULD PUSH main ({sc.BASE_COMMIT[:7]} -> {head[:7]}) and {len(tags)} tags")
        else:
            _git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
            _git(repo, "push", "-q", "origin", *[f"refs/tags/{t}" for t in tags])
            print(f"pushed main -> {head[:7]} and {len(tags)} tags")

    if not dry_run:
        state["git"] = {"head": head, "tags": tags}
        save_state(state)


# ---------------------------------------------------------------- sentry


def _sentry_target() -> tuple[str, str]:
    dsn = urlparse(_env("SENTRY_DSN"))
    url = f"{dsn.scheme}://{dsn.hostname}/api/{dsn.path.strip('/')}/envelope/"
    auth = f"Sentry sentry_version=7, sentry_key={dsn.username}, sentry_client=mei-demo-generator/0.1"
    return url, auth


def _send_envelope(header: dict, item_type: str, payload: dict) -> None:
    url, auth = _sentry_target()
    body = "\n".join([json.dumps(header), json.dumps({"type": item_type}), json.dumps(payload)]) + "\n"
    httpx.post(url, content=body, timeout=30,
               headers={"X-Sentry-Auth": auth, "Content-Type": "application/x-sentry-envelope"}).raise_for_status()


def build_event(spec: sc.IncidentSpec, subject: sc.Subject, occurred_at: datetime) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": _iso(occurred_at),
        "platform": "javascript",
        "level": "error",
        "environment": "production",
        "release": ORG.sentry_release_for(spec.release),
        "fingerprint": ["demo", spec.case],
        "user": {"id": subject.user_id},
        "tags": {"demo_case": spec.case, "installation_id": subject.installation_id, **spec.flags},
        "contexts": {
            "device": {"family": "iOS", "model": "iPhone15,2"},
            "os": {"name": "iOS", "version": "18.4"},
            "app": {"app_version": spec.release},
        },
        "breadcrumbs": {"values": [
            {"timestamp": _iso(occurred_at - timedelta(seconds=len(spec.breadcrumbs) - i)), **crumb}
            for i, crumb in enumerate(spec.breadcrumbs)
        ]},
        "exception": {"values": [{
            "type": spec.exception_type,
            "value": spec.exception_value,
            "stacktrace": {"frames": [
                {"filename": f.filename, "abs_path": f.filename, "function": f.function,
                 "lineno": f.lineno, "in_app": True}
                for f in spec.frames
            ]},
        }]},
    }


def cmd_sentry_events(dry_run: bool) -> None:
    state = load_state()
    now = datetime.now(timezone.utc)
    # First-release is decided by the first event Sentry processes, so send
    # older releases first and keep every case within the last ~2 days.
    ordered = sorted(sc.INCIDENTS, key=lambda s: tuple(int(p) for p in s.release.split(".")))
    sent = state.setdefault("sentry_events", [])
    for n, spec in enumerate(ordered):
        for m, subject in enumerate(spec.subjects):
            occurred_at = now - timedelta(hours=36) + timedelta(minutes=30 * n + 5 * m)
            event = build_event(spec, subject, occurred_at)
            label = (f"{spec.case} {event['release']} {spec.exception_type} "
                     f"user={subject.user_id} install={subject.installation_id}")
            if dry_run:
                print(f"WOULD SEND {label}")
                continue
            _send_envelope({"event_id": event["event_id"], "sent_at": _iso(now)}, "event", event)
            sent.append({"case": spec.case, "event_id": event["event_id"], "sent_at": _iso(now)})
            print(f"sent {label}")
    if not dry_run:
        save_state(state)


def cmd_sentry_sessions(dry_run: bool) -> None:
    state = load_state()
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=30)
    for version, (total, crashed) in sc.SESSIONS.items():
        release = ORG.sentry_release_for(version)
        aggregates = []
        for b in range(sc.SESSION_BUCKETS):
            share = total // sc.SESSION_BUCKETS + (1 if b < total % sc.SESSION_BUCKETS else 0)
            crash = crashed // sc.SESSION_BUCKETS + (1 if b < crashed % sc.SESSION_BUCKETS else 0)
            aggregates.append({"started": _iso(start + timedelta(hours=b)), "exited": share - crash, "crashed": crash})
        payload = {"aggregates": aggregates, "attrs": {"release": release, "environment": "production"}}
        if dry_run:
            print(f"WOULD SEND {release}: {total} sessions, {crashed} crashed, {sc.SESSION_BUCKETS} hourly buckets")
            continue
        _send_envelope({"sent_at": _iso(datetime.now(timezone.utc))}, "sessions", payload)
        print(f"sent {release}: {total} sessions, {crashed} crashed")
    if not dry_run:
        state["sessions_window"] = {"start": _iso(start), "end": _iso(start + timedelta(hours=sc.SESSION_BUCKETS))}
        save_state(state)


COMMANDS = {
    "jira": cmd_jira,
    "git": cmd_git,
    "sentry-events": cmd_sentry_events,
    "sentry-sessions": cmd_sentry_sessions,
}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--dry-run", action="store_true", help="print planned writes, write nothing")
    args = parser.parse_args()
    COMMANDS[args.command](args.dry_run)


if __name__ == "__main__":
    main()
