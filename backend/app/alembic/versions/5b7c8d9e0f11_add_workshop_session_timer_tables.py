"""Add workshop session timer tables

Revision ID: 5b7c8d9e0f11
Revises: 4f6e7d8c9a01
Create Date: 2026-05-06 11:10:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "5b7c8d9e0f11"
down_revision = "4f6e7d8c9a01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workshop_session_timer",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("target_seconds", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("target_seconds >= 1", name="ck_timer_target_seconds_min"),
        sa.CheckConstraint("target_seconds <= 86400", name="ck_timer_target_seconds_max"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["workshop_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_workshop_session_timer_session"),
    )
    op.create_table(
        "workshop_session_timer_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("target_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_seconds >= 1", name="ck_timer_event_target_seconds_min"
        ),
        sa.CheckConstraint(
            "target_seconds <= 86400", name="ck_timer_event_target_seconds_max"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["workshop_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("workshop_session_timer_event")
    op.drop_table("workshop_session_timer")
