"""add incident status and regression release (Slice R)

Revision ID: e81d29c0495c
Revises: 69aee76d7d3b
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e81d29c0495c"
down_revision = "69aee76d7d3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incident", sa.Column("status", sa.Text()))
    op.add_column("incident", sa.Column("substatus", sa.Text()))
    # Sentry release name in which the issue last regressed (resolved -> seen again).
    op.add_column("incident", sa.Column("regressed_release", sa.Text()))


def downgrade() -> None:
    op.drop_column("incident", "regressed_release")
    op.drop_column("incident", "substatus")
    op.drop_column("incident", "status")
