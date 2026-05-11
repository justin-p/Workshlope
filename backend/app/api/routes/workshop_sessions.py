import json
import posixpath
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import quote

import jwt
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from jwt.exceptions import PyJWTError
from pydantic import BaseModel
from sqlalchemy import String, cast, literal, or_
from sqlalchemy.sql import func as sa_func
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import engine
from app.core.security import ALGORITHM
from app.models import (
    Lesson,
    LessonPart,
    LessonPrerequisite,
    LessonRepo,
    LessonRepoAsset,
    Message,
    OAuthAccount,
    SessionInstructor,
    User,
    UserPrerequisiteCompletion,
    WorkshopLessonPartBrief,
    WorkshopLessonSummaryPublic,
    WorkshopParticipant,
    WorkshopParticipantPatch,
    WorkshopParticipantSelfPublic,
    WorkshopRosterInstructorRowPublic,
    WorkshopRosterParticipantRowPublic,
    WorkshopRosterUserPickerPublic,
    WorkshopRosterUserPickerRowPublic,
    WorkshopSession,
    WorkshopSessionCorePublic,
    WorkshopSessionCreate,
    WorkshopSessionCreatedPublic,
    WorkshopSessionListItem,
    WorkshopSessionMemberBatchResultItem,
    WorkshopSessionMembersBatchBody,
    WorkshopSessionMembersBatchResponse,
    WorkshopSessionPatch,
    WorkshopSessionPublicInstructor,
    WorkshopSessionPublicParticipant,
    WorkshopSessionsPublic,
    WorkshopSessionTimer,
    WorkshopSessionTimerEvent,
    WorkshopSessionTimerEventPublic,
    WorkshopSessionTimerEventsPublic,
    WorkshopSessionTimerExtend,
    WorkshopSessionTimerPublic,
    WorkshopSessionTimerStart,
    WorkshopSessionUpsertMember,
)
from app.services.lesson_markdown_pipeline import (
    lesson_markdown_to_safe_html,
    rewrite_relative_asset_urls,
)
from app.services.workshop_realtime import (
    WorkshopWsConnection,
    workshop_hub,
)

router = APIRouter(prefix="/workshop/sessions", tags=["workshop-sessions"])

ALLOWED_WS_LIVE_STATUSES = frozenset({"busy", "done"})
# Part moves are frozen unless the workshop is actively running (`live`).
WS_PART_ADVANCE_REQUIRES_STATUS = frozenset({"live"})
# Enter only when the session is running or paused (scheduled uses lobby-only HTTP).
WORKSHOP_ACTIVE_STATUSES = frozenset({"live", "paused"})
# WebSocket ticket + handshake: scheduled allows lobby listeners (status fan-out).
WORKSHOP_WS_HANDSHAKE_STATUSES = frozenset({"scheduled", "live", "paused"})


def _workshop_session_start_content_issue(
    session_db: Session, *, workshop_row: WorkshopSession
) -> str | None:
    lesson = session_db.get(Lesson, workshop_row.lesson_id)
    if lesson is None:
        return "lesson_missing"

    lesson_repo = session_db.get(LessonRepo, lesson.repo_id)
    if lesson_repo is None:
        return "lesson_repo_missing"
    if lesson_repo.health != "healthy":
        return "lesson_repo_unhealthy"

    has_part = session_db.exec(
        select(LessonPart.id).where(LessonPart.lesson_id == lesson.id).limit(1)
    ).first()
    if has_part is None:
        return "no_parts_synced"

    return None


@dataclass(frozen=True, slots=True)
class WorkshopWsHandshake:
    """Snapshot of websocket auth tied to DB state at handshake time."""

    user_id: uuid.UUID
    role: Literal["participant", "instructor"]
    part_generation: int


class WorkshopWsTicket(BaseModel):
    ticket: str
    expires_at: datetime


def _extract_ws_ticket_from_subprotocols(header_value: str | None) -> str | None:
    if not header_value:
        return None
    parts = [part.strip() for part in header_value.split(",") if part.strip()]
    if len(parts) < 2 or parts[0] != "ticket":
        return None
    return parts[1]


def _decode_workshop_ws_ticket(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        audience="workshop-ws",
    )


def _authorize_workshop_ws_handshake(
    db: Session,
    *,
    route_session_id: uuid.UUID,
    claims: dict[str, Any],
) -> WorkshopWsHandshake | None:
    """Return snapshot when JWT + DB authorize the socket; ``None`` to reject handshake."""
    try:
        token_session_id = uuid.UUID(str(claims["sid"]))
        token_user_id = uuid.UUID(str(claims["uid"]))
        role = str(claims["role"])
        token_part_generation = int(claims["pg"])
    except (KeyError, TypeError, ValueError):
        return None

    if token_session_id != route_session_id:
        return None

    workshop_session = db.get(WorkshopSession, route_session_id)
    if workshop_session is None:
        return None
    if workshop_session.status not in WORKSHOP_WS_HANDSHAKE_STATUSES:
        return None
    if token_part_generation != workshop_session.part_generation:
        return None

    user = db.get(User, token_user_id)
    if user is None or not user.is_active:
        return None

    if role == "participant":
        participant = db.exec(
            select(WorkshopParticipant).where(
                WorkshopParticipant.session_id == route_session_id,
                WorkshopParticipant.user_id == token_user_id,
                col(WorkshopParticipant.removed_at).is_(None),
            )
        ).first()
        if participant is None or participant.joined_at is None:
            return None
        narrowed_role: Literal["participant", "instructor"] = "participant"
    elif role == "instructor":
        instructor = db.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == route_session_id,
                SessionInstructor.user_id == token_user_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if instructor is None and not user.is_superuser:
            return None
        narrowed_role = "instructor"
    else:
        return None

    return WorkshopWsHandshake(
        user_id=token_user_id,
        role=narrowed_role,
        part_generation=int(workshop_session.part_generation),
    )


def _workshop_list_item_role(
    session_db: Session,
    *,
    workshop_session_id: uuid.UUID,
    current_user: User,
) -> Literal["participant", "instructor"] | None:
    """How the caller is seated on this session, if at all."""

    instructor = session_db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == workshop_session_id,
            SessionInstructor.user_id == current_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).first()
    if instructor is not None:
        return "instructor"
    participant = session_db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == workshop_session_id,
            WorkshopParticipant.user_id == current_user.id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is not None:
        return "participant"
    return None


