import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from jwt.exceptions import PyJWTError
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import engine
from app.core.security import ALGORITHM
from app.models import (
    LessonPart,
    Message,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)
from app.services.workshop_realtime import (
    WorkshopWsConnection,
    workshop_hub,
)

router = APIRouter(prefix="/workshop/sessions", tags=["workshop-sessions"])

ALLOWED_WS_LIVE_STATUSES = frozenset({"busy", "done"})
# Part moves are frozen unless the workshop is actively running (`live`).
WS_PART_ADVANCE_REQUIRES_STATUS = frozenset({"live"})
# Enter, ws-ticket, and websocket handshake only when the session is running or paused.
WORKSHOP_ACTIVE_STATUSES = frozenset({"live", "paused"})


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
    if workshop_session.status not in WORKSHOP_ACTIVE_STATUSES:
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


@router.post("/{session_id}/ws-ticket", response_model=WorkshopWsTicket)
def create_workshop_ws_ticket(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopWsTicket:
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
