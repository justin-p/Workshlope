import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import (
    Lesson,
    LessonPart,
    LessonPrerequisite,
    LessonRepo,
    SessionInstructor,
    User,
    UserCreate,
    UserPrerequisiteCompletion,
    WorkshopParticipant,
    WorkshopSession,
)
from app.services import workshop_realtime as workshop_realtime_mod
from tests.utils.user import (
    authentication_token_from_email,
    user_authentication_headers,
)
from tests.utils.utils import get_superuser_token_headers


def _create_scheduled_session(db: Session) -> WorkshopSession:
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
        status="scheduled",
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


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


def test_enter_rejected_when_session_ended(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "ended"
    db.add(session_row)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Session has ended"


def test_ws_ticket_rejected_when_session_ended(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
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
    session_row.status = "ended"
    db.add(session_row)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Session has ended"


def test_http_start_requires_instructor_role(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "User is not an instructor for this session"


def test_http_start_scheduled_then_ws_ticket_allowed(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    instructor_email = f"instr-start-{uuid.uuid4()}@example.com"
    inst_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    inst_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert inst_user is not None
    inst_user.is_instructor = True
    db.add(inst_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=inst_user.id,
            role="lead",
        )
    )
    participant_email = f"participant-start-{uuid.uuid4()}@example.com"
    p_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    p_user = db.exec(select(User).where(User.email == participant_email)).first()
    assert p_user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=p_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    start = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=inst_headers,
    )
    assert start.status_code == 200
    assert start.json()["message"] == "Session started"

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=p_headers,
    )
    assert ticket.status_code == 200


def test_http_second_start_rejected(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()
    instructor_email = f"i2-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
            headers=i_headers,
        ).status_code
        == 200
    )
    again = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=i_headers,
    )
    assert again.status_code == 403
    assert again.json()["detail"] == "start_requires_scheduled_session"


def test_http_end_broadcast_blocked_when_scheduled(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()
    instructor_email = f"i3-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=i_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "end_requires_active_session"


def test_ws_connect_ticket_rejected_after_session_end(
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
    db.commit()

    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )

    instructor_email = f"i-end-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    end_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=i_headers,
    )
    assert end_resp.status_code == 200

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_live_status_rejected_after_session_http_end(
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
    db.commit()

    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    instructor_email = f"i-live-end-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"
        assert (
            client.post(
                f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
                headers=i_headers,
            ).status_code
            == 200
        )
        ended_push = trainee_ws.receive_json()
        assert ended_push == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "ended",
        }
        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        denied = trainee_ws.receive_json()

    assert denied == {"type": "error", "detail": "session_not_active"}


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


def test_ws_rejects_when_db_part_generation_runs_ahead_of_connection_mirror(
    client: TestClient,
    db: Session,
) -> None:
    """If DB part_generation moves without mirroring into the hub connections, the
    next inbound frame is rejected so the client must mint a fresh ws-ticket."""
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
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws_row = db.get(WorkshopSession, session_row.id)
        assert ws_row is not None
        ws_row.part_generation = int(ws_row.part_generation) + 1
        db.add(ws_row)
        db.commit()
        expected_gen = int(ws_row.part_generation)

        ws.send_json({"type": "live_status", "live_status": "done"})
        err = ws.receive_json()

    assert err == {
        "type": "error",
        "detail": "part_generation_stale",
        "part_generation": expected_gen,
    }


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


def test_ws_participant_live_status_rejected_when_session_paused(
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

    instructor_email = f"instructor-pause-ls-{uuid.uuid4()}@example.com"
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
        assert participant_ws.receive_json() == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }
        participant_ws.send_json({"type": "live_status", "live_status": "done"})
        denied = participant_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "live_status_requires_live_session",
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


def test_http_workshop_enter_start_end_ticket_return_404_for_unknown_session_id(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    missing = uuid.uuid4()
    for suffix in ("enter", "start", "end", "ws-ticket"):
        r = client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{missing}/{suffix}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "Session not found"


def test_http_ws_ticket_403_when_rostered_but_never_entered_live_session(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            invited_at=datetime.now(timezone.utc),
            joined_at=None,
        )
    )
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "User must enter session first"


