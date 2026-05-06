"""Add lesson prerequisite tables

Revision ID: 4f6e7d8c9a01
Revises: e8f9a0b1c2d3
Create Date: 2026-05-04 18:40:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "4f6e7d8c9a01"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lesson_prerequisite",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("details", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("ordering", sa.Integer(), nullable=False),
        sa.Column("required_flag", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lesson.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "ordering", name="uq_lesson_prerequisite_ordering"),
    )
    op.create_table(
        "user_prerequisite_completion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("prerequisite_id", sa.UUID(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lesson.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["prerequisite_id"], ["lesson_prerequisite.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "prerequisite_id", name="uq_user_prerequisite_completion"
        ),
    )


def downgrade():
    op.drop_table("user_prerequisite_completion")
    op.drop_table("lesson_prerequisite")
