import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.roster_user_picker_query import workshop_roster_user_picker_public
from app.core.config import settings
from app.models import (
    Lesson,
    Message,
    OAuthAccount,
    SessionInstructor,
    User,
    WorkshopBadgeDefinition,
    WorkshopBadgeDefinitionCreate,
    WorkshopBadgeDefinitionPublic,
    WorkshopBadgeDefinitionsPublic,
    WorkshopBadgeDefinitionUpdate,
    WorkshopBadgeGrant,
    WorkshopBadgeGrantRecipientPublic,
    WorkshopBadgeGrantRecipientsPublic,
    WorkshopBadgeGrantRequest,
    WorkshopBadgeGrantRevokeForBadgeRequest,
    WorkshopBadgeHubGrantRequest,
    WorkshopBadgeRevokeRequest,
    WorkshopGlobalLeaderboardPublic,
    WorkshopGlobalLeaderboardRowPublic,
    WorkshopParticipant,
    WorkshopRosterUserPickerPublic,
    WorkshopSession,
    WorkshopSessionLeaderboardPublic,
    WorkshopSessionLeaderboardRowPublic,
)

router = APIRouter(prefix="/workshop/badges", tags=["workshop-badges"])
logger = logging.getLogger(__name__)

_BADGE_IMAGE_MAX_BYTES = 512 * 1024
_ALLOWED_IMAGE_CT = frozenset({"image/png", "image/jpeg", "image/webp"})
_CT_SUFFIX = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


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


def _active_grant_global(
    session: Session, *, user_id: uuid.UUID, badge_id: uuid.UUID
) -> WorkshopBadgeGrant | None:
    return session.exec(
        select(WorkshopBadgeGrant).where(
            WorkshopBadgeGrant.user_id == user_id,
            WorkshopBadgeGrant.badge_id == badge_id,
            col(WorkshopBadgeGrant.revoked_at).is_(None),
        )
    ).first()


def _badge_image_dir() -> Path:
    return Path(settings.BADGE_IMAGE_DIR)


def _badge_definition_public(
    *,
    api_prefix: str,
    row: WorkshopBadgeDefinition,
    lesson_slug: str | None,
    lesson_title: str | None,
) -> WorkshopBadgeDefinitionPublic:
    image_url = (
        f"{api_prefix}/workshop/badges/{row.id}/image" if row.image_filename else None
    )
    return WorkshopBadgeDefinitionPublic(
        id=row.id,
        slug=row.slug,
        title=row.title,
        description=row.description,
        points=row.points,
        lesson_id=row.lesson_id,
        lesson_slug=lesson_slug,
        lesson_title=lesson_title,
        image_url=image_url,
        archived_at=row.archived_at,
    )


