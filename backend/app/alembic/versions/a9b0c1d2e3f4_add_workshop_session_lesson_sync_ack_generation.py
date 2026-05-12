"""Add workshop_session.lesson_sync_ack_generation

Revision ID: a9b0c1d2e3f4
Revises: f0a1b2c3d4e5
Create Date: 2026-05-12 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workshop_session",
        sa.Column("lesson_sync_ack_generation", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE workshop_session AS ws
        SET lesson_sync_ack_generation = COALESCE(l.lesson_sync_generation, 1)
        FROM lesson AS l
        WHERE l.id = ws.lesson_id
        """
    )
    op.execute(
        """
        UPDATE workshop_session
        SET lesson_sync_ack_generation = 1
        WHERE lesson_sync_ack_generation IS NULL
        """
    )
    op.alter_column(
        "workshop_session",
        "lesson_sync_ack_generation",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade():
    op.drop_column("workshop_session", "lesson_sync_ack_generation")
