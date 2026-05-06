"""Add lesson sync tables

Revision ID: c4d5e6f7a8b9
Revises: 7a1f3c2d9b10
Create Date: 2026-05-01 13:25:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "7a1f3c2d9b10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lesson_repo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column(
            "default_branch", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("health", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lesson_repo_full_name"), "lesson_repo", ["full_name"], unique=True)

    op.create_table(
        "lesson",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column("lesson_sync_generation", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["lesson_repo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "slug", name="uq_lesson_repo_slug"),
    )

    op.create_table(
        "lesson_part",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("ordering", sa.Integer(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("body_md", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lesson.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "slug", name="uq_lesson_part_slug"),
        sa.UniqueConstraint("lesson_id", "ordering", name="uq_lesson_part_ordering"),
    )


def downgrade():
    op.drop_table("lesson_part")
    op.drop_table("lesson")
    op.drop_index(op.f("ix_lesson_repo_full_name"), table_name="lesson_repo")
    op.drop_table("lesson_repo")
