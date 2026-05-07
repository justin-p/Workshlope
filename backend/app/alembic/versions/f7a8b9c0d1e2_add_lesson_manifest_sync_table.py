"""Add lesson manifest sync table

Revision ID: f7a8b9c0d1e2
Revises: c3d4e5f6a7b9
Create Date: 2026-05-07 16:40:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "c3d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lesson_manifest_sync",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column(
            "lesson_slug", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "manifest_repo_path",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=False,
        ),
        sa.Column(
            "manifest_sha256",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["lesson_repo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repo_id",
            "manifest_repo_path",
            name="uq_lesson_manifest_sync_repo_path",
        ),
        sa.UniqueConstraint(
            "repo_id",
            "lesson_slug",
            name="uq_lesson_manifest_sync_repo_slug",
        ),
    )


def downgrade():
    op.drop_table("lesson_manifest_sync")
