"""Org configuration: everything organization-specific lives in
config/org.<name>.yaml, so moving from the demo accounts to another org is a
config change, not a code change."""

import re
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GithubConfig(_Strict):
    repo: str


class JiraConfig(_Strict):
    base_url: str
    project_key: str
    ticket_key_pattern: str

    @field_validator("ticket_key_pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        re.compile(value)
        return value


class SentryConfig(_Strict):
    base_url: str
    org: str
    project: str


class ReleaseConfig(_Strict):
    sentry_template: str
    tag_template: str

    @field_validator("sentry_template", "tag_template")
    @classmethod
    def _has_version(cls, value: str) -> str:
        if value.count("{version}") != 1:
            raise ValueError("template must contain {version} exactly once")
        return value


class ComponentRule(_Strict):
    glob: str
    component: str


class FramePathConfig(_Strict):
    strip_prefixes: tuple[str, ...] = ()
    unmappable: tuple[str, ...] = ()


class ImpactConfig(_Strict):
    min_sessions: int = 100
    crash_regression_pp: float = 2.0
    settle_minutes: int = 60


class OrgConfig(_Strict):
    name: str
    github: GithubConfig
    jira: JiraConfig
    sentry: SentryConfig
    releases: ReleaseConfig
    components: tuple[ComponentRule, ...]
    frame_paths: FramePathConfig
    impact: ImpactConfig = ImpactConfig()

    # ---- releases ----

    def _template_regex(self, template: str) -> re.Pattern[str]:
        prefix, suffix = template.split("{version}")
        return re.compile(rf"^{re.escape(prefix)}(?P<version>.+?){re.escape(suffix)}$")

    def version_from_sentry_release(self, release: str) -> str | None:
        """None when the release doesn't follow this app's naming (e.g. probes)."""
        match = self._template_regex(self.releases.sentry_template).match(release)
        return match["version"] if match else None

    def version_from_tag(self, tag: str) -> str | None:
        match = self._template_regex(self.releases.tag_template).match(tag)
        return match["version"] if match else None

    def tag_for(self, version: str) -> str:
        return self.releases.tag_template.format(version=version)

    def sentry_release_for(self, version: str) -> str:
        return self.releases.sentry_template.format(version=version)

    # ---- tickets ----

    def ticket_keys(self, text: str) -> list[str]:
        """Unique ticket keys in order of first appearance."""
        seen: dict[str, None] = {}
        for key in re.findall(self.jira.ticket_key_pattern, text):
            seen.setdefault(key)
        return list(seen)

    # ---- paths ----

    def component_for(self, path: str) -> str | None:
        for rule in self.components:
            if fnmatchcase(path, rule.glob):
                return rule.component
        return None

    def normalize_frame_path(self, raw: str | None) -> str | None:
        """Frame path as a repo-relative path, or None if it can't be mapped
        (missing, or bundled output such as main.<hash>.js)."""
        if not raw:
            return None
        path = raw
        for prefix in self.frame_paths.strip_prefixes:
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        path = path.lstrip("/")
        if any(re.search(pattern, path) for pattern in self.frame_paths.unmappable):
            return None
        return path


def available_orgs() -> list[str]:
    return sorted(p.stem.removeprefix("org.") for p in CONFIG_DIR.glob("org.*.yaml"))


@cache
def load_org(name: str) -> OrgConfig:
    path = CONFIG_DIR / f"org.{name}.yaml"
    if not path.is_file():
        raise KeyError(f"Unknown org {name!r}; available: {available_orgs()}")
    return OrgConfig.model_validate(yaml.safe_load(path.read_text()))