def _workshop_session_detail_view_kind(
    session_db: Session,
    *,
    session_id: uuid.UUID,
    current_user: User,
) -> Literal["participant", "instructor"] | None:
    """Who may read session detail; mirrors ws-ticket elevation for superusers."""

    if current_user.is_superuser:
        return "instructor"
    instructor = session_db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_id,
            SessionInstructor.user_id == current_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).first()
    if instructor is not None:
        return "instructor"
    participant = session_db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == current_user.id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is not None:
        return "participant"
    return None


def _validate_workshop_session_status_transition(
    *, current_status: str, target_status: str
) -> None:
    """Raise HTTPException when ``target_status`` is not allowed from ``current_status``."""
    if current_status == target_status:
        return
    if current_status == "ended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="session_already_ended",
        )
    if target_status == "live":
        if current_status not in {"scheduled", "paused"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid_session_status_transition",
            )
    elif target_status == "paused":
        if current_status != "live":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="pause_requires_live_session",
            )
    elif target_status == "ended":
        if current_status not in {"live", "paused"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="end_requires_active_session",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid_session_status_transition",
        )


def _count_active_session_instructors_excluding(
    session_db: Session,
    *,
    session_id: uuid.UUID,
    exclude_user_id: uuid.UUID,
) -> int:
    return int(
        session_db.exec(
            select(func.count())
            .select_from(SessionInstructor)
            .where(
                SessionInstructor.session_id == session_id,
                col(SessionInstructor.removed_at).is_(None),
                SessionInstructor.user_id != exclude_user_id,
            )
        ).one()
    )


def _require_workshop_instructor(
    *, session_db: Session, session_id: uuid.UUID, current_user: User
) -> None:
    instructor = session_db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_id,
            SessionInstructor.user_id == current_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).first()
    if instructor is not None or current_user.is_superuser:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User is not an instructor for this session",
    )


ROSTER_PICKER_MIN_Q_LEN = 2
ROSTER_PICKER_DEFAULT_LIMIT = 25
ROSTER_PICKER_MAX_LIMIT = 100
ROSTER_BATCH_MAX_IDS = 100


def _upsert_workshop_session_participant_seat(
    session_db: Session,
    *,
    session_id: uuid.UUID,
    target_user: User,
) -> Literal["added", "already"]:
    """Ensure ``target_user`` has an active participant seat; mirrors single-member POST."""
    now = datetime.now(timezone.utc)
    instructor = session_db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_id,
            SessionInstructor.user_id == target_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).first()
    if instructor is not None:
        instructor.removed_at = now
        session_db.add(instructor)

    participant = session_db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == target_user.id,
        )
    ).first()
    if participant is None:
        session_db.add(
            WorkshopParticipant(
                session_id=session_id,
                user_id=target_user.id,
                invited_at=now,
            )
        )
        return "added"
    if participant.removed_at is None:
        return "already"
    participant.removed_at = None
    participant.user_id = target_user.id
    if participant.invited_at is None:
        participant.invited_at = now
    session_db.add(participant)
    return "added"


