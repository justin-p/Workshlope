"""Add GitHub App installation + lesson_repo link

Revision ID: a1b2c3d4e5f7
Revises: 6c8d9e0f1a22
Create Date: 2026-05-06

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "6c8d9e0f1a22"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "github_app_installation",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("account_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("target_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "repository_selection",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.Column("app_slug", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_github_app_installation_account_login"),
        "github_app_installation",
        ["account_login"],
        unique=False,
    )
    op.add_column(
        "lesson_repo",
        sa.Column("github_installation_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_lesson_repo_github_installation_id_github_app_installation",
        "lesson_repo",
        "github_app_installation",
        ["github_installation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_lesson_repo_github_installation_id_github_app_installation",
        "lesson_repo",
        type_="foreignkey",
    )
    op.drop_column("lesson_repo", "github_installation_id")
    op.drop_index(
        op.f("ix_github_app_installation_account_login"),
        table_name="github_app_installation",
    )
    op.drop_table("github_app_installation")