def test_http_enter_sets_joined_at_when_invited_but_not_entered(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    participant = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        invited_at=datetime.now(timezone.utc),
        joined_at=None,
    )
    db.add(participant)
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200

    db.refresh(participant)
    assert participant.joined_at is not None


def test_http_ws_ticket_allows_superuser_as_instructor_without_assignment(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=get_superuser_token_headers(client),
    )
    assert resp.status_code == 200

    decoded = jwt.decode(
        resp.json()["ticket"],
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        audience="workshop-ws",
    )
    assert decoded["role"] == "instructor"


def test_ws_rejects_truncated_ticket_for_pyjwt_error(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", "this-is-not-three-jwt-segments"],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_reports_invalid_json_and_invalid_message_shapes(
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
    db.commit()
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.connected"
        websocket.send_text("{")
        assert websocket.receive_json() == {"type": "error", "detail": "invalid_json"}

        websocket.send_text("[]")
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "invalid_message",
        }

        websocket.send_json({"type": "__unknown_xyz__"})
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "unknown_message_type",
        }


def test_ws_instructor_cannot_publish_live_status(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"i-ls-ban-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
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

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"
        ws.send_json({"type": "live_status", "live_status": "done"})
        assert ws.receive_json() == {"type": "error", "detail": "forbidden"}


def test_ws_trainee_cannot_advance_pause_or_resume(
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
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        trainee_ws.send_json({"type": "part.advance", "part_index": 0})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}

        trainee_ws.send_json({"type": "session.pause"})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}

        trainee_ws.send_json({"type": "session.resume"})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}


def test_ws_live_status_validation_errors_before_db(
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
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws.send_json({"type": "live_status", "live_status": 123})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_live_status"}

        ws.send_json({"type": "live_status", "live_status": "nope"})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_live_status"}


def test_ws_part_advance_requires_integer_part_index(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    instructor_email = f"i-idx-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
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

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws.send_json({"type": "part.advance", "part_index": "0"})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}

        ws.send_json({"type": "part.advance", "part_index": -1})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}

        ws.send_json({"type": "part.advance", "part_index": 99})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}


def test_http_enter_creates_participant_when_user_not_rostered_yet(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    trainee_email = f"walk-in-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=trainee_email, db=db)
    user = db.exec(select(User).where(User.email == trainee_email)).first()
    assert user is not None

    prior = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == user.id,
        )
    ).first()
    assert prior is None

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=headers,
    )
    assert resp.status_code == 200

    rostered = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == user.id,
        )
    ).first()
    assert rostered is not None
    assert rostered.joined_at is not None


