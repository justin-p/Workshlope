"""Add avatar_url to oauth_account

Revision ID: b3c4d5e6f7a8
Revises: aa12bb34cc56
Create Date: 2026-05-07

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "aa12bb34cc56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_account",
        sa.Column(
            "avatar_url",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_account", "avatar_url")
