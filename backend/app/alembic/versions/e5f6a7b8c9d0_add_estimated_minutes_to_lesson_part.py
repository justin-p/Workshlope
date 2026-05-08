"""Add estimated_minutes to lesson_part.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-08
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_part",
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lesson_part", "estimated_minutes")
