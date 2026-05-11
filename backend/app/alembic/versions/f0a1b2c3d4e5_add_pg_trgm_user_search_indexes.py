"""Add pg_trgm extension and GIN indexes for user roster picker search.

Revision ID: f0a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11
"""

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_user_email_gin_trgm '
        'ON "user" USING gin (email gin_trgm_ops)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_user_full_name_gin_trgm '
        'ON "user" USING gin (full_name gin_trgm_ops)'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_full_name_gin_trgm")
    op.execute("DROP INDEX IF EXISTS ix_user_email_gin_trgm")
    # Leave pg_trgm extension installed (other features may rely on it later).
