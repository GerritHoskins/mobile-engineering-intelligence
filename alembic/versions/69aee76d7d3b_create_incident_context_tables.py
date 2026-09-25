"""create incident context tables (Slice F)

Revision ID: 69aee76d7d3b
Revises: 27c47fa8f0b4
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "69aee76d7d3b"
down_revision = "27c47fa8f0b4"
branch_labels = None
depends_on = None

JSONB_LIST = sa.text("'[]'")
JSONB_OBJECT = sa.text("'{}'")


def _org() -> sa.Column:
    return sa.Column("org", sa.Text(), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "release",
        _org(),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("tag", sa.Text()),
        sa.Column("sentry_release", sa.Text()),
    )
    op.create_table(
        "commit",
        _org(),
        sa.Column("repo", sa.Text(), primary_key=True),
        sa.Column("sha", sa.Text(), primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "release_commit",
        _org(),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("repo", sa.Text(), primary_key=True),
        sa.Column("sha", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "changed_file",
        _org(),
        sa.Column("repo", sa.Text(), primary_key=True),
        sa.Column("sha", sa.Text(), primary_key=True),
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("component", sa.Text()),
    )
    op.create_table(
        "ticket",
        _org(),
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("summary", sa.Text()),
        sa.Column("issue_type", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("components", postgresql.JSONB(), nullable=False, server_default=JSONB_LIST),
        sa.Column("fix_versions", postgresql.JSONB(), nullable=False, server_default=JSONB_LIST),
        sa.Column("missing_in_jira", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "commit_ticket",
        _org(),
        sa.Column("repo", sa.Text(), primary_key=True),
        sa.Column("sha", sa.Text(), primary_key=True),
        sa.Column("ticket_key", sa.Text(), primary_key=True),
    )
    op.create_table(
        "incident",
        _org(),
        sa.Column("sentry_issue_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("culprit", sa.Text()),
        sa.Column("level", sa.Text()),
        sa.Column("first_release", sa.Text()),
        sa.Column("first_seen", sa.DateTime(timezone=True)),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "incident_event",
        _org(),
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("sentry_issue_id", sa.Text(), nullable=False),
        sa.Column("release", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Text()),
        sa.Column("installation_id", sa.Text()),
        sa.Column("exception", postgresql.JSONB(), nullable=False, server_default=JSONB_OBJECT),
        sa.Column("frames", postgresql.JSONB(), nullable=False, server_default=JSONB_LIST),
        sa.Column("breadcrumbs", postgresql.JSONB(), nullable=False, server_default=JSONB_LIST),
        sa.Column("contexts", postgresql.JSONB(), nullable=False, server_default=JSONB_OBJECT),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=JSONB_OBJECT),
    )
    op.create_index("ix_incident_event_issue", "incident_event", ["org", "sentry_issue_id"])
    op.create_table(
        "release_session_count",
        _org(),
        sa.Column("sentry_release", sa.Text(), primary_key=True),
        sa.Column("bucket_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("status", sa.Text(), primary_key=True),
        sa.Column("sessions", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("release_session_count")
    op.drop_index("ix_incident_event_issue", table_name="incident_event")
    for table in ("incident_event", "incident", "commit_ticket", "ticket", "changed_file",
                  "release_commit", "commit", "release"):
        op.drop_table(table)
