"""Badge definitions: lesson link + image; org-wide grants (nullable session).

Revision ID: g1h2i3j4k5l6
Revises: f0a1b2c3d4e5
Create Date: 2026-05-12

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "g1h2i3j4k5l6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workshop_badge_definition",
        sa.Column("lesson_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "workshop_badge_definition",
        sa.Column(
            "image_filename",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_workshop_badge_definition_lesson_id",
        "workshop_badge_definition",
        "lesson",
        ["lesson_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column(
        "workshop_badge_definition",
        "slug",
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    op.drop_constraint(
        "uq_workshop_badge_grant_once", "workshop_badge_grant", type_="unique"
    )
    op.alter_column(
        "workshop_badge_grant",
        "session_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_workshop_badge_grant_session "
            "ON workshop_badge_grant (session_id, user_id, badge_id) "
            "WHERE session_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_workshop_badge_grant_org "
            "ON workshop_badge_grant (user_id, badge_id) "
            "WHERE session_id IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_workshop_badge_grant_org"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_workshop_badge_grant_session"))
    op.alter_column(
        "workshop_badge_grant",
        "session_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_workshop_badge_grant_once",
        "workshop_badge_grant",
        ["session_id", "user_id", "badge_id"],
    )
    op.alter_column(
        "workshop_badge_definition",
        "slug",
        existing_type=sa.String(length=128),
        type_=sa.VARCHAR(length=64),
        existing_nullable=False,
    )
    op.drop_constraint(
        "fk_workshop_badge_definition_lesson_id",
        "workshop_badge_definition",
        type_="foreignkey",
    )
    op.drop_column("workshop_badge_definition", "image_filename")
    op.drop_column("workshop_badge_definition", "lesson_id")
