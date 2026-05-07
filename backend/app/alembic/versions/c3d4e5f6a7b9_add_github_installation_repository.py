"""Add github_installation_repository entitlement table.

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-05-07

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "c3d4e5f6a7b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_installation_repository",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "full_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["github_app_installation.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "full_name",
            name="uq_github_installation_repository_full_name",
        ),
    )
    op.create_index(
        op.f("ix_github_installation_repository_full_name"),
        "github_installation_repository",
        ["full_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_github_installation_repository_installation_id"),
        "github_installation_repository",
        ["installation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_github_installation_repository_installation_id"),
        table_name="github_installation_repository",
    )
    op.drop_index(
        op.f("ix_github_installation_repository_full_name"),
        table_name="github_installation_repository",
    )
    op.drop_table("github_installation_repository")