def test_http_enter_403_when_required_prerequisites_incomplete(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    trainee_email = f"gate-enter-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=trainee_email, db=db)
    user = db.exec(select(User).where(User.email == trainee_email)).first()
    assert user is not None

    db.add(
        LessonPrerequisite(
            lesson_id=session_row.lesson_id,
            type="task",
            title="Read setup guide",
            ordering=1,
            required_flag=True,
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Required prerequisites incomplete"


def test_http_ws_ticket_rejects_when_session_scheduled(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    instructor_email = f"scheduled-ticket-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Session not started yet"


def test_http_ws_ticket_403_when_required_prerequisites_incomplete(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    trainee_email = f"gate-ticket-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=trainee_email, db=db)
    user = db.exec(select(User).where(User.email == trainee_email)).first()
    assert user is not None

    prerequisite = LessonPrerequisite(
        lesson_id=session_row.lesson_id,
        type="task",
        title="Install dependencies",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Required prerequisites incomplete"


def test_http_ws_ticket_allows_when_required_prerequisites_complete(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    trainee_email = f"gate-ticket-ok-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=trainee_email, db=db)
    user = db.exec(select(User).where(User.email == trainee_email)).first()
    assert user is not None

    prerequisite = LessonPrerequisite(
        lesson_id=session_row.lesson_id,
        type="task",
        title="Install dependencies",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        UserPrerequisiteCompletion(
            user_id=user.id,
            lesson_id=session_row.lesson_id,
            prerequisite_id=prerequisite.id,
            source="self",
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    assert resp.status_code == 200
    assert "ticket" in resp.json()


def test_ws_snap_reports_session_deleted_for_non_advance_frames(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    participant_email = f"snap-delete-{uuid.uuid4()}@example.com"
    participant_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    user = db.exec(select(User).where(User.email == participant_email)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        row = db.get(WorkshopSession, session_row.id)
        assert row is not None
        sid = session_row.id
        db.delete(row)
        db.commit()

        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        err = trainee_ws.receive_json()

    assert err == {"type": "error", "detail": "session_not_found"}
    assert db.get(WorkshopSession, sid) is None


def test_ws_live_status_errors_when_participant_soft_removed_mid_socket(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    participant_email = f"soft-rem-ws-{uuid.uuid4()}@example.com"
    participant_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    user = db.exec(select(User).where(User.email == participant_email)).first()
    assert user is not None
    roster = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(roster)
    db.commit()
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        db.refresh(roster)
        roster.removed_at = datetime.now(timezone.utc)
        db.add(roster)
        db.commit()

        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        err = trainee_ws.receive_json()

    assert err == {"type": "error", "detail": "participant_not_found"}


def test_ws_part_advance_reports_session_not_found_when_row_deleted_skip_snap(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)

    instructor_email = f"i-del-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
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

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        row = db.get(WorkshopSession, session_row.id)
        assert row is not None
        sid = session_row.id
        db.delete(row)
        db.commit()

        ws.send_json({"type": "part.advance", "part_index": 0})
        err = ws.receive_json()

    assert err == {"type": "error", "detail": "session_not_found"}
    assert db.get(WorkshopSession, sid) is None


def test_ws_resume_requires_paused_session(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)

    instructor_email = f"i-resume-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
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

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "session.resume"})
        err = instructor_ws.receive_json()

    assert err == {
        "type": "error",
        "detail": "resume_requires_paused_session",
    }


def test_list_workshop_sessions_empty_without_membership(
    client: TestClient, db: Session
) -> None:
    iso_email = f"list-none-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=iso_email, db=db)
    _create_live_session(db)

    response = client.get(f"{settings.API_V1_STR}/workshop/sessions/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["data"] == []


def test_list_workshop_sessions_includes_participant_membership(
    client: TestClient, db: Session
) -> None:
    iso_email = f"list-seat-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=iso_email, db=db)
    user = db.exec(select(User).where(User.email == iso_email)).first()
    assert user is not None

    session_row = _create_live_session(db)

    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
        )
    )
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/workshop/sessions/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["id"] == str(session_row.id)
    assert row["status"] == "live"
    assert row["my_role"] == "participant"
    assert row["blocked_required_prereq_count"] is None
    lesson = db.get(Lesson, session_row.lesson_id)
    assert lesson is not None
    assert row["lesson_title"] == lesson.title
    assert row["lesson_slug"] == lesson.slug


def test_list_workshop_sessions_includes_instructor_membership(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    instructor_email = f"instr-list-{uuid.uuid4()}@example.com"
    password = "testpass123"
    instructor = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password=password,
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=instructor_email, password=password
    )
    response = client.get(f"{settings.API_V1_STR}/workshop/sessions/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["my_role"] == "instructor"
    assert body["data"][0]["blocked_required_prereq_count"] == 0


def test_list_workshop_sessions_instructor_includes_blocked_prereq_count(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"instr-list-blocked-{uuid.uuid4()}@example.com"
    password = "testpass123"
    instructor = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password=password,
            is_instructor=True,
        ),
    )
    trainee = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"trainee-list-blocked-{uuid.uuid4()}@example.com",
            password=password,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=trainee.id,
        )
    )
    db.add(
        LessonPrerequisite(
            lesson_id=session_row.lesson_id,
            title="Read docs",
            required_flag=True,
            ordering=0,
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=instructor_email, password=password
    )
    response = client.get(f"{settings.API_V1_STR}/workshop/sessions/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["my_role"] == "instructor"
    assert body["data"][0]["blocked_required_prereq_count"] == 1


def test_list_workshop_sessions_excludes_removed_participant(
    client: TestClient, db: Session
) -> None:
    iso_email = f"list-removed-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=iso_email, db=db)
    user = db.exec(select(User).where(User.email == iso_email)).first()
    assert user is not None

    session_row = _create_live_session(db)

    participant = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        removed_at=datetime.now(timezone.utc),
    )
    db.add(participant)
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/workshop/sessions/", headers=headers)
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_list_workshop_sessions_superuser_sees_all(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    iso_email = f"list-su-{uuid.uuid4()}@example.com"
    user_headers = authentication_token_from_email(
        client=client, email=iso_email, db=db
    )
    iso_user = db.exec(select(User).where(User.email == iso_email)).first()
    assert iso_user is not None

    a = _create_live_session(db)
    b = _create_live_session(db)

    db.add(WorkshopParticipant(session_id=a.id, user_id=iso_user.id))
    db.commit()

    response_a = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/",
        headers=user_headers,
    )
    assert response_a.json()["count"] == 1

    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["data"]}
    assert str(a.id) in ids
    assert str(b.id) in ids

    rows_by_id = {item["id"]: item for item in body["data"]}
    assert rows_by_id[str(a.id)]["my_role"] is None
    assert rows_by_id[str(b.id)]["my_role"] is None


def test_get_workshop_session_detail_participant_view(
    client: TestClient, db: Session
) -> None:
    iso_email = f"detail-pt-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=iso_email, db=db)
    user = db.exec(select(User).where(User.email == iso_email)).first()
    assert user is not None

    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "participant"
    assert "participants" not in body
    assert "self" in body
    assert body["self"]["live_status"] == "busy"
    assert len(body["parts"]) == 2
    assert body["session"]["id"] == str(session_row.id)


def test_get_workshop_session_detail_instructor_roster(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    train_email = f"detail-tr-{uuid.uuid4()}@example.com"
    train_user = crud.create_user(
        session=db,
        user_create=UserCreate(email=train_email, password="pw123456"),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=train_user.id))
    inst_email = f"detail-inst-{uuid.uuid4()}@example.com"
    inst_user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=inst_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=inst_user.id,
            role="lead",
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=inst_email, password="pw123456"
    )
    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "instructor"
    emails = {p["email"] for p in body["participants"]}
    assert train_email in emails
    ins_emails = {i["email"] for i in body["instructors"]}
    assert inst_email in ins_emails


def test_get_workshop_session_detail_forbidden(client: TestClient, db: Session) -> None:
    iso_email = f"detail-xx-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=iso_email, db=db)
    session_row = _create_live_session(db)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
    )
    assert response.status_code == 403


def test_get_workshop_session_detail_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    missing = uuid.uuid4()
    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{missing}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_get_workshop_session_detail_superuser_instructor_shape(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    session_row = _create_live_session(db)
    train_email = f"detail-su-tr-{uuid.uuid4()}@example.com"
    train_user = crud.create_user(
        session=db,
        user_create=UserCreate(email=train_email, password="pw123456"),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=train_user.id))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "instructor"
    assert {p["email"] for p in body["participants"]} == {train_email}


def test_upsert_member_requires_instructor_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    actor_email = f"member-actor-{uuid.uuid4()}@example.com"
    actor_headers = authentication_token_from_email(
        client=client, email=actor_email, db=db
    )
    target_email = f"member-target-{uuid.uuid4()}@example.com"
    target = crud.create_user(
        session=db,
        user_create=UserCreate(email=target_email, password="pw123456"),
    )
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/members",
        headers=actor_headers,
        json={"user_id": str(target.id), "role": "participant"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not an instructor for this session"


def test_upsert_member_adds_participant_and_replaces_instructor_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"member-inst-{uuid.uuid4()}@example.com"
    instructor = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(session_id=session_row.id, user_id=instructor.id, role="lead")
    )

    target_email = f"member-target2-{uuid.uuid4()}@example.com"
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=target_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=target.id,
            role="co_instructor",
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=instructor_email, password="pw123456"
    )
    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/members",
        headers=headers,
        json={"user_id": str(target.id), "role": "participant"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Member upserted as participant"

    active_participant = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == target.id,
            WorkshopParticipant.removed_at.is_(None),
        )
    ).first()
    assert active_participant is not None
    inactive_instructor = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == target.id,
        )
    ).first()
    assert inactive_instructor is not None
    assert inactive_instructor.removed_at is not None


def test_upsert_member_adds_instructor_and_replaces_participant_seat(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"member-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))

    target_email = f"member-target3-{uuid.uuid4()}@example.com"
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=target_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=target.id))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/members",
        headers=headers,
        json={
            "user_id": str(target.id),
            "role": "instructor",
            "instructor_role": "co_instructor",
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Member upserted as instructor"

    active_instructor = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == target.id,
            SessionInstructor.removed_at.is_(None),
        )
    ).first()
    assert active_instructor is not None
    assert active_instructor.role == "co_instructor"
    inactive_participant = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == target.id,
        )
    ).first()
    assert inactive_participant is not None
    assert inactive_participant.removed_at is not None


