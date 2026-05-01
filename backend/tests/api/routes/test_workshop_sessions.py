import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import (
    Lesson,
    LessonPart,
    LessonRepo,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)
from app.services import workshop_realtime as workshop_realtime_mod
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


def _add_two_parts_to_session_lesson(db: Session, session: WorkshopSession) -> None:
    lesson = db.get(Lesson, session.lesson_id)
    assert lesson is not None
    db.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=0,
            slug=f"part-0-{uuid.uuid4()}",
            title="Part 0",
            path="01-part-0.md",
            body_md="# Part 0",
        )
    )
    db.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=1,
            slug=f"part-1-{uuid.uuid4()}",
            title="Part 1",
            path="02-part-1.md",
            body_md="# Part 1",
        )
    )
    db.commit()


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


def test_ws_participant_live_status_persists_ack_and_fanout_registered(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    participant_row = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(participant_row)
    db.commit()
    db.refresh(participant_row)
    assert participant_row.live_status == "busy"

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    published: list[tuple[uuid.UUID, uuid.UUID, str]] = []

    async def capture_publish(
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        live_status: str,
    ) -> None:
        published.append((session_id, user_id, live_status))

    monkeypatch.setattr(
        workshop_realtime_mod.workshop_hub,
        "publish_participant_live_status",
        capture_publish,
    )

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.connected"
        websocket.send_json({"type": "live_status", "live_status": "done"})
        ack = websocket.receive_json()
        assert ack == {"type": "live_status.ack", "live_status": "done"}

    db.refresh(participant_row)
    assert participant_row.live_status == "done"
    assert published == [(session_row.id, user.id, "done")]


def test_ws_instructor_can_advance_part_and_broadcast_to_participants(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    participant_user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert participant_user is not None
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=participant_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    participant_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]
    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", participant_ticket],
    ) as participant_ws:
        assert participant_ws.receive_json()["type"] == "session.connected"
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket],
        ) as instructor_ws:
            assert instructor_ws.receive_json()["type"] == "session.connected"
            instructor_ws.send_json({"type": "part.advance", "part_index": 1})
            ack = instructor_ws.receive_json()
            broadcast = participant_ws.receive_json()

    assert ack["type"] == "part.advance.ack"
    assert ack["part_index"] == 1
    assert broadcast["type"] == "session.part_changed"
    assert broadcast["part_index"] == 1


def test_ws_part_advance_denied_when_session_paused(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    session_row.status = "paused"
    db.add(session_row)
    db.commit()

    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", instructor_ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "part.advance", "part_index": 1})
        denied = instructor_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "advance_requires_live_session",
    }


def test_ws_instructor_pause_resume_broadcasts_status(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    participant_user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert participant_user is not None

    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=participant_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    assert session_row.status == "live"

    participant_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]
    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", participant_ticket],
    ) as participant_ws:
        assert participant_ws.receive_json()["type"] == "session.connected"

        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket],
        ) as instructor_ws:
            assert instructor_ws.receive_json()["type"] == "session.connected"
            instructor_ws.send_json({"type": "session.pause"})
            pause_ack = instructor_ws.receive_json()
            pause_broadcast = participant_ws.receive_json()

        assert pause_ack == {"type": "session.pause.ack", "status": "paused"}
        assert pause_broadcast == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }

        db.refresh(session_row)
        assert session_row.status == "paused"

        instructor_ticket_resume = client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
            headers=instructor_headers,
        ).json()["ticket"]

        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket_resume],
        ) as instructor_resume_ws:
            assert instructor_resume_ws.receive_json()["type"] == "session.connected"
            instructor_resume_ws.send_json({"type": "session.resume"})
            resume_ack = instructor_resume_ws.receive_json()
            resume_broadcast = participant_ws.receive_json()

        assert resume_ack == {"type": "session.resume.ack", "status": "live"}
        assert resume_broadcast == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "live",
        }

    db.refresh(session_row)
    assert session_row.status == "live"


def test_ws_second_pause_rejected(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", instructor_ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "session.pause"})
        assert instructor_ws.receive_json() == {
            "type": "session.pause.ack",
            "status": "paused",
        }
        assert instructor_ws.receive_json() == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }
        instructor_ws.send_json({"type": "session.pause"})
        denied = instructor_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "pause_requires_live_session",
    }
