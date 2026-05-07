"""Add github_webhook_delivery for webhook idempotency

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-05-06

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_webhook_delivery",
        sa.Column(
            "delivery_id",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
        ),
        sa.Column(
            "github_event",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("delivery_id"),
    )


def downgrade() -> None:
    op.drop_table("github_webhook_delivery")