def test_upsert_member_rejects_instructor_role_for_non_instructor_user(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"member-lead2-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"member-target4-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=False,
        ),
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/members",
        headers=headers,
        json={"user_id": str(target.id), "role": "instructor"},
    )
    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Instructor role requires target user.is_instructor"
    )


def test_remove_participant_requires_instructor_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"remove-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"remove-target-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=target.id))
    db.commit()

    response = client.delete(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=actor_headers,
    )
    assert response.status_code == 403


def test_remove_participant_soft_removes_active_seat(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"remove-lead-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"remove-target2-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=target.id))
    db.commit()

    lead_headers = user_authentication_headers(
        client=client,
        email=lead.email,
        password="pw123456",
    )
    response = client.delete(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=lead_headers,
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Participant removed"

    participant = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == target.id,
        )
    ).first()
    assert participant is not None
    assert participant.removed_at is not None


def test_remove_participant_not_found_when_no_active_seat(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"remove-lead2-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"remove-target3-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.commit()

    lead_headers = user_authentication_headers(
        client=client,
        email=lead.email,
        password="pw123456",
    )
    response = client.delete(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=lead_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Participant not found"


def test_patch_participant_override_requires_instructor_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"patch-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"patch-target-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=target.id))
    db.commit()

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=actor_headers,
        json={"live_status": "done"},
    )
    assert response.status_code == 403


