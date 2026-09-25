"""Build connectors for an org from its config plus environment tokens."""

import os

import httpx
from dotenv import load_dotenv

from app.connectors.github import GitHubClient
from app.connectors.jira import JiraClient
from app.connectors.sentry import SentryClient
from app.orgs import OrgConfig


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value


def build_clients(org: OrgConfig, transport: httpx.BaseTransport | None = None):
    load_dotenv()  # no-op for variables already in the environment
    return (
        GitHubClient(org.github.repo, _env("GITHUB_READ_TOKEN"), transport),
        JiraClient(org.jira.base_url, _env("JIRA_EMAIL"), _env("JIRA_API_TOKEN"), transport),
        SentryClient(org.sentry.base_url, org.sentry.org, org.sentry.project, _env("SENTRY_READ_TOKEN"), transport),
    )
