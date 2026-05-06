import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Message,
    SessionInstructor,
    WorkshopBadgeDefinition,
    WorkshopBadgeDefinitionCreate,
    WorkshopBadgeDefinitionPublic,
    WorkshopBadgeDefinitionsPublic,
    WorkshopBadgeGrant,
    WorkshopBadgeGrantRequest,
    WorkshopBadgeRevokeRequest,
    WorkshopParticipant,
    WorkshopSession,
    WorkshopSessionLeaderboardPublic,
    WorkshopSessionLeaderboardRowPublic,
)

router = APIRouter(prefix="/workshop/badges", tags=["workshop-badges"])


def _require_superuser_or_instructor(current_user: CurrentUser) -> None:
    if current_user.is_superuser or current_user.is_instructor:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="The user doesn't have enough privileges",
    )


def _require_session_instructor_or_superuser(
    *,
    session_db: Session,
    session_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    if current_user.is_superuser:
        return
    seat = session_db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_id,
            SessionInstructor.user_id == current_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).first()
    if seat is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User is not an instructor for this session",
    )


def _require_active_session_participant(
    *, session_db: Session, session_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    seat = session_db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == user_id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if seat is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Participant not in session roster",
    )


@router.get("", response_model=WorkshopBadgeDefinitionsPublic)
def read_workshop_badges(
    *, session: SessionDep, current_user: CurrentUser
) -> WorkshopBadgeDefinitionsPublic:
    _require_superuser_or_instructor(current_user)
    rows = session.exec(select(WorkshopBadgeDefinition)).all()
    data = [
        WorkshopBadgeDefinitionPublic(
            id=row.id,
            slug=row.slug,
            title=row.title,
            description=row.description,
            points=row.points,
        )
        for row in rows
    ]
    return WorkshopBadgeDefinitionsPublic(data=data, count=len(data))


@router.post("", response_model=WorkshopBadgeDefinitionPublic)
def create_workshop_badge(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: WorkshopBadgeDefinitionCreate,
) -> WorkshopBadgeDefinitionPublic:
    _require_superuser_or_instructor(current_user)
    exists = session.exec(
        select(WorkshopBadgeDefinition).where(WorkshopBadgeDefinition.slug == body.slug)
    ).first()
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_slug_conflict",
        )
    row = WorkshopBadgeDefinition(
        slug=body.slug,
        title=body.title,
        description=body.description,
        points=body.points,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return WorkshopBadgeDefinitionPublic(
        id=row.id,
        slug=row.slug,
        title=row.title,
        description=row.description,
        points=row.points,
    )


@router.post("/sessions/{session_id}/grant", response_model=Message)
def grant_workshop_badge(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopBadgeGrantRequest,
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_session_instructor_or_superuser(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_active_session_participant(
        session_db=session, session_id=session_id, user_id=body.user_id
    )
    badge = session.get(WorkshopBadgeDefinition, body.badge_id)
    if badge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found"
        )
    grant = session.exec(
        select(WorkshopBadgeGrant).where(
            WorkshopBadgeGrant.session_id == session_id,
            WorkshopBadgeGrant.user_id == body.user_id,
            WorkshopBadgeGrant.badge_id == body.badge_id,
        )
    ).first()
    if grant is not None and grant.revoked_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_already_granted",
        )
    if grant is None:
        grant = WorkshopBadgeGrant(
            session_id=session_id,
            user_id=body.user_id,
            badge_id=body.badge_id,
            granted_by_user_id=current_user.id,
        )
    else:
        grant.granted_by_user_id = current_user.id
        grant.granted_at = datetime.now(timezone.utc)
        grant.revoked_at = None
        grant.revoked_by_user_id = None
        grant.revoked_reason = None
    session.add(grant)
    session.commit()
    return Message(message="Badge granted")


@router.post("/sessions/{session_id}/revoke", response_model=Message)
def revoke_workshop_badge(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopBadgeRevokeRequest,
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_session_instructor_or_superuser(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_active_session_participant(
        session_db=session, session_id=session_id, user_id=body.user_id
    )
    normalized_reason = (body.reason or "").strip()
    if not normalized_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="badge_revoke_reason_required",
        )
    grant = session.exec(
        select(WorkshopBadgeGrant).where(
            WorkshopBadgeGrant.session_id == session_id,
            WorkshopBadgeGrant.user_id == body.user_id,
            WorkshopBadgeGrant.badge_id == body.badge_id,
        )
    ).first()
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Active badge grant not found"
        )
    if grant.revoked_at is not None:
        # Idempotent revoke for retry-safe instructor actions.
        return Message(message="Badge already revoked")
    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by_user_id = current_user.id
    grant.revoked_reason = normalized_reason
    session.add(grant)
    session.commit()
    return Message(message="Badge revoked")


@router.get(
    "/sessions/{session_id}/leaderboard",
    response_model=WorkshopSessionLeaderboardPublic,
)
def read_workshop_session_badge_leaderboard(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionLeaderboardPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_session_instructor_or_superuser(
        session_db=session, session_id=session_id, current_user=current_user
    )
    rows = session.exec(
        select(
            WorkshopBadgeGrant.user_id,
            func.sum(WorkshopBadgeDefinition.points),
            func.count(col(WorkshopBadgeGrant.id)),
        )
        .join(
            WorkshopBadgeDefinition,
            col(WorkshopBadgeGrant.badge_id) == col(WorkshopBadgeDefinition.id),
        )
        .where(
            WorkshopBadgeGrant.session_id == session_id,
            col(WorkshopBadgeGrant.revoked_at).is_(None),
        )
        .group_by(col(WorkshopBadgeGrant.user_id))
        .order_by(func.sum(WorkshopBadgeDefinition.points).desc())
    ).all()
    data = [
        WorkshopSessionLeaderboardRowPublic(
            user_id=user_id,
            total_points=int(total_points or 0),
            badge_count=int(badge_count or 0),
        )
        for user_id, total_points, badge_count in rows
    ]
    return WorkshopSessionLeaderboardPublic(data=data, count=len(data))