def test_patch_participant_override_updates_fields(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"patch-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"patch-target2-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=target.id))
    db.commit()

    finished_at = datetime.now(timezone.utc)
    lead_headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=lead_headers,
        json={"live_status": "done", "finished_at": finished_at.isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Participant updated"

    participant = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == target.id,
            WorkshopParticipant.removed_at.is_(None),
        )
    ).first()
    assert participant is not None
    assert participant.live_status == "done"
    assert participant.finished_at is not None


def test_patch_participant_override_not_found_for_removed_seat(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"patch-lead2-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"patch-target3-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=target.id,
            removed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    lead_headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/participants/{target.id}",
        headers=lead_headers,
        json={"live_status": "busy"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Participant not found"


def test_patch_session_requires_instructor_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    actor_email = f"sess-patch-actor-{uuid.uuid4()}@example.com"
    actor_headers = authentication_token_from_email(
        client=client, email=actor_email, db=db
    )
    target = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-t-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=target.id, role="co_instructor"
        )
    )
    db.commit()

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=actor_headers,
        json={
            "instructor_seat": {"user_id": str(target.id), "role": "lead"},
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not an instructor for this session"


def test_patch_session_updates_instructor_seat_role(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    co_email = f"sess-patch-co-{uuid.uuid4()}@example.com"
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=co_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "instructor_seat": {"user_id": str(co.id), "role": "lead"},
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Session updated"

    seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == co.id,
            SessionInstructor.removed_at.is_(None),
        )
    ).first()
    assert seat is not None
    assert seat.role == "lead"