def _github_avatar_urls_for_users(
    session_db: Session, *, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    if not user_ids:
        return {}
    rows = session_db.exec(
        select(OAuthAccount.user_id, OAuthAccount.avatar_url).where(
            OAuthAccount.provider == "github",
            col(OAuthAccount.user_id).in_(user_ids),
        )
    ).all()
    return dict(rows)


@router.get("", response_model=WorkshopBadgeDefinitionsPublic)
def read_workshop_badges(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    include_archived: bool = Query(default=False),
) -> WorkshopBadgeDefinitionsPublic:
    _require_superuser_or_instructor(current_user)
    stmt = select(WorkshopBadgeDefinition)
    if not include_archived:
        stmt = stmt.where(col(WorkshopBadgeDefinition.archived_at).is_(None))
    rows = session.exec(stmt).all()
    lesson_ids = {r.lesson_id for r in rows if r.lesson_id is not None}
    lessons_by_id: dict[uuid.UUID, tuple[str, str]] = {}
    if lesson_ids:
        for les in session.exec(
            select(Lesson).where(col(Lesson.id).in_(lesson_ids))
        ).all():
            lessons_by_id[les.id] = (les.slug, les.title)

    data = [
        _badge_definition_public(
            api_prefix=settings.API_V1_STR,
            row=row,
            lesson_slug=lessons_by_id.get(row.lesson_id, (None, None))[0]
            if row.lesson_id
            else None,
            lesson_title=lessons_by_id.get(row.lesson_id, (None, None))[1]
            if row.lesson_id
            else None,
        )
        for row in rows
    ]
    return WorkshopBadgeDefinitionsPublic(data=data, count=len(data))


@router.get(
    "/leaderboard",
    response_model=WorkshopGlobalLeaderboardPublic,
)
def read_workshop_global_badge_leaderboard(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> WorkshopGlobalLeaderboardPublic:
    _ = current_user.id
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
        .where(col(WorkshopBadgeGrant.revoked_at).is_(None))
        .group_by(col(WorkshopBadgeGrant.user_id))
    ).all()
    sorted_rows = sorted(
        rows,
        key=lambda r: (-int(r[1] or 0), str(r[0])),
    )
    user_ids = {r[0] for r in sorted_rows}
    avatars = _github_avatar_urls_for_users(session, user_ids=user_ids)
    users_by_id = {
        u.id: u
        for u in session.exec(select(User).where(col(User.id).in_(user_ids))).all()
    }
    data: list[WorkshopGlobalLeaderboardRowPublic] = []
    rank = 0
    for user_id, total_points, badge_count in sorted_rows:
        u = users_by_id.get(user_id)
        if u is None:
            continue
        rank += 1
        data.append(
            WorkshopGlobalLeaderboardRowPublic(
                rank=rank,
                user_id=user_id,
                full_name=u.full_name,
                email=str(u.email),
                avatar_url=avatars.get(user_id),
                total_points=int(total_points or 0),
                badge_count=int(badge_count or 0),
            )
        )
    return WorkshopGlobalLeaderboardPublic(data=data, count=len(data))


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
    lesson_id: uuid.UUID | None = None
    lesson_slug: str | None = None
    lesson_title: str | None = None
    if body.lesson_id is not None:
        les = session.get(Lesson, body.lesson_id)
        if les is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="lesson_not_found",
            )
        lesson_id = body.lesson_id
        lesson_slug = les.slug
        lesson_title = les.title

    row = WorkshopBadgeDefinition(
        slug=body.slug,
        title=body.title,
        description=body.description,
        points=body.points,
        lesson_id=lesson_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _badge_definition_public(
        api_prefix=settings.API_V1_STR,
        row=row,
        lesson_slug=lesson_slug,
        lesson_title=lesson_title,
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
    if badge.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_archived",
        )
    if _active_grant_global(session, user_id=body.user_id, badge_id=body.badge_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_already_granted",
        )
    grant = session.exec(
        select(WorkshopBadgeGrant)
        .where(
            WorkshopBadgeGrant.session_id == session_id,
            WorkshopBadgeGrant.user_id == body.user_id,
            WorkshopBadgeGrant.badge_id == body.badge_id,
        )
        .order_by(col(WorkshopBadgeGrant.granted_at).desc())
    ).first()
    was_regrant = grant is not None and grant.revoked_at is not None
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
    logger.info(
        "workshop_badge_granted",
        extra={
            "session_id": str(session_id),
            "target_user_id": str(body.user_id),
            "badge_id": str(body.badge_id),
            "actor_user_id": str(current_user.id),
            "regranted": was_regrant,
        },
    )
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
        logger.info(
            "workshop_badge_revoke_idempotent",
            extra={
                "session_id": str(session_id),
                "target_user_id": str(body.user_id),
                "badge_id": str(body.badge_id),
                "actor_user_id": str(current_user.id),
            },
        )
        return Message(message="Badge already revoked")
    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by_user_id = current_user.id
    grant.revoked_reason = normalized_reason
    session.add(grant)
    session.commit()
    logger.info(
        "workshop_badge_revoked",
        extra={
            "session_id": str(session_id),
            "target_user_id": str(body.user_id),
            "badge_id": str(body.badge_id),
            "actor_user_id": str(current_user.id),
            "reason": normalized_reason,
        },
    )
    return Message(message="Badge revoked")


@router.post("/org/grant", response_model=Message)
def grant_workshop_badge_org(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: WorkshopBadgeGrantRequest,
) -> Message:
    _require_superuser_or_instructor(current_user)
    target = session.get(User, body.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    badge = session.get(WorkshopBadgeDefinition, body.badge_id)
    if badge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found"
        )
    if badge.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_archived",
        )
    if _active_grant_global(session, user_id=body.user_id, badge_id=body.badge_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="badge_already_granted",
        )
    grant = session.exec(
        select(WorkshopBadgeGrant)
        .where(
            col(WorkshopBadgeGrant.session_id).is_(None),
            WorkshopBadgeGrant.user_id == body.user_id,
            WorkshopBadgeGrant.badge_id == body.badge_id,
        )
        .order_by(col(WorkshopBadgeGrant.granted_at).desc())
    ).first()
    was_regrant = grant is not None and grant.revoked_at is not None
    if grant is None:
        grant = WorkshopBadgeGrant(
            session_id=None,
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
    logger.info(
        "workshop_badge_granted_org",
        extra={
            "target_user_id": str(body.user_id),
            "badge_id": str(body.badge_id),
            "actor_user_id": str(current_user.id),
            "regranted": was_regrant,
        },
    )
    return Message(message="Badge granted")


@router.post("/org/revoke", response_model=Message)
def revoke_workshop_badge_org(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: WorkshopBadgeRevokeRequest,
) -> Message:
    _require_superuser_or_instructor(current_user)
    normalized_reason = (body.reason or "").strip()
    if not normalized_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="badge_revoke_reason_required",
        )
    grant = _active_grant_global(session, user_id=body.user_id, badge_id=body.badge_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Active badge grant not found"
        )
    if grant.revoked_at is not None:
        logger.info(
            "workshop_badge_revoke_org_idempotent",
            extra={
                "target_user_id": str(body.user_id),
                "badge_id": str(body.badge_id),
                "actor_user_id": str(current_user.id),
            },
        )
        return Message(message="Badge already revoked")
    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by_user_id = current_user.id
    grant.revoked_reason = normalized_reason
    session.add(grant)
    session.commit()
    logger.info(
        "workshop_badge_revoked_org",
        extra={
            "target_user_id": str(body.user_id),
            "badge_id": str(body.badge_id),
            "actor_user_id": str(current_user.id),
            "reason": normalized_reason,
        },
    )
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


