import httpx

from app.connectors.http import get_with_retry, iter_link_pages


class GitHubClient:
    def __init__(self, repo: str, token: str, transport: httpx.BaseTransport | None = None):
        self.repo = repo
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30, transport=transport,
        )

    def list_tags(self) -> list[dict]:
        tags: list[dict] = []
        for page in iter_link_pages(self.client, f"/repos/{self.repo}/tags", {"per_page": 100}):
            tags.extend(page.json())
        return tags

    def compare_commits(self, base: str, head: str) -> list[dict]:
        """Commits in (base, head], oldest first. Files are fetched per commit
        (compare's file list is aggregated over the whole range)."""
        data = get_with_retry(self.client, f"/repos/{self.repo}/compare/{base}...{head}").json()
        return data["commits"]

    def get_commit(self, sha: str) -> dict:
        return get_with_retry(self.client, f"/repos/{self.repo}/commits/{sha}").json()