def test_patch_session_instructor_seat_not_found(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-nf-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    stranger = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-stranger-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "instructor_seat": {"user_id": str(stranger.id), "role": "co_instructor"},
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Instructor seat not found"


def test_patch_session_empty_body_returns_422(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-empty-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "patch_requires_update"


def test_patch_session_cannot_update_and_remove_same_instructor_returns_422(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-both-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-co-both-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "instructor_seat": {"user_id": str(co.id), "role": "lead"},
            "remove_instructor_user_id": str(co.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "cannot_update_and_remove_same_instructor"


def test_patch_session_handoff_target_must_be_active_instructor_returns_422(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-handoff-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    outsider = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-handoff-outsider-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"primary_instructor_user_id": str(outsider.id)},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "handoff_target_not_instructor"


def test_patch_session_handoff_promotes_target_and_demotes_previous_lead(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-handoff1-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-handoff2-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"primary_instructor_user_id": str(co.id)},
    )
    assert response.status_code == 200

    lead_seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == lead.id,
            SessionInstructor.removed_at.is_(None),
        )
    ).first()
    co_seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == co.id,
            SessionInstructor.removed_at.is_(None),
        )
    ).first()
    assert lead_seat is not None
    assert co_seat is not None
    assert lead_seat.role == "co_instructor"
    assert co_seat.role == "lead"


def test_patch_session_status_start_publishes_hub(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_row = _create_scheduled_session(db)
    lead_email = f"sess-patch-start-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    published: list[tuple[uuid.UUID, str]] = []

    async def capture_publish(*, session_id: uuid.UUID, status: str) -> None:
        published.append((session_id, status))

    monkeypatch.setattr(
        workshop_realtime_mod.workshop_hub,
        "publish_session_status_changed",
        capture_publish,
    )

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "live"},
    )
    assert response.status_code == 200
    db.refresh(session_row)
    assert session_row.status == "live"
    assert published == [(session_row.id, "live")]


def test_patch_session_status_pause_and_resume(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-pause-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    r1 = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "paused"},
    )
    assert r1.status_code == 200
    db.refresh(session_row)
    assert session_row.status == "paused"

    r2 = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "live"},
    )
    assert r2.status_code == 200
    db.refresh(session_row)
    assert session_row.status == "live"


def test_patch_session_status_end_from_paused(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-end-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "paused"},
    )

    published: list[tuple[uuid.UUID, str]] = []

    async def capture_publish(*, session_id: uuid.UUID, status: str) -> None:
        published.append((session_id, status))

    monkeypatch.setattr(
        workshop_realtime_mod.workshop_hub,
        "publish_session_status_changed",
        capture_publish,
    )

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "ended"},
    )
    assert response.status_code == 200
    db.refresh(session_row)
    assert session_row.status == "ended"
    assert published == [(session_row.id, "ended")]


def test_patch_session_invalid_status_transition_returns_403(
    client: TestClient, db: Session
) -> None:
    session_row = _create_scheduled_session(db)
    lead_email = f"sess-patch-bad-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"status": "paused"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "pause_requires_live_session"


def test_patch_session_remove_last_instructor_returns_409(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-rm409-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"remove_instructor_user_id": str(lead.id)},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "last_instructor_removal_blocked"


def test_patch_session_remove_instructor_ok_when_co_remains(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-rmok-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-rm-co-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={"remove_instructor_user_id": str(co.id)},
    )
    assert response.status_code == 200

    co_seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == co.id,
        )
    ).first()
    assert co_seat is not None
    assert co_seat.removed_at is not None


