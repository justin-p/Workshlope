"""Add workshop badge catalog and grants tables

Revision ID: 6c8d9e0f1a22
Revises: 5b7c8d9e0f11
Create Date: 2026-05-06 13:40:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "6c8d9e0f1a22"
down_revision = "5b7c8d9e0f11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workshop_badge_definition",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "description", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("points >= 0", name="ck_badge_definition_points_min"),
        sa.CheckConstraint("points <= 1000", name="ck_badge_definition_points_max"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        op.f("ix_workshop_badge_definition_slug"),
        "workshop_badge_definition",
        ["slug"],
        unique=False,
    )
    op.create_table(
        "workshop_badge_grant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("badge_id", sa.UUID(), nullable=False),
        sa.Column("granted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "revoked_reason", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["badge_id"], ["workshop_badge_definition.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["workshop_session.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "user_id", "badge_id", name="uq_workshop_badge_grant_once"
        ),
    )


def downgrade():
    op.drop_table("workshop_badge_grant")
    op.drop_index(
        op.f("ix_workshop_badge_definition_slug"), table_name="workshop_badge_definition"
    )
    op.drop_table("workshop_badge_definition")