@router.get(
    "/{badge_id}/grant-user-picker",
    response_model=WorkshopRosterUserPickerPublic,
)
def read_workshop_badge_grant_user_picker(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
    q: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
) -> WorkshopRosterUserPickerPublic:
    _require_superuser_or_instructor(current_user)
    row = session.get(WorkshopBadgeDefinition, badge_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found"
        )
    _ = row.id
    try:
        return workshop_roster_user_picker_public(session, q=q, skip=skip, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{badge_id}/grants",
    response_model=WorkshopBadgeGrantRecipientsPublic,
)
def read_workshop_badge_grant_recipients(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
) -> WorkshopBadgeGrantRecipientsPublic:
    _require_superuser_or_instructor(current_user)
    badge = session.get(WorkshopBadgeDefinition, badge_id)
    if badge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found"
        )
    grants = session.exec(
        select(WorkshopBadgeGrant)
        .where(
            WorkshopBadgeGrant.badge_id == badge_id,
            col(WorkshopBadgeGrant.revoked_at).is_(None),
        )
        .order_by(col(WorkshopBadgeGrant.granted_at).desc())
    ).all()
    user_ids = [g.user_id for g in grants]
    users_by_id: dict[uuid.UUID, User] = {}
    if user_ids:
        users_by_id = {
            u.id: u
            for u in session.exec(select(User).where(col(User.id).in_(user_ids))).all()
        }
    data: list[WorkshopBadgeGrantRecipientPublic] = []
    for g in grants:
        u = users_by_id.get(g.user_id)
        if u is None:
            continue
        data.append(
            WorkshopBadgeGrantRecipientPublic(
                user_id=g.user_id,
                email=str(u.email),
                full_name=u.full_name,
                granted_at=g.granted_at,
            )
        )
    return WorkshopBadgeGrantRecipientsPublic(data=data, count=len(data))


@router.post("/{badge_id}/grants", response_model=Message)
def grant_workshop_badge_from_hub(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
    body: WorkshopBadgeHubGrantRequest,
) -> Message:
    return grant_workshop_badge_org(
        session=session,
        current_user=current_user,
        body=WorkshopBadgeGrantRequest(user_id=body.user_id, badge_id=badge_id),
    )


@router.post("/{badge_id}/grants/revoke", response_model=Message)
def revoke_workshop_badge_from_hub(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
    body: WorkshopBadgeGrantRevokeForBadgeRequest,
) -> Message:
    return revoke_workshop_badge_org(
        session=session,
        current_user=current_user,
        body=WorkshopBadgeRevokeRequest(
            user_id=body.user_id,
            badge_id=badge_id,
            reason=body.reason,
        ),
    )


@router.get("/{badge_id}/image")
def read_workshop_badge_image(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
) -> FileResponse:
    _ = current_user.id
    row = session.get(WorkshopBadgeDefinition, badge_id)
    if row is None or not row.image_filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = _badge_image_dir() / row.image_filename
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
    )


@router.post("/{badge_id}/image", response_model=WorkshopBadgeDefinitionPublic)
async def upload_workshop_badge_image(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    badge_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
) -> WorkshopBadgeDefinitionPublic:
    _require_superuser_or_instructor(current_user)
    row = session.get(WorkshopBadgeDefinition, badge_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found"
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_IMAGE_CT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="badge_image_invalid_type",
        )
    raw = await file.read()
    if len(raw) > _BADGE_IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="badge_image_too_large",
        )
    suffix = _CT_SUFFIX[content_type]
    dest_dir = _badge_image_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{row.id.hex}.{suffix}"
    dest = dest_dir / filename
    dest.write_bytes(raw)
    row.image_filename = filename
    session.add(row)
    session.commit()
    session.refresh(row)
    lesson_slug: str | None = None
    lesson_title: str | None = None
    if row.lesson_id is not None:
        les = session.get(Lesson, row.lesson_id)
        if les is not None:
            lesson_slug = les.slug
            lesson_title = les.title
    return _badge_definition_public(
        api_prefix=settings.API_V1_STR,
        row=row,
        lesson_slug=lesson_slug,
        lesson_title=lesson_title,
    )