def test_patch_session_combined_handoff_and_remove_current_lead_succeeds(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-combo-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-combo-co-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "primary_instructor_user_id": str(co.id),
            "remove_instructor_user_id": str(lead.id),
        },
    )
    assert response.status_code == 200

    lead_seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == lead.id,
        )
    ).first()
    co_seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == co.id,
            SessionInstructor.removed_at.is_(None),
        )
    ).first()
    assert lead_seat is not None
    assert lead_seat.removed_at is not None
    assert co_seat is not None
    assert co_seat.role == "lead"


def test_patch_session_cannot_handoff_to_removed_instructor_returns_422(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-combo-bad-lead-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    co = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"sess-patch-combo-bad-co-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.add(
        SessionInstructor(
            session_id=session_row.id, user_id=co.id, role="co_instructor"
        )
    )
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "primary_instructor_user_id": str(co.id),
            "remove_instructor_user_id": str(co.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "cannot_handoff_to_removed_instructor"


def test_patch_session_end_and_remove_last_instructor_ok(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    lead_email = f"sess-patch-endrm-{uuid.uuid4()}@example.com"
    lead = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=lead_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    db.add(SessionInstructor(session_id=session_row.id, user_id=lead.id, role="lead"))
    db.commit()

    headers = user_authentication_headers(
        client=client, email=lead_email, password="pw123456"
    )
    response = client.patch(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
        json={
            "status": "ended",
            "remove_instructor_user_id": str(lead.id),
        },
    )
    assert response.status_code == 200
    db.refresh(session_row)
    assert session_row.status == "ended"
    seat = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == session_row.id,
            SessionInstructor.user_id == lead.id,
        )
    ).first()
    assert seat is not None
    assert seat.removed_at is not None


def test_timer_lifecycle_for_instructor(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"timer-instr-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor = db.exec(select(User).where(User.email == instructor_email)).first()
    assert instructor is not None
    instructor.is_instructor = True
    db.add(instructor)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    db.commit()

    start = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=headers,
        json={"mode": "countdown", "target_seconds": 300},
    )
    assert start.status_code == 200
    assert start.json()["status"] == "running"
    assert start.json()["mode"] == "countdown"
    assert start.json()["target_seconds"] == 300

    pause = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/pause",
        headers=headers,
    )
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    resume = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/resume",
        headers=headers,
    )
    assert resume.status_code == 200
    assert resume.json()["status"] == "running"

    read = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer",
        headers=headers,
    )
    assert read.status_code == 200
    assert read.json()["status"] == "running"

    stop = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/stop",
        headers=headers,
    )
    assert stop.status_code == 200
    assert stop.json()["status"] == "inactive"


def test_timer_requires_instructor_and_active_session(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    normal_headers = authentication_token_from_email(
        client=client, email=f"timer-user-{uuid.uuid4()}@example.com", db=db
    )
    denied = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=normal_headers,
        json={"mode": "countup"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "User is not an instructor for this session"

    instructor_email = f"timer-inactive-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor = db.exec(select(User).where(User.email == instructor_email)).first()
    assert instructor is not None
    instructor.is_instructor = True
    db.add(instructor)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    blocked = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=headers,
        json={"mode": "countup"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "timer_requires_active_session"


def test_timer_validation_and_conflict_paths(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"timer-conflict-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor = db.exec(select(User).where(User.email == instructor_email)).first()
    assert instructor is not None
    instructor.is_instructor = True
    db.add(instructor)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    db.commit()

    bad_countdown = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=headers,
        json={"mode": "countdown"},
    )
    assert bad_countdown.status_code == 422
    assert bad_countdown.json()["detail"] == "countdown_requires_target_seconds"

    ok_start = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=headers,
        json={"mode": "countup"},
    )
    assert ok_start.status_code == 200

    dup_start = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/start",
        headers=headers,
        json={"mode": "countup"},
    )
    assert dup_start.status_code == 409
    assert dup_start.json()["detail"] == "timer_already_active"

    bad_resume = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/timer/resume",
        headers=headers,
    )
    assert bad_resume.status_code == 409
    assert bad_resume.json()["detail"] == "timer_not_paused"
