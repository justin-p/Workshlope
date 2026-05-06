"""Add is_instructor flag to user

Revision ID: 7a1f3c2d9b10
Revises: 3b4c5d6e7f80
Create Date: 2026-05-01 13:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "7a1f3c2d9b10"
down_revision = "3b4c5d6e7f80"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("is_instructor", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("user", "is_instructor", server_default=None)


def downgrade():
    op.drop_column("user", "is_instructor")
