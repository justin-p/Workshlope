"""Auto-award manifest-linked lesson badges to session participants when a session ends."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    WorkshopBadgeDefinition,
    WorkshopBadgeGrant,
    WorkshopParticipant,
    WorkshopSession,
)

logger = logging.getLogger(__name__)


def _active_grant(
    session: Session, *, user_id: uuid.UUID, badge_id: uuid.UUID
) -> WorkshopBadgeGrant | None:
    return session.exec(
        select(WorkshopBadgeGrant).where(
            WorkshopBadgeGrant.user_id == user_id,
            WorkshopBadgeGrant.badge_id == badge_id,
            col(WorkshopBadgeGrant.revoked_at).is_(None),
        )
    ).first()


def award_lesson_badges_on_session_end(
    session: Session,
    *,
    workshop_session: WorkshopSession,
    granted_by_user_id: uuid.UUID,
) -> int:
    """
    For each active participant and each non-archived badge definition for the
    session's lesson, create a session-scoped grant if the user has no active
    grant for that badge yet (idempotent).
    Returns the number of new grant rows inserted (not skipped).
    """
    badge_rows = session.exec(
        select(WorkshopBadgeDefinition).where(
            WorkshopBadgeDefinition.lesson_id == workshop_session.lesson_id,
            col(WorkshopBadgeDefinition.archived_at).is_(None),
        )
    ).all()
    if not badge_rows:
        return 0

    participant_user_ids = [
        row.user_id
        for row in session.exec(
            select(WorkshopParticipant).where(
                WorkshopParticipant.session_id == workshop_session.id,
                col(WorkshopParticipant.removed_at).is_(None),
            )
        ).all()
        if row.user_id is not None
    ]
    if not participant_user_ids:
        return 0

    inserted = 0
    now = datetime.now(timezone.utc)
    sid = workshop_session.id
    for user_id in participant_user_ids:
        for badge in badge_rows:
            existing = _active_grant(session, user_id=user_id, badge_id=badge.id)
            if existing is not None:
                continue
            session.add(
                WorkshopBadgeGrant(
                    session_id=sid,
                    user_id=user_id,
                    badge_id=badge.id,
                    granted_by_user_id=granted_by_user_id,
                    granted_at=now,
                )
            )
            inserted += 1
    if inserted:
        session.flush()
    logger.info(
        "workshop_badge_session_end_auto_award",
        extra={
            "session_id": str(sid),
            "lesson_id": str(workshop_session.lesson_id),
            "participants": len(participant_user_ids),
            "badges": len(badge_rows),
            "grants_inserted": inserted,
        },
    )
    return inserted
