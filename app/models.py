import uuid

from sqlalchemy import Boolean, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StateObservation(Base):
    __tablename__ = "state_observation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    __table_args__ = (
        Index("ix_state_observation_subject_domain", "subject_type", "subject_id", "domain"),
    )


# ---------------------------------------------------------------------------
# Slice F: releases, commits, tickets and incidents. Every table leads its
# primary key with `org`, so several orgs (the demo accounts, later meinestadt)
# live side by side without colliding, and ingestion upserts on the key.


class Release(Base):
    __tablename__ = "release"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    tag: Mapped[str | None] = mapped_column(Text)  # None: seen in Sentry, no git tag
    sentry_release: Mapped[str | None] = mapped_column(Text)


class Commit(Base):
    __tablename__ = "commit"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    repo: Mapped[str] = mapped_column(Text, primary_key=True)
    sha: Mapped[str] = mapped_column(Text, primary_key=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    authored_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ReleaseCommit(Base):
    __tablename__ = "release_commit"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    repo: Mapped[str] = mapped_column(Text, primary_key=True)
    sha: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # oldest first


class ChangedFile(Base):
    __tablename__ = "changed_file"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    repo: Mapped[str] = mapped_column(Text, primary_key=True)
    sha: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str | None] = mapped_column(Text)


class Ticket(Base):
    __tablename__ = "ticket"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    summary: Mapped[str | None] = mapped_column(Text)
    issue_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    components: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    fix_versions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Referenced by a commit but not returned by Jira.
    missing_in_jira: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class CommitTicket(Base):
    __tablename__ = "commit_ticket"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    repo: Mapped[str] = mapped_column(Text, primary_key=True)
    sha: Mapped[str] = mapped_column(Text, primary_key=True)
    ticket_key: Mapped[str] = mapped_column(Text, primary_key=True)


class Incident(Base):
    __tablename__ = "incident"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    sentry_issue_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    culprit: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)
    first_release: Mapped[str | None] = mapped_column(Text)  # Sentry release name
    first_seen: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(Text)
    substatus: Mapped[str | None] = mapped_column(Text)
    regressed_release: Mapped[str | None] = mapped_column(Text)  # Sentry release of the latest regression


class IncidentEvent(Base):
    __tablename__ = "incident_event"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sentry_issue_id: Mapped[str] = mapped_column(Text, nullable=False)
    release: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[str | None] = mapped_column(Text)
    installation_id: Mapped[str | None] = mapped_column(Text)
    exception: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    frames: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")  # normalized
    breadcrumbs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    contexts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (Index("ix_incident_event_issue", "org", "sentry_issue_id"),)


class ReleaseSessionCount(Base):
    """Raw hourly release-health counts. Rates are computed from these (Slice R),
    never read from Sentry's crash_free_rate."""

    __tablename__ = "release_session_count"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    sentry_release: Mapped[str] = mapped_column(Text, primary_key=True)
    bucket_start: Mapped[object] = mapped_column(DateTime(timezone=True), primary_key=True)
    status: Mapped[str] = mapped_column(Text, primary_key=True)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False)


class LlmOutput(Base):
    """Stored LLM explanations, keyed by a hash of exactly what the model saw
    (packet + model + prompt version): same input -> same stored text, no call."""

    __tablename__ = "llm_output"

    org: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    subject: Mapped[str] = mapped_column(Text, primary_key=True)
    input_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    served_by: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rejected: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
