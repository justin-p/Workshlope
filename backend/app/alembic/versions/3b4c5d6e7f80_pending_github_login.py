"""Replace github_invite with pending_github_login

Revision ID: 3b4c5d6e7f80
Revises: 20a1b2c3d4e5
Create Date: 2026-04-28 18:30:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "3b4c5d6e7f80"
down_revision = "20a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index(op.f("ix_github_invite_token_hash"), table_name="github_invite")
    op.drop_table("github_invite")

    op.create_table(
        "pending_github_login",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "provider", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column(
            "provider_account_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "provider_login",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "full_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "avatar_url",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_pending_github_provider_account",
        ),
    )
    op.create_index(
        op.f("ix_pending_github_login_provider"),
        "pending_github_login",
        ["provider"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_pending_github_login_provider"), table_name="pending_github_login"
    )
    op.drop_table("pending_github_login")

    op.create_table(
        "github_invite",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "token_hash",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_github_invite_token_hash"),
        "github_invite",
        ["token_hash"],
        unique=True,
    )