def _required_prerequisites_complete_for_user(
    session_db: Session, *, lesson_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    required_ids = session_db.exec(
        select(LessonPrerequisite.id).where(
            LessonPrerequisite.lesson_id == lesson_id,
            col(LessonPrerequisite.required_flag).is_(True),
        )
    ).all()
    if not required_ids:
        return True
    completed_ids = set(
        session_db.exec(
            select(UserPrerequisiteCompletion.prerequisite_id).where(
                UserPrerequisiteCompletion.user_id == user_id,
                UserPrerequisiteCompletion.lesson_id == lesson_id,
                col(UserPrerequisiteCompletion.prerequisite_id).in_(required_ids),
            )
        ).all()
    )
    return len(completed_ids) == len(required_ids)


def _required_prereq_blocked_count_by_session(
    session_db: Session, *, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not session_ids:
        return {}
    rows = session_db.exec(
        select(
            WorkshopParticipant.session_id,
            func.count(func.distinct(WorkshopParticipant.user_id)),
        )
        .join(
            WorkshopSession,
            col(WorkshopSession.id) == col(WorkshopParticipant.session_id),
        )
        .where(
            col(WorkshopParticipant.session_id).in_(session_ids),
            col(WorkshopParticipant.removed_at).is_(None),
            col(WorkshopParticipant.user_id).is_not(None),
            select(LessonPrerequisite.id)
            .where(
                LessonPrerequisite.lesson_id == WorkshopSession.lesson_id,
                col(LessonPrerequisite.required_flag).is_(True),
                ~select(UserPrerequisiteCompletion.id)
                .where(
                    UserPrerequisiteCompletion.user_id == WorkshopParticipant.user_id,
                    UserPrerequisiteCompletion.lesson_id == WorkshopSession.lesson_id,
                    UserPrerequisiteCompletion.prerequisite_id == LessonPrerequisite.id,
                )
                .exists(),
            )
            .exists(),
        )
        .group_by(col(WorkshopParticipant.session_id))
    ).all()
    return {session_id: int(count) for session_id, count in rows}


def _require_timer_allowed_session_status(session_row: WorkshopSession) -> None:
    if session_row.status not in WORKSHOP_ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="timer_requires_active_session",
        )


def _timer_public(
    session_id: uuid.UUID, state: Any | None
) -> WorkshopSessionTimerPublic:
    if state is None:
        return WorkshopSessionTimerPublic(session_id=session_id, status="inactive")
    elapsed_seconds: int | None = None
    remaining_seconds: int | None = None
    if state.started_at is not None:
        now = datetime.now(timezone.utc)
        effective_end = state.paused_at if state.status == "paused" else now
        elapsed_seconds = max(
            0,
            int((effective_end - state.started_at).total_seconds()),
        )
    if (
        elapsed_seconds is not None
        and state.mode == "countdown"
        and state.target_seconds is not None
    ):
        remaining_seconds = max(0, state.target_seconds - elapsed_seconds)
    return WorkshopSessionTimerPublic(
        session_id=session_id,
        status=state.status,
        mode=state.mode,
        target_seconds=state.target_seconds,
        started_at=state.started_at,
        paused_at=state.paused_at,
        elapsed_seconds=elapsed_seconds,
        remaining_seconds=remaining_seconds,
    )


def _record_timer_event(
    session_db: Session,
    *,
    session_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    mode: str | None,
    target_seconds: int | None,
) -> None:
    session_db.add(
        WorkshopSessionTimerEvent(
            session_id=session_id,
            actor_user_id=actor_user_id,
            action=action,
            mode=mode,
            target_seconds=target_seconds,
        )
    )


async def _dispatch_workshop_ws_text(
    *,
    websocket: WebSocket,
    session_id: uuid.UUID,
    handshake: WorkshopWsHandshake,
    connection: WorkshopWsConnection,
    text: str,
) -> bool:
    """Handle one client text JSON frame.

    Returns ``False`` when the server's receive loop for this websocket should stop
    (e.g. after policy close for stale ``part_generation``).
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "detail": "invalid_json"})
        return True
    if not isinstance(payload, dict):
        await websocket.send_json({"type": "error", "detail": "invalid_message"})
        return True

    msg_type = payload.get("type")
    # Part advance bumps generation in-room before any awaits; staleness gates other frames.
    if msg_type != "part.advance":
        with Session(engine) as db_snap:
            row_snap = db_snap.get(WorkshopSession, session_id)
            if row_snap is None:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_found"}
                )
                return True
            if int(row_snap.part_generation) != connection.part_generation:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "part_generation_stale",
                        "part_generation": int(row_snap.part_generation),
                    }
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return False

    if msg_type == "live_status":
        if handshake.role != "participant":
            await websocket.send_json({"type": "error", "detail": "forbidden"})
            return True

        live_status_raw = payload.get("live_status")
        if not isinstance(live_status_raw, str):
            await websocket.send_json(
                {"type": "error", "detail": "invalid_live_status"}
            )
            return True
        live_status = live_status_raw.strip()[:16]
        if live_status not in ALLOWED_WS_LIVE_STATUSES:
            await websocket.send_json(
                {"type": "error", "detail": "invalid_live_status"}
            )
            return True

        with Session(engine) as db:
            workshop_row = db.get(WorkshopSession, session_id)
            if workshop_row is None:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_found"}
                )
                return True
            if workshop_row.status not in WORKSHOP_ACTIVE_STATUSES:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_active"}
                )
                return True
            if workshop_row.status != "live":
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "live_status_requires_live_session",
                    }
                )
                return True
            participant = db.exec(
                select(WorkshopParticipant).where(
                    WorkshopParticipant.session_id == session_id,
                    WorkshopParticipant.user_id == handshake.user_id,
                    col(WorkshopParticipant.removed_at).is_(None),
                )
            ).first()
            if participant is None:
                await websocket.send_json(
                    {"type": "error", "detail": "participant_not_found"}
                )
                return True
            participant.live_status = live_status
            db.add(participant)
            db.commit()

        await workshop_hub.publish_participant_live_status(
            session_id=session_id,
            user_id=handshake.user_id,
            live_status=live_status,
        )
        await websocket.send_json(
            {"type": "live_status.ack", "live_status": live_status}
        )
        return True

    if msg_type == "part.advance":
        if handshake.role != "instructor":
            await websocket.send_json({"type": "error", "detail": "forbidden"})
            return True
        part_index_raw = payload.get("part_index")
        if not isinstance(part_index_raw, int) or part_index_raw < 0:
            await websocket.send_json({"type": "error", "detail": "invalid_part_index"})
            return True

        with Session(engine) as db:
            workshop_session = db.get(WorkshopSession, session_id)
            if workshop_session is None:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_found"}
                )
                return True
            if workshop_session.status not in WS_PART_ADVANCE_REQUIRES_STATUS:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "advance_requires_live_session",
                    }
                )
                return True
            lesson_parts = db.exec(
                select(LessonPart)
                .where(LessonPart.lesson_id == workshop_session.lesson_id)
                .order_by(col(LessonPart.ordering))
            ).all()
            if part_index_raw >= len(lesson_parts):
                await websocket.send_json(
                    {"type": "error", "detail": "invalid_part_index"}
                )
                return True
            target_part = lesson_parts[part_index_raw]
            target_part_slug = str(target_part.slug)
            timer_row = db.exec(
                select(WorkshopSessionTimer).where(
                    WorkshopSessionTimer.session_id == session_id
                )
            ).first()
            if timer_row is not None and timer_row.status != "inactive":
                timer_row.status = "inactive"
                timer_row.paused_at = None
                timer_row.updated_at = datetime.now(timezone.utc)
                db.add(timer_row)
                _record_timer_event(
                    db,
                    session_id=session_id,
                    actor_user_id=handshake.user_id,
                    action="stop",
                    mode=timer_row.mode,
                    target_seconds=timer_row.target_seconds,
                )
            workshop_session.current_part_index = part_index_raw
            workshop_session.current_part_slug = target_part_slug
            workshop_session.part_generation = int(workshop_session.part_generation) + 1
            db.add(workshop_session)
            participants = db.exec(
                select(WorkshopParticipant).where(
                    WorkshopParticipant.session_id == session_id,
                    col(WorkshopParticipant.removed_at).is_(None),
                )
            ).all()
            for participant in participants:
                participant.live_status = "busy"
                db.add(participant)
            db.commit()
            next_generation = int(workshop_session.part_generation)

        workshop_hub.sync_bump_room_part_generation(session_id, next_generation)

        await websocket.send_json(
            {
                "type": "part.advance.ack",
                "part_index": part_index_raw,
                "part_slug": target_part_slug,
                "part_generation": next_generation,
            }
        )
        await workshop_hub.publish_session_part_changed(
            session_id=session_id,
            part_index=part_index_raw,
            part_slug=target_part_slug,
            part_generation=next_generation,
        )
        return True

    if msg_type == "session.pause":
        if handshake.role != "instructor":
            await websocket.send_json({"type": "error", "detail": "forbidden"})
            return True
        with Session(engine) as db:
            workshop_session_row = db.get(WorkshopSession, session_id)
            if workshop_session_row is None:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_found"}
                )
                return True
            if workshop_session_row.status != "live":
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "pause_requires_live_session",
                    }
                )
                return True
            workshop_session_row.status = "paused"
            db.add(workshop_session_row)
            db.commit()

        await websocket.send_json({"type": "session.pause.ack", "status": "paused"})
        await workshop_hub.publish_session_status_changed(
            session_id=session_id,
            status="paused",
        )
        return True

    if msg_type == "session.resume":
        if handshake.role != "instructor":
            await websocket.send_json({"type": "error", "detail": "forbidden"})
            return True
        with Session(engine) as db:
            workshop_session_row = db.get(WorkshopSession, session_id)
            if workshop_session_row is None:
                await websocket.send_json(
                    {"type": "error", "detail": "session_not_found"}
                )
                return True
            if workshop_session_row.status != "paused":
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "resume_requires_paused_session",
                    }
                )
                return True
            workshop_session_row.status = "live"
            db.add(workshop_session_row)
            db.commit()

        await websocket.send_json({"type": "session.resume.ack", "status": "live"})
        await workshop_hub.publish_session_status_changed(
            session_id=session_id,
            status="live",
        )
        return True

    await websocket.send_json({"type": "error", "detail": "unknown_message_type"})
    return True


@router.get("/", response_model=WorkshopSessionsPublic)
def read_workshop_sessions_for_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> WorkshopSessionsPublic:
    """List workshop sessions visible to the caller.

    Non-superusers see sessions where they have an active participant or
    instructor seat. Superusers see all sessions; ``my_role`` is ``null`` when
    they are not seated (admin-style visibility).
    """

    base_join = select(WorkshopSession, Lesson.title, Lesson.slug).join(
        Lesson, col(WorkshopSession.lesson_id) == Lesson.id
    )

    if not current_user.is_superuser:
        participant_sessions = select(WorkshopParticipant.session_id).where(
            WorkshopParticipant.user_id == current_user.id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
        instructor_sessions = select(SessionInstructor.session_id).where(
            SessionInstructor.user_id == current_user.id,
            col(SessionInstructor.removed_at).is_(None),
        )
        visible_filter = or_(
            col(WorkshopSession.id).in_(participant_sessions),
            col(WorkshopSession.id).in_(instructor_sessions),
        )
        count_statement = (
            select(func.count())
            .select_from(WorkshopSession)
            .join(Lesson, col(WorkshopSession.lesson_id) == Lesson.id)
            .where(visible_filter)
        )
        data_statement = (
            base_join.where(visible_filter)
            .order_by(col(WorkshopSession.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
    else:
        count_statement = (
            select(func.count())
            .select_from(WorkshopSession)
            .join(Lesson, col(WorkshopSession.lesson_id) == Lesson.id)
        )
        data_statement = (
            base_join.order_by(col(WorkshopSession.created_at).desc())
            .offset(skip)
            .limit(limit)
        )

    count = session.exec(count_statement).one()
    rows = session.exec(data_statement).all()
    blocked_counts = _required_prereq_blocked_count_by_session(
        session, session_ids=[ws.id for ws, _lesson_title, _lesson_slug in rows]
    )

    data: list[WorkshopSessionListItem] = []
    for ws, lesson_title, lesson_slug in rows:
        role = _workshop_list_item_role(
            session,
            workshop_session_id=ws.id,
            current_user=current_user,
        )
        data.append(
            WorkshopSessionListItem(
                id=ws.id,
                status=ws.status,
                part_generation=ws.part_generation,
                lesson_id=ws.lesson_id,
                lesson_title=lesson_title,
                lesson_slug=lesson_slug,
                my_role=role,
                blocked_required_prereq_count=(
                    None if role == "participant" else blocked_counts.get(ws.id, 0)
                ),
            )
        )

    return WorkshopSessionsPublic(data=data, count=count)


@router.post("/", response_model=WorkshopSessionCreatedPublic)
def create_workshop_session(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: WorkshopSessionCreate,
) -> WorkshopSessionCreatedPublic:
    if not (current_user.is_superuser or current_user.is_instructor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instructor privileges required",
        )
    lesson = session.get(Lesson, body.lesson_id)
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        )

    first_part = session.exec(
        select(LessonPart)
        .where(LessonPart.lesson_id == lesson.id)
        .order_by(col(LessonPart.ordering))
        .limit(1)
    ).first()
    created = WorkshopSession(
        lesson_id=lesson.id,
        status="scheduled",
        current_part_index=0,
        current_part_slug=(first_part.slug if first_part is not None else None),
        part_generation=1,
    )
    session.add(created)
    session.commit()
    session.refresh(created)

    seat = SessionInstructor(
        session_id=created.id,
        user_id=current_user.id,
        role="lead",
    )
    session.add(seat)
    session.commit()

    return WorkshopSessionCreatedPublic(
        session_id=created.id,
        lesson_id=created.lesson_id,
        status=created.status,
    )


def _workshop_session_detail_shared(
    session: Session,
    *,
    workshop_row: WorkshopSession,
) -> tuple[
    WorkshopSessionCorePublic,
    WorkshopLessonSummaryPublic,
    list[WorkshopLessonPartBrief],
]:
    lesson = session.get(Lesson, workshop_row.lesson_id)
    if lesson is None:
        core = WorkshopSessionCorePublic(
            id=workshop_row.id,
            status=workshop_row.status,
            current_part_index=workshop_row.current_part_index,
            current_part_slug=workshop_row.current_part_slug,
            part_generation=workshop_row.part_generation,
            created_at=workshop_row.created_at,
        )
        return (
            core,
            WorkshopLessonSummaryPublic(
                id=workshop_row.lesson_id,
                title="Lesson unavailable",
                slug="lesson-unavailable",
                lesson_repo_health="unhealthy",
                lesson_content_available=False,
                lesson_content_issue="lesson_missing",
            ),
            [],
        )

    core = WorkshopSessionCorePublic(
        id=workshop_row.id,
        status=workshop_row.status,
        current_part_index=workshop_row.current_part_index,
        current_part_slug=workshop_row.current_part_slug,
        part_generation=workshop_row.part_generation,
        created_at=workshop_row.created_at,
    )
    lesson_repo = session.get(LessonRepo, lesson.repo_id)
    if lesson_repo is None:
        return (
            core,
            WorkshopLessonSummaryPublic(
                id=lesson.id,
                title=lesson.title,
                slug=lesson.slug,
                lesson_repo_health="unhealthy",
                lesson_content_available=False,
                lesson_content_issue="lesson_repo_missing",
            ),
            [],
        )

    lesson_summary = WorkshopLessonSummaryPublic(
        id=lesson.id,
        title=lesson.title,
        slug=lesson.slug,
        lesson_repo_health=lesson_repo.health,
        lesson_repo_last_synced_at=lesson_repo.last_synced_at,
    )
    part_rows = session.exec(
        select(LessonPart)
        .where(LessonPart.lesson_id == lesson.id)
        .order_by(col(LessonPart.ordering))
    ).all()
    parts: list[WorkshopLessonPartBrief] = []
    for row in part_rows:
        row_id = row.id
        part_repo_path = _canonical_part_repo_path(
            lesson_slug=lesson.slug,
            part_path=row.path,
        )

        def asset_url_for_repo_path(
            repo_relative_path: str, *, row_id: uuid.UUID = row_id
        ) -> str:
            token = _issue_workshop_asset_token(
                session_id=workshop_row.id,
                part_id=row_id,
                repo_path=repo_relative_path,
            )
            return (
                f"{settings.FRONTEND_HOST.rstrip('/')}{settings.API_V1_STR}"
                f"/workshop/sessions/{workshop_row.id}/parts/{row_id}/asset"
                f"?path={quote(repo_relative_path, safe='/')}"
                f"&token={quote(token, safe='')}"
            )

        body_md = rewrite_relative_asset_urls(
            row.body_md,
            part_repo_path=part_repo_path,
            rewrite_repo_relative_path=asset_url_for_repo_path,
        )
        parts.append(
            WorkshopLessonPartBrief(
                id=row.id,
                ordering=int(row.ordering),
                slug=row.slug,
                title=row.title,
                estimated_minutes=row.estimated_minutes,
                body_html=lesson_markdown_to_safe_html(body_md),
            )
        )
    if len(parts) == 0:
        lesson_summary.lesson_content_available = False
        lesson_summary.lesson_content_issue = "no_parts_synced"
    return core, lesson_summary, parts


def _normalize_repo_asset_path(path: str) -> str:
    normalized = posixpath.normpath(path.strip().lstrip("/"))
    if (
        normalized == ""
        or normalized == "."
        or normalized.startswith("../")
        or "/../" in f"/{normalized}/"
    ):
        raise HTTPException(status_code=400, detail="invalid asset path")
    return normalized


def _canonical_part_repo_path(*, lesson_slug: str, part_path: str) -> str:
    cleaned = part_path.strip().lstrip("/")
    if cleaned.startswith("lessons/"):
        return cleaned
    # Manifest part paths are usually lesson-relative (e.g. `01.md`), so anchor
    # them under the conventional lesson directory to resolve ../../.img assets.
    return f"lessons/{lesson_slug}/{cleaned}"


def _current_part_manifest_target_seconds(
    session: Session, *, workshop_session: WorkshopSession
) -> int | None:
    lesson_row = session.get(Lesson, workshop_session.lesson_id)
    if lesson_row is None:
        return None
    current_part = session.exec(
        select(LessonPart).where(
            LessonPart.lesson_id == lesson_row.id,
            LessonPart.ordering == workshop_session.current_part_index,
        )
    ).first()
    if current_part is None or current_part.estimated_minutes is None:
        return None
    return int(current_part.estimated_minutes) * 60


def _issue_workshop_asset_token(
    *,
    session_id: uuid.UUID,
    part_id: uuid.UUID,
    repo_path: str,
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "workshop.asset",
        "sid": str(session_id),
        "pid": str(part_id),
        "path": repo_path,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM)
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def _verify_workshop_asset_token(
    *,
    token: str,
    session_id: uuid.UUID,
    part_id: uuid.UUID,
    repo_path: str,
) -> None:
    try:
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except PyJWTError as exc:
        raise HTTPException(status_code=403, detail="invalid asset token") from exc
    if (
        decoded.get("sub") != "workshop.asset"
        or decoded.get("sid") != str(session_id)
        or decoded.get("pid") != str(part_id)
        or decoded.get("path") != repo_path
    ):
        raise HTTPException(status_code=403, detail="invalid asset token")


def _github_avatar_urls_for_roster_users(
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


@router.get("/{session_id}/parts/{part_id}/asset")
def read_workshop_part_asset(
    *,
    session: SessionDep,
    session_id: uuid.UUID,
    part_id: uuid.UUID,
    path: str = Query(min_length=1),
    token: str = Query(min_length=1),
) -> Response:
    workshop_row = session.get(WorkshopSession, session_id)
    if workshop_row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    lesson = session.get(Lesson, workshop_row.lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson_repo = session.get(LessonRepo, lesson.repo_id)
    if lesson_repo is None:
        raise HTTPException(status_code=404, detail="Lesson repository not found")

    part = session.get(LessonPart, part_id)
    if part is None or part.lesson_id != lesson.id:
        raise HTTPException(status_code=404, detail="Lesson part not found")

    normalized_path = _normalize_repo_asset_path(path)
    _verify_workshop_asset_token(
        token=token,
        session_id=session_id,
        part_id=part_id,
        repo_path=normalized_path,
    )
    asset_row = session.exec(
        select(LessonRepoAsset).where(
            LessonRepoAsset.repo_id == lesson_repo.id,
            LessonRepoAsset.repo_path == normalized_path,
        )
    ).first()
    if asset_row is None:
        raise HTTPException(status_code=404, detail="Lesson asset not found")

    return Response(
        content=asset_row.content_bytes,
        media_type=asset_row.content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/{session_id}",
    response_model=WorkshopSessionPublicParticipant | WorkshopSessionPublicInstructor,
)
def read_workshop_session_detail(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionPublicParticipant | WorkshopSessionPublicInstructor:
    workshop_row = session.get(WorkshopSession, session_id)
    if workshop_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    view_kind = _workshop_session_detail_view_kind(
        session,
        session_id=session_id,
        current_user=current_user,
    )
    if view_kind is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this session",
        )

    core, lesson_summary, parts = _workshop_session_detail_shared(
        session, workshop_row=workshop_row
    )

    if view_kind == "participant":
        participant = session.exec(
            select(WorkshopParticipant).where(
                WorkshopParticipant.session_id == session_id,
                WorkshopParticipant.user_id == current_user.id,
                col(WorkshopParticipant.removed_at).is_(None),
            )
        ).first()
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="participant_seat_missing",
            )
        self_snap = WorkshopParticipantSelfPublic(
            invited_at=participant.invited_at,
            joined_at=participant.joined_at,
            finished_at=participant.finished_at,
            live_status=participant.live_status,
        )
        return WorkshopSessionPublicParticipant(
            session=core,
            lesson=lesson_summary,
            parts=parts,
            participant_self=self_snap,
        )

    p_pairs = session.exec(
        select(WorkshopParticipant, User)
        .join(User, col(WorkshopParticipant.user_id) == User.id)
        .where(
            WorkshopParticipant.session_id == session_id,
            col(WorkshopParticipant.removed_at).is_(None),
            col(WorkshopParticipant.user_id).is_not(None),
        )
    ).all()
    participants_out = sorted(p_pairs, key=lambda pair: str(pair[1].email))
    i_pairs = session.exec(
        select(SessionInstructor, User)
        .join(User, col(SessionInstructor.user_id) == User.id)
        .where(
            SessionInstructor.session_id == session_id,
            col(SessionInstructor.removed_at).is_(None),
        )
    ).all()
    roster_user_ids = {user.id for _, user in participants_out}
    instructors_out = sorted(i_pairs, key=lambda pair: str(pair[1].email))
    roster_user_ids |= {user.id for _, user in instructors_out}
    avatars_by_user_id = _github_avatar_urls_for_roster_users(
        session, user_ids=roster_user_ids
    )
    participants_public = [
        WorkshopRosterParticipantRowPublic(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            avatar_url=avatars_by_user_id.get(user.id),
            invited_at=seat.invited_at,
            joined_at=seat.joined_at,
            finished_at=seat.finished_at,
            live_status=seat.live_status,
        )
        for seat, user in participants_out
    ]

    instructors_public = [
        WorkshopRosterInstructorRowPublic(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            avatar_url=avatars_by_user_id.get(user.id),
            role=seat.role,
            assigned_at=seat.assigned_at,
        )
        for seat, user in instructors_out
    ]

    return WorkshopSessionPublicInstructor(
        session=core,
        lesson=lesson_summary,
        parts=parts,
        participants=participants_public,
        instructors=instructors_public,
    )


@router.patch("/{session_id}", response_model=Message)
async def patch_workshop_session(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopSessionPatch,
) -> Message:
    """Instructor/superuser updates session state (status), roster seats, or seat roles."""
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    has_status = body.status is not None
    has_seat_role = body.instructor_seat is not None
    has_primary_handoff = body.primary_instructor_user_id is not None
    has_remove = body.remove_instructor_user_id is not None
    if (
        not has_status
        and not has_seat_role
        and not has_primary_handoff
        and not has_remove
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="patch_requires_update",
        )
    if (
        has_seat_role
        and has_remove
        and body.instructor_seat is not None
        and body.remove_instructor_user_id is not None
        and body.instructor_seat.user_id == body.remove_instructor_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot_update_and_remove_same_instructor",
        )
    if (
        has_primary_handoff
        and has_remove
        and body.primary_instructor_user_id is not None
        and body.remove_instructor_user_id is not None
        and body.primary_instructor_user_id == body.remove_instructor_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot_handoff_to_removed_instructor",
        )

    if has_status and body.status is not None:
        _validate_workshop_session_status_transition(
            current_status=str(workshop_session.status),
            target_status=body.status,
        )
    tentative_status = str(body.status) if has_status else str(workshop_session.status)

    if has_remove and body.remove_instructor_user_id is not None:
        remaining = _count_active_session_instructors_excluding(
            session,
            session_id=session_id,
            exclude_user_id=body.remove_instructor_user_id,
        )
        if remaining == 0 and tentative_status != "ended":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="last_instructor_removal_blocked",
            )

    status_changed = False
    if has_status and body.status is not None:
        if body.status != str(workshop_session.status):
            workshop_session.status = body.status
            session.add(workshop_session)
            status_changed = True

    if has_seat_role and body.instructor_seat is not None:
        seat = session.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                SessionInstructor.user_id == body.instructor_seat.user_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if seat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instructor seat not found",
            )
        seat.role = body.instructor_seat.role
        session.add(seat)

    if has_primary_handoff and body.primary_instructor_user_id is not None:
        target_primary = session.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                SessionInstructor.user_id == body.primary_instructor_user_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if target_primary is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="handoff_target_not_instructor",
            )
        active_seats = session.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).all()
        for instructor_seat in active_seats:
            if instructor_seat.user_id == body.primary_instructor_user_id:
                instructor_seat.role = "lead"
            elif instructor_seat.role == "lead":
                instructor_seat.role = "co_instructor"
            session.add(instructor_seat)

    if has_remove and body.remove_instructor_user_id is not None:
        remove_seat = session.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                SessionInstructor.user_id == body.remove_instructor_user_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if remove_seat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instructor seat not found",
            )
        remove_seat.removed_at = datetime.now(timezone.utc)
        session.add(remove_seat)

    session.commit()
    if status_changed and body.status is not None:
        await workshop_hub.publish_session_status_changed(
            session_id=session_id,
            status=str(body.status),
        )
    return Message(message="Session updated")


@router.get(
    "/{session_id}/roster-user-picker",
    response_model=WorkshopRosterUserPickerPublic,
)
def read_workshop_session_roster_user_picker(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    q: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(
        ROSTER_PICKER_DEFAULT_LIMIT,
        ge=1,
        le=ROSTER_PICKER_MAX_LIMIT,
    ),
) -> WorkshopRosterUserPickerPublic:
    """Instructor-only paginated user list for roster; optional pg_trgm-ranked search."""
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    q_stripped = (q or "").strip()
    if q_stripped:
        if len(q_stripped) < ROSTER_PICKER_MIN_Q_LEN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Search query must be at least 2 characters",
            )
        email_c = cast(User.email, String)
        name_c = func.coalesce(cast(User.full_name, String), "")
        q_lit = literal(q_stripped)
        sim_e = sa_func.similarity(email_c, q_lit)
        sim_n = sa_func.similarity(name_c, q_lit)
        match_expr = sa_func.greatest(sim_e, sim_n)
        cond = or_(email_c.op("%")(q_lit), name_c.op("%")(q_lit))
        count_val = session.exec(
            select(func.count()).select_from(User).where(cond)
        ).one()
        stmt = (
            select(User, match_expr.label("match_score"))
            .where(cond)
            .order_by(match_expr.desc(), User.email)
            .offset(skip)
            .limit(limit)
        )
        rows = session.exec(stmt).all()
        data = [
            WorkshopRosterUserPickerRowPublic(
                user_id=user.id,
                email=str(user.email),
                full_name=user.full_name,
                is_superuser=user.is_superuser,
                is_instructor=user.is_instructor,
                is_active=user.is_active,
                match_score=float(score) if score is not None else None,
            )
            for user, score in rows
        ]
        return WorkshopRosterUserPickerPublic(data=data, count=int(count_val))

    count_val = session.exec(select(func.count()).select_from(User)).one()
    browse_stmt = select(User).order_by(User.email).offset(skip).limit(limit)
    users = session.exec(browse_stmt).all()
    data = [
        WorkshopRosterUserPickerRowPublic(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            is_superuser=user.is_superuser,
            is_instructor=user.is_instructor,
            is_active=user.is_active,
            match_score=None,
        )
        for user in users
    ]
    return WorkshopRosterUserPickerPublic(data=data, count=int(count_val))


@router.post(
    "/{session_id}/members/batch",
    response_model=WorkshopSessionMembersBatchResponse,
)
def batch_upsert_workshop_session_participants(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopSessionMembersBatchBody,
) -> WorkshopSessionMembersBatchResponse:
    """Add many participants at once (deduped, stable order)."""
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    if len(body.user_ids) > ROSTER_BATCH_MAX_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {ROSTER_BATCH_MAX_IDS} user_ids per request",
        )

    seen: set[uuid.UUID] = set()
    ordered_unique: list[uuid.UUID] = []
    for uid in body.user_ids:
        if uid not in seen:
            seen.add(uid)
            ordered_unique.append(uid)

    results: list[WorkshopSessionMemberBatchResultItem] = []
    for uid in ordered_unique:
        target_user = session.get(User, uid)
        if target_user is None:
            results.append(
                WorkshopSessionMemberBatchResultItem(
                    user_id=uid,
                    status="not_found",
                    detail="Target user not found",
                )
            )
            continue
        try:
            st = _upsert_workshop_session_participant_seat(
                session,
                session_id=session_id,
                target_user=target_user,
            )
            results.append(
                WorkshopSessionMemberBatchResultItem(
                    user_id=uid,
                    status=st,
                    detail=None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                WorkshopSessionMemberBatchResultItem(
                    user_id=uid,
                    status="error",
                    detail=str(exc),
                )
            )
    session.commit()
    return WorkshopSessionMembersBatchResponse(results=results)


@router.post("/{session_id}/members", response_model=Message)
def upsert_workshop_session_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopSessionUpsertMember,
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    target_user = session.get(User, body.user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found",
        )

    now = datetime.now(timezone.utc)
    if body.role == "participant":
        _upsert_workshop_session_participant_seat(
            session,
            session_id=session_id,
            target_user=target_user,
        )
        session.commit()
        return Message(message="Member upserted as participant")

    if not target_user.is_instructor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instructor role requires target user.is_instructor",
        )

    participant = session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == target_user.id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is not None:
        participant.removed_at = now
        session.add(participant)

    instructor = session.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_id,
            SessionInstructor.user_id == target_user.id,
        )
    ).first()
    if instructor is None:
        instructor = SessionInstructor(
            session_id=session_id,
            user_id=target_user.id,
            role=body.instructor_role,
            assigned_at=now,
        )
    else:
        instructor.removed_at = None
        instructor.role = body.instructor_role
    session.add(instructor)
    session.commit()
    return Message(message="Member upserted as instructor")


@router.delete("/{session_id}/participants/{user_id}", response_model=Message)
def remove_workshop_session_participant(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    participant = session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == user_id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )

    participant.removed_at = datetime.now(timezone.utc)
    session.add(participant)
    session.commit()
    return Message(message="Participant removed")


@router.patch("/{session_id}/participants/{user_id}", response_model=Message)
def patch_workshop_session_participant(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    body: WorkshopParticipantPatch,
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )

    participant = session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == user_id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )

    if body.live_status is not None:
        participant.live_status = body.live_status
    if body.joined_at is not None:
        participant.joined_at = body.joined_at
    if body.finished_at is not None:
        participant.finished_at = body.finished_at
    session.add(participant)
    session.commit()
    return Message(message="Participant updated")


@router.post("/{session_id}/enter", response_model=Message)
def enter_workshop_session(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    if workshop_session.status not in WORKSHOP_ACTIVE_STATUSES:
        if workshop_session.status == "scheduled":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session not started yet",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session has ended",
        )

    if not _required_prerequisites_complete_for_user(
        session,
        lesson_id=workshop_session.lesson_id,
        user_id=current_user.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Required prerequisites incomplete",
        )

    participant = session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == current_user.id,
        )
    ).first()
    if participant is None:
        participant = WorkshopParticipant(
            session_id=session_id,
            user_id=current_user.id,
            invited_at=datetime.now(timezone.utc),
            joined_at=datetime.now(timezone.utc),
        )
        session.add(participant)
    elif participant.joined_at is None:
        participant.joined_at = datetime.now(timezone.utc)

    session.commit()
    return Message(message="Entered session")


@router.post("/{session_id}/start", response_model=Message)
async def start_workshop_session(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    if workshop_session.status != "scheduled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="start_requires_scheduled_session",
        )
    content_issue = _workshop_session_start_content_issue(
        session, workshop_row=workshop_session
    )
    if content_issue is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"lesson_content_unavailable:{content_issue}",
        )
    workshop_session.status = "live"
    session.add(workshop_session)
    session.commit()
    await workshop_hub.publish_session_status_changed(
        session_id=session_id,
        status="live",
    )
    return Message(message="Session started")


@router.post("/{session_id}/end", response_model=Message)
async def end_workshop_session(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    if workshop_session.status not in WORKSHOP_ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="end_requires_active_session",
        )
    workshop_session.status = "ended"
    session.add(workshop_session)
    session.commit()
    await workshop_hub.publish_session_status_changed(
        session_id=session_id,
        status="ended",
    )
    return Message(message="Session ended")


@router.get("/{session_id}/timer", response_model=WorkshopSessionTimerPublic)
async def read_workshop_session_timer(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is None or timer_row.status == "inactive":
        return WorkshopSessionTimerPublic(session_id=session_id, status="inactive")
    return _timer_public(session_id, timer_row)


@router.get(
    "/{session_id}/timer/events", response_model=WorkshopSessionTimerEventsPublic
)
def read_workshop_session_timer_events(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=100),
) -> WorkshopSessionTimerEventsPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    rows = session.exec(
        select(WorkshopSessionTimerEvent)
        .where(WorkshopSessionTimerEvent.session_id == session_id)
        .order_by(col(WorkshopSessionTimerEvent.created_at).desc())
        .limit(limit)
    ).all()
    data = [
        WorkshopSessionTimerEventPublic(
            id=row.id,
            session_id=row.session_id,
            actor_user_id=row.actor_user_id,
            action=row.action,
            mode=row.mode,
            target_seconds=row.target_seconds,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return WorkshopSessionTimerEventsPublic(data=data, count=len(data))


@router.post("/{session_id}/timer/start", response_model=WorkshopSessionTimerPublic)
async def start_workshop_session_timer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopSessionTimerStart,
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_timer_allowed_session_status(workshop_session)
    target_seconds = body.target_seconds
    if body.mode == "countdown" and target_seconds is None:
        target_seconds = _current_part_manifest_target_seconds(
            session, workshop_session=workshop_session
        )
    if body.mode == "countdown" and target_seconds is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="countdown_requires_target_seconds",
        )
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is not None and timer_row.status in {"running", "paused"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_already_active",
        )
    now = datetime.now(timezone.utc)
    if timer_row is None:
        timer_row = WorkshopSessionTimer(session_id=session_id)
    timer_row.status = "running"
    timer_row.mode = body.mode
    timer_row.target_seconds = target_seconds
    timer_row.started_at = now
    timer_row.paused_at = None
    timer_row.updated_at = now
    session.add(timer_row)
    _record_timer_event(
        session,
        session_id=session_id,
        actor_user_id=current_user.id,
        action="start",
        mode=timer_row.mode,
        target_seconds=timer_row.target_seconds,
    )
    session.commit()
    session.refresh(timer_row)
    return _timer_public(session_id, timer_row)


@router.post("/{session_id}/timer/extend", response_model=WorkshopSessionTimerPublic)
async def extend_workshop_session_timer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: uuid.UUID,
    body: WorkshopSessionTimerExtend,
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_timer_allowed_session_status(workshop_session)
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is None or timer_row.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_active",
        )
    if timer_row.mode != "countdown":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_countdown",
        )
    if timer_row.target_seconds is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_target_missing",
        )

    now = datetime.now(timezone.utc)
    timer_row.target_seconds = min(
        86_400, int(timer_row.target_seconds) + int(body.additional_seconds)
    )
    timer_row.updated_at = now
    session.add(timer_row)
    _record_timer_event(
        session,
        session_id=session_id,
        actor_user_id=current_user.id,
        action="extend",
        mode=timer_row.mode,
        target_seconds=timer_row.target_seconds,
    )
    session.commit()
    session.refresh(timer_row)
    return _timer_public(session_id, timer_row)


@router.post("/{session_id}/timer/pause", response_model=WorkshopSessionTimerPublic)
async def pause_workshop_session_timer(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_timer_allowed_session_status(workshop_session)
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is None or timer_row.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_active",
        )
    if timer_row.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_running",
        )
    now = datetime.now(timezone.utc)
    timer_row.status = "paused"
    timer_row.paused_at = now
    timer_row.updated_at = now
    session.add(timer_row)
    _record_timer_event(
        session,
        session_id=session_id,
        actor_user_id=current_user.id,
        action="pause",
        mode=timer_row.mode,
        target_seconds=timer_row.target_seconds,
    )
    session.commit()
    session.refresh(timer_row)
    return _timer_public(session_id, timer_row)


@router.post("/{session_id}/timer/resume", response_model=WorkshopSessionTimerPublic)
async def resume_workshop_session_timer(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_timer_allowed_session_status(workshop_session)
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is None or timer_row.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_active",
        )
    if timer_row.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_paused",
        )
    now = datetime.now(timezone.utc)
    if timer_row.paused_at is not None and timer_row.started_at is not None:
        paused_duration = now - timer_row.paused_at
        timer_row.started_at = timer_row.started_at + paused_duration
    timer_row.status = "running"
    timer_row.paused_at = None
    timer_row.updated_at = now
    session.add(timer_row)
    _record_timer_event(
        session,
        session_id=session_id,
        actor_user_id=current_user.id,
        action="resume",
        mode=timer_row.mode,
        target_seconds=timer_row.target_seconds,
    )
    session.commit()
    session.refresh(timer_row)
    return _timer_public(session_id, timer_row)


@router.post("/{session_id}/timer/stop", response_model=WorkshopSessionTimerPublic)
async def stop_workshop_session_timer(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopSessionTimerPublic:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    _require_workshop_instructor(
        session_db=session, session_id=session_id, current_user=current_user
    )
    _require_timer_allowed_session_status(workshop_session)
    timer_row = session.exec(
        select(WorkshopSessionTimer).where(
            WorkshopSessionTimer.session_id == session_id
        )
    ).first()
    if timer_row is None or timer_row.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="timer_not_active",
        )
    now = datetime.now(timezone.utc)
    timer_row.status = "inactive"
    timer_row.paused_at = None
    timer_row.updated_at = now
    session.add(timer_row)
    _record_timer_event(
        session,
        session_id=session_id,
        actor_user_id=current_user.id,
        action="stop",
        mode=timer_row.mode,
        target_seconds=timer_row.target_seconds,
    )
    session.commit()
    return WorkshopSessionTimerPublic(session_id=session_id, status="inactive")


@router.post("/{session_id}/ws-ticket", response_model=WorkshopWsTicket)
def create_workshop_ws_ticket(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopWsTicket:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if workshop_session.status not in WORKSHOP_WS_HANDSHAKE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Session has ended"
                if workshop_session.status == "ended"
                else "Session not available for realtime"
            ),
        )

    role = None
    participant = session.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_id,
            WorkshopParticipant.user_id == current_user.id,
            col(WorkshopParticipant.removed_at).is_(None),
        )
    ).first()
    if participant is not None:
        if participant.joined_at is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User must enter session first",
            )
        if not _required_prerequisites_complete_for_user(
            session,
            lesson_id=workshop_session.lesson_id,
            user_id=current_user.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Required prerequisites incomplete",
            )
        role = "participant"

    if role is None:
        instructor = session.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                SessionInstructor.user_id == current_user.id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if instructor is not None or current_user.is_superuser:
            role = "instructor"

    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not part of this session",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sid": str(session_id),
        "uid": str(current_user.id),
        "role": role,
        "pg": workshop_session.part_generation,
        "aud": "workshop-ws",
        "exp": expires_at,
    }
    ticket = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return WorkshopWsTicket(ticket=ticket, expires_at=expires_at)


@router.websocket("/{session_id}/ws")
async def workshop_session_ws(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """Workshop realtime channel.

    Authentication: ``Sec-WebSocket-Protocol`` must include ``ticket`` followed by
    the JWT from ``POST /workshop/sessions/{session_id}/ws-ticket``, e.g.
    ``ticket, <jwt>``.
    """
    raw_token = _extract_ws_ticket_from_subprotocols(
        websocket.headers.get("sec-websocket-protocol")
    )
    if raw_token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        claims = _decode_workshop_ws_ticket(raw_token)
    except PyJWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    with Session(engine) as db:
        handshake = _authorize_workshop_ws_handshake(
            db, route_session_id=session_id, claims=claims
        )
    if handshake is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol="ticket")
    connection = WorkshopWsConnection(
        websocket=websocket,
        session_id=session_id,
        user_id=handshake.user_id,
        role=handshake.role,
        part_generation=handshake.part_generation,
    )
    await workshop_hub.attach(connection)
    try:
        await websocket.send_json(
            {
                "type": "session.connected",
                "session_id": str(session_id),
                "role": handshake.role,
                "part_generation": handshake.part_generation,
            }
        )
        while True:
            text = await websocket.receive_text()
            keep_receiving = await _dispatch_workshop_ws_text(
                websocket=websocket,
                session_id=session_id,
                handshake=handshake,
                connection=connection,
                text=text,
            )
            if not keep_receiving:
                break
    except WebSocketDisconnect:
        return
    finally:
        await workshop_hub.detach(connection)
