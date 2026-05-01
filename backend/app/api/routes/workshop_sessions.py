import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, WebSocket, status
from jwt.exceptions import PyJWTError
from pydantic import BaseModel
from sqlmodel import col, select
from starlette.websockets import WebSocketDisconnect

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import (
    Message,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)

router = APIRouter(prefix="/workshop/sessions", tags=["workshop-sessions"])


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


@router.post("/{session_id}/enter", response_model=Message)
def enter_workshop_session(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> Message:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    if workshop_session.status == "scheduled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session not started yet",
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


@router.post("/{session_id}/ws-ticket", response_model=WorkshopWsTicket)
def create_workshop_ws_ticket(
    *, session: SessionDep, current_user: CurrentUser, session_id: uuid.UUID
) -> WorkshopWsTicket:
    workshop_session = session.get(WorkshopSession, session_id)
    if workshop_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if workshop_session.status == "scheduled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session not started yet",
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
async def workshop_session_ws(
    websocket: WebSocket, session_id: uuid.UUID, db: SessionDep
) -> None:
    """Workshop realtime channel (handshake only in this slice).

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

    try:
        token_session_id = uuid.UUID(str(claims["sid"]))
        token_user_id = uuid.UUID(str(claims["uid"]))
        role = str(claims["role"])
        token_part_generation = int(claims["pg"])
    except (KeyError, TypeError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if token_session_id != session_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    workshop_session = db.get(WorkshopSession, session_id)
    if workshop_session is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if workshop_session.status == "scheduled":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if token_part_generation != workshop_session.part_generation:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = db.get(User, token_user_id)
    if user is None or not user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if role == "participant":
        participant = db.exec(
            select(WorkshopParticipant).where(
                WorkshopParticipant.session_id == session_id,
                WorkshopParticipant.user_id == token_user_id,
                col(WorkshopParticipant.removed_at).is_(None),
            )
        ).first()
        if participant is None or participant.joined_at is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    elif role == "instructor":
        instructor = db.exec(
            select(SessionInstructor).where(
                SessionInstructor.session_id == session_id,
                SessionInstructor.user_id == token_user_id,
                col(SessionInstructor.removed_at).is_(None),
            )
        ).first()
        if instructor is None and not user.is_superuser:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    else:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol="ticket")
    await websocket.send_json(
        {
            "type": "session.connected",
            "session_id": str(session_id),
            "role": role,
            "part_generation": workshop_session.part_generation,
        }
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
