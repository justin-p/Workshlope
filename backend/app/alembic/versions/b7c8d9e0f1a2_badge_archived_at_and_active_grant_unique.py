"""Badge definition archived_at; unique active grant per user+badge.

Revision ID: b7c8d9e0f1a2
Revises: a6357a27fcd7
Create Date: 2026-05-12

"""

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a6357a27fcd7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workshop_badge_definition",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workshop_badge_definition_archived_at",
        "workshop_badge_definition",
        ["archived_at"],
        unique=False,
    )
    # One non-revoked grant per (user_id, badge_id) for leaderboard + idempotency.
    op.execute(
        """
        DELETE FROM workshop_badge_grant g1
        USING workshop_badge_grant g2
        WHERE g1.revoked_at IS NULL
          AND g2.revoked_at IS NULL
          AND g1.user_id = g2.user_id
          AND g1.badge_id = g2.badge_id
          AND g1.id > g2.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_workshop_badge_grant_active_user_badge
        ON workshop_badge_grant (user_id, badge_id)
        WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workshop_badge_grant_active_user_badge")
    op.drop_index("ix_workshop_badge_definition_archived_at", table_name="workshop_badge_definition")
    op.drop_column("workshop_badge_definition", "archived_at")
