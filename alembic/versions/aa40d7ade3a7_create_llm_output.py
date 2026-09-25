"""create llm_output (LLM layer)

Revision ID: aa40d7ade3a7
Revises: e81d29c0495c
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "aa40d7ade3a7"
down_revision = "e81d29c0495c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_output",
        sa.Column("org", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),  # release_summary | repro_narrative
        sa.Column("subject", sa.Text(), primary_key=True),  # release version or Sentry issue id
        sa.Column("input_hash", sa.Text(), primary_key=True),  # packet + model + prompt version
        sa.Column("model", sa.Text(), nullable=False),  # requested model
        sa.Column("served_by", sa.Text(), nullable=False),  # model that answered (fallback-aware)
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("rejected", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("llm_output")
