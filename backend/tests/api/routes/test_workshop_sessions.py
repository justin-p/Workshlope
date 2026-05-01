import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import Lesson, LessonRepo, User, WorkshopParticipant, WorkshopSession
from tests.utils.user import authentication_token_from_email


def _create_live_session(db: Session) -> WorkshopSession:
    repo = LessonRepo(
        full_name=f"org/repo-{uuid.uuid4()}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    lesson = Lesson(
        repo_id=repo.id,
        slug=f"intro-{uuid.uuid4()}",
        title="Intro",
        lesson_sync_generation=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    session = WorkshopSession(
        lesson_id=lesson.id,
        status="live",
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_enter_rejected_when_session_scheduled(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    session.status = "scheduled"
    db.add(session)
    db.commit()
    db.refresh(session)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/enter",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


def test_ws_ticket_requires_roster_membership(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not part of this session"


def test_ws_ticket_returns_signed_claims_for_joined_participant(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    decoded = jwt.decode(
        payload["ticket"],
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        audience="workshop-ws",
    )
    assert decoded["sid"] == str(session.id)
    assert decoded["uid"] == str(user.id)
    assert decoded["role"] == "participant"


def _workshop_ws_path(session_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/workshop/sessions/{session_id}/ws"


def test_ws_connect_accepts_ticket_subprotocol(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.accepted_subprotocol == "ticket"
        hello = websocket.receive_json()
        assert hello["type"] == "session.connected"
        assert hello["session_id"] == str(session_row.id)
        assert hello["role"] == "participant"
        assert hello["part_generation"] == session_row.part_generation


def test_ws_connect_denies_without_ticket_marker(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=[ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_connect_denies_stale_part_generation(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    session_row.part_generation = 5
    db.add(session_row)
    db.commit()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    stale_ticket = jwt.encode(
        {
            "sid": str(session_row.id),
            "uid": str(user.id),
            "role": "participant",
            "pg": 1,
            "aud": "workshop-ws",
            "exp": expires_at,
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", stale_ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_connect_denies_session_path_mismatch(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    other_session = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(other_session.id),
            subprotocols=["ticket", ticket],
        ):
            pass
    assert exc_info.value.code == 1008
