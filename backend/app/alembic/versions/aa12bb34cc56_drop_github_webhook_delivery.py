"""Drop github_webhook_delivery table

Revision ID: aa12bb34cc56
Revises: f7a8b9c0d1e2
Create Date: 2026-05-07

"""

from alembic import op

revision = "aa12bb34cc56"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("github_webhook_delivery")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE github_webhook_delivery (
            delivery_id VARCHAR(128) NOT NULL,
            github_event VARCHAR(128) NOT NULL,
            received_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (delivery_id)
        )
        """
    )
