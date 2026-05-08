"""Add lesson repo asset cache table.

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-08
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_repo_asset",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("repo_path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column(
            "content_type",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "content_sha256",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["lesson_repo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "repo_path", name="uq_lesson_repo_asset_repo_path"),
    )


def downgrade() -> None:
    op.drop_table("lesson_repo_asset")
